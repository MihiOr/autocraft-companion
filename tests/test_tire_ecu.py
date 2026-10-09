import json
from pathlib import Path
import sys
import unittest
from patcher import JBeam
from tire_ecu_patch import apply


class TireTests(unittest.TestCase):
    def test_per_wheel_grip_and_motor_control_channels(self):
        prefix='vehicles/Car/'
        entries={prefix+'companion_ev_report.json':b'{}',prefix+'engine.jbeam':json.dumps({'engine':{
            'evMotor'+w:{} for w in ('FL','FR','RL','RR')}}).encode()}
        for axle in ('F','R'):
            entries[prefix+'wheels_'+axle+'.jbeam']=json.dumps({'wheels_'+axle:{'pressureWheels':[
                ['name','hubGroup','group','node1:','node2:','nodeS','nodeArm:','wheelDir'],
                {'frictionCoef':1},[axle+'L','hub','tire','a','b',9999,'c',1,{'nodeCoupling:':'d'}],
                [axle+'R','hub','tire','a','b',9999,'c',-1,{'nodeCoupling:':'d'}]]}}).encode()
        settings={'ev_tire_enabled':True,'ev_tire_grip':1.4,'ev_ecu_mode':'Launch + traction control',
                  'ev_tc_slip':8,'ev_launch_slip':8,'ev_launch_ramp':.4}
        result=apply(entries,prefix,settings)
        for axle in ('F','R'):
            table=json.loads(result[prefix+'wheels_'+axle+'.jbeam'])['wheels_'+axle]['pressureWheels']
            for row in table[2:]:
                self.assertEqual(row[-1]['frictionCoef'],1.4)
                self.assertEqual(row[-1]['nodeCoupling:'],'d')
        engine=json.loads(result[prefix+'engine.jbeam'])['engine']
        self.assertEqual(len({engine['evMotor'+w]['electricsThrottleFactorName'] for w in ('FL','FR','RL','RR')}),4)
        self.assertIn(prefix+'lua/controller/companion_ev_ecu.lua',result)


class LuaECUTests(unittest.TestCase):
    def test_zero_ramp_immediate_release(self):
        from tire_ecu_patch import validate
        self.assertEqual(validate({'ev_ecu_mode':'Launch + traction control', 'ev_tc_slip':8,
                                   'ev_launch_slip':8, 'ev_launch_ramp':0})['ramp'], 0)
        self.ecu.init(self.lua.table_from({'launchEnabled':True,'targetSlip':.08,'launchSlip':.08,'launchRamp':0}))
        self.lua.execute('input.throttle=1; input.brake=1')
        self.step()
        self.assertEqual(self.lua.globals().electrics['values'].companionTorqueFL,0)
        self.lua.execute('input.brake=0')
        self.step()
        self.assertEqual(self.lua.globals().electrics['values'].companionTorqueFL,1)

    def setUp(self):
        from lupa import LuaRuntime
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''speed=0; input={throttle=0,brake=0,parkingbrake=0}
            electrics={values={gearIndex=1}}; wheels={wheels={}}
            for _,n in ipairs({'FL','FR','RL','RR'}) do wheels.wheels[n]={name=n,wheelSpeed=0} end
            obj={getVelocity=function() return {length=function() return speed end} end}
            log=function() end''')
        self.ecu=self.lua.execute((Path(__file__).parents[1]/'companion_ev_ecu.lua').read_text())
        self.ecu.init(self.lua.table_from({'launchEnabled':True,'targetSlip':.08,'launchSlip':.08,'launchRamp':.4}))

    def step(self,n=1):
        for _ in range(n):self.ecu.updateFixedStep(.01)

    def test_only_spinning_wheel_loses_torque_and_recovers(self):
        self.lua.execute("speed=5; input.throttle=1; for _,w in pairs(wheels.wheels) do w.wheelSpeed=5 end; wheels.wheels.FL.wheelSpeed=15")
        self.step(100)
        ev=self.lua.globals().electrics['values']
        self.assertEqual(ev.companionTorqueFL,0)
        self.assertEqual(ev.companionTorqueFR,1)
        self.lua.execute('wheels.wheels.FL.wheelSpeed=5')
        self.step(100)
        self.assertEqual(ev.companionTorqueFL,1)

    def test_launch_bypasses_tc_until_throttle_drop_or_brake(self):
        for stop in ('input.throttle=.49', 'input.brake=.8'):
            self.ecu.reset()
            self.lua.execute('speed=0; input.throttle=1; input.brake=1')
            self.step()
            self.lua.execute('input.brake=0; wheels.wheels.FL.wheelSpeed=60; speed=0')
            self.step()
            self.lua.execute('speed=30')
            self.step(100)
            ev=self.lua.globals().electrics['values']
            self.assertEqual(ev.companionLaunchState,2)
            self.assertEqual(ev.companionTorqueFL,1)
            self.lua.execute(stop)
            self.step()
            self.assertEqual(ev.companionLaunchState,0)
            self.lua.execute('input.brake=0; input.throttle=.49')
            self.step(100)
            self.assertEqual(ev.companionTorqueFL,0)

    def test_brake_release_launch_reset_and_reverse(self):
        ev=self.lua.globals().electrics['values']
        self.lua.execute('input.throttle=1; input.brake=1')
        self.step()
        self.assertEqual(ev.companionLaunchState,1)
        self.assertEqual(ev.companionTorqueFL,0)
        self.lua.execute('input.brake=0')
        self.step()
        self.assertEqual(ev.companionLaunchState,2)
        self.assertGreater(ev.companionTorqueFL,.25)
        self.assertLess(ev.companionTorqueFL,.3)
        self.step(50)
        self.assertEqual(ev.companionTorqueFL,1)
        self.lua.execute('electrics.values.gearIndex=-1')
        self.step()
        self.assertEqual(ev.companionLaunchState,0)
        self.ecu.reset()
        self.assertEqual(ev.companionTorqueFL,1)
