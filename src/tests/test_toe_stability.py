import json
import unittest

from patcher import JBeam,PatchError
from suspension_values import beam_rows
from toe_stability_patch import apply


def fixture():
    entries={}
    for axle in ('F','R'):
        a=axle.lower()
        ids=[a+'x1l',a+'x2l',a+'h1l',a+'h2l',a+'nal',a+'ncl',a+'w1l','st1l','st2l','tlml','coilA','coilB']
        part={'nodes':[['id','posX','posY','posZ'],{'nodeWeight':1}]+[[n,i,0,0] for i,n in enumerate(ids)],
              'beams':[['id1:','id2:'],{'beamSpring':100000,'beamDamp':2,'beamType':'|NORMAL','beamStrength':12345,'beamDeform':4567},
                       [a+'nal',a+'h1l'],[a+'w1l',a+'h1l'],[a+'x1l',a+'h1l'],
                       ['st1l' if axle=='F' else 'tlml',a+'ncl'],
                       ['st2l' if axle=='F' else 'tlml',a+'x2l'],
                       ['coilA','coilB',{'beamSpring':20000,'beamDamp':900}],
                       [a+'ncl',a+'x1l',{'beamType':'|BOUNDED','beamSpring':0,'beamDamp':0,'beamLimitSpring':123}],
                       [a+'h2l',a+'x2l',{'beamSpring':0,'beamDamp':100}]],
              'hydros':[['id1:','id2:'],{'beamSpring':100000,'beamDamp':2,'beamType':'|NORMAL'},['st1l','st2l',{'factor':.9,'inRate':20}]] if axle=='F' else []}
        entries['vehicles/Car/suspension_'+axle+'.jbeam']=json.dumps({'suspension_'+axle:part}).encode()
    entries['vehicles/Car/engine.jbeam']=b'unchanged'
    return entries


class ToeStabilityTests(unittest.TestCase):
    def test_only_positive_structural_links_change_and_repeat_does_not_compound(self):
        source=fixture();settings={'toe_stability_enabled':True,'toe_stability_multiplier':'1,2'}
        result=apply(source,'vehicles/Car/',settings)
        report=json.loads(result['vehicles/Car/companion_toe_stability.json'])
        self.assertTrue(report['beams'])
        for beam in report['beams']:
            self.assertEqual(beam['spring_after'],beam['spring_before']*1.2)
            self.assertGreater(beam['damp_after'],beam['damp_before'])
        for axle in ('F','R'):
            old=json.loads(source['vehicles/Car/suspension_'+axle+'.jbeam'])['suspension_'+axle]
            new=json.loads(result['vehicles/Car/suspension_'+axle+'.jbeam'])['suspension_'+axle]
            self.assertEqual(old['nodes'],new['nodes'])
            self.assertEqual(old['beams'][-3:],new['beams'][-3:])
            for row in new['beams'][2:-3]:
                self.assertNotIn('beamStrength',row[-1])
                self.assertNotIn('beamDeform',row[-1])
        self.assertEqual(result['vehicles/Car/engine.jbeam'],b'unchanged')
        again=apply(result,'vehicles/Car/',settings)
        self.assertEqual(again,result)
        other=apply(result,'vehicles/Car/',dict(settings,toe_stability_multiplier=1))
        report=json.loads(other['vehicles/Car/companion_toe_stability.json'])
        self.assertTrue(all(b['spring_after']==b['spring_before'] for b in report['beams']))

    def test_disabled_and_invalid_layout_or_settings(self):
        source=fixture();self.assertEqual(apply(source,'vehicles/Car/',{}),source)
        for key,value in [('toe_stability_multiplier',10),('toe_stability_multiplier','nan'),('toe_stability_damping_ratio',-.1)]:
            with self.assertRaises(PatchError):apply(source,'vehicles/Car/',{'toe_stability_enabled':True,key:value})
        broken=dict(source);broken.pop('vehicles/Car/suspension_R.jbeam')
        with self.assertRaises(PatchError):apply(broken,'vehicles/Car/',{'toe_stability_enabled':True})
