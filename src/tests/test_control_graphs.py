import bisect
import copy
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests/_runtime'))
import control_graphs as g
from lupa.luajit21 import LuaRuntime


class ControlGraphTests(unittest.TestCase):
    def setUp(self):self.profile=g.defaults()

    def functions(self,p=None):
        source=g.lua_source((ROOT/'tests/fixtures/legacy_yaw_control.lua').read_text(),p or self.profile)
        lua=LuaRuntime(unpack_returned_tuples=True)
        return lua.execute(source[:source.index('local function median')]
                           +'\nreturn steeringRequest,yawErrorCorrection')

    def test_all_193_measured_knots_are_kept_in_bezier_and_lua(self):
        graph=self.profile['graphs']['steering'];rows=g.bake(graph);steer,_=self.functions()
        self.assertEqual(len(graph['points']),193)
        for pt in graph['points']:
            self.assertIn((pt['x'],pt['y']),rows)
            self.assertAlmostEqual(steer(pt['x']/480*-1,480),
                                   math.radians(pt['y'])/(10/3.6),places=10)

    def test_default_correction_is_exactly_12_times_error_including_extrapolation(self):
        _,correct=self.functions()
        for error in (-10,-math.pi,-1,-.001,0,.1,1,math.pi,10):
            self.assertAlmostEqual(correct(error),12*error,places=10)

    def custom(self):
        p=copy.deepcopy(self.profile)
        p['graphs']['correction']=dict(mode='manual',points=[
            dict(x=-10,y=-120),dict(x=0,y=0,out=[2,100]),dict(x=10,y=120,**{'in':[8,120]})])
        return p

    def test_manual_bezier_changes_real_lua_correction(self):
        _,correct=self.functions(self.custom())
        self.assertAlmostEqual(math.degrees(correct(math.radians(5))),97.5,places=7)
        self.assertNotAlmostEqual(math.degrees(correct(math.radians(5))),60)

    def test_adaptive_baking_matches_actual_bezier_between_knots(self):
        graph=self.custom()['graphs']['correction'];rows=g.bake(graph,tolerance=.05)
        xs=[x for x,y in rows]
        for seg in g.segments(graph):
            for i in range(1001):
                x,y=g.bezier(seg,i/1000);j=max(1,min(len(rows)-1,bisect.bisect_left(xs,x)))
                a,b=rows[j-1],rows[j]
                approx=a[1]+(x-a[0])/(b[0]-a[0])*(b[1]-a[1])
                self.assertLess(abs(y-approx),.055)

    def test_both_graphs_and_handles_round_trip_in_one_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'profile.json';p=self.custom();g.save(path,p)
            self.assertEqual(g.load(path),g.validate(p))
            self.assertEqual(len(g.load(path)['graphs']),2)

    def test_invalid_points_handles_and_reference_are_rejected(self):
        cases=[]
        for bad in (float('nan'),float('inf')):
            p=self.custom();p['graphs']['correction']['points'][0]['y']=bad;cases.append(p)
        p=self.custom();p['reference_speed_kmh']=0;cases.append(p)
        p=self.custom();p['graphs']['correction']['points'][1]['x']=-10;cases.append(p)
        p=self.custom();p['graphs']['correction']['points'][1]['out'][0]=11;cases.append(p)
        for p in cases:
            with self.assertRaises(ValueError):g.validate(p)

    def test_comma_numbers(self):self.assertEqual(g.number('1,25'),1.25)

    def test_malformed_file_structure_is_rejected_without_crashing_editor(self):
        for value in ([], None, 'invalid', {'version':1}):
            with self.assertRaises(ValueError):g.validate(value)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json';path.write_text('[]')
            with self.assertRaises(ValueError):g.load(path)

    def test_editor_add_move_delete_and_manual_handles(self):
        import tkinter as tk
        from graph_editor import GraphEditor
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(g,'FOLDER',Path(folder)),patch.object(g,'ACTIVE',Path(folder)/'_active.json'):
                root=tk.Tk();root.withdraw()
                try:
                    editor=GraphEditor(root);editor.withdraw();root.update_idletasks()
                    page=editor.pages['correction'];old=len(page.graph['points'])
                    x,y=page.pixel(90,500);page.add(SimpleNamespace(x=x,y=y))
                    self.assertEqual(len(page.graph['points']),old+1)
                    page.x.set('90,5');page.y.set('800,5');page.edit_point()
                    self.assertEqual(page.graph['points'][page.selected]['y'],800.5)
                    page.manual.set(True);page.toggle_manual();page.draw()
                    self.assertEqual(len(page.canvas.find_withtag('handle')),2)
                    page.delete();self.assertEqual(len(page.graph['points']),old)
                    self.assertTrue((Path(folder)/'_draft.json').exists())
                finally:root.destroy()

    def test_apply_and_save_use_commit_typed_values_without_update_point(self):
        import tkinter as tk
        import custom_control
        from graph_editor import GraphEditor
        source=(ROOT/'tests/fixtures/legacy_yaw_control.lua').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);user=folder/'motor.lua';user.write_text(source,encoding='utf-8')
            with patch.object(g,'FOLDER',folder),patch.object(g,'ACTIVE',folder/'_active.json'),patch.object(custom_control,'USER_FILE',user):
                root=tk.Tk();root.withdraw()
                try:
                    editor=GraphEditor(root);editor.withdraw()
                    page=editor.pages['correction'];page.selected=1;page.selection()
                    page.x.set('0');page.y.set('25,5')
                    self.assertTrue(editor.apply())
                    self.assertEqual(g.load(g.ACTIVE)['graphs']['correction']['points'][1]['y'],25.5)
                    page.y.set('50,5')
                    saved=folder/'saved.json'
                    with patch('graph_editor.filedialog.asksaveasfilename',return_value=str(saved)):
                        editor.save_use()
                    self.assertEqual(g.load(saved)['graphs']['correction']['points'][1]['y'],50.5)
                    self.assertEqual(g.load(g.ACTIVE),g.load(saved))
                    self.assertEqual(user.read_text(encoding='utf-8'),g.lua_source(source,g.load(saved)))
                finally:root.destroy()

    def test_hiding_handles_keeps_manual_curve_until_explicit_auto_reset(self):
        import tkinter as tk
        from graph_editor import GraphEditor
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(g,'FOLDER',Path(folder)),patch.object(g,'ACTIVE',Path(folder)/'_active.json'):
                root=tk.Tk();root.withdraw()
                try:
                    editor=GraphEditor(root);editor.withdraw()
                    editor.profile=self.custom()
                    page=editor.pages['correction'];page.refresh()
                    before=g.bake(page.graph)
                    page.manual.set(False);page.toggle_manual()
                    self.assertEqual(page.graph['mode'],'manual')
                    self.assertEqual(g.bake(page.graph),before)
                    page.reset_auto()
                    self.assertEqual(page.graph['mode'],'auto')
                    self.assertNotEqual(g.bake(page.graph),before)
                finally:root.destroy()

    def test_failed_policy_write_rolls_back_active_and_saved_profile(self):
        import custom_control
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);user=folder/'motor.lua'
            old=(ROOT/'tests/fixtures/legacy_yaw_control.lua').read_bytes();user.write_bytes(old)
            active=folder/'_active.json';g.save(active,self.profile);old_active=active.read_bytes()
            write=g._atomic_write
            def fail_policy(path,raw):
                if path==user:raise OSError('Simulated write failure')
                write(path,raw)
            with patch.object(g,'FOLDER',folder),patch.object(g,'ACTIVE',active),patch.object(custom_control,'USER_FILE',user),patch.object(g,'_atomic_write',side_effect=fail_policy):
                with self.assertRaises(OSError):g.apply(self.custom(),save_path=folder/'new.json')
            self.assertEqual(user.read_bytes(),old)
            self.assertEqual(active.read_bytes(),old_active)
            self.assertFalse((folder/'new.json').exists())

    def test_export_rebuilds_graph_tables_from_applied_profile_and_keeps_user_code(self):
        import custom_control
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);user=folder/'motor.lua'
            old=(ROOT/'tests/fixtures/legacy_yaw_control.lua').read_text(encoding='utf-8')
            user.write_text(old,encoding='utf-8');active=folder/'_active.json';g.save(active,self.custom())
            with patch.object(custom_control,'USER_FILE',user),patch.object(g,'ACTIVE',active):
                source=custom_control.source_for_export()
            self.assertEqual(source,g.lua_source(old,self.custom()))
            self.assertNotEqual(source,old)
            adapter=custom_control.build_controller(source)
            self.assertIn(source,adapter)


if __name__=='__main__':unittest.main()
