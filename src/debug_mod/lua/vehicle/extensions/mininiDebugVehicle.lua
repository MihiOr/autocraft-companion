-- __IMU__
local M={version=7}
local names={'FL','FR','RL','RR'}
local control, lease, elapsed, sampler, imu, imuError = nil, 0, 0, nil, {}, nil
local sampleElapsed=0
local speedIntegral=0
local function calibration(enabled)
  local ecu=controller and controller.getController and controller.getController('companion_custom_ecu')
  if ecu and ecu.setCalibrationMode then ecu.setCalibrationMode(enabled) end
end
local function supported()
  if not powertrain or not powertrain.getDevice or not v or not v.data then return false end
  local hasController=false
  for _,row in pairs(v.data.controller or {}) do
    if row.fileName=='companion_custom_ecu' then hasController=true end
  end
  if not hasController then return false end
  for _,name in ipairs(names) do
    local motor=powertrain.getDevice('evMotor'..name)
    if not motor or motor.electricsThrottleName~='companionCustom'..name then return false end
  end
  return true
end
local function release()
  if control then
    for _,name in ipairs({'throttle','brake','steering','parkingbrake'}) do
      -- Do not cancel an input that the human has already taken back.
      if input.state[name] and input.state[name].source=='mininiDebug' then
        input.event(name,0,FILTER_DIRECT,nil,nil,nil,'mininiDebug')
      end
    end
  end
  control=nil;lease=0;speedIntegral=0;calibration(false)
end
local function publish(data)
  obj:queueGameEngineLua(string.format("if extensions.mininiDebug then extensions.mininiDebug.ingest(%d,%q) end",obj:getID(),jsonEncode(data)))
end
local function initializeIMUs()
  local cfg
  for _,row in pairs(v.data.controller or {}) do
    if row.fileName=='companion_custom_ecu' then cfg=row.imu end
  end
  -- Also diagnose older exports whose ECU never initialized.
  if not cfg then cfg=jsonReadFile('/lua/vehicle/extensions/mininiDebugIMU.json') end
  local ok,result=pcall(createIMUSampler,cfg)
  if ok then sampler=result else imuError=tostring(result) end
end
local function finite(value)
  return type(value)=='number' and value==value and math.abs(value)<math.huge
end
local function alignment()
  -- Diagnostic angles only. These never enter the custom ECU's sensor inputs.
  if not obj.getNodePosition then return {} end
  local ids={}
  for key,node in pairs(v.data.nodes or {}) do
    if type(node)=='table' and type(node.name)=='string' then ids[node.name]=node.cid or key end
  end
  local corners={FL='cc1ll',FR='cc1rr',RL='cc4ll',RR='cc4rr'}
  for _,row in pairs(v.data.controller or {}) do
    if row.fileName=='companion_custom_ecu' and row.imu and row.imu.bodyCornerNodes then corners=row.imu.bodyCornerNodes end
  end
  for _,name in ipairs(names) do if not corners[name] or not ids[corners[name]] then return {} end end
  local fl,fr,rl,rr=obj:getNodePosition(ids[corners.FL]),obj:getNodePosition(ids[corners.FR]),obj:getNodePosition(ids[corners.RL]),obj:getNodePosition(ids[corners.RR])
  local forward=(fl+fr-rl-rr)*0.5
  local left=(fl+rl-fr-rr)*0.5
  if forward:length()<.1 or left:length()<.1 then return {} end
  forward:normalize()
  local up=forward:cross(left)
  if up:length()<.1 then return {} end
  up:normalize();left=up:cross(forward);left:normalize()
  local result={}
  for _,w in pairs(wheels.wheels or {}) do
    if w.node1 and w.node2 then
      local axis=obj:getNodePosition(w.node2)-obj:getNodePosition(w.node1)
      if axis:length()>.01 then
        axis:normalize()
        if axis:dot(left)<0 then axis=axis*-1 end
        local rolling=axis:cross(up)
        result[w.name]={steerDegrees=math.atan2(rolling:dot(left),rolling:dot(forward))*180/math.pi,
          camberDegrees=math.asin(math.max(-1,math.min(1,axis:dot(up))))*180/math.pi,
          slipSpeed=w.lastSlip or 0,sideSlipSpeed=w.lastSideSlip or 0}
      end
    end
  end
  return result
