import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from custom_control import ROOT, USER_FILE
from imu_patch import mounts
from test_electric import ev_sample

sys.path.insert(0,str(ROOT/'tests/_runtime'))
from lupa.luajit21 import LuaRuntime


class IMUHardwareTests(unittest.TestCase):
    def test_four_chassis_mounts_measure_yaw_and_specific_force_in_car_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'source.zip';ev_sample(file)
            with zipfile.ZipFile(file) as z:entries={n:z.read(n) for n in z.namelist()}
        config=mounts(entries,'vehicles/Car/')
        self.assertEqual(set(config['mounts']),{'FL','FR','RL','RR'})
        self.assertEqual(len({m['nodes'][0] for m in config['mounts'].values()}),4)
        from electric_patch import node_positions
        points=node_positions(entries['vehicles/Car/main.jbeam'].decode())
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          local mt={};mt.__index=mt
          function V(x,y,z) return setmetatable({x=x,y=y,z=z},mt) end
          mt.__add=function(a,b) return V(a.x+b.x,a.y+b.y,a.z+b.z) end
          mt.__sub=function(a,b) return V(a.x-b.x,a.y-b.y,a.z-b.z) end
          mt.__mul=function(a,b) return V(a.x*b,a.y*b,a.z*b) end
          function mt:length() return math.sqrt(self.x*self.x+self.y*self.y+self.z*self.z) end
          function mt:normalize() local n=self:length();self.x=self.x/n;self.y=self.y/n;self.z=self.z/n;return self end
          function mt:cross(b) return V(self.y*b.z-self.z*b.y,self.z*b.x-self.x*b.z,self.x*b.y-self.y*b.x) end
          function mt:dot(b) return self.x*b.x+self.y*b.y+self.z*b.z end
          theta=0;rate=.4;speed=15;v={data={nodes={}}};points={}
          obj={getGravityVector=function() return V(0,0,-9.81) end,
            getNodePosition=function(_,id)
              local p=points[id];local c,s=math.cos(theta),math.sin(theta)
              return V(c*p[1]-s*p[2],s*p[1]+c*p[2],p[3])
            end,
            getNodeVelocityVector=function(_,id)
              local p=points[id];local vx=speed-rate*p[2];local vy=rate*(p[1]-1.5)
              local c,s=math.cos(theta),math.sin(theta)
              return V(c*vx-s*vy,s*vx+c*vy,0)
            end}
        ''')
        for i,(name,point) in enumerate(points.items(),1):
            lua.globals().points[i]=lua.table_from(point)
            lua.globals().v.data.nodes[i]=lua.table_from(dict(name=name,cid=i))
        lua.execute("v.data.nodes.__astNodeIdx=123;v.data.nodes.metadata={};v.data.nodes.generated={cid=1000}")
        create=lua.execute((ROOT/'companion_imu.lua').read_text()+'\nreturn createIMUSampler')
        sensor=create(lua.table_from(config,recursive=True))
        first=sensor.sample(.01)
        self.assertFalse(first.FL.valid)
        lua.globals().theta=.004
        out=sensor.sample(.01)
        for n in ('FL','FR','RL','RR'):
            self.assertTrue(out[n].valid)
            self.assertAlmostEqual(out[n].gyro.up,.4,places=4)
            self.assertAlmostEqual(out[n].acceleration.up,9.81)
            expected=6-.4*.4*config['mounts'][n]['offset']['left']
            self.assertAlmostEqual(out[n].acceleration.left,expected,places=2)
        sensor.reset()
        self.assertFalse(sensor.sample(.01).FL.valid)
        for delta in (.004,.008,.012):
            lua.globals().theta=lua.globals().theta+delta
            filtered=sensor.sample(.01)
        self.assertAlmostEqual(filtered.FL.gyro.up,.8,places=3)
        self.assertAlmostEqual(filtered.FL.rawGyro.up,1.2,places=3)
        self.assertEqual(filtered.FL.smoothingSamples,3)
        sensor.reset()
        self.assertFalse(sensor.sample(.01).FL.valid)
        lua.globals().theta=.004
        # Verify the complete adapter passes all four sensor instances into user Lua.
        from custom_control import build_controller
        lua.execute('''
          input={};sensors={};electrics={values={gearIndex=1}};wheels={wheels={}};motors={}
          log=function(level,tag,msg) if level=='E' then error(msg) end end
          for _,n in ipairs({'FL','FR','RL','RR'}) do
            wheels.wheels[n]={name=n,wheelSpeed=15}
            motors['evMotor'..n]={torqueUpdate=function() end}
          end
          powertrain={getDevice=function(n) return motors[n] end}
          obj.getVelocity=function() return V(15,0,0) end
          obj.getDirectionVector=function() return V(1,0,0) end
        ''')
        source='''return function(s,m)
          m.calls=(m.calls or 0)+1
          if m.calls>1 then
            assert(s.geometry.wheelbase==3)
            for _,n in ipairs({'FL','FR','RL','RR'}) do
              assert(s.imu[n].valid and math.abs(s.imu[n].gyro.up-.4)<.0001)
              assert(math.abs(s.imu[n].acceleration.up-9.81)<.0001)
            end
          end
          return {FL=0,FR=0,RL=0,RR=0}
        end'''
        ecu=lua.execute(build_controller(source));ecu.init(lua.table_from({'imu':config},recursive=True))
        ecu.updateGFX(.01);ecu.updateFixedStep(.01)
        lua.globals().theta=.008;ecu.updateGFX(.01);ecu.updateFixedStep(.01)
        sampled=ecu.getDebugState().input.imuSampleTime
        # An extra fixed update must reuse the sample instead of differentiating
        # the same rendered node pose again and producing a zero-rate gyro.
        ecu.updateFixedStep(.01)
        self.assertAlmostEqual(ecu.getDebugState().input.imuSampleTime,sampled)
        self.assertAlmostEqual(ecu.getDebugState().input.imu.FL.gyro.up,.4,places=4)
        lua.execute('obj.getPosition=function() return V(100,200,1) end')
        lua.execute('vec3=V')
        for steer,side in ((-1,'left'),(1,'right'),(0,None)):
            lua.globals().input.steering=steer
            lua.globals().theta=lua.globals().theta+.004
            ecu.updateGFX(.01);ecu.updateFixedStep(.01)
            wanted=ecu.getDebugState().input.wantedRC
            if side is None:
                self.assertIsNone(wanted)
            else:
                self.assertEqual(wanted.side,side)
                self.assertEqual(wanted.distance,10)
                readings=ecu.getDebugState().input.imu
                cx=100+sum(readings[n].frame.position.x for n in ('FL','FR','RL','RR'))/4
                cy=200+sum(readings[n].frame.position.y for n in ('FL','FR','RL','RR'))/4
                self.assertAlmostEqual(math.hypot(wanted.x-cx,wanted.y-cy),10)
        ecu.shutdown()
