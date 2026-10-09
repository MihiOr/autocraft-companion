import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from patcher import (patch_engine, patch_zip, install_zip, PatchError, JBeam, MANIFEST)
from site_client import Page, garage_download, SiteError


class WorkflowTests(unittest.TestCase):
    def test_website_delete_clears_only_matching_saved_order(self):
        import app
        import threading
        import queue
        for pending_id in ('554', '555'):
            runner = MagicMock()
            runner.cancel = threading.Event()
            runner.events = queue.Queue()
            client = MagicMock()
            client.delete_order.return_value = {}
            config = {'email': 'test', 'password': 'test', 'pending': {'id': pending_id}}
            with patch('app.Client', return_value=client), patch('app.install_zip') as install:
                app.Companion.run_job(runner, 'delete_order', config, {'id': '554', 'name': 'Car'})
            client.delete_order.assert_called_once_with('554', 'Car')
            install.assert_not_called()
            if pending_id == '554':
                runner.persist.assert_called_once_with({'pending': None})
            else:
                runner.persist.assert_not_called()
            self.assertEqual(list(runner.events.queue), [('orders', {}), ('done', None)])

    def test_remove_order_keeps_settings_and_download(self):
        import app
        runner = MagicMock()
        runner.worker = None
        runner.settings = {'pending': {'id': '550'}, 'front_lift': '100', 'last_download': 'original.zip'}
        app.Companion.remove_order(runner)
        self.assertEqual(runner.settings, {'front_lift': '100', 'last_download': 'original.zip'})
        runner.save.assert_called_once()
        runner.worker = MagicMock()
        runner.worker.is_alive.return_value = True
        runner.settings['pending'] = {'id': '551'}
        app.Companion.remove_order(runner)
        self.assertIn('pending', runner.settings)

    def test_resume_copied_order_submits_and_finishes_without_reupload(self):
        import app
        import threading
        import queue
        pending = {'id': '550', 'name': 'ExampleCar', 'state': 'uploaded',
                   'fields': {'rid': '550', 'vFile': '550_999_ExampleCar.vcl', 'submit2': 'Submit mod request'},
                   'action': 'https://delta-cross.com/Submitmod.php#'}
        config = dict(settings(), pending=pending, email='test', password='test', mods='unused')
        runner = MagicMock()
        runner.cancel = threading.Event()
        runner.events = queue.Queue()
        c = MagicMock()
        copied = {'550': {'id': '550', 'name': 'ExampleCar', 'status': 'copied'}}
        processed = {'550': {'id': '550', 'name': 'ExampleCar', 'status': 'processed'}}
        c.orders.side_effect = [copied, processed]
        c.garage_html.return_value = '<a href="downloadUser.php?fp=mods/550_999_ExampleCar.zip">Download</a>'
        with patch('app.Client', return_value=c), patch('app.patch_zip', return_value='ExampleCar'), \
             patch('app.install_zip', return_value=(Path('ExampleCar.zip'), None)):
            app.Companion.run_job(runner, 'resume', config, None)
        c.upload.assert_not_called()
        c.submit.assert_called_once()
        c.download.assert_called_once()
        states = [call.args[0]['pending']['state'] for call in runner.persist.call_args_list if 'pending' in call.args[0]]
        self.assertEqual(states, ['submitting', 'submitted', 'processed', 'installed'])
        self.assertEqual(list(runner.events.queue), [('done', None)])

    def test_processed_order_does_not_submit_twice(self):
        from site_client import needs_submission
        pending = {'id': '550', 'name': 'ExampleCar', 'state': 'uploaded'}
        for status in ('submitted', 'processing', 'processed'):
            self.assertFalse(needs_submission(pending, {'name': 'ExampleCar', 'status': status}))
        with self.assertRaises(SiteError):
            needs_submission(pending, {'name': 'OtherCar', 'status': 'copied'})


def settings(**kw):
    return dict(front_lift='2', rear_lift='3', front_rate='', rear_rate='',
                front_damping='', rear_damping='', clear_glass=True, glass_opacity='0.1', **kw)


ENGINE = '{"engine":{"mainEngine":{"torque":[["rpm","torque"],[350,577],[8000,969]],"idleRPM":600}}}'


