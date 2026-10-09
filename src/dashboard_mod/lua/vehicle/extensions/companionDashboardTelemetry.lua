-- Read-only telemetry: never changes pedals, motors, or vehicle physics.
local M = {}
local active, udp = false, nil
local elapsed, previousEnergy = 0, nil
local tripKm, usedKwh, recoveredKwh = 0, 0, 0
local lastPower = nil
local function flag(value)
  return (value == true or (type(value) == 'number' and value > 0)) and 1 or 0
end
local function reset()
  elapsed, previousEnergy = 0, nil
  tripKm, usedKwh, recoveredKwh = 0, 0, 0
  lastPower = nil
end
local function setActive(value)
  if value and not udp then
    udp = socket.udp()
    udp:settimeout(0)
    udp:setpeername('127.0.0.1', 28574)
  end
  if active ~= value then previousEnergy = nil end
  active = value
end
local function updateGFX(dt)
  if not active or not udp or dt <= 0 then return end
  local e = electrics.values
  local speed = obj:getVelocity():length()
  tripKm = tripKm + speed * dt / 1000
  local energy, capacity, batteries = 0, 0, 0
  for _, storage in pairs(energyStorage.getStorages()) do
    if storage.type == 'electricBattery' then
      energy = energy + storage.storedEnergy
      capacity = capacity + storage.energyCapacity
      batteries = batteries + 1
    end
  end
  if batteries > 0 then
    if previousEnergy then
      local change = previousEnergy - energy
      lastPower = change / dt / 1000
      usedKwh = usedKwh + math.max(0, change) / 3600000
      recoveredKwh = recoveredKwh + math.max(0, -change) / 3600000
    else lastPower = 0 end
    previousEnergy = energy
  else previousEnergy, lastPower = nil, nil end
  elapsed = elapsed + dt
  if elapsed < 1/24 then return end
  elapsed = elapsed % (1/24)
  -- Match the stock G-meter exactly, including its near-zero-gravity guard.
  local gravity = obj:getGravity()
  gravity = gravity >= 0 and math.max(0.1, gravity) or math.min(-0.1, gravity)
  local gear = e.gearIndex
  local values = {
    speedKmh = speed * 3.6,
    longitudinalG = sensors.gy2 / -gravity,
    lateralG = sensors.gx2 / -gravity,
    gear = gear and (gear < 0 and 0 or (gear > 0 and 2 or 1)) or nil,
    parking = flag(e.parkingbrake), throttle = input.throttle,
    brake = input.brake, steering = input.steering,
    launch = e.companionLaunchState or 0,
    leftTurn = flag(e.signal_left_input), rightTurn = flag(e.signal_right_input),
    lowBeam = flag(e.lowbeam), highBeam = flag(e.highbeam),
    powerKw = lastPower, tripKm = tripKm,
    outsideC = obj:getEnvTemperature() - 273.15
  }
  if batteries > 0 then
    local soc = capacity > 0 and 100 * energy / capacity or 0
    for _, corner in ipairs({'fl','fr','rl','rr'}) do values[corner .. 'Battery'] = soc end
    values.remainingKwh = energy / 3600000
    values.tripKwh, values.recoveredKwh = usedKwh, recoveredKwh
    -- Net consumption includes recuperation; wait for 10 m before estimating range.
    local average = tripKm >= 0.01 and math.max(0, usedKwh - recoveredKwh) / tripKm * 100 or 0
    values.averageKwh = average
    values.rangeKm = average > 0.001 and values.remainingKwh / average * 100 or 0
    values.recoveredKm = average > 0.001 and recoveredKwh / average * 100 or 0
  end
  -- Omitted values become protocol minimums in the serial bridge.
  udp:send(jsonEncode({schema=1, source=obj:getID(), values=values}))
end
local function unload()
  active = false
  if udp then udp:close(); udp = nil end
end
M.setActive = setActive
M.updateGFX = updateGFX
M.onReset = reset
M.onExtensionUnloaded = unload
return M
