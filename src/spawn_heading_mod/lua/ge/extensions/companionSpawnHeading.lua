-- Spawn transforms only; geometry and ordinary physics resets are untouched.
local M = {}
local hooks = {}
local function correction(model)
  if type(model) ~= 'string' or model:find('..',1,true) or model:find('/',1,true) then return 0 end
  local data=jsonReadFile('/vehicles/'..model..'/companion_spawn_heading.json')
  return type(data)=='table' and data.rightDegrees==90 and math.pi/2 or 0
end
local function rotate(rot, angle)
  if not rot or angle==0 then return rot end
  return quatFromEuler(0,0,angle)*quat(rot)
end
local function vehicleCorrection(vehicle)
  return vehicle and correction(vehicle:getJBeamFilename()) or 0
end
local factories={
  spawnVehicle=function(original)
    return function(model,config,pos,rot,options)
      return original(model,config,pos,rotate(rot,correction(model)),options)
    end
  end,
  setVehicleObject=function(original)
    return function(vehicle,options)
      if not vehicle or not options then return original(vehicle,options) end
      local angle=correction(options.model)
      -- Only subtract the previous correction when inheriting that exact pose.
      if options.keepOtherVehRotation then angle=angle-vehicleCorrection(vehicle) end
      local copy={}
      for k,v in pairs(options) do copy[k]=v end
      copy.rot=rotate(options.rot,angle)
      return original(vehicle,copy)
    end
  end,
  safeTeleport=function(original)
    return function(vehicle,pos,rot,...)
      -- An explicit destination rotation is a new world heading. A nil
      -- rotation keeps the game's default behavior; do not turn ordinary resets.
      return original(vehicle,pos,rotate(rot,vehicleCorrection(vehicle)),...)
    end
  end
}
local function ensureHooks()
  if not spawn then return end
  for name,factory in pairs(factories) do
    local current=spawn[name]
    local hook=hooks[name]
    if type(current)=='function' and (not hook or current~=hook.wrapper) then
      local wrapper=factory(current)
      hooks[name]={owner=spawn,original=current,wrapper=wrapper}
      spawn[name]=wrapper
    end
  end
end
M.onExtensionLoaded=ensureHooks
-- The extension survives map transitions, while engine functions can reload.
M.onClientPreStartMission=ensureHooks
M.onClientStartMission=ensureHooks
M.onClientPostStartMission=ensureHooks
M.onUpdate=ensureHooks
M.onExtensionUnloaded=function()
  for name,hook in pairs(hooks) do
    if hook.owner[name]==hook.wrapper then hook.owner[name]=hook.original end
  end
  hooks={}
end
return M
