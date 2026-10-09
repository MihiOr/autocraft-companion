import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from patcher import PatchError, patch_zip
from wheel_attachment_patch import patch_axle, apply
from test_companion import sample, settings


def fixture(axle):
    letter=axle.lower()
    beams=[['id1:','id2:'],{'beamStrength':1000,'beamDeform':100,
             'beamSpring':500000,'beamDamp':70,'breakGroup':'wheel_'+axle+'L'}]
    for side in ('l','r'):
        beams.append({'breakGroup':'wheel_'+axle+side.upper()})
        beams.append([letter+'w1'+side,letter+'w2'+side,{'beamStrength':'FLT_MAX','beamDeform':'FLT_MAX'}])
        for hub in ('w1','w2'):
            for upright in ('na','nc','h1','h2'):
                beams.append([letter+hub+side,letter+upright+side,
                              {'beamPrecompression':'$=1+$Toe_'+axle+'/175'}])
    beams.append([letter+'x3l',letter+'h2l'])
    return json.dumps({'suspension_'+axle:{'beams':beams}})


def effective(text,axle):
    state={};result={}
    for row in json.loads(text)['suspension_'+axle]['beams'][1:]:
        if isinstance(row,dict):state.update(row)
        else:
            opts=dict(state)
            if isinstance(row[-1],dict):opts.update(row[-1])
            result[tuple(row[:2])]=opts
    return result


class WheelAttachmentTests(unittest.TestCase):
    def test_only_mount_break_and_deformation_limits_change(self):
        for axle in ('F','R'):
            original=fixture(axle);text,report=patch_axle(original,axle,2)
            before=effective(original,axle);after=effective(text,axle)
            self.assertEqual(len(report),16)
            targeted={tuple(item['nodes']) for item in report}
            for pair,opts in before.items():
                expected=dict(opts)
                if pair in targeted:
                    expected['beamStrength']*=2;expected['beamDeform']*=2
                self.assertEqual(after[pair],expected)

    def test_inline_strength_overrides_and_infinite_limits(self):
        data=json.loads(fixture('F'))
        data['suspension_F']['beams'][4][-1].update(beamStrength=321,beamDeform='FLT_MAX')
        text=json.dumps(data).replace('"beamStrength": 321','beamStrength: 321')
        patched,report=patch_axle(text,'F',2)
        self.assertIn('beamStrength: 642,',patched)
        self.assertEqual(report[0]['beamStrength']['after'],642)
        self.assertNotIn('beamDeform',report[0])

    def test_settings_validation_and_missing_layout(self):
        entries={'vehicles/Car/suspension_'+a+'.jbeam':fixture(a).encode() for a in ('F','R')}
        self.assertEqual(apply(entries,'vehicles/Car/',{}),entries)
        result=apply(entries,'vehicles/Car/',{'wheel_attachment_enabled':True,'wheel_attachment_multiplier':'2,5'})
        report=json.loads(result['vehicles/Car/companion_wheel_attachment_report.json'])
        self.assertEqual(report['multiplier'],2.5)
        for value in ('NaN','0','-1','101','nonsense'):
            with self.assertRaises(PatchError):
                apply(entries,'vehicles/Car/',{'wheel_attachment_enabled':True,'wheel_attachment_multiplier':value})
        with self.assertRaisesRegex(PatchError,'eight'):
            patch_axle('{"suspension_F":{"beams":[["id1:","id2:"]]}}','F',2)

    def test_zip_reapply_multiplier_change_and_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[Path(tmp)/f'{i}.zip' for i in range(5)]
            sample(paths[0])
            with zipfile.ZipFile(paths[0]) as z:entries={n:z.read(n) for n in z.namelist()}
            for a in ('F','R'):entries['vehicles/Car/suspension_'+a+'.jbeam']=fixture(a).encode()
            with zipfile.ZipFile(paths[0],'w') as z:
                for n,data in entries.items():z.writestr(n,data)
            config=settings(suspension_enabled=False,wheel_attachment_enabled=True,wheel_attachment_multiplier='2')
            patch_zip(paths[0],paths[1],config);patch_zip(paths[1],paths[2],config)
            with zipfile.ZipFile(paths[1]) as a,zipfile.ZipFile(paths[2]) as b:
                self.assertEqual({n:a.read(n) for n in a.namelist()},{n:b.read(n) for n in b.namelist()})
            config['wheel_attachment_multiplier']='3'
            patch_zip(paths[2],paths[3],config)
            with zipfile.ZipFile(paths[3]) as z:
                report=json.loads(z.read('vehicles/Car/companion_wheel_attachment_report.json'))
                self.assertEqual(report['axles']['F'][0]['beamStrength']['after'],3000)
            config['wheel_attachment_enabled']=False
            patch_zip(paths[3],paths[4],config)
            with zipfile.ZipFile(paths[4]) as z:
                for a in ('F','R'):self.assertEqual(z.read('vehicles/Car/suspension_'+a+'.jbeam'),fixture(a).encode())
                self.assertNotIn('vehicles/Car/companion_wheel_attachment_report.json',z.namelist())
