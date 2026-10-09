"""Exercise the adapter against this machine's actual BeamNG torque function."""
from pathlib import Path
import os
import sys
import unittest
from custom_control import build_controller

sys.path.insert(0, str(Path(__file__).parent / '_runtime'))
from lupa.luajit21 import LuaRuntime

STOCK = Path(os.environ.get('BEAMNG_HOME','__no_game__'))/'lua/vehicle/powertrain/electricMotor.lua'


@unittest.skipUnless(STOCK.exists(), 'BeamNG installation needed for integration check')
class StockMotorTests(unittest.TestCase):
    def test_actual_motor_zero_full_and_reverse(self):
        text = STOCK.read_text()
        start = text.index('local function updateTorqueWithoutClutch(')
        end = text.index('\nlocal function ', start + 1)
        regen='return function() return {FL=0,FR=0,RL=0,RR=0,regen={FL=1,FR=.5,RL=0,RR=1}} end'
        for source, wanted, shaft_speed in [
            ('return function() return {FL=0,FR=0,RL=0,RR=0} end', 0, 0),
            ('return function() return {FL=1,FR=1,RL=1,RR=1} end', 740, 0),
            ('return function() return {FL=-1,FR=-1,RL=-1,RR=-1} end', -740, 0),
            (regen, {'FL':-300,'FR':-150,'RL':0,'RR':-300}, 20),
            (regen, {'FL':300,'FR':150,'RL':0,'RR':300}, -20),
            ('return function() return {FL=0,FR=0,RL=0,RR=0} end', 0, 20),
            (regen, 0, 0)]:
            lua = LuaRuntime()
            lua.execute('''
              abs=math.abs; floor=math.floor; min=math.min; max=math.max; avToRPM=9.549296586
              function clamp(v,a,b) return min(b,max(a,v)) end
              function sign(v) return v<0 and -1 or (v>0 and 1 or 0) end
              input={throttle=1,brake=0}; sensors={}; electrics={values={gearIndex=1,throttle=1,regenThrottle=1}}
              wheels={wheels={}}; motors={}; log=function() end
              obj={applyTorqueAxisCouple=function() end,
                getVelocity=function() return {length=function() return 0 end,dot=function() return 0 end} end,
                getDirectionVector=function() return {} end}
              powertrain={getDevice=function(n) return motors[n] end}
            ''')
            lua.globals().stockTorque = lua.execute(text[start:end] + '\nreturn updateTorqueWithoutClutch')
            lua.execute('''
              for _,n in ipairs({'FL','FR','RL','RR'}) do
                wheels.wheels[n]={name=n,wheelSpeed=0}
                motors['evMotor'..n]={
                  torqueUpdate=stockTorque,outputAV1=0,lastOutputAV1=0,outputRPM=0,
                  electricsThrottleName='companionCustom'..n,
                  electricsThrottleFactorName='companionCustomFactor',electricsRegenThrottleName='companionCustomRegen'..n,
                  throttleFactor=1,tempRevLimiterAV=10000,tempRevLimiterMaxAVOvershoot=100,invTempRevLimiterRange=.01,
                  isAffectedByIgnition=false,ignitionCoef=1,throttleSmoother={},motorDirection=1,
                  torqueCurve={[0]=740},torqueCoef=1,outputTorqueState=1,maxTorqueLimit=math.huge,
                  friction=0,dynamicFriction=0,regenCurve={[0]=0,[190]=300,[191]=300},minWantedRegenTorque=300,maxWantedRegenTorque=300,
                  loadSmoother={getCapped=function(_,x) return x end},inertia=.1,torqueReactionNodes={1,2,3},
                  grossWorkPerUpdate=0,spentEnergy=0,frictionLossPerUpdate=0,
                  electricalEfficiencyTable=setmetatable({},{__index=function() return .95 end})}
              end
            ''')
            for motor in lua.globals().motors.values():
                motor.outputAV1=shaft_speed
                motor.lastOutputAV1=shaft_speed
            ecu = lua.execute(build_controller(source))
            ecu.init()
            for _ in range(10):
                ecu.updateFixedStep(.01)
                lua.execute('for _,m in pairs(motors) do m:torqueUpdate(.01) end')
                for wheel in ('FL', 'FR', 'RL', 'RR'):
                    motor=lua.globals().motors['evMotor'+wheel]
                    torque=wanted[wheel] if isinstance(wanted,dict) else wanted
                    self.assertAlmostEqual(motor.outputTorque1,torque, msg=f"shaft={shaft_speed}, wheel={wheel}, regen={motor.regenThrottle}, raw={motor.instantMaxRegenTorque}")
                    self.assertEqual(motor.regenCurve[0],0)  # temporary lookup restored
                    if shaft_speed and torque:
                        self.assertLess(motor.spentEnergy,0)  # true recovered energy
                    elif not torque:
                        self.assertEqual(motor.spentEnergy,0)
            if isinstance(wanted,dict):
                start_energy=text.index('local function updateEnergyUsage(')
                end_energy=text.index('\nlocal function ',start_energy+1)
                lua.execute('battery={name="battery",storedEnergy=100,energyCapacity=100000}; energyStorage={getStorage=function() return battery end}')
                update=lua.execute(text[start_energy:end_energy]+'\nreturn updateEnergyUsage')
                motor=lua.globals().motors.evMotorFL
                motor.registeredEnergyStorages=lua.table_from(['battery'])
                motor.energyStorageRegenRatios=lua.table_from({'battery':1})
                motor.energyStorageRatios=lua.table_from({'battery':1})
                motor.previousEnergyLevels=lua.table_from({'battery':100})
                motor.energyStorage='battery'
                motor.hasEnergy=True
                update(motor)
                self.assertGreater(lua.globals().battery.storedEnergy,100)
