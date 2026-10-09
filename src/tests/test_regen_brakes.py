import json
import unittest
from patcher import JBeam
from tire_ecu_patch import apply, disable_friction_brakes, PRESET_FILE, DEFAULT_TIRE_PROFILE
import test_tire_ecu


class RegenBrakeTests(unittest.TestCase):
    def test_all_selectable_tires_have_zero_friction_brakes_and_keep_hardware(self):
        prefix='vehicles/Car/'
        entries=test_tire_ecu.TireTests().stock_fixture()
        entries[prefix+'engine.jbeam']=json.dumps({'engine':{
            'evMotor'+n:{'maxRegenTorque':0} for n in ('FL','FR','RL','RR')}}).encode()
        for axle in ('F','R'):
            path=prefix+'wheels_'+axle+'.jbeam'
            data=json.loads(entries[path]);part=data['wheels_'+axle]
            part['flexbodies']=[['mesh'],['brake_disc_mesh']]
            part['pressureWheels'][1].update(parkingTorque=1200,enableBrakeThermals=True)
            part['pressureWheels'][2][-1].update(brakeTorque=9999,parkingTorque=999,enableBrakeThermals=True)
            entries[path]=json.dumps(data).encode()
        settings=dict(ev_ecu_mode='Custom Lua',ev_tire_enabled=True,ev_tire_grip=1,
                      ev_tire_profile=DEFAULT_TIRE_PROFILE,ev_tire_carcass=True,ev_tire_ingame=True)
        result=apply(entries,prefix,settings)
        self.assertEqual(result,apply(result,prefix,settings))
        variants=json.loads(result[prefix+PRESET_FILE])
        self.assertEqual(len(variants),8)
        for axle in ('F','R'):
            variants.update(json.loads(result[prefix+'wheels_'+axle+'.jbeam']))
        self.assertEqual(len(variants),10)
        for part in variants.values():
            self.assertEqual(part['flexbodies'],[['mesh'],['brake_disc_mesh']])
            state={};count=0
            for row in part['pressureWheels'][1:]:
                if isinstance(row,dict):state.update(row);continue
                effective=dict(state);effective.update(row[-1]);count+=1
                self.assertEqual(effective['brakeTorque'],0)
                self.assertEqual(effective['parkingTorque'],999 if count==1 else 1200)
                self.assertFalse(effective['enableBrakeThermals'])
                self.assertIn(effective['nodeWeight'],(.03,.04))
            self.assertEqual(count,2)

    def test_unquoted_expression_and_missing_defaults_are_zeroed_idempotently(self):
        prefix='vehicles/Car/'
        raw=b'{"part":{"pressureWheels":[["name"],["FL",{brakeTorque:"$=$brake",parkingTorque:100,enableBrakeThermals:true}],["FR"]],"flexbodies":[["mesh"],["brakes"]]}}'
        entries={prefix+'wheels.jbeam':raw}
        result=disable_friction_brakes(entries,prefix)
        self.assertEqual(result,disable_friction_brakes(result,prefix))
        doc=JBeam(result[prefix+'wheels.jbeam'].decode())
        self.assertNotIn('$brake',doc.text)
        self.assertIn('brakeTorque:0',doc.text)
        self.assertIn('parkingTorque:100',doc.text)
        self.assertIn('enableBrakeThermals:false',doc.text)
        self.assertIn('"flexbodies":[["mesh"],["brakes"]]',doc.text)
