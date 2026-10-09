-- Edit this file: Companion always uses it for EV motor control.
-- Check code before exporting/reapplying. Changes require a fresh patch/reload.
-- No BeamNG globals here: use inputs and persistent memory only.
-- Inputs (updated each fixed step):
-- s.dt: seconds; s.time: seconds since vehicle reset
-- s.wheelSpeed.FL/FR/RL/RR: signed tire surface speed, m/s
-- s.wheelRPM.FL/FR/RL/RR: signed wheel RPM (forward positive)
-- s.motorRPM.FL/FR/RL/RR: motor shaft RPM
-- s.bodySpeed: unsigned ground-relative speed, m/s
-- s.forwardSpeed: signed body speed along vehicle forward axis, m/s
-- s.acceleration.x/y/z: BeamNG body sensor axes, m/s^2 (not g).
--   Axis interpretation follows the car's reference nodes.
-- s.throttle, s.brake, s.parkingBrake: pedals 0..1; s.steering: -1..1
-- s.gear: gearIndex (negative reverse, zero neutral, positive drive)
-- s.gearName: selector text; s.launchActive/s.launchArmed: previous call's state
-- memory: your persistent table; cleared on vehicle reset.
-- Return FL/FR/RL/RR, each finite -1..1:
-- -1 = full available reverse torque, +1 = full available forward torque,
-- 0 = no commanded motor torque or automatic regen. Friction brakes still work.
-- Torque is limited by the motor's RPM curve, battery and damage.
-- The adapter does NOT multiply your outputs by the pedals or selected gear.
-- You own all pedal/gear/traction/launch decisions; this example handles them.
-- Optional launchActive/launchArmed booleans update indicators and next inputs.

-- TUNING: starting points, not measured optimum tire slip.
-- Launch uses its OWN slip regulator; normal TC does not run on top of it.
local config = {
  tractionEnabled = true,
  launchEnabled = true,
  tractionSlip = 0.08,       -- 8% above body speed
  launchSlip = 1.00,         -- 100% during launch
  tractionLowSpeedSlip = 0.08,-- permitted wheel overspeed near rest, m/s
  launchLowSpeedSlip = 1.0,
  cutRate = 100,              -- faster cuts for larger excess slip
  recoveryRate = 1.5,        -- torque fraction recovered per second
  slipDeadband = 0.00,       -- m/s, prevents constant small corrections
  launchRampSeconds = 0,    -- 0 = no timed torque ramp
  launchInitialTorque = 0.35, -- used only with a nonzero ramp
}
local names = {'FL','FR','RL','RR'}
local function clamp(x,a,b) return math.max(a,math.min(b,x)) end

return function(s, memory)
  local dt = clamp(s.dt,0,0.05)
  local speed = math.abs(s.bodySpeed)
  local gas, brake, park = clamp(s.throttle,0,1), clamp(s.brake,0,1), clamp(s.parkingBrake,0,1)
  local direction = s.gear > 0 and 1 or (s.gear < 0 and -1 or 0)
  memory.limits = memory.limits or {FL=1,FR=1,RL=1,RR=1}
  local wasLaunching = memory.launch == true
  if memory.launch and (not config.launchEnabled or direction~=1 or gas<0.5 or brake>0.01 or park>0.05) then
    memory.launch=false
  end
  if memory.armed and (not config.launchEnabled or direction~=1 or gas<0.5 or speed>2) then memory.armed=false end
  local armRequest = config.launchEnabled and direction==1 and speed<1 and gas>0.5 and brake>0.5
  -- A brake press that ends a launch cannot re-arm it in the same press.
  if armRequest and not memory.armHeld and not wasLaunching then memory.armed=true end
  memory.armHeld=armRequest
  if memory.armed and brake<=0.01 and park<=0.05 then
    memory.armed=false; memory.launch=true; memory.launchTime=0
  end
  if memory.launch then memory.launchTime=(memory.launchTime or 0)+dt end

  local blocked = direction==0 or brake>0.01 or park>0.05 or memory.armed or gas==0
  local slipTarget = memory.launch and config.launchSlip or config.tractionSlip
  local lowSpeedSlip = memory.launch and config.launchLowSpeedSlip or config.tractionLowSpeedSlip
  -- At rest a ratio is undefined, so use a finite permitted speed difference.
  local allowance = math.max(lowSpeedSlip,speed*slipTarget)
  -- Approximate allowance for different wheel path lengths when cornering.
  if not memory.launch then allowance=allowance+speed*0.03*math.abs(s.steering or 0) end
  local regulate = memory.launch or config.tractionEnabled
  local ramp=1
  if memory.launch and config.launchRampSeconds>0 then
    ramp=clamp(config.launchInitialTorque+(1-config.launchInitialTorque)*memory.launchTime/config.launchRampSeconds,0,1)
  end
  local out={launchActive=memory.launch==true,launchArmed=memory.armed==true}
  for _,name in ipairs(names) do
    local limit=memory.limits[name]
    if blocked or memory.direction~=direction or not regulate then
      limit=1
    else
      local excess=math.abs(s.wheelSpeed[name])-speed-allowance
      if excess>config.slipDeadband then
        limit=clamp(limit-config.cutRate*excess/math.max(speed,2)*dt,0,1)
      elseif excess < -config.slipDeadband then
        limit=math.min(1,limit+config.recoveryRate*dt)
      end
    end
    memory.limits[name]=limit
    out[name]=blocked and 0 or direction*gas*math.min(limit,ramp)
  end
  memory.direction=direction
  return out
end