end
local function snapshot()
  if not supported() then
    publish({status='unsupported',reason='Only Companion EVs with four custom motor channels are enabled.'})
    return
  end
  local ecu=controller.getController('companion_custom_ecu')
  local state
  if ecu and type(ecu.getDebugState)=='function' then
    local ok,result=pcall(ecu.getDebugState)
    if ok then state=result else state={error=tostring(result),failed=true} end
  else
    state={failed=ecu==nil,error=ecu and 'Older ECU: detailed diagnostics unavailable.' or 'Custom ECU did not initialize. Check beamng.log.'}
  end
  local motors,wheelData={},{}
  for _,name in ipairs(names) do
    local m=powertrain.getDevice('evMotor'..name)
    motors[name]={rpm=m.outputRPM or 0,torque=m.outputTorque1 or 0,
      throttle=m.throttle or 0,regen=m.regenThrottle or 0,hasEnergy=m.hasEnergy,isBroken=m.isBroken,
      command=electrics.values['companionCustom'..name] or 0,
      regenCommand=electrics.values['companionCustomRegen'..name] or 0}
  end
  for _,wheel in pairs(wheels.wheels or {}) do
    for _,name in ipairs(names) do
      if wheel.name==name then
        wheelData[name]={speed=wheel.wheelSpeed or 0,
          rpm=(wheel.angularVelocity or 0)*(wheel.wheelDir or 1)*9.549296586}
      end
    end
  end
  publish({status='ready',model=v.data.model,remoteActive=control~=nil,speed=obj:getVelocity():length(),
    pedals={throttle=input.throttle or 0,brake=input.brake or 0,
      steering=input.steering or 0,parkingBrake=input.parkingbrake or 0},
    gear=electrics.values.gear,gearIndex=electrics.values.gearIndex,
    ecu=state,motors=motors,wheels=wheelData,imu=imu,imuError=imuError,alignment=alignment(),debugVersion=M.version,
    launch=electrics.values.companionLaunchState or 0,
    vectoring=electrics.values.companionVectoringState or 0,
    calibrationActive=control and control.calibration==true or false,
    speedHoldKmh=control and control.speedKmh or nil,
    steeringWheelLock=v.data.input and v.data.input.steeringWheelLock or 480})
end
local function request(encoded)
  local ok,p=pcall(jsonDecode,encoded)
  if not ok or type(p)~='table' or p.schema~=1 or p.vehicleID~=obj:getID() then return end
  if p.op=='release' then release();return end
  if not supported() then snapshot();return end
  if p.op=='snapshot' then snapshot();return end
  if p.op~='control' then return end
  for _,name in ipairs({'throttle','brake','steering','parkingbrake'}) do
    local val=p[name]
    local low=name=='steering' and -1 or 0
    if not finite(val) or val<low or val>1 then return end
  end
  if p.steeringDegrees~=nil then
    local lock=v.data.input and v.data.input.steeringWheelLock or 480
    if not finite(p.steeringDegrees) or math.abs(p.steeringDegrees)>lock then return end
    p.steering=p.steeringDegrees/lock
  end
  if p.speedKmh~=nil then
    if not finite(p.speedKmh) or p.speedKmh<1 or p.speedKmh>20 then return end
    local ecu=controller.getController('companion_custom_ecu')
    if not ecu or not ecu.setCalibrationMode then return end
  end
  if p.calibration~=nil and type(p.calibration)~='boolean' then return end
  if p.calibration==true and p.speedKmh==nil then return end
  if p.gear~=nil and p.gear~=-1 and p.gear~=0 and p.gear~=1 then return end
  if p.gear~=nil and controller.mainController and controller.mainController.shiftToGearIndex then
    -- BeamNG's electric selector maps H-shifter index 1 to Park, 2 to Drive.
    controller.mainController.shiftToGearIndex(p.gear==1 and 2 or p.gear)
  end
  if not control or control.speedKmh~=p.speedKmh then speedIntegral=0 end
  control=p;lease=.5;calibration(p.calibration==true)
end
local function onPhysicsStep(dt)
  if not sampler or not supported() then return end
  -- Node positions are exposed at the vehicle update cadence. Sampling every
  -- solver substep would alternate a gyro spike with zero-rate readings.
  sampleElapsed=sampleElapsed+dt
  if sampleElapsed<.01 then return end
  local interval=sampleElapsed;sampleElapsed=0
  local ok,result=pcall(sampler.sample,interval)
  if ok then imu=result else imuError=tostring(result);sampler=nil end
end
local function updateGFX(dt)
  if control then
    lease=lease-dt
    if not supported() or lease<=0 then release() else
      local throttle,brake=control.throttle,control.brake
      if control.speedKmh then
        local speed=obj:getVelocity():length()
        local error=control.speedKmh/3.6-speed
        speedIntegral=math.max(-.4,math.min(.4,speedIntegral+error*dt))
        local command=math.max(-.3,math.min(.3,.08*error+.05*speedIntegral))
        throttle=math.max(0,command);brake=math.max(0,-command)
      end
      for _,name in ipairs({'throttle','brake','steering','parkingbrake'}) do
        local value=name=='throttle' and throttle or (name=='brake' and brake or control[name])
        input.event(name,value,FILTER_DIRECT,nil,nil,nil,'mininiDebug')
      end
    end
  end
  elapsed=elapsed+dt
  if elapsed>=.05 then elapsed=0;snapshot() end
end
M.onExtensionLoaded=function()
  if supported() then
    initializeIMUs()
    if type(enablePhysicsStepHook)=='function' then enablePhysicsStepHook() end
  end
end
M.onReset=function()
  release();imu={};sampler=nil;imuError=nil;sampleElapsed=0
  if supported() then initializeIMUs() end
end
M.onExtensionUnloaded=release
M.release=release
M.request=request
M.onPhysicsStep=onPhysicsStep
M.updateGFX=updateGFX
return M
