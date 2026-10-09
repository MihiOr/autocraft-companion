"""Offline Scintilla conversion checks against the installed GTx source."""
import json
import os
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import civetta_patch as c


def parts(archive):
    result={}
    for name in archive.namelist():
        if name.endswith('.jbeam'):
            doc=c.JBeam(archive.read(name).decode('utf-8-sig'))
            for part,index in doc.props(0):
                if part in result:raise AssertionError('Duplicate part '+part)
                result[part]=c.data_value(doc,index)
    return result


def selected(all_parts,pc,main):
    result={}
    def visit(name):
        if not name or name in result or name not in all_parts:return
        p=result[name]=all_parts[name]
        for field in ('slots','slots2'):
            for row in p.get(field,[])[1:]:
                if isinstance(row,list) and len(row)>1:
                    visit(pc['parts'].get(row[0],row[3 if field=='slots2' else 1]))
    visit(main)
    return result


def unresolved(items):
    nodes={r[0] for p in items.values() for r in p.get('nodes',[])[1:] if isinstance(r,list)}
    refs={r[i] for p in items.values() for r in p.get('beams',[])[1:] if isinstance(r,list) and len(r)>1 for i in (0,1)}
    return refs-nodes


@unittest.skipUnless(os.environ.get('BEAMNG_HOME') and c.GAME.exists(),'Installed Scintilla source required')
class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings={'civetta_csv':str(c.ROOT/'one_wheel_realistic_overdrive_dyno.csv'),'civetta_capacity':'100','civetta_version':'v00'}
        c.build_physical(cls.settings)
        with zipfile.ZipFile(c.SOURCE) as z:
            cls.original=parts(z);cls.original_pc=json.loads(z.read('vehicles/scintilla/gtx.pc'))
        with zipfile.ZipFile(c.CACHE) as z:
            cls.converted=parts(z);cls.pc=json.loads(z.read('vehicles/'+c.BASE+'/gtx.pc'))
            cls.manifest=json.loads(z.read('vehicles/'+c.BASE+'/companion_civetta.json'))
            cls.integrity=z.testzip()
        cls.active=selected(cls.converted,cls.pc,c.BASE)
        cls.engine=cls.converted[c.BASE+'_engine_ev_direct']

    def test_four_exclusive_motors_without_old_drivetrain_or_assistance(self):
        devices=[r for p in self.active.values() for r in p.get('powertrain',[])[1:] if isinstance(r,list)]
        self.assertEqual(sorted(r[0] for r in devices),['electricMotor']*4+['shaft']*4+['torsionReactor']*4)
        controllers=[r[0] for p in self.active.values() for r in p.get('controller',[])[1:] if isinstance(r,list)]
        self.assertEqual(controllers.count('companion_custom_ecu'),1)
        for name in controllers:
            self.assertFalse(any(s in name.lower() for s in ('traction','yawcontrol','twosteplaunch','electronicdifflock','electronicsplitshaftlock','/cmu','postcrashbrake')))
        self.assertNotIn(c.BASE+'_transaxle_7DCT',self.active)
        for n in ('FL','FR','RL','RR'):
            motor=self.engine['evMotor'+n]
            self.assertEqual(motor['electricsThrottleName'],'companionCustom'+n)
            self.assertEqual(motor['electricsRegenThrottleName'],'companionCustomRegen'+n)
            self.assertEqual(self.engine['evHalfshaft'+n]['connectedWheel'],n)
            self.assertEqual(self.engine['evHalfshaft'+n]['gearRatio'],1)
            reactor='evReaction'+n
            self.assertIn(['torsionReactor',reactor,'evMotor'+n,1],devices)
            self.assertIn(['shaft','evHalfshaft'+n,reactor,1],devices)
            self.assertEqual(self.engine[reactor]['torqueReactionNodes:'],motor['torqueReactionNodes:'])
            self.assertEqual(self.engine['evHalfshaft'+n]['breakTriggerBeam'],'axle_'+n)
            self.assertAlmostEqual(max(t for _,t in motor['torque'][1:]),1500)

    def test_no_new_missing_attachments_and_stock_suspension_preserved(self):
        stock=selected(self.original,self.original_pc,'scintilla')
        self.assertLessEqual(unresolved(self.active),unresolved(stock))
        for suffix in ('chassis','subframe_R','suspension_F','suspension_R','steering','halfshafts_F','halfshafts_R','wheeldata_F','wheeldata_R'):
            for field in ('nodes','beams','hydros','torsionbars'):
                before=self.original['scintilla_'+suffix].get(field)
                after=self.converted[c.BASE+'_'+suffix].get(field)
                self.assertEqual(after,json.loads(json.dumps(before).replace('scintilla',c.BASE)))
        self.assertEqual(self.pc['parts']['tire_F_20x9'],self.original_pc['parts']['tire_F_20x9'])
        self.assertEqual(self.pc['parts']['tire_R_20x11'],self.original_pc['parts']['tire_R_20x11'])

    def test_virtual_battery_and_physical_parking_brake(self):
        self.assertEqual(self.manifest['battery_mass_kg'],0)
        stores=[r for p in self.active.values() for r in p.get('energyStorage',[])[1:]]
        self.assertEqual(stores,[['electricBattery','mainBattery']])
        self.assertEqual(self.engine['mainBattery']['batteryCapacity'],100)
        for axle in ('F','R'):
            rows=self.converted[c.BASE+'_brake_'+axle]['pressureWheels']
            self.assertTrue(any(isinstance(r,dict) and r.get('brakeTorque')==0 for r in rows))
        self.assertTrue(any(isinstance(r,dict) and r.get('parkingTorque',0)>0 for r in self.converted[c.BASE+'_brake_R']['pressureWheels']))
        self.assertNotIn('battery',json.dumps(self.engine.get('nodes',[])).lower())

    def test_imu_frames_use_existing_fixed_chassis_nodes(self):
        imu=self.engine['controller'][1][1]['imu']
        self.assertEqual(set(imu['mounts']),{'FL','FR','RL','RR'})
        nodes=c.positions(self.original['scintilla_chassis']);nodes.update(c.positions(self.original['scintilla_subframe_R']))
        for mount in imu['mounts'].values():
            self.assertEqual(len(set(mount['nodes'])),3)
            self.assertTrue(all(n in nodes and not n.startswith(('arf','arr')) for n in mount['nodes']))
            for axis in ('forward','left','up'):
                self.assertAlmostEqual(sum(v*v for v in mount[axis]),1)
            self.assertAlmostEqual(sum(a*b for a,b in zip(mount['forward'],mount['left'])),0)
        self.assertAlmostEqual(imu['wheelbase'],2.6547)

    def test_source_namespace_integrity_and_cache_reuse(self):
        self.assertIsNone(self.integrity)
        self.assertEqual(self.pc['model'],c.BASE)
        self.assertEqual(self.pc['parts']['main'],c.BASE)
        with zipfile.ZipFile(c.CACHE) as z:
            self.assertFalse(any(c.compiled_mesh_cache(n) for n in z.namelist()))
            self.assertIn('vehicles/'+c.BASE+'/'+c.BASE+'.dae',z.namelist())
            dae=z.read('vehicles/'+c.BASE+'/'+c.BASE+'.dae')
            for wheel in ('FL','FR','RL','RR'):
                self.assertIn((c.BASE+'_halfshaft_'+wheel).encode(),dae)
            for axle in ('F','R'):
                self.assertIn(c.BASE+'_halfshafts_'+axle,self.active)
        before=c.CACHE.stat().st_mtime_ns
        path,reused=c.build_physical(self.settings)
        self.assertTrue(reused);self.assertEqual(path.stat().st_mtime_ns,before)
        with zipfile.ZipFile(c.GAME) as stock,zipfile.ZipFile(c.SOURCE) as local:
            self.assertEqual(local.read('vehicles/scintilla/gtx.pc'),stock.read('vehicles/scintilla/gtx.pc'))
        old=c.signature(c.SOURCE,self.settings)
        new=c.signature(c.SOURCE,{**self.settings,'civetta_capacity':'101'})
        self.assertNotEqual(old,new)
        self.assertNotEqual(old,c.signature(c.SOURCE,{**self.settings,'civetta_peak_torque':'1400'}))


