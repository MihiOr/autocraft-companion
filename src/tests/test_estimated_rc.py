"""Four-sensor RC fusion checks without running BeamNG."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/_runtime'))
from lupa.luajit21 import LuaRuntime

class EstimatedRCTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          local mt={};mt.__index=mt
          function vec3(x,y,z)return setmetatable({x=x,y=y,z=z},mt)end
          function mt.__add(a,b)return vec3(a.x+b.x,a.y+b.y,a.z+b.z)end
          function mt.__sub(a,b)return vec3(a.x-b.x,a.y-b.y,a.z-b.z)end
          function mt.__mul(a,b)return vec3(a.x*b,a.y*b,a.z*b)end
          function mt:length()return math.sqrt(self.x*self.x+self.y*self.y+self.z*self.z)end
          function mt:normalize()local n=self:length();self.x=self.x/n;self.y=self.y/n;self.z=self.z/n end
          function mt:cross(b)return vec3(self.y*b.z-self.z*b.y,self.z*b.x-self.x*b.z,self.x*b.y-self.y*b.x)end
          function mt:dot(b)return self.x*b.x+self.y*b.y+self.z*b.z end
          points={vec3(0,0,0),vec3(1,0,0),vec3(0,1,0)}
          v={data={vehicleDirectory='vehicles/Test_v22_66/',nodes={
            {name='a',cid=1},{name='b',cid=2},{name='c',cid=3}}}}
          state={time=0,imu={},geometry={mounts={}}}
          for _,name in ipairs({'FL','FR','RL','RR'})do
            state.geometry.mounts[name]={nodes={'a','b','c'},forward={1,0,0},left={0,0,1},up={0,1,0}}
            state.imu[name]={valid=true,gyro={forward=0,left=0,up=.5},
              acceleration={forward=0,left=5,up=9.81},velocity={forward=10,left=0,up=0}}
          end
          controller={getController=function()return {getDebugState=function()return {input=state}end}end}
          obj={getNodePosition=function(self,id)return points[id]end,getID=function()return 1 end,
            getPosition=function()return vec3(100,200,1)end,getGravityVector=function()return vec3(0,0,-9.81)end,
            queueGameEngineLua=function(self,command)received=command end}
          function serialize(value)estimate=value;return 'nil' end
        ''')
        self.mod=self.lua.execute((ROOT/'rotation_center_mod/lua/vehicle/extensions/mininiEstimatedRC.lua').read_text())

    def test_left_right_reverse_and_four_gyro_average(self):
        for speed,yaw in ((10,.5),(10,-.5),(-10,.5),(-10,-.5)):
            self.mod.onReset()
            self.lua.execute(f"for _,s in pairs(state.imu)do s.velocity.forward={speed};s.gyro.up={yaw};s.valid=true end")
            self.mod.report()
            e=self.lua.globals().estimate
            self.assertAlmostEqual(e.x,100)
            self.assertAlmostEqual(e.y,200+speed/yaw)
            self.assertAlmostEqual(e.distance,20)
        self.mod.onReset()
        self.lua.execute('state.imu.FL.gyro.up=-1;state.imu.FR.gyro.up=1;state.imu.RL.gyro.up=1;state.imu.RR.gyro.up=1')
        self.mod.report()
        self.assertAlmostEqual(self.lua.globals().estimate.distance,20)

    def test_ecu_owns_same_fused_center(self):
        self.lua.execute('''for _,s in pairs(state.imu)do s.frame={
          forward={x=1,y=0,z=0},left={x=0,y=1,z=0},up={x=0,y=0,z=1},position={x=0,y=0,z=0}} end''')
        create=self.lua.execute((ROOT/'companion_rc.lua').read_text(encoding='utf-8')+'\nreturn createRCEstimator')
        core=create()
        e=core.sample(self.lua.globals().state.imu,.02)
        self.assertAlmostEqual(e.x,100)
        self.assertAlmostEqual(e.y,220)
        self.assertAlmostEqual(e.rotationSpeed,36)
        self.lua.execute('state.imu.FL.valid=false')
        self.assertIsNone(core.sample(self.lua.globals().state.imu,.02))

    def test_acceleration_integration_and_velocity_drift_correction(self):
        import math
        self.mod.report()
        self.lua.execute('state.time=.1;for _,s in pairs(state.imu)do s.acceleration.forward=2;s.acceleration.left=0 end')
        self.mod.report()
        self.assertAlmostEqual(self.lua.globals().estimate.distance,(10+.2*math.exp(-.1/.5))/.5)

    def test_invalid_straight_and_civetta_hide_estimate(self):
        self.lua.execute('state.imu.FL.valid=false')
        self.mod.report();self.assertIsNone(self.lua.globals().estimate)
        self.lua.execute('state.imu.FL.valid=true;for _,s in pairs(state.imu)do s.gyro.up=0 end')
        self.mod.report();self.assertIsNone(self.lua.globals().estimate)
        self.lua.execute("v.data.vehicleDirectory='vehicles/Civetta_v01_03/'")
        self.mod.report();self.assertIsNone(self.lua.globals().estimate)

    def test_cached_imu_sample_is_not_integrated_twice(self):
        self.lua.execute('state.imuSampleTime=1;state.imuSampleDt=.02')
        self.mod.report()
        before=self.lua.globals().estimate.distance
        self.lua.execute('state.time=.1;for _,s in pairs(state.imu)do s.acceleration.forward=100 end')
        self.mod.report()
        self.assertAlmostEqual(self.lua.globals().estimate.distance,before)

if __name__=='__main__':unittest.main()
