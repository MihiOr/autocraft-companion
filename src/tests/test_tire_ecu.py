import json
from pathlib import Path
import sys
import unittest
from patcher import JBeam, PatchError
from tire_ecu_patch import apply, stock_profiles, DEFAULT_TIRE_PROFILE, validate, PRESET_FILE


class TireTests(unittest.TestCase):
    def stock_fixture(self):
        prefix='vehicles/Car/'
        entries={prefix+'companion_ev_report.json':b'{}'}
        for axle in ('F','R'):
            entries[prefix+'wheels_'+axle+'.jbeam']=json.dumps({'wheels_'+axle:{'pressureWheels':[
                ['name','hubGroup','group','node1:','node2:','nodeS','nodeArm:','wheelDir'],
                {'nodeWeight':.03,'hubNodeWeight':.25,'numRays':16,'radius':.313,
                 'hubRadius':.216,'tireWidth':.17272,'pressurePSI':'$tirepressure_'+axle,
                 'brakeTorque':2500,'collision':True,'selfCollision':False,
                 'wheelTreadBeamStrength':18000},
                [axle+'L','hub','tire','a','b',9999,'c',1,{'nodeCoupling:':'d','frictionCoef':.7}],
                [axle+'R','hub','tire','a','b',9999,'c',-1,{'nodeCoupling:':'e','nodeWeight':.04}]]}}).encode()
        return entries

    def test_stock_profiles_preserve_mass_geometry_brakes_and_reapply(self):
        prefix='vehicles/Car/'
        source=self.stock_fixture()
        for profile,donors in stock_profiles().items():
            settings={'ev_tire_enabled':True,'ev_tire_grip':'1,1','ev_tire_profile':profile,
                      'ev_tire_carcass':True,'ev_ecu_mode':'Off'}
            result=apply(source,prefix,settings)
            self.assertEqual(result,apply(result,prefix,settings))
            for axle in ('F','R'):
                name=prefix+'wheels_'+axle+'.jbeam'
                old=json.loads(source[name])['wheels_'+axle]['pressureWheels']
                new=json.loads(result[name])['wheels_'+axle]['pressureWheels']
                donor=donors[axle]
                self.assertEqual(old[1],new[1])
                for before,after,mass in zip(old[2:],new[2:],(.03,.04)):
                    self.assertEqual(before[:-1],after[:-1])
                    self.assertEqual(after[-1].get('nodeWeight',new[1]['nodeWeight']),mass)
                    for key,value in before[-1].items():
                        if key!='frictionCoef':self.assertEqual(after[-1][key],value)
                    for key,value in donor['rubber'].items():
                        self.assertAlmostEqual(after[-1][key],value*1.1 if key in ('frictionCoef','slidingFrictionCoef') else value)
                    scale=mass/donor['reference_node_mass']
                    self.assertAlmostEqual(after[-1]['wheelTreadBeamSpring'],donor['carcass']['wheelTreadBeamSpring']*scale)
                    self.assertAlmostEqual(after[-1]['wheelTreadBeamDamp'],donor['carcass']['wheelTreadBeamDamp']*scale)
                    self.assertEqual(after[-1]['wheelTreadBeamDampCutoffHz'],donor['carcass']['wheelTreadBeamDampCutoffHz'])
                    self.assertTrue(after[-1]['wheelSideBeamSpring'].startswith('$=($tirepressure_'+axle))
                    for key in ('radius','brakeTorque','hubNodeWeight','wheelTreadBeamStrength'):
                        self.assertNotIn(key,after[-1])

    def test_empty_or_absent_wheel_options_and_rubber_only(self):
        prefix='vehicles/Car/'
        settings={'ev_tire_enabled':True,'ev_tire_grip':1,'ev_tire_profile':DEFAULT_TIRE_PROFILE,
                  'ev_tire_carcass':False,'ev_ecu_mode':'Off'}
        for inline in (None,{}):
            entries=self.stock_fixture()
            for axle in ('F','R'):
                name=prefix+'wheels_'+axle+'.jbeam';data=json.loads(entries[name])
                table=data['wheels_'+axle]['pressureWheels']
                del table[1]['nodeWeight']
                for row in table[2:]:
                    row.pop()
                    if inline is not None:row.append(inline)
                entries[name]=json.dumps(data).encode()
            result=apply(entries,prefix,settings)
            for axle in ('F','R'):
                table=json.loads(result[prefix+'wheels_'+axle+'.jbeam'])['wheels_'+axle]['pressureWheels']
                for row in table[2:]:
                    self.assertEqual(row[-1]['frictionCoef'],1)
                    self.assertNotIn('wheelTreadBeamSpring',row[-1])

    def test_disabled_unknown_profile_and_invalid_mass(self):
        prefix='vehicles/Car/'
        entries=self.stock_fixture()
        result=apply(entries,prefix,{'ev_tire_enabled':False,'ev_ecu_mode':'Off'})
        for axle in ('F','R'):
            name=prefix+'wheels_'+axle+'.jbeam'
            self.assertEqual(entries[name],result[name])
        with self.assertRaises(PatchError):
            validate({'ev_tire_enabled':True,'ev_tire_grip':1,'ev_tire_profile':'not a tire'})
        for axle in ('F','R'):
            name=prefix+'wheels_'+axle+'.jbeam';data=json.loads(entries[name])
            data['wheels_'+axle]['pressureWheels'][1]['nodeWeight']=0
            entries[name]=json.dumps(data).encode()
        with self.assertRaisesRegex(PatchError,'node mass'):
            apply(entries,prefix,{'ev_tire_enabled':True,'ev_tire_grip':1,
                                 'ev_tire_profile':DEFAULT_TIRE_PROFILE,'ev_ecu_mode':'Off'})

    def test_ingame_choices_keep_original_and_use_existing_wheel_slots(self):
        prefix='vehicles/Car/'
        source=self.stock_fixture()
        settings={'ev_tire_enabled':True,'ev_tire_grip':1,'ev_tire_profile':DEFAULT_TIRE_PROFILE,
                  'ev_tire_carcass':True,'ev_tire_ingame':True,'ev_ecu_mode':'Off'}
        result=apply(source,prefix,settings)
        self.assertEqual(result,apply(result,prefix,settings))
        parts=json.loads(result[prefix+PRESET_FILE])
        self.assertEqual(len(parts),8)
        for axle in ('F','R'):
            default=json.loads(result[prefix+'wheels_'+axle+'.jbeam'])['wheels_'+axle]
            self.assertIn(DEFAULT_TIRE_PROFILE,default['information']['name'])
            original=json.loads(source[prefix+'wheels_'+axle+'.jbeam'])['wheels_'+axle]['pressureWheels']
            for tag in ('autocraft','sport_plus','race_slicks','legacy'):
                part=parts['companion_tires_'+axle+'_'+tag]
                self.assertEqual(part['slotType'],'wheels_'+axle)
                table=part['pressureWheels']
                self.assertEqual(table[0:2],original[0:2])
                self.assertEqual(len(table),len(original))
                for wheel,before in zip(table[2:],original[2:]):
                    self.assertEqual(wheel[:-1],before[:-1])
                    self.assertEqual(wheel[-1].get('nodeWeight',table[1]['nodeWeight']),
                                     before[-1].get('nodeWeight',original[1]['nodeWeight']))
                if tag=='autocraft':self.assertEqual(table,original)
                if tag=='sport_plus':self.assertEqual(table,default['pressureWheels'])
        # Companion's switches can leave the original single wheel part alone.
        settings['ev_tire_ingame']=False
        self.assertNotIn(prefix+PRESET_FILE,apply(source,prefix,settings))

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
        sys.path.insert(0,str(Path(__file__).parent/'_runtime'))
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
