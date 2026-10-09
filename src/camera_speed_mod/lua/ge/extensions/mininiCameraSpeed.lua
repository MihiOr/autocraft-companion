-- Set the free-camera default once per game/map, preserving Alt+wheel changes.
local M={}
local pending=true
local camera
M.onUpdate=function()
  if not core_camera or not core_camera.setSpeed or not core_camera.getSpeed then return end
  if camera~=core_camera then camera=core_camera;pending=true end
  if pending then
    local ok,speed=pcall(core_camera.getSpeed)
    if ok and type(speed)=='number' then
      local applied=pcall(core_camera.setSpeed,100)
      if applied then pending=false end
    end
  end
end
M.onExtensionLoaded=function() pending=true end
M.onClientPostStartMission=function() pending=true end
return M
