-- Per-wheel electric traction control, with brake-release launch assistance.
local M = {type = 'auxiliary', defaultOrder = 80}
local cfg, channels = {}, {}
local armed, launching, elapsed = false, false, 0
local armHeld = false
local abs, min, max = math.abs, math.min, math.max
local function clamp01(x) return min(1, max(0, x)) end

local function reset()
  armed, launching, elapsed = false, false, 0
  armHeld = false
  for _, ch in ipairs(channels) do
    ch.factor = 1
    electrics.values[ch.signal] = 1
  end
  electrics.values.companionLaunchState = 0
end

local function init(data)
  cfg = data
  channels = {}
  for _, name in ipairs({'FL','FR','RL','RR'}) do
    local wd
    for _, wheel in pairs(wheels.wheels) do
      if wheel.name == name then wd = wheel; break end
    end
    if wd then
      table.insert(channels, {wheel = wd, signal = 'companionTorque'..name, factor = 1})
    else
      log('E', 'companion_ev_ecu', 'Missing wheel '..name..'; torque control disabled for that channel')
      electrics.values['companionTorque'..name] = 1
    end
  end
  reset()
end

local function updateFixedStep(dt)
  dt = min(max(dt, 0), 0.05)
  -- Ground-relative body speed avoids treating four simultaneously spinning
  -- driven wheels as the speed reference. This is a simulation-only sensor.
  local speed = obj:getVelocity():length()
  local throttle = input.throttle or 0
  local brake = input.brake or 0
  local park = input.parkingbrake or 0
  local forward = (electrics.values.gearIndex or 0) > 0
  local armRequest = cfg.launchEnabled and speed < 1 and throttle > 0.5 and brake > 0.5 and forward
  if armRequest and not armHeld and not launching then
    if not armed and guihooks then guihooks.message('EV launch armed: release brake', 3, 'companionLaunch') end
    armed = true
  end
  armHeld = armRequest
  if armed and (not forward or throttle < 0.5 or speed > 2) then armed = false end
  if armed and brake <= 0.01 and park < 0.05 then
    armed, launching, elapsed = false, true, 0
    if guihooks then guihooks.message('EV launch active', 2, 'companionLaunch') end
    for _, ch in ipairs(channels) do
      ch.factor = (cfg.launchRamp == 0) and 1 or min(ch.factor, 0.25)
    end
  end
  if launching then
    elapsed = elapsed + dt
    if throttle < 0.5 or brake > 0.01 or not forward then
      launching = false
      if guihooks then guihooks.message('EV launch ended: traction control restored', 2, 'companionLaunch') end
    end
  end
  local target = cfg.targetSlip or 0.08
  local ramp = cfg.launchRamp or 0.4
  local launchCap = (launching and ramp > 0) and min(1, 0.25 + 0.75 * elapsed / ramp) or 1
  local active = forward and throttle > 0.02 and brake < 0.05 and park < 0.05
  for _, ch in ipairs(channels) do
    local ws = abs(ch.wheel.wheelSpeed or 0)
    -- Slip ratio is ill-defined at rest; below 2 m/s use a speed floor.
    local slip = max(0, (ws - speed) / max(speed, 2))
    if active and not launching then
      local error = target - slip
      if error < 0 then
        ch.factor = clamp01(ch.factor + error * 16 * dt)
      else
        ch.factor = min(1, ch.factor + 1.5 * dt)
      end
    else
      ch.factor = 1
    end
    -- Never command torque independently of the driver's throttle. Zero while
    -- launch is armed avoids driving against the friction brakes.
    electrics.values[ch.signal] = armed and 0 or min(ch.factor, launchCap)
    electrics.values[ch.signal..'Slip'] = slip
  end
  electrics.values.companionLaunchState = armed and 1 or (launching and 2 or 0)
end

local function shutdown()
  for _, ch in ipairs(channels) do electrics.values[ch.signal] = 1 end
end
M.init, M.reset, M.updateFixedStep, M.shutdown = init, reset, updateFixedStep, shutdown
return M
