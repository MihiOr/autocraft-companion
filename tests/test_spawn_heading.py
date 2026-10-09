import sys
import unittest
from pathlib import Path
from spawn_heading_patch import apply

ROOT=Path(__file__).parents[1]
from lupa.luajit21 import LuaRuntime


class SpawnHeadingTests(unittest.TestCase):
    def test_marker_leaves_geometry_untouched(self):
        original={'vehicles/Car/main.jbeam':b'original geometry','vehicles/Car/main.dae':b'mesh'}
        result=apply(original,'vehicles/Car/')
        for key,value in original.items(): self.assertEqual(result[key],value)

    def test_new_replace_repeat_and_unload(self):
        lua=LuaRuntime()
        lua.execute('''
          local mt={__mul=function(a,b) return quat(a.angle+b.angle) end}
          function quat(a) return setmetatable({angle=type(a)=='table' and a.angle or a},mt) end
          function quatFromEuler(x,y,z) return quat(z) end
          function jsonReadFile(path) if path:find('/Patched/',1,true) then return {rightDegrees=90} end end
          spawn={spawnVehicle=function(m,c,p,r,o) result=r; return 'new' end,
                 setVehicleObject=function(v,o) result=o.rot; return 'replace' end}
          oldSpawn=spawn.spawnVehicle; oldSet=spawn.setVehicleObject
        ''')
        mod=lua.execute((ROOT/'spawn_heading_mod/lua/ge/extensions/companionSpawnHeading.lua').read_text())
        mod.onExtensionLoaded()
        lua.execute('''
          assert(spawn.spawnVehicle('Patched',nil,nil,quat(0),{})=='new')
          assert(math.abs(result.angle-math.pi/2)<1e-9)
          spawn.spawnVehicle('Stock',nil,nil,quat(0),{}); assert(result.angle==0)
          local v={getJBeamFilename=function() return 'Patched' end}
          local options={model='Patched',rot=quat(math.pi/2),keepOtherVehRotation=true}
          for i=1,4 do spawn.setVehicleObject(v,options); assert(result.angle==math.pi/2) end
          options.model='Stock'; spawn.setVehicleObject(v,options); assert(result.angle==0)
          assert(options.rot.angle==math.pi/2)
        ''')
        mod.onExtensionUnloaded()
        lua.execute('assert(spawn.spawnVehicle==oldSpawn and spawn.setVehicleObject==oldSet)')
