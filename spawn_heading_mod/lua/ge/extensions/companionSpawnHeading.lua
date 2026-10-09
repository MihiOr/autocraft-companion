-- Spawn transform only: no node, mesh, suspension or reference-axis edits.
local M = {}
local originalSpawn, originalSet, wrappedSpawn, wrappedSet
local function correction(model)
  if type(model) ~= 'string' or model:find('..',1,true) or model:find('/',1,true) then return 0 end
  local data=jsonReadFile('/vehicles/'..model..'/companion_spawn_heading.json')
  return type(data)=='table' and data.rightDegrees==90 and math.pi/2 or 0
end
local function rotate(rot, angle)
  if not rot or angle==0 then return rot end
  return quatFromEuler(0,0,angle)*quat(rot)
end
local function onExtensionLoaded()
  if originalSpawn then return end
  originalSpawn,originalSet=spawn.spawnVehicle,spawn.setVehicleObject
  wrappedSpawn=function(model,config,pos,rot,options)
    return originalSpawn(model,config,pos,rotate(rot,correction(model)),options)
  end
  wrappedSet=function(vehicle,options)
    local angle=correction(options.model)
    -- Replacement inherits the existing car's reference rotation. Remove its
    -- correction before applying the target model's, avoiding repeated turns.
    if options.keepOtherVehRotation then angle=angle-correction(vehicle:getJBeamFilename()) end
    local copy={}
    for k,v in pairs(options) do copy[k]=v end
    copy.rot=rotate(options.rot,angle)
    return originalSet(vehicle,copy)
  end
  spawn.spawnVehicle,spawn.setVehicleObject=wrappedSpawn,wrappedSet
end
M.onExtensionLoaded=onExtensionLoaded
M.onExtensionUnloaded=function()
  if spawn.spawnVehicle==wrappedSpawn then spawn.spawnVehicle=originalSpawn end
  if spawn.setVehicleObject==wrappedSet then spawn.setVehicleObject=originalSet end
end
return M
