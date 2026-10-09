"""Offline test-bench control, input ownership and ideal actuator checks."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/_runtime'))
from lupa.luajit21 import LuaRuntime

class TestBenchTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          FILTER_DIRECT=1
          function jsonDecode(x)return x end
          function jsonEncode(x)return '{}' end
          speed=0;inputCalls=0
          input={state={throttle={},brake={},steering={},parkingbrake={}},event=function(...)inputCalls=inputCalls+1 end}
          oldEvent=input.event
          v={data={input={steeringWheelLock=480}}}
          obj={getID=function()return 1 end,queueGameEngineLua=function()end,getVelocity=function()return {length=function()return speed end} end}
          motors={}
          for _,n in ipairs({'FL','FR','RL','RR'}) do motors[n]={outputTorque1=100,hasEnergy=true} end
          powertrain={getDevice=function(n)return motors[n:sub(8)]end}
          ecu={setTestTorque=function(x) command=x;return true end}
          controller={getController=function()return ecu end}
        ''')
        self.mod=self.lua.execute((ROOT/'test_bench_mod/lua/vehicle/extensions/mininiTestBenchVehicle.lua').read_text())

    def packet(self,mode='exact',speed=0):
        return self.lua.table_from(dict(op='start',mode=mode,speed=speed,steering=120,torque=dict(FL=20,FR=-30,RL=40,RR=-50)),recursive=True)

    def test_exact_torque_and_exclusive_input(self):
        self.mod.request(self.packet());self.lua.execute("input.event('throttle',1,1,nil,nil,nil,'human');assert(inputCalls==0)")
        self.mod.updateGFX(.31)
        self.assertEqual(self.lua.globals().command.FL,20)
        self.assertEqual(self.lua.globals().command.FR,-30)
        self.assertEqual(self.lua.globals().input.steering,.25)
        self.assertEqual(self.lua.globals().input.throttle,0)
        self.mod.request(self.lua.table_from(dict(op='stop')))
        self.lua.execute('assert(input.event==oldEvent and command==nil)')

    def test_full_1500_nm_in_both_directions(self):
        packet=self.packet();packet.torque.FL=1500;packet.torque.FR=-1500
        self.mod.request(packet);self.mod.updateGFX(.31)
        self.assertEqual(self.lua.globals().command.FL,1500)
        self.assertEqual(self.lua.globals().command.FR,-1500)

    def test_additional_uses_frozen_baseline(self):
        self.mod.request(self.packet('additional'));self.mod.updateGFX(.31)
        self.assertEqual(self.lua.globals().command.FL,120)
        self.assertEqual(self.lua.globals().command.FR,70)
        self.lua.execute('motors.FL.outputTorque1=900')
        self.mod.updateGFX(.1);self.assertEqual(self.lua.globals().command.FL,120)

    def test_steering_precedes_speed_matching_then_exact_configuration(self):
        self.mod.request(self.packet(speed=36));self.mod.updateGFX(.1)
        self.assertEqual(self.lua.globals().input.steering,.25)
        self.assertEqual(self.lua.globals().command.FL,0)
        self.mod.updateGFX(.21)
        self.assertGreater(self.lua.globals().command.FL,0)
        self.assertEqual(self.lua.globals().command.FL,self.lua.globals().command.FR)
        self.lua.globals().speed=10
        self.mod.updateGFX(.1);self.mod.updateGFX(.1)
        self.assertEqual(self.lua.globals().command.FR,-30)
        self.assertEqual(self.lua.globals().input.steering,.25)
        self.lua.globals().speed=20;self.mod.updateGFX(.1)
        self.assertEqual(self.lua.globals().command.FR,-30)

    def test_watchdog_reset_and_unsupported_car_release_control(self):
        self.mod.request(self.packet());self.mod.updateGFX(1.1)
        self.lua.execute('assert(input.event==oldEvent and command==nil)')
        self.mod.request(self.packet());self.mod.onReset()
        self.lua.execute('assert(input.event==oldEvent and command==nil);ecu={}')
        self.mod.request(self.packet());self.lua.execute('assert(input.event==oldEvent)')

    def test_live_mode_switch_reuses_baseline_without_restart(self):
        self.mod.request(self.packet());self.mod.updateGFX(.31)
        for mode,expected in (('additional',120),('exact',20),('additional',120)):
            p=self.packet(mode);p.op='update';p.session=0
            self.mod.request(p);self.mod.updateGFX(.01)
            self.assertEqual(self.lua.globals().command.FL,expected)
            self.lua.execute('assert(input.event~=oldEvent)')
        p=self.packet('additional');p.op='update';p.session=0;p.torque.FL=-60
        self.mod.request(p);self.mod.updateGFX(.01)
        self.assertEqual(self.lua.globals().command.FL,40)

    def test_runup_baseline_survives_exact_to_additional_switch(self):
        self.lua.execute("function jsonEncode(data) published=data;return '{}' end")
        self.mod.request(self.packet(speed=36));self.mod.updateGFX(.31)
        self.lua.globals().speed=10
        self.mod.updateGFX(.1);self.mod.updateGFX(.1)
        baseline=self.lua.globals().published.baseline.FL
        self.assertNotEqual(baseline,0)
        p=self.packet('additional');p.op='update';p.session=0
        self.mod.request(p);self.mod.updateGFX(.01)
        self.assertAlmostEqual(self.lua.globals().command.FL,baseline+20)
        p.mode='exact';self.mod.request(p);self.mod.updateGFX(.01)
        self.assertEqual(self.lua.globals().command.FL,20)
        p.mode='additional';self.mod.request(p);self.mod.updateGFX(.01)
        self.assertAlmostEqual(self.lua.globals().command.FL,baseline+20)

    def test_bad_configuration_does_not_take_control(self):
        for mode,speed,steering,torque in (('bad',0,0,0),('exact',-1,0,0),('exact',0,500,0),('exact',0,0,1501)):
            p=self.packet(mode,speed);p.steering=steering;p.torque.FL=torque
            self.mod.request(p);self.lua.execute('assert(input.event==oldEvent)')

    def test_adapter_delivers_exact_signed_nm_and_expires_lease(self):
        import custom_control
        source=custom_control.build_controller(custom_control.source_for_export())
        self.lua.execute('''
          function log()end
          guihooks={message=function()end}
          electrics={values={}}
          sensors={}
          wheels={wheels={}}
          for _,n in ipairs({'FL','FR','RL','RR'}) do
            table.insert(wheels.wheels,{name=n,wheelSpeed=0})
            motors[n].torqueUpdate=function(d,dt)d.outputTorque1=-2 end
            motors[n].torqueCurve={[0]=700};motors[n].regenCurve={[0]=500}
            motors[n].outputAV1=10;motors[n].grossWorkPerUpdate=0;motors[n].spentEnergy=0
          end
          obj.getVelocity=function()return {length=function()return 0 end,dot=function()return 0 end}end
          obj.getDirectionVector=function()return {}end
        ''')
        adapter=self.lua.execute(source);adapter.init(self.lua.table())
        self.assertTrue(adapter.setTestTorque(self.lua.table_from(dict(FL=123,FR=-456,RL=0,RR=700))))
        adapter.updateFixedStep(.01)
        self.lua.globals().motors.FR.torqueUpdate(self.lua.globals().motors.FR,.01)
        self.assertEqual(self.lua.globals().motors.FR.outputTorque1,-456)
        adapter.updateFixedStep(1.1)
        self.lua.globals().motors.FR.torqueUpdate(self.lua.globals().motors.FR,.01)
        self.assertEqual(self.lua.globals().motors.FR.outputTorque1,-2)

if __name__=='__main__':unittest.main()
