import json
from pathlib import Path
import sys
import unittest

from custom_control import build_controller, check_code, USER_FILE, verify_motor_wiring
from tire_ecu_patch import apply

from lupa.luajit21 import LuaRuntime


class CustomControlTests(unittest.TestCase):
    def test_checks_errors_and_endless_loop(self):
        self.assertIn('270', check_code())
        for source in ('return function(', 'return {}',
                       'return function() return {FL=2,FR=0,RL=0,RR=0} end',
                       'return function() error("broken") end',
                       'return function() while true do end end',
                       'return function() return {FL=0/0,FR=0,RL=0,RR=0} end'):
            with self.assertRaises(ValueError):
                check_code(source)

    def test_packaging_replaces_builtin_ecu(self):
        prefix = 'vehicles/Test/'
        entries = {prefix+'engine.jbeam':json.dumps({'engine':{
            'evMotor'+n:{} for n in ('FL','FR','RL','RR')}}).encode(),
            prefix+'companion_ev_report.json':b'{}'}
        patched = apply(entries, prefix, {'ev_ecu_mode':'Custom Lua'})
        verify_motor_wiring(patched)
        with self.assertRaises(ValueError):
            verify_motor_wiring(entries)
        engine = json.loads(patched[prefix+'engine.jbeam'])['engine']
        self.assertEqual(engine['controller'][1][0], 'companion_custom_ecu')
        self.assertEqual(patched[prefix+'custom_motor_control.lua'].decode(),USER_FILE.read_text())
        for n in ('FL','FR','RL','RR'):
            self.assertEqual(engine['evMotor'+n]['electricsThrottleName'],'companionCustom'+n)
            self.assertEqual(engine['evMotor'+n]['maxRegenTorque'],0)

    def test_signed_independent_commands_zero_and_runtime_failure(self):
        lua = LuaRuntime()
        lua.execute('''
          input={}; sensors={}; electrics={values={gearIndex=-1}}
          motors={}; wheels={wheels={}}; log=function() end
          obj={getVelocity=function() return {length=function() return 0 end,dot=function() return 0 end} end,
               getDirectionVector=function() return {} end}
          for _,n in ipairs({'FL','FR','RL','RR'}) do
            wheels.wheels[n]={name=n,wheelSpeed=0}
            motors['evMotor'..n]={motorDirection=-1,throttleSmoother={},torqueCoef=0,maxTorqueLimit=0,tempRevLimiterAV=0,isAffectedByIgnition=true,
              torqueUpdate=function(m,dt)
                m.seen=m.motorDirection*m.throttleSmoother:getUncapped(electrics.values['companionCustom'..n])
                assert(electrics.values.companionCustomFactor==1)
                assert(electrics.values.companionCustomRegen==0 and m.minWantedRegenTorque==0)
                assert(m.torqueCoef==1 and m.maxTorqueLimit==math.huge and m.tempRevLimiterAV==math.huge)
                assert(not m.isAffectedByIgnition)
              end}
          end
          powertrain={getDevice=function(n) return motors[n] end}
        ''')
        code = '''return function(s,m)
          m.calls=(m.calls or 0)+1
          if m.calls==3 then error('oops') end
          return {FL=-1,FR=0,RL=.25,RR=1}
        end'''
        ecu = lua.execute(build_controller(code))
        ecu.init()
        ecu.updateFixedStep(.01)
        lua.execute('for _,m in pairs(motors) do m:torqueUpdate(.01) end')
        motors = lua.globals().motors
        for n,value in [('FL',-1),('FR',0),('RL',.25),('RR',1)]:
            self.assertEqual(motors['evMotor'+n].seen,value)
            self.assertEqual(motors['evMotor'+n].motorDirection,-1)
            self.assertEqual(motors['evMotor'+n].torqueCoef,0)
        ecu.updateFixedStep(.01)
        ecu.updateFixedStep(.01)
        lua.execute('for _,m in pairs(motors) do m:torqueUpdate(.01) end')
        for n in ('FL','FR','RL','RR'):
            self.assertEqual(motors['evMotor'+n].seen,0)
        ecu.reset()
        ecu.updateFixedStep(.01)
        lua.execute('motors.evMotorFL:torqueUpdate(.01)')
        self.assertEqual(motors.evMotorFL.seen,-1)


if __name__ == '__main__':
    unittest.main()
