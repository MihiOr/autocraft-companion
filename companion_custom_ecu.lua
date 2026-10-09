-- __CONTRACT__
local source = __USER_SOURCE__
local M = {type='auxiliary', defaultOrder=100}
local user, memory, channels, failed, time, active, armed
local names = {'FL','FR','RL','RR'}
local function stop(reason)
  failed = true
  for _,ch in pairs(channels or {}) do ch.command=0 end
  electrics.values.companionLaunchState=0
  log('E','companion_custom_ecu',tostring(reason))
  if guihooks then guihooks.message('Custom ECU error: motors disabled. Check vehicle console.', 8, 'customECU') end
end
local function reset()
  memory, time, active, armed, failed = {}, 0, false, false, false
  for _,ch in pairs(channels or {}) do ch.command=0 end
  local ok, result = pcall(loadUser, source)
  if ok then user=result else stop(result) end
end
local function init()
  channels = {}
  for _,name in ipairs(names) do
    local wheel
    for _,w in pairs(wheels.wheels) do if w.name==name then wheel=w end end
    local motor=powertrain.getDevice('evMotor'..name)
    if not motor or not wheel then stop('Missing motor/wheel '..name); return end
    channels[name]={wheel=wheel,motor=motor,command=0}
  end
  reset()
end
local function updateFixedStep(dt)
  -- Attach after powertrain setup; reattach if powertrain replaces torqueUpdate.
  for name,ch in pairs(channels) do
    local motor=ch.motor
    if motor.torqueUpdate ~= ch.wrapper then
      ch.original=motor.torqueUpdate
      ch.wrapper=function(device, step)
        local direction, smoother = device.motorDirection, device.throttleSmoother
        local coef, limit, rev, ignition = device.torqueCoef, device.maxTorqueLimit, device.tempRevLimiterAV, device.isAffectedByIgnition
        -- Commands come solely from the user's function. Keep the motor curve,
        -- battery/damage state and physical torque calculation in BeamNG.
        device.torqueCoef, device.maxTorqueLimit, device.tempRevLimiterAV = 1, math.huge, math.huge
        device.isAffectedByIgnition=false
        device.motorDirection=1 -- signed commands are independent of the stock selector
        device.throttleSmoother=ch.smoother
        electrics.values['companionCustom'..name]=failed and 0 or ch.command
        electrics.values.companionCustomFactor=1
        electrics.values.companionCustomRegen=0
        device.minWantedRegenTorque=0
        device.maxWantedRegenTorque=0
        ch.original(device,step)
        device.motorDirection, device.throttleSmoother=direction,smoother
        device.torqueCoef, device.maxTorqueLimit, device.tempRevLimiterAV, device.isAffectedByIgnition=coef,limit,rev,ignition
      end
      ch.smoother={getUncapped=function(_,value) return value end}
      motor.torqueUpdate=ch.wrapper
    end
  end
  if failed then return end
  time=time+dt
  local velocity=obj:getVelocity()
  local s={dt=dt,time=time,wheelSpeed={},wheelRPM={},motorRPM={},
    bodySpeed=velocity:length(),forwardSpeed=velocity:dot(obj:getDirectionVector()),
    acceleration={x=sensors.gx or 0,y=sensors.gy or 0,z=sensors.gz or 0},
    throttle=input.throttle or 0,brake=input.brake or 0,parkingBrake=input.parkingbrake or 0,
    steering=input.steering or 0,gear=electrics.values.gearIndex or 0,
    gearName=electrics.values.gear or '',launchActive=active,launchArmed=armed}
  for name,ch in pairs(channels) do
    s.wheelSpeed[name]=ch.wheel.wheelSpeed or 0
    s.wheelRPM[name]=(ch.wheel.angularVelocity or 0)*(ch.wheel.wheelDir or 1)*9.549296586
    s.motorRPM[name]=ch.motor.outputRPM or 0
  end
  local ok,out=pcall(evaluateUser,user,s,memory)
  if not ok then stop(out); return end
  for name,ch in pairs(channels) do ch.command=out[name] end
  local wasActive, wasArmed = active, armed
  active,armed=out.launchActive==true,out.launchArmed==true
  electrics.values.companionLaunchState=armed and 1 or (active and 2 or 0)
  -- Display only: all arming/launch decisions still belong to the user's Lua.
  if guihooks and (active ~= wasActive or armed ~= wasArmed) then
    local text = armed and 'EV launch armed: release brake' or (active and 'EV launch active' or 'EV launch inactive')
    guihooks.message(text, 3, 'companionLaunch')
  end
end
local function shutdown()
  for _,ch in pairs(channels or {}) do
    ch.command=0
    if ch.motor.torqueUpdate==ch.wrapper then ch.motor.torqueUpdate=ch.original end
  end
end
M.init,M.reset,M.updateFixedStep,M.shutdown=init,reset,updateFixedStep,shutdown
return M
