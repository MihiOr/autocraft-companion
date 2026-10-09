import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from electric_patch import read_curve, scale_curve, ratio_settings, electric_settings
from patcher import patch_zip, PatchError
from test_electric import ev_sample, ev_settings


class RatioTests(unittest.TestCase):
    def test_vertical_torque_scale_preserves_rpm_and_regen_and_does_not_compound(self):
        config=dict(ev_settings(),ev_ratio_enabled=True,ev_original_ratio='5.4',ev_ratio='4.3',ev_reference_speed='130')
        original=electric_settings(config)['curve']
        config['ev_torque_multiplier']='1,25'
        scaled=electric_settings(config)['curve']
        for (rpm,torque),(new_rpm,new_torque) in zip(original,scaled):
            self.assertEqual(rpm,new_rpm)
            self.assertAlmostEqual(new_torque,torque*1.25)
        with tempfile.TemporaryDirectory() as folder:
            paths=[Path(folder)/f'{i}.zip' for i in range(3)]
            ev_sample(paths[0]);patch_zip(paths[0],paths[1],config);patch_zip(paths[1],paths[2],config)
            with zipfile.ZipFile(paths[1]) as a,zipfile.ZipFile(paths[2]) as b:
                self.assertEqual({n:a.read(n) for n in a.namelist()},{n:b.read(n) for n in b.namelist()})
                part=json.loads(a.read('vehicles/Car/engine.jbeam'))['engine']
                for wheel in ('FL','FR','RL','RR'):
                    m=part['evMotor'+wheel]
                    self.assertEqual(m['torque'][1:],scaled)
                    for (rpm,t),(_,regen) in zip(original,m['regenTorqueCurve'][1:]):
                        self.assertAlmostEqual(regen,t*min(1,rpm/30))

    def test_scaling_power_comma_and_estimate(self):
        ratio=ratio_settings(dict(ev_ratio_enabled=True,ev_original_ratio='5,4',ev_ratio='4,3',ev_reference_speed='130'))
        original=read_curve(ev_settings()['ev_csv'])
        scaled=scale_curve(original,ratio)
        self.assertAlmostEqual(ratio['estimated_speed_kmh'],163.25581395348837)
        self.assertAlmostEqual(scaled[0][1],740.674*4.3/5.4)
        self.assertAlmostEqual(scaled[-1][0],1341*5.4/4.3)
        for (r,t),(new_r,new_t) in zip(original,scaled):
            self.assertAlmostEqual(r*t,new_r*new_t,places=7)
        self.assertEqual(scale_curve(original,ratio_settings({})),original)
        with self.assertRaises(PatchError): ratio_settings(dict(ev_ratio_enabled=True,ev_ratio='0'))

    def test_reapply_does_not_compound_and_disable_restores_curve(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[Path(folder)/f'{i}.zip' for i in range(4)]
            ev_sample(paths[0]);s=dict(ev_settings(),ev_ratio_enabled=True,ev_original_ratio='5.4',ev_ratio='4.3',ev_reference_speed='130')
            patch_zip(paths[0],paths[1],s);patch_zip(paths[1],paths[2],s)
            with zipfile.ZipFile(paths[1]) as a,zipfile.ZipFile(paths[2]) as b:
                self.assertEqual(a.read('vehicles/Car/engine.jbeam'),b.read('vehicles/Car/engine.jbeam'))
                part=json.loads(a.read('vehicles/Car/engine.jbeam'))['engine']
                expected=scale_curve(read_curve(s['ev_csv']),ratio_settings(s))
                for w in ('FL','FR','RL','RR'):
                    self.assertEqual(part['evMotor'+w]['torque'][1:],expected)
                    self.assertEqual(part['evHalfshaft'+w]['gearRatio'],1)
            s['ev_ratio_enabled']=False;patch_zip(paths[2],paths[3],s)
            with zipfile.ZipFile(paths[3]) as z:
                part=json.loads(z.read('vehicles/Car/engine.jbeam'))['engine']
                self.assertEqual(part['evMotorFL']['torque'][1:],read_curve(s['ev_csv']))
