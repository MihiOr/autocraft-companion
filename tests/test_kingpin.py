import math
import unittest
from kingpin_patch import rotation_limit
from patcher import PatchError


class KingpinTests(unittest.TestCase):
    def test_twist_is_free_inside_limit_and_resisted_outside(self):
        axis=((0,0,0),(0,0,1))
        point=(1,0,0)
        anchors=((0,1,0),(0,-1,0))
        limits=[rotation_limit(*axis,point,a,45) for a in anchors]
        for angle in (-90,-46,-45,0,45,46,90):
            p=(math.cos(math.radians(angle)),math.sin(math.radians(angle)),0)
            outside=any(math.dist(p,a)<lo-1e-8 or math.dist(p,a)>hi+1e-8
                        for a,(_,lo,hi) in zip(anchors,limits))
            self.assertEqual(outside,abs(angle)>45)

    def test_invalid_lever_rejected(self):
        with self.assertRaises(PatchError):
            rotation_limit((0,0,0),(0,0,1),(0,0,.5),(1,0,0),45)
