-- __CONTRACT__
-- __IMU__
-- __RC__
local source = __USER_SOURCE__
local M = {type='auxiliary', defaultOrder=100}
local user, memory, channels, failed, time, active, armed
local names = {'FL','FR','RL','RR'}
local imuSampler, geometry
local imuReadings,imuTime,imuDt={},0,0
local wantedRC
local rcEstimator,estimatedRC
local calibrationMode=false
local testTorque,testLease=nil,0
local lastInput, lastOutput, lastError
local function stop(reason)
  failed = true
  lastError=tostring(reason)
  for _,ch in pairs(channels or {}) do ch.command=0; ch.regen=0 end
  electrics.values.companionLaunchState=0
  electrics.values.companionYawTelemetryValid=0
  electrics.values.companionRCControlValid=0
  electrics.values.companionWheelCorrectionValid=0
  log('E','companion_custom_ecu',tostring(reason))
  if guihooks then guihooks.message('Custom ECU error: motors disabled. Check vehicle console.', 8, 'customECU') end
end
local function reset()
  testTorque,testLease=nil,0
  memory, time, active, armed, failed = {}, 0, false, false, false
  lastInput,lastOutput,lastError=nil,nil,nil
  electrics.values.companionYawTelemetryValid=0
  electrics.values.companionWheelCorrectionValid=0
  if imuSampler then imuSampler.reset() end
  imuReadings,imuTime,imuDt={},0,0
  wantedRC=nil
  estimatedRC=nil
  if rcEstimator then rcEstimator.reset() end
  for _,ch in pairs(channels or {}) do ch.command=0; ch.regen=0 end
  for _,name in ipairs(names) do
    if not channels or not channels[name] then
      stop('ECU initialization incomplete: missing motor channel '..name)
      return
    end
  end
  local ok, result = pcall(loadUser, source)
  if ok then user=result else stop(result) end
end
local function init(data)
  channels = {}
  geometry=data and data.imu
  local ok,result=pcall(createIMUSampler,geometry)
  if not ok then stop('IMU initialization: '..tostring(result));return end
  imuSampler=result
  rcEstimator=createRCEstimator()
  for _,name in ipairs(names) do
    local wheel
    for _,w in pairs(wheels.wheels) do if w.name==name then wheel=w end end
    local motor=powertrain.getDevice('evMotor'..name)
    if not motor or not wheel then stop('Missing motor/wheel '..name); return end
    channels[name]={wheel=wheel,motor=motor,command=0,regen=0}
  end
  reset()
end
local function updateGFX(dt)
  -- Node poses are exposed on the graphics-frame clock. Differencing these
  -- inside the independent fixed-step clock produced shared half-rate spikes.
  if not imuSampler or dt<=0 then return end
  local ok,result=pcall(imuSampler.sample,dt)
  if not ok then stop('IMU sampling: '..tostring(result));return end
  imuReadings=result;imuTime=imuTime+dt;imuDt=dt
  estimatedRC=nil
  if rcEstimator and obj.getPosition then estimatedRC=rcEstimator.sample(result,dt) end
  -- Temporary wanted center: fixed 10 m radius, steering chooses the side.
  -- Use the IMU chassis frame because Minini's model axes are nonstandard.
  wantedRC=nil
  local steering=input.steering or 0
  if steering~=0 and obj.getPosition then
    local cx,cy,cz,lx,ly,count=0,0,0,0,0,0
    for _,name in ipairs(names) do
      local sensor=result[name]
      local frame=sensor and sensor.valid and sensor.frame
      if frame then
        cx=cx+frame.position.x;cy=cy+frame.position.y;cz=cz+frame.position.z
        lx=lx+frame.left.x;ly=ly+frame.left.y;count=count+1
      end
    end
    local length=math.sqrt(lx*lx+ly*ly)
    if count==4 and length>.1 then
      local origin=obj:getPosition()
      local side=steering>0 and -1 or 1 -- positive input is right
      wantedRC={x=origin.x+cx/4+side*10*lx/length,y=origin.y+cy/4+side*10*ly/length,
        z=origin.z+cz/4,distance=10,side=side>0 and 'left' or 'right'}
    end
  end