def suspension(axle, base, rate):
    return ('{"suspension_' + axle + '":{"variables":[["name","type"],'
            '["$Damp_bump_' + axle + '","range","Ns/m","Suspension",100,0,200],'
            '["$Damp_rebd_' + axle + '","range","Ns/m","Suspension",100,0,200]]},'
            '"coils_' + axle + '":{"beams":[{"beamPrecompression":"$=(1+$RH_' + axle +
            '*-0.001)*' + str(base) + '"},{"beamSpring":' + str(rate) + '},["a","b"]]}}')


def sample(path):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('vehicles/Car/info.json', json.dumps({'Name': 'Concept'}))
        z.writestr('vehicles/Car/main.jbeam', '{"main":{"information":{"name":"Concept"}}}')
        z.writestr('vehicles/Car/paths.json', '{"texture":"vehicles/Car/body.png", "shared":"vehicles/textures/a.dds"}')
        z.writestr('vehicles/textures/a.dds', b'texture')
        z.writestr('vehicles/Car/engine.jbeam', ENGINE)
        z.writestr('vehicles/Car/suspension_F.jbeam', suspension('F', 1.4, 72960))
        z.writestr('vehicles/Car/suspension_R.jbeam', suspension('R', 1.3, 45192))
        z.writestr('vehicles/Car/main.materials.json', json.dumps({'Glass': {'mapTo': 'Glass', 'dynamicCubemap': True,
            'Stages': [{'metallicFactor': 1, 'opacityFactor': 0.25}]}, 'Paint': {'Stages': [{'metallicFactor': 1}]}}))
        z.writestr('vehicles/Car/mesh.dae', b'unchanged mesh')


