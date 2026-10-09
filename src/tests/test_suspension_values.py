import json
import unittest
from suspension_values import evaluate, inspect_entries, apply_absolute
from patcher import PatchError, validate_settings
from test_companion import settings


class SuspensionValuesTests(unittest.TestCase):
    def test_independent_multipliers_and_disabled_or_blank_fields(self):
        s=settings()
        s.update(suspension_absolute=True,front_length='400',rear_length='300',front_rate='10000',rear_rate='20000',front_damping='1000',rear_damping='2000')
        for key,m in {'front_length':1.1,'rear_length':.9,'front_rate':1.2,'rear_rate':.8,'front_damping':.5,'rear_damping':2}.items():
            s[key+'_multiplier']=str(m)
        v=validate_settings(s)
        for key,want in {'front_length':440,'rear_length':270,'front_rate':12000,'rear_rate':16000,'front_damping':500,'rear_damping':4000}.items():
            self.assertAlmostEqual(v[key],want)
        s['front_rate']=''
        s['front_rate_multiplier']='bad'
        self.assertIsNone(validate_settings(s)['front_rate'])
        s['suspension_enabled']=False
        self.assertIsNone(validate_settings(s)['rear_length'])
        s.update(suspension_enabled=True,front_length_multiplier=100)
        with self.assertRaises(PatchError):validate_settings(s)

    def test_arithmetic_is_safe(self):
        self.assertEqual(evaluate('$=($Damp_F+2)*0.5',{'$Damp_F':8}),5)
        with self.assertRaises(PatchError):evaluate('__import__("os").getcwd()',{})

    def test_pair_averages_and_absolute_rest_lengths(self):
        prefix='vehicles/Car/';entries={}
        for axle in ('F','R'):
            part={'suspension_'+axle:{'nodes':[['id','posX','posY','posZ'],['a',0,0,0],['b',1,0,0],['c',2,0,0]]},
                  'coils_'+axle:{'beams':[['id1:','id2:'],{'beamPrecompression':1,'beamSpring':100},['a','b'],['a','c',{'beamSpring':300}]]},
                  'dampers_'+axle:{'beams':[['id1:','id2:'],{'beamDamp':10},['a','b'],['a','c',{'beamDamp':30}]]}}
            entries[prefix+'suspension_'+axle+'.jbeam']=json.dumps(part).encode()
        v,_,_,_=inspect_entries(entries,prefix)
        self.assertEqual(v['front_length'],1500)
        self.assertEqual(v['front_rate'],200)
        self.assertEqual(v['rear_damping'],20)
        v.update(front_length=1200,rear_length=900)
        result=apply_absolute(entries,prefix,v)
        new,_,_,_=inspect_entries(result,prefix)
        self.assertEqual(new,v)

    def test_disabled_fields_are_not_validated(self):
        s=settings();s.update(suspension_enabled=False,suspension_absolute=True,front_length='bad',front_rate='bad',rear_damping='bad')
        v=validate_settings(s)
        self.assertIsNone(v['front_length'])
        self.assertIsNone(v['front_rate'])