end
local function updateFixedStep(dt)
  testLease=testLease-dt
  if testLease<=0 then testTorque=nil end
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
        electrics.values.companionCustomRegen=0 -- old shared channel stays disabled
        electrics.values['companionCustomRegen'..name]=failed and 0 or ch.regen
        device.minWantedRegenTorque=0
        device.maxWantedRegenTorque=math.huge
        -- Stock clutchless motors look up RPM zero when throttle is zero
        -- (sign(throttle)=0). Supply the actual shaft-speed regen value there,
        -- then restore the curve. Stock torque and energy accounting do the work.
        local curve=device.regenCurve
        local zero=curve and curve[0]
        if curve then curve[0]=curve[math.floor(math.abs((device.outputAV1 or 0)*9.549296586))] or 0 end
        ch.original(device,step)
        if curve then curve[0]=zero end
        if testTorque then
          -- Ideal prescribed shaft torque, independent of RPM torque curves.
          -- Stock dynamics and reaction torque still run; correct net work.
          local requested=testTorque[name] or 0
          if device.isBroken or device.hasEnergy==false then requested=0 end
          local delta=requested-(device.outputTorque1 or 0)
          device.outputTorque1=requested
          local work=delta*(device.outputAV1 or 0)*step
          device.grossWorkPerUpdate=(device.grossWorkPerUpdate or 0)+work
          local efficiency=device.electricalEfficiencyTable and device.electricalEfficiencyTable[math.floor(math.abs(device.engineLoad or 0)*100)*.01] or 1
          device.spentEnergy=(device.spentEnergy or 0)+work/math.max(efficiency or 1,.01)
        end
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
  local s={dt=dt,time=time,wheelSpeed={},wheelRPM={},motorRPM={},wheelGroundSpeed={},motorLimits={},
    bodySpeed=velocity:length(),forwardSpeed=velocity:dot(obj:getDirectionVector()),
    acceleration={x=sensors.gx or 0,y=sensors.gy or 0,z=sensors.gz or 0},
    throttle=input.throttle or 0,brake=input.brake or 0,parkingBrake=input.parkingbrake or 0,
    steering=input.steering or 0,gear=electrics.values.gearIndex or 0,
    gearName=electrics.values.gear or '',launchActive=active,launchArmed=armed}
  s.imu=imuReadings
  s.imuSampleTime=imuTime
  s.imuSampleDt=imuDt
  s.wantedRC=wantedRC
  s.wantedRotationSpeed=30 -- km/h, temporary constant WRS target
  s.estimatedRC=estimatedRC
  s.rcEstimatorVersion=1
  s.geometry=geometry
  s.calibrationActive=calibrationMode
  local velocities={}
  for _,sensor in pairs(s.imu) do
    if sensor.valid and sensor.velocity then velocities[#velocities+1]=sensor.velocity.forward end
  end
  if #velocities>=3 then
    table.sort(velocities)
    local middle=math.floor((#velocities+1)/2)
    s.travelSpeed=#velocities%2==0 and (velocities[middle]+velocities[middle+1])/2 or velocities[middle]
  end
  s.steeringWheelLock=v.data.input and v.data.input.steeringWheelLock or 480
  s.motorTorque={}
  for name,ch in pairs(channels) do
    s.wheelSpeed[name]=ch.wheel.wheelSpeed or 0
    s.wheelRPM[name]=(ch.wheel.angularVelocity or 0)*(ch.wheel.wheelDir or 1)*9.549296586
    s.motorRPM[name]=ch.motor.outputRPM or 0
    -- Read-only calibration/actuator limits, not another motor-control policy.
    -- The user Lua allocates Nm, then returns the matching drive/regen fractions.
    local motor=ch.motor
    s.motorTorque[name]=motor.outputTorque1 or 0
    local rpm=math.floor(math.abs((motor.outputAV1 or 0)*9.549296586))
    local available=motor.hasEnergy~=false and not motor.isBroken
    local damage=math.max(0,math.min(1,motor.outputTorqueState or 1))
    s.motorLimits[name]={
      drive=available and math.max(0,(motor.torqueCurve and motor.torqueCurve[rpm] or 0)*damage) or 0,
      regen=available and math.max(0,motor.regenCurve and motor.regenCurve[rpm] or 0) or 0,
      radius=ch.wheel.radius or ch.wheel.dynamicRadius or .313,
      inertia=geometry and geometry.wheelInertia or .611}
    s.wheelGroundSpeed[name]=s.bodySpeed
    -- Project hub motion onto the wheel's rolling direction. This follows steering
    -- and cornering without trusting AutoCraft's misaligned forward reference axis.
    local w=ch.wheel
    if w.node1 and w.node2 and obj.getNodePosition and obj.getNodeVelocityVector and obj.getDirectionVectorUp then
      local axis=obj:getNodePosition(w.node2)-obj:getNodePosition(w.node1)
      local rolling=axis:cross(obj:getDirectionVectorUp())
      if rolling:length()>1e-6 then
        rolling:normalize()
        s.wheelGroundSpeed[name]=math.abs(obj:getNodeVelocityVector(w.node1):dot(rolling))
      end
    end
  end
  lastInput=s
  local ok,out
  if testTorque then
    ok=true;out={FL=0,FR=0,RL=0,RR=0,regen={FL=0,FR=0,RL=0,RR=0},gear=1}
  else ok,out=pcall(evaluateUser,user,s,memory) end
  if not ok then stop(out); return end
  lastOutput=out
  -- The user Lua chooses direction. Stock selector is only its actuator/display.
  if out.gear~=nil and controller and controller.mainController then
    local selector=controller.mainController
    if electrics.values.gearboxMode~='realistic' and selector.setGearboxMode then
      selector.setGearboxMode('realistic')
    end
    local desired=out.gear==1 and 'D' or (out.gear==-1 and 'R' or 'N')
    if electrics.values.gear~=desired and selector.shiftToGearIndex then
      selector.shiftToGearIndex(out.gear==1 and 2 or out.gear)
    end
  end
  for name,ch in pairs(channels) do ch.command=out[name]; ch.regen=out.regen and out.regen[name] or 0 end
  local wasActive, wasArmed = active, armed
  active,armed=out.launchActive==true,out.launchArmed==true
  local tv=type(out.vectoring)=='table' and out.vectoring or {}
  electrics.values.companionRCControlValid=type(out.trc)=='table' and 1 or 0
  electrics.values.companionWantedRC=tv.wantedRC
  electrics.values.companionEstimatedRC=tv.estimatedRC
  electrics.values.companionRCError=tv.rcError
  electrics.values.companionWantedRS=tv.wantedRS
  electrics.values.companionEstimatedRS=tv.estimatedRS
  electrics.values.companionRSError=tv.rsError
  electrics.values.companionVectoringState=tv.active and (tv.axle=='all' and 3 or (tv.axle=='front' and 1 or 2)) or 0
  electrics.values.companionRecoveryStop=tv.recoveryStop and 1 or 0
  electrics.values.companionRequestedYawMoment=tv.requestedYawMoment or 0
  electrics.values.companionAllocatedYawMoment=tv.allocatedYawMoment or 0
  electrics.values.companionYawRate=tv.yawRate or 0
  electrics.values.companionTargetYawRate=tv.targetYawRate or 0
  electrics.values.companionYawRateError=tv.yawRateError
  electrics.values.companionYawCorrection=tv.yawCorrection
  electrics.values.companionBrakePedal=s.brake
  electrics.values.companionAcceleratorPedal=s.throttle
  electrics.values.companionPedalRequest=tv.pedalRequest
  electrics.values.companionYawTelemetryValid=(type(tv.yawRate)=='number' and type(tv.targetYawRate)=='number') and 1 or 0
  electrics.values.companionWheelCorrectionValid=type(tv.wheelCorrection)=='table' and 1 or 0
  for _,name in ipairs(names) do
    local row=type(tv.wheelCorrection)=='table' and tv.wheelCorrection[name] or nil
    for key,field in pairs({Share='share',MotorUse='motorUse',GripUse='gripUse',LongitudinalSlip='longitudinalSlip',LateralSlipDegrees='lateralSlip',TorqueNm='commandedTorqueNm',DeltaNm='deltaTorqueNm',YawMomentNm='yawMomentNm',MotorLimitNm='motorLimitNm',GripLimitNm='gripLimitNm'}) do
      electrics.values['companionTV'..name..key]=row and row[field] or nil
    end
    electrics.values['companionTV'..name..'Slipping']=row and (row.slipping and 1 or 0) or nil
  end
  electrics.values.companionRollEstimate=tv.rollEstimate
  electrics.values.companionPitchEstimate=tv.pitchEstimate
  electrics.values.companionSideslipEstimate=tv.sideslipEstimate or 0
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
    ch.regen=0
    if ch.motor.torqueUpdate==ch.wrapper then ch.motor.torqueUpdate=ch.original end
  end
end
M.init,M.reset,M.updateFixedStep,M.shutdown=init,reset,updateFixedStep,shutdown
M.updateGFX=updateGFX
-- Dedicated test bench: ideal prescribed torque, with a short heartbeat lease.
M.setTestTorque=function(values)
  if values==nil then testTorque=nil;testLease=0;return true end
  if failed then return false end
  local copy={}
  for _,name in ipairs(names) do
    local value=values[name]
    if type(value)~='number' or value~=value or math.abs(value)>5000 then return false end
    copy[name]=value
  end
  testTorque=copy;testLease=1;return true
end
M.setCalibrationMode=function(enabled) calibrationMode=enabled==true end
M.getDebugState=function()
  local motors={}
  for name,ch in pairs(channels or {}) do
    local m=ch.motor
    motors[name]={command=ch.command,regen=ch.regen,rpm=m.outputRPM or 0,
      torque=m.outputTorque1 or 0,throttle=m.throttle or 0,
      hasEnergy=m.hasEnergy,isBroken=m.isBroken}
  end
  return {version=2,failed=failed==true,error=lastError,input=lastInput,
    output=lastOutput,motors=motors,imuConfigured=imuSampler~=nil}
end
return M