class ExportTests(unittest.TestCase):
    def test_sequential_local_export_and_current_lua_without_reconversion(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);cache=folder/'cache.zip'
            with zipfile.ZipFile(cache,'w') as z:
                z.writestr('vehicles/'+c.BASE+'/'+c.BASE+'.cdae',b'stale compiled meshes scintilla_body')
                z.writestr('vehicles/'+c.BASE+'/'+c.BASE+'.dae','<mesh name="'+c.BASE+'_body"/>')
                z.writestr('vehicles/'+c.BASE+'/info.json',json.dumps({'Name':'EV','default_pc':'gtx'}))
                z.writestr('vehicles/'+c.BASE+'/gtx.pc',json.dumps({'model':c.BASE,'parts':{'main':c.BASE}}))
            settings={'mods':str(folder/'mods'),'civetta_version':'v00','civetta_capacity':'100','civetta_csv':str(c.ROOT/'one_wheel_realistic_overdrive_dyno.csv')}
            with patch.object(c,'build_physical',return_value=(cache,True)) as build:
                first,_=c.export(settings);second,_=c.export(settings)
            self.assertEqual(first.name,'Civetta_v00_01.zip');self.assertEqual(second.name,'Civetta_v00_02.zip')
            self.assertEqual(build.call_count,2)
            with zipfile.ZipFile(second) as z:
                prefix='vehicles/Civetta_v00_02/'
                self.assertFalse(any(c.compiled_mesh_cache(n) for n in z.namelist()))
                self.assertEqual(z.read(prefix+'Civetta_v00_02.dae'),b'<mesh name="Civetta_v00_02_body"/>')
                self.assertEqual(json.loads(z.read(prefix+'gtx.pc'))['model'],'Civetta_v00_02')
                adapter=z.read(prefix+'lua/controller/companion_custom_ecu.lua').decode()
                self.assertNotIn('__USER_SOURCE__',adapter);self.assertNotIn('-- __IMU__',adapter)
                self.assertIn('function createIMUSampler',adapter)
                self.assertIn('setTestTorque',adapter)
                self.assertEqual(z.read(prefix+'custom_motor_control.lua').decode(),(c.ROOT/'civetta/custom_motor_control.lua').read_text())

    def test_invalid_modes_and_capacity_are_rejected(self):
        for bad in ({'civetta_version':'../v00'},{'civetta_capacity':'nan'},{'civetta_capacity':'0'},{'mods':''},{'civetta_peak_torque':'nan'},{'civetta_peak_torque':'-1'}):
            settings={'mods':'mods','civetta_version':'v00','civetta_capacity':'100','civetta_csv':str(c.ROOT/'one_wheel_realistic_overdrive_dyno.csv'),**bad}
            with self.assertRaises(ValueError):c.validate(settings)

if __name__=='__main__':unittest.main()
