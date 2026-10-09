local M = {}
local lastID, timer = nil, 0
local function deactivate(id)
  local vehicle = id and be:getObjectByID(id)
  if vehicle then vehicle:queueLuaCommand("if extensions.companionDashboardTelemetry then extensions.companionDashboardTelemetry.setActive(false) end") end
end
local function update(dtReal)
  timer = timer + dtReal
  if timer < 0.25 then return end
  timer = 0
  local vehicle = getPlayerVehicle(0)
  local id = vehicle and vehicle:getID() or nil
  if lastID ~= id then deactivate(lastID); lastID = id end
  if vehicle then
    -- Re-check after vehicle Lua reloads; loading an existing extension is avoided.
    vehicle:queueLuaCommand("if not extensions.companionDashboardTelemetry then extensions.load('companionDashboardTelemetry') end; if extensions.companionDashboardTelemetry then extensions.companionDashboardTelemetry.setActive(true) end")
  end
end
M.onUpdate = update
M.onExtensionUnloaded = function() deactivate(lastID); lastID = nil end
return M
