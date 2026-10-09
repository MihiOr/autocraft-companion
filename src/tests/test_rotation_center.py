"""Actual-pose rotation-center regressions; no running game required."""
import math
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/_runtime'))
from lupa.luajit21 import LuaRuntime

class RotationCenterTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.source=(ROOT/'rotation_center_mod/lua/ge/extensions/mininiRotationCenter.lua').read_text()
        self.center=self.lua.execute(self.source[:self.source.index('local function reset')]+'\nreturn center')

    def test_left_right_and_reverse_circles(self):
        for angle in (.01,-.01,.1,-.1):
            for radius in (5,20,100):
                x,y,r=self.center(radius,0,radius*math.cos(angle),radius*math.sin(angle),angle,.1)
                self.assertAlmostEqual(x,0,places=7);self.assertAlmostEqual(y,0,places=7)
                self.assertAlmostEqual(r,radius,places=7)

    def test_translated_circle_and_pivot_spin(self):
        x,y,r=self.center(12,3,2+10*math.cos(.01),3+10*math.sin(.01),.01,.02)
        self.assertAlmostEqual(x,2);self.assertAlmostEqual(y,3)
        self.assertEqual(self.center(2,3,2,3,.01,.02),(2,3,0))

    def test_straight_teleport_large_radius_and_invalid_timestep_hide_marker(self):
        for args in ((0,0,1,0,0,.02),(0,0,100,0,.01,.02),(1000,0,1000*math.cos(.01),1000*math.sin(.01),.01,.1),(0,0,1,0,.1,0),(0,0,1,0,.1,.3)):
            self.assertIsNone(self.center(*args))

    def test_draw_pause_reset_map_vehicle_switch_and_toggle(self):
        self.lua.execute('''
          local mt={__add=function(a,b)return vec3(a.x+b.x,a.y+b.y,a.z+b.z) end}
          function vec3(x,y,z)return setmetatable({x=x,y=y,z=z},mt) end
          function ColorF(...)return {...} end
          function ColorI(...)return {...} end
          debugDrawer={drawSphere=function(self,p,r,c) drawn=p;drawCount=(drawCount or 0)+1;assert(c[2]==1) end,
            drawTextAdvanced=function(self,p,t,...)assert(t=='RC')end}
          car={getID=function()return vehicleId end,getPosition=function()return position end,getDirectionVector=function()return direction end}
          vehicleId=1;position=vec3(10,0,1);direction=vec3(0,1,0)
          function getPlayerVehicle()return car end
        ''')
        mod=self.lua.execute(self.source)
        mod.onUpdate(.02,.02)
        self.lua.execute('position=vec3(10*math.cos(.01),10*math.sin(.01),1);direction=vec3(-math.sin(.01),math.cos(.01),0)')
        mod.onUpdate(.02,.02)
        self.assertAlmostEqual(self.lua.globals().drawn.x,0,places=7)
        mod.onUpdate(.02,0);self.assertEqual(self.lua.globals().drawCount,2)
        for reset in (mod.onVehicleReset,mod.onClientPreStartMission,mod.onVehicleSpawned):
            reset();mod.onUpdate(.02,.02)
            self.assertEqual(self.lua.globals().drawCount,2)
        mod.toggle();mod.onUpdate(.02,.02);self.assertEqual(self.lua.globals().drawCount,2)
        mod.toggle();self.lua.execute('vehicleId=2');mod.onUpdate(.02,.02)
        self.assertEqual(self.lua.globals().drawCount,2)

if __name__=='__main__':unittest.main()
