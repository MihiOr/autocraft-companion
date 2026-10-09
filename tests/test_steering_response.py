import json
import unittest
from steering_response_patch import apply
from patcher import PatchError


class SteeringResponseTests(unittest.TestCase):
    def test_only_steering_rates_change_and_reapply_is_identical(self):
        name='vehicles/Car/suspension_F.jbeam'
        original={'suspension_F':{'hydros':[
            ['id1:','id2:'],{'beamSpring':700000,'beamDamp':5,'inRate':2},
            ['a','b',{'factor':.9,'steeringWheelLock':480}],
            ['c','d',{'factor':-.9,'inRate':3,'outRate':4}],
            {'inputSource':'door'},['e','f',{'inRate':.2}]]}}
        entries={name:json.dumps(original).encode()}
        patched=apply(entries,'vehicles/Car/',{'steering_hydro_rate':'20,0'})
        table=json.loads(patched[name])['suspension_F']['hydros']
        for index in (2,3):
            for key in ('inRate','outRate','autoCenterRate'): self.assertEqual(table[index][-1][key],20)
            for key,value in original['suspension_F']['hydros'][index][-1].items():
                if key not in ('inRate','outRate'): self.assertEqual(table[index][-1][key],value)
        self.assertEqual(table[1],original['suspension_F']['hydros'][1])
        self.assertEqual(table[4:],original['suspension_F']['hydros'][4:])
        self.assertEqual(apply(patched,'vehicles/Car/',{'steering_hydro_rate':20}),patched)

    def test_missing_hydros_and_invalid_rate_are_reported(self):
        with self.assertRaises(PatchError): apply({},'vehicles/Car/',{})
        with self.assertRaises(PatchError): apply({},'vehicles/Car/',{'steering_hydro_rate':0})
