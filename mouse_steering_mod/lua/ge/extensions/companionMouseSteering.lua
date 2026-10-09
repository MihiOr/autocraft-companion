-- Toggle the same mouse steering binding exposed by the Controls menu.
local M = {}
M.dependencies = {'core_input_bindings'}
local cooldown = 0
local function toggle()
  if cooldown > 0 then return end
  local device
  for _,d in ipairs(core_input_bindings.bindings or {}) do
    if d.devname == 'mouse0' then device=d; break end
  end
  if not device then
    guihooks.message('Mouse steering: no mouse device available', 3, 'companionMouseSteering')
    return
  end
  local data=deepcopy(device.contents)
  local enabled=false
  for i=#data.bindings,1,-1 do
    local b=data.bindings[i]
    if b.action=='steering' and b.control=='xaxis' then
      enabled=true
      table.remove(data.bindings,i)
    end
  end
  if not enabled then
    table.insert(data.bindings,{action='steering',control='xaxis',filterType=2,
      deadzoneResting=0,deadzoneEnd=0,linearity=1,isInverted=false,isForceEnabled=false})
  end
  -- Save through BeamNG's normal diff writer: preserve other controls and let
  -- the engine rebuild its action maps, just like clicking Apply in Controls.
  local ok,err=pcall(core_input_bindings.saveBindingsToDisk,data)
  cooldown=0.5
  if not ok then
    log('E','companionMouseSteering',tostring(err))
    guihooks.message('Mouse steering could not update: check console',4,'companionMouseSteering')
    return
  end
  if enabled then
    local car=be:getPlayerVehicle(0)
    if car then car:queueLuaCommand("input.event('steering',0,FILTER_DIRECT)") end
  end
  guihooks.message(enabled and 'Mouse steering OFF' or 'Mouse steering ON — Wheel (direct)',3,'companionMouseSteering')
end
M.toggle=toggle
M.onUpdate=function(dt) cooldown=math.max(0,cooldown-(dt or 0)) end
return M
