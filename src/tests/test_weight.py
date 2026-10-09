import json
import math
import unittest
from weight_patch import apply_weight
from patcher import PatchError


def fixture():
    prefix='vehicles/Car/'
    main={'main':{'nodes':[['id','posX','posY','posZ'],{'nodeWeight':100},
        ['cc1',0,-.5,.3],['cc2',0,.5,.3],['cc3',3,-.5,.3],['cc4',3,.5,.3]],
        'camerasInternal':[['type','x','y','z'],['Driver',1.5,.4,1.2]]}}
    engine={'engine':{'nodes':[['id','posX','posY','posZ']], 'beams':[['id1:','id2:']]}}
    for wheel in ('FL','FR','RL','RR'):
        engine['engine']['nodes'].append(['ev_'+wheel+'0',1,0,.5,{'nodeWeight':35}])
    engine['engine']['nodes'].append(['ev_battery_0',1,0,.3,{'nodeWeight':500}])
    wheels={'wheels':{'pressureWheels':[['name','hubGroup','group','node1:','node2:','nodeS','nodeArm:','wheelDir'],
        {'nodeWeight':1,'hubNodeWeight':2,'numRays':16,'enableHubcaps':False},
        ['FL','hub','tire','a','b',9999,'c',1],['FR','hub','tire','a','b',9999,'c',-1]]}}
    return {prefix+'main.jbeam':json.dumps(main).encode(),prefix+'engine.jbeam':json.dumps(engine).encode(),
            prefix+'wheels.jbeam':json.dumps(wheels).encode(),prefix+'companion_ev_report.json':b'{}',prefix+'info.json':b'{}'}


class WeightTests(unittest.TestCase):
    def test_mass_budget_includes_generated_wheels_and_preserves_motors(self):
        s={'ev_base_mass':450,'ev_passenger_left':80,'ev_passenger_right':80}
        result=apply_weight(fixture(),'vehicles/Car/',s)
        main=json.loads(result['vehicles/Car/main.jbeam'])['main']
        engine=json.loads(result['vehicles/Car/engine.jbeam'])['engine']
        wheels=json.loads(result['vehicles/Car/wheels.jbeam'])['wheels']['pressureWheels']
        explicit=sum(row[-1]['nodeWeight'] for row in main['nodes'][2:])
        explicit+=sum(row[-1]['nodeWeight'] for row in engine['nodes'][1:])
        wheel_mass=2*2*16*(wheels[1]['nodeWeight']+wheels[1]['hubNodeWeight'])
        self.assertAlmostEqual(explicit+wheel_mass,1110,places=7)
        for row in engine['nodes'][1:5]:self.assertEqual(row[-1]['nodeWeight'],35)
        self.assertEqual(engine['nodes'][5][-1]['nodeWeight'],500)
        for row in engine['nodes'][6:]:
            self.assertEqual(row[-1]['nodeWeight'],20)
            self.assertEqual(row[2]>0,'left' in row[0])

    def test_zero_passenger_creates_no_mass_nodes(self):
        result=apply_weight(fixture(),'vehicles/Car/',{'ev_base_mass':450,'ev_passenger_left':0,'ev_passenger_right':80})
        nodes=json.loads(result['vehicles/Car/engine.jbeam'])['engine']['nodes'][1:]
        self.assertFalse(any('passenger_left' in row[0] for row in nodes))
        self.assertEqual(json.loads(result['vehicles/Car/info.json'])['Weight'],1030)

    def test_target_cannot_be_less_than_motors(self):
        with self.assertRaises(PatchError):
            apply_weight(fixture(),'vehicles/Car/',{'ev_base_mass':100,'ev_passenger_left':0,'ev_passenger_right':0})