class Tests(unittest.TestCase):
    def test_order_links_stay_with_their_rows(self):
        from site_client import parse_orders
        html = ('<table><tr><th>id</th><th>File Name</th><th>Status</th></tr>'
                '<tr><td>554</td><td>Car &amp; A</td><td>processed</td><td><a href="deletereq.php?rid=554">Delete(+2&#9021;)</a></td></tr>'
                '<tr><td>555</td><td>Other</td><td>processing</td><td><a href="#"></a></td></tr>'
                '<tr><td>556</td><td>Bad link</td><td>copied</td><td><a href="deletereq.php?rid=554">Delete</a></td></tr></table>')
        rows = parse_orders(html)
        self.assertEqual(rows['554']['name'], 'Car & A')
        self.assertEqual(rows['554']['delete_url'], 'https://delta-cross.com/deletereq.php?rid=554')
        self.assertIsNone(rows['555']['delete_url'])
        self.assertIsNone(rows['556']['delete_url'])
        with self.assertRaises(SiteError):
            parse_orders('<html>Something went wrong</html>')

    def test_delete_rechecks_target_and_verifies_removal(self):
        from site_client import Client
        c = Client()
        row = {'name': 'Car', 'delete_url': 'https://delta-cross.com/deletereq.php?rid=554'}
        c.orders = MagicMock(side_effect=[{'554': row}, {}])
        c.request = MagicMock()
        self.assertEqual(c.delete_order('554', 'Car'), {})
        c.request.assert_called_once_with('GET', row['delete_url'])
        c.request.reset_mock()
        c.orders = MagicMock(return_value={})
        c.delete_order('554', 'Car')
        c.request.assert_not_called()
        c.orders = MagicMock(return_value={'554': row})
        with self.assertRaises(SiteError):
            c.delete_order('554', 'Wrong name')
        c.request.assert_not_called()
        c.orders = MagicMock(side_effect=[{'554': row}, {'554': row}])
        with self.assertRaises(SiteError):
            c.delete_order('554', 'Car')

    def test_delete_rejects_foreign_or_wrong_id_url(self):
        from site_client import Client
        for url in ('https://example.com/deletereq.php?rid=554',
                    'https://delta-cross.com/deletereq.php?rid=555',
                    'https://delta-cross.com/deletereq.php?rid=554&rid=555'):
            c = Client()
            c.orders = MagicMock(return_value={'554': {'name': 'Car', 'delete_url': url}})
            c.request = MagicMock()
            with self.assertRaises(SiteError):
                c.delete_order('554', 'Car')
            c.request.assert_not_called()

    def test_starter_insert_order_and_replacement(self):
        for source in (ENGINE, ENGINE.replace('"idleRPM":600', '"starterMaxRPM":250,"idleRPM":600')):
            result = patch_engine(source)
            d = json.loads(result)['engine']['mainEngine']
            self.assertEqual(d['starterMaxRPM'], 500)
            self.assertEqual(list(d)[:2], ['torque', 'starterMaxRPM'])
            self.assertEqual(result.count('"starterMaxRPM"'), 1)
        # Braces in comments/strings are not syntax, and AutoCraft omits some commas.
        self.assertIn('500', patch_engine(ENGINE.replace('"idleRPM"', '/* } ] */ "idleRPM"')))

    def test_patches_noncompounding_and_restore_glass(self):
        with tempfile.TemporaryDirectory() as t:
            a, b, c, d = [Path(t) / n for n in ('a.zip', 'b.zip', 'c.zip', 'd.zip')]
            sample(a)
            patch_zip(a, b, settings())
            patch_zip(b, c, settings())
            with zipfile.ZipFile(b) as zb, zipfile.ZipFile(c) as zc, zipfile.ZipFile(a) as za:
                for n in zb.namelist():
                    self.assertEqual(zb.read(n), zc.read(n))
                self.assertEqual(zb.read('vehicles/Car/mesh.dae'), za.read('vehicles/Car/mesh.dae'))
                mat = json.loads(zb.read('vehicles/Car/main.materials.json'))
                self.assertEqual(mat['Paint'], {'Stages': [{'metallicFactor': 1}]})
                self.assertFalse(mat['Glass']['dynamicCubemap'])
                self.assertIn(b'*1.428"', zb.read('vehicles/Car/suspension_F.jbeam'))
            s = settings()
            s['clear_glass'] = False
            s['front_lift'] = '0'
            patch_zip(c, d, s)
            with zipfile.ZipFile(a) as za, zipfile.ZipFile(d) as zd:
                self.assertEqual(json.loads(za.read('vehicles/Car/main.materials.json')),
                                 json.loads(zd.read('vehicles/Car/main.materials.json')))

    def test_invalid_export_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / 'a.zip', Path(t) / 'b.zip'
            sample(a)
            # Build invalid replacement without duplicate ZIP members.
            with zipfile.ZipFile(a) as z:
                entries = {n: z.read(n) for n in z.namelist()}
            entries['vehicles/Car/suspension_F.jbeam'] = suspension('F', -20, -1470).encode()
            with zipfile.ZipFile(a, 'w') as z:
                for n, data in entries.items():
                    z.writestr(n, data)
            with self.assertRaises(PatchError):
                patch_zip(a, b, settings())
            self.assertFalse(b.exists())

    def test_nan_and_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / 'a.zip', Path(t) / 'b.zip'
            sample(a)
            s = settings()
            s['front_lift'] = 'nan'
            with self.assertRaises(PatchError):
                patch_zip(a, b, s)
            with zipfile.ZipFile(a, 'a') as z:
                z.writestr('../escape', 'bad')
            with self.assertRaises(PatchError):
                patch_zip(a, b, settings())

    def test_install_keeps_existing_mods_and_numbers_copies(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            mods, backups = base / 'mods', base / 'backups'
            mods.mkdir()
            sample(base / 'new.zip')
            sample(mods / 'old.zip')
            old = (mods / 'old.zip').read_bytes()
            unpacked = mods / 'unpacked' / 'Car'
            (unpacked / 'vehicles' / 'Car').mkdir(parents=True)
            (unpacked / 'vehicles' / 'Car' / 'engine.jbeam').write_text('old')
            (mods / 'unrelated.txt').write_text('keep')
            with patch('patcher.renamed_zip', side_effect=OSError('simulated disk failure')):
                with self.assertRaises(OSError):
                    install_zip(base / 'new.zip', mods, backups)
            self.assertEqual((mods / 'old.zip').read_bytes(), old)
            self.assertTrue(unpacked.exists())
            target, backup = install_zip(base / 'new.zip', mods, backups)
            self.assertTrue(target.is_file())
            self.assertEqual(target.name, 'Car_01.zip')
            self.assertIsNone(backup)
            original = target.read_bytes()
            seen = {target.name}
            for number in range(2, 5):
                installed, backup = install_zip(base / 'new.zip', mods, backups)
                self.assertEqual(installed.name, f'Car_{number:02d}.zip')
                self.assertNotIn(installed.name, seen)
                seen.add(installed.name)
                self.assertIsNone(backup)
            self.assertEqual(target.read_bytes(), original)
            self.assertTrue(unpacked.exists())
            self.assertEqual((mods / 'old.zip').read_bytes(), old)
            self.assertFalse(backups.exists())
            self.assertEqual(list(mods.glob('.companion-*')), [])
            self.assertEqual((mods / 'unrelated.txt').read_text(), 'keep')

    def test_install_preserves_invalid_zip_with_same_name(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            mods = base / 'mods'
            mods.mkdir()
            sample(base / 'new.zip')
            (mods / 'Car.zip').write_bytes(b'old broken zip')
            target, _ = install_zip(base / 'new.zip', mods, base / 'backups')
            self.assertEqual(target.name, 'Car_01.zip')
            self.assertEqual((mods / 'Car.zip').read_bytes(), b'old broken zip')

    def test_duplicate_identity_paths_and_repatch(self):
        from patcher import vehicle_roots
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            sample(base / 'source.zip')
            patch_zip(base / 'source.zip', base / 'patched.zip', settings())
            first, _ = install_zip(base / 'patched.zip', base / 'mods', base / 'backups')
            self.assertEqual(first.name, 'Car.zip')
            second, _ = install_zip(base / 'patched.zip', base / 'mods', base / 'backups')
            suffix = second.stem.rsplit('_', 1)[1]
            with zipfile.ZipFile(second) as z:
                root = next(iter(vehicle_roots(z.namelist())))
                self.assertRegex(root, r'^Car_[0-9]{12}$')
                self.assertEqual(json.loads(z.read(f'vehicles/{root}/info.json'))['Name'], 'Concept_' + suffix)
                self.assertIn(('Concept_' + suffix).encode(), z.read(f'vehicles/{root}/main.jbeam'))
                paths = json.loads(z.read(f'vehicles/{root}/paths.json'))
                self.assertEqual(paths['texture'], f'vehicles/{root}/body.png')
                self.assertEqual(z.read(paths['shared']), b'texture')
                self.assertFalse(any(n.startswith('vehicles/Car/') for n in z.namelist()))
            patch_zip(second, base / 'repatched.zip', settings())
            with zipfile.ZipFile(second) as a, zipfile.ZipFile(base / 'repatched.zip') as b:
                self.assertEqual({n: a.read(n) for n in a.namelist()}, {n: b.read(n) for n in b.namelist()})

    def test_install_sequence_skips_gaps_and_existing_legacy_numbers(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            mods = base / 'mods'
            mods.mkdir()
            sample(base / 'new.zip')
            (mods / 'Car_02.zip').write_bytes(b'keep')
            installed, _ = install_zip(base / 'new.zip', mods, base / 'backups')
            self.assertEqual(installed.name, 'Car_03.zip')
            (mods / 'Car_982.zip').write_bytes(b'legacy')
            installed, _ = install_zip(base / 'new.zip', mods, base / 'backups')
            self.assertEqual(installed.name, 'Car_983.zip')
            self.assertEqual((mods / 'Car_982.zip').read_bytes(), b'legacy')

    def test_forms_and_exact_order_download(self):
        page = Page('<form action="#"><input type="hidden" name="rid" value="549"><input name="submit2" value="Submit"></form>'
                    '<table><tr><td>549</td><td>SampleCar</td><td>processed</td></tr></table>')
        self.assertEqual(page.forms[0]['fields']['rid'], '549')
        self.assertEqual(page.rows[0], ['549', 'SampleCar', 'processed'])
        html = '<a href="downloadUser.php?fp=mods/549_999_SampleCar.zip">Download</a><a href="downloadUser.php?fp=mods/550_999_Other.zip">Download</a>'
        self.assertIn('549_999_', garage_download(html, {'id': '549'}))
        with self.assertRaises(SiteError):
            garage_download(html, {'id': '551'})


if __name__ == '__main__':
    unittest.main()
