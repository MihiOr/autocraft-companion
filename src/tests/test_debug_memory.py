import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / '_runtime'))
from lupa import LuaRuntime


class DebugMemoryTests(unittest.TestCase):
    def test_save_restore_and_ignore_other_vehicles(self):
        lua = LuaRuntime()
        lua.execute('''
          disk=nil; writes=0; commands={}; id=7
          function jsonReadFile() return disk end
          function jsonWriteFile(p,s) disk=s; writes=writes+1 end
          function serialize(v)
            if type(v) ~= 'table' then return tostring(v) end
            local s='{' for k,x in pairs(v) do s=s..'['..string.format('%q',k)..']='..serialize(x)..',' end
            return s..'}'
          end
          car={getID=function() return id end,
               queueLuaCommand=function(_,s) table.insert(commands,s) end}
          be={getPlayerVehicle=function() return car end}
          spawn=false; info=false; mesh=1
          core_vehicle_manager={getDebug=function() return spawn end,setDebug=function(v) spawn=v end}
          debug_vehicleDebug={getDebugEnabled=function() return info end,setDebugEnabled=function(v) info=v end}
          core_vehicles={setMeshVisibility=function(v) mesh=v end}
          function state(visible,mode)
            return {objectId=id,vehicleDebugVisible=visible,
              vehicle={beamVisMode=mode,beamVisModes={{},{},{}},cogMode=1,nodeDebugTextMode=2}}
          end
        ''')
        source = (Path(__file__).parents[1] / 'debug_memory_mod/lua/ge/extensions/companionDebugMemory.lua').read_text()
        lua.globals().mod = lua.execute(source)
        lua.execute('''
          mod.onExtensionLoaded(); mod.onUpdate(0.6)
          mod.onBDebugUpdate(state(true,3),{})
          mod.onUpdate(0.6)
          assert(disk.vehicle.beamVisMode==3 and disk.visible and writes==1)
          assert(disk.vehicle.nodeDebugTextMode==nil)
          local other=state(false,1); other.objectId=9
          mod.onBDebugUpdate(other,{}); mod.onUpdate(0.6)
          assert(writes==1)
          -- A fresh game session must not overwrite the saved state with spawn defaults.
          mod.onExtensionLoaded(); id=10
          mod.onBDebugUpdate(state(false,1),{})
          mod.onUpdate(0.1); mod.onBDebugUpdate(state(false,1),{})
          mod.onUpdate(0.5); mod.onBDebugUpdate(state(false,1),{})
          bdebug={setState=function(s,n) restored=s end,
                  setEnabled=function(v) enabled=v end}
          assert(load(commands[#commands]))()
          assert(restored.objectId==10 and restored.vehicle.beamVisMode==3 and enabled)
          assert(restored.vehicle.nodeDebugTextMode==2)
          -- Explicitly disabling the display survives another restart.
          mod.onBDebugUpdate(state(false,3),{}); mod.onUpdate(0.6)
          assert(not disk.visible)
          mod.onExtensionLoaded(); mod.onUpdate(0.6)
          mod.onBDebugUpdate(state(false,1),{})
          assert(load(commands[#commands]))()
          assert(enabled==false and restored.vehicle.beamVisMode==3)
          -- Simulate a menu change with no event: the next poll must request state.
          mod.onUpdate(0.6)
          assert(commands[#commands]=='bdebug.requestState()')
          mod.onBDebugUpdate(state(true,2),{})
          core_vehicles.setMeshVisibility(0.25); spawn=true; info=true
          mod.onUpdate(0.6)
          assert(disk.vehicle.beamVisMode==2 and disk.globals.mesh==0.25)
          spawn=false; info=false; mesh=1
          mod.onExtensionLoaded()
          assert(spawn and info)
          mod.onUpdate(0.6); mod.onBDebugUpdate(state(false,1),{})
          assert(mesh==0.25)
        ''')


if __name__ == '__main__':
    unittest.main()
