-- Audio-only RPM scaling for direct-drive motors. No powertrain values change.
local M = {type = 'auxiliary', defaultOrder = 90}
local motors, pitch = {}, 1
local function silenceLegacy()
  sounds.disableOldEngineSounds()
end
local function motorSound(device, dt)
  local rpm = device.soundRPMSmoother:get(math.abs(device.outputAV1 * 9.5492965855) * pitch, dt)
  local load = math.min(device.soundMaxLoadMix, math.max(device.soundMinLoadMix,
    device.soundLoadSmoother:get(math.abs(device.instantEngineLoad), dt)))
  obj:setEngineSound(device.engineSoundID, rpm, load,
    sounds.hzToFMODHz(rpm * device.fundamentalFrequencyRPMCoef), device.engineVolumeCoef)
end
local function init(data)
  motors, pitch = {}, data.pitchScale or 6.7
  for _, name in ipairs({'evMotorFL','evMotorFR','evMotorRL','evMotorRR'}) do
    local motor = powertrain.getDevice(name)
    if motor then table.insert(motors, motor) end
  end
end
local function updateGFX()
  for _, motor in ipairs(motors) do
    if motor.engineSoundID and motor.soundRPMSmoother then motor.updateSounds = motorSound end
  end
end
M.init, M.initSounds, M.resetSounds, M.updateGFX = init, silenceLegacy, silenceLegacy, updateGFX
return M
