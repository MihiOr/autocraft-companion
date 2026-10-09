import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from electric_patch import read_curve, convert, node_positions
from patcher import patch_zip, JBeam, PatchError
from test_companion import sample, settings


def ev_settings():
    return dict(settings(), electric_enabled=True,
                ev_csv=str(Path(__file__).resolve().parents[1] / 'one_wheel_realistic_overdrive_dyno.csv'),
                ev_curve_mode='Wheel output (direct drive)', ev_capacity='100', ev_battery_mass='500',
                ev_motor_mass='35', ev_inertia='.1', ev_regen='15')


def ev_sample(path):
    sample(path)
    with zipfile.ZipFile(path) as z: entries={n:z.read(n) for n in z.namelist()}
    main={'information':{'name':'Concept'},'slots':[['type','default','description'],['engine','engine','Engine'],
          ['drivetrain','drivetrain','Drivetrain'],['radiator','radiator','Radiator'],['fueltank','fueltank','Fuel']],
          'nodes':[['id','posX','posY','posZ']]+[[f'cc{i}',x,y,z] for i,(x,y,z) in enumerate(
              [(0,-.5,.2),(0,.5,.2),(3,-.5,.2),(3,.5,.2),(1,-.5,.6),(1,.5,.6)])]}
    entries['vehicles/Car/main.jbeam']=json.dumps({'main':main}).encode()
    for axle,x in [('F',3),('R',0)]:
        n='vehicles/Car/suspension_'+axle+'.jbeam';s=entries[n].decode()
        rows=[['id','posX','posY','posZ']]
        for side,sign in [('l',1),('r',-1)]:
            for i in range(1,5): rows.append([axle.lower()+'x'+str(i)+side,x+(i%2)*.1,.4*sign,.2+(i//3)*.2])
            for name,y in [('w1',.85),('w2',1.15),('na',.9)]:rows.append([axle.lower()+name+side,x,y*sign,.313])
            rows.append([axle.lower()+'h1'+side,x,.9*sign,.463])
        # Append a separate suspension part to the existing comma-optional fixture.
        entries[n]=(s.rstrip()[:-1]+', '+json.dumps('suspension_'+axle)+':'+json.dumps({'nodes':rows})+'}').encode()
    for file in ('drivetrain','radiator','fueltank'):
        entries['vehicles/Car/'+file+'.jbeam']=json.dumps({file:{'nodes':[['id','posX','posY','posZ']]}}).encode()
    with zipfile.ZipFile(path,'w') as z:
        for n,raw in entries.items():z.writestr(n,raw)


class ElectricTests(unittest.TestCase):
    def test_csv_uses_one_wheel_curve_without_gearing(self):
        curve=read_curve(ev_settings()['ev_csv'])
        self.assertEqual(curve[0],[0,740.674])
        self.assertEqual(curve[-1][0],1341)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.csv'
            p.write_text('wheel_rpm,motor_rpm,wheel_torque_nm,wheel_power_kw\n0,0,NaN,0\n')
            with self.assertRaises(PatchError):read_curve(p)

    def test_four_motors_geometry_and_reversible_patch(self):
        with tempfile.TemporaryDirectory() as t:
            paths=[Path(t)/f'{i}.zip' for i in range(4)]
            ev_sample(paths[0]);s=ev_settings()
            patch_zip(paths[0],paths[1],s)
            patch_zip(paths[1],paths[2],s)
            with zipfile.ZipFile(paths[1]) as a,zipfile.ZipFile(paths[2]) as b:
                self.assertEqual({n:a.read(n) for n in a.namelist()},{n:b.read(n) for n in b.namelist()})
                motor=json.loads(a.read('vehicles/Car/engine.jbeam'))['engine']
                devices=motor['powertrain'][1:]
                self.assertEqual([r[0] for r in devices].count('electricMotor'),4)
                self.assertEqual([r[0] for r in devices].count('shaft'),4)
                self.assertEqual(len(devices),8)
                for wheel in ('FL','FR','RL','RR'):
                    self.assertEqual(motor['evHalfshaft'+wheel]['connectedWheel'],wheel)
                    self.assertEqual(motor['evHalfshaft'+wheel]['gearRatio'],1)
                report=json.loads(a.read('vehicles/Car/companion_ev_report.json'))
                for shaft in report['shafts'].values():
                    self.assertAlmostEqual(shaft['length_m'],math.dist(shaft['motor_output_m'],shaft['wheel_center_m']))
                ET.fromstring(a.read('vehicles/Car/companion_ev.dae'))
                for n in a.namelist():
                    if n.endswith('.jbeam'):JBeam(a.read(n).decode())
                self.assertNotIn('vehicles/Car/drivetrain.jbeam',a.namelist())
            s['electric_enabled']=False
            patch_zip(paths[2],paths[3],s)
            with zipfile.ZipFile(paths[3]) as z:
                self.assertIn('vehicles/Car/drivetrain.jbeam',z.namelist())
                self.assertNotIn('vehicles/Car/companion_ev.dae',z.namelist())
                self.assertIn(b'mainEngine',z.read('vehicles/Car/engine.jbeam'))
