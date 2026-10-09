-- Remember the player's vehicle debug modes across game sessions.
local M = {}
local path = '/settings/companionDebugMemory.json'
local saved, activeId, pending, timer, dirty
local globals = {}
local originalMesh, meshWrapper

local function scalar(value)
  return type(value) == 'boolean' or (type(value) == 'number' and value == value and math.abs(value) < math.huge)
end

local function flush()
  if dirty and saved then
    saved.globals = globals
    jsonWriteFile(path, saved, true)
    dirty = false
  end
end

local function onExtensionLoaded()
  local ok, data = pcall(jsonReadFile, path)
  saved = ok and type(data) == 'table' and type(data.vehicle) == 'table' and data or nil
  globals = saved and type(saved.globals) == 'table' and saved.globals or {}
  activeId, pending, timer, dirty = nil, false, 0, false
  if core_vehicle_manager and type(globals.debugSpawn) == 'boolean' then core_vehicle_manager.setDebug(globals.debugSpawn) end
  if debug_vehicleDebug and type(globals.vehicleInfo) == 'boolean' then debug_vehicleDebug.setDebugEnabled(globals.vehicleInfo) end
  if core_vehicles and not originalMesh then
    originalMesh = core_vehicles.setMeshVisibility
    meshWrapper = function(alpha, ...)
      if scalar(alpha) and type(alpha) == 'number' then globals.mesh = alpha; dirty = true end
      return originalMesh(alpha, ...)
    end
    core_vehicles.setMeshVisibility = meshWrapper
  end
end

local function onBDebugUpdate(state, noReset)
  local car = be:getPlayerVehicle(0)
  if not car or type(state) ~= 'table' or state.objectId ~= car:getID() or type(state.vehicle) ~= 'table' then return end
  -- Ignore spawn defaults until our explicit request, after the vehicle settles.
  if activeId ~= state.objectId or pending == 'delay' then return end
  if pending == 'request' then
    pending = false
    if saved then
      if originalMesh and type(globals.mesh) == 'number' then originalMesh(globals.mesh) end
      for key, value in pairs(saved.vehicle) do
        if scalar(value) and type(state.vehicle[key]) == type(value) and key ~= 'nodeDebugTextMode' then
          local modes = state.vehicle[key .. 's']
          if type(modes) ~= 'table' or (value >= 1 and value <= #modes and value == math.floor(value)) then
            state.vehicle[key] = value
          end
        end
      end
      -- Use this car's defaults/tables/IDs; never transplant another car's node selections.
      car:queueLuaCommand('bdebug.setState(' .. serialize(state) .. ',' .. serialize(noReset or {}) .. ',true); bdebug.setEnabled(' .. tostring(saved.visible == true) .. ')')
      return
    end
  end
  local nextState = {version = 1, visible = state.vehicleDebugVisible == true, vehicle = {}}
  for key, value in pairs(state.vehicle) do
    if scalar(value) and key ~= 'nodeDebugTextMode' then nextState.vehicle[key] = value end
  end
  local changed = not saved or saved.visible ~= nextState.visible
  if saved then
    for key, value in pairs(nextState.vehicle) do
      if saved.vehicle[key] ~= value then changed = true; break end
    end
  end
  if changed then saved = nextState; dirty = true end
end

local function onUpdate(dtReal)
  local car = be:getPlayerVehicle(0)
  local id = car and car:getID() or nil
  if id ~= activeId then
    flush()
    activeId, pending, timer = id, id and 'delay' or false, 0
  end
  timer = timer + (dtReal or 0)
  if pending and timer >= 0.5 and car then
    pending, timer = 'request', 0
    car:queueLuaCommand('bdebug.requestState()')
  elseif not pending and timer >= 0.5 then
    -- Debug.vue often calls setState(..., true), suppressing onBDebugUpdate.
    -- Explicit requests capture those changes even while the menu is closed.
    if car then car:queueLuaCommand('bdebug.requestState()') end
    if core_vehicle_manager then
      local value = core_vehicle_manager.getDebug()
      if globals.debugSpawn ~= value then globals.debugSpawn = value; dirty = true end
    end
    if debug_vehicleDebug then
      local value = debug_vehicleDebug.getDebugEnabled()
      if globals.vehicleInfo ~= value then globals.vehicleInfo = value; dirty = true end
    end
    flush()
    timer = 0
  end
end

local function onVehicleSpawned(id)
  if id == activeId then pending, timer = 'delay', 0 end
end

M.onExtensionLoaded = onExtensionLoaded
M.onBDebugUpdate = onBDebugUpdate
M.onUpdate = onUpdate
M.onVehicleSpawned = onVehicleSpawned
M.onExtensionUnloaded = function()
  flush()
  if core_vehicles and core_vehicles.setMeshVisibility == meshWrapper then core_vehicles.setMeshVisibility = originalMesh end
end
M.onClientEndMission = flush
M.onExit = flush
return M
