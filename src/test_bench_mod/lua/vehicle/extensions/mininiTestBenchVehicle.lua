local M={}
local names={'FL','FR','RL','RR'}
local test,lease,phase,baseline,integral,settled,elapsed=nil,0,'idle',{},0,0,0
local originalEvent,blockedEvent
local session=0
local steeringElapsed=0
local previousHeading,yawRate,rcDistance=nil,0,nil
local rotationSpeed
local function sampleMotion(dt)
  if not obj.getDirectionVector then return end
  local direction=obj:getDirectionVector()
  local horizontal=math.sqrt(direction.x*direction.x+direction.y*direction.y)
  if horizontal<.1 or dt<=0 or dt>.25 then previousHeading=nil;yawRate=0;rcDistance=nil;rotationSpeed=nil;return end
  local heading={x=direction.x/horizontal,y=direction.y/horizontal}
  if previousHeading then
    local rate=math.atan2(previousHeading.x*heading.y-previousHeading.y*heading.x,
      previousHeading.x*heading.x+previousHeading.y*heading.y)/dt
    yawRate=math.deg(rate)
    local velocity=obj:getVelocity()
    local speed=math.sqrt(velocity.x*velocity.x+velocity.y*velocity.y)
    -- Horizontal instantaneous radius from motion, independent of ECU targets.
    rcDistance=math.abs(rate)>=math.rad(.5) and speed/math.abs(rate) or nil
    rotationSpeed=rcDistance and math.abs(rate)*rcDistance*3.6 or nil
  end
  previousHeading=heading
end
local function ecu() return controller and controller.getController and controller.getController('companion_custom_ecu') end
local function publish(reason)
  local motors={}
  for _,n in ipairs(names) do
    local motor=powertrain.getDevice('evMotor'..n)
    motors[n]=motor and motor.outputTorque1 or 0
  end
  local estimator=extensions and extensions.mininiEstimatedRC
  local estimated=estimator and estimator.getState and estimator.getState()
  local c=ecu()
  local state=c and c.getDebugState and c.getDebugState().input
  local data={session=session,phase=phase,reason=reason,speed=obj:getVelocity():length()*3.6,torques=motors,
    yawRate=yawRate,rcDistance=rcDistance,
    rotationSpeed=rotationSpeed,estimatedRotationSpeed=estimated and estimated.rotationSpeed,
    wantedRotationSpeed=state and state.wantedRotationSpeed or 30,
    baseline=baseline,mode=test and test.mode or nil,
    steeringLock=v.data.input and v.data.input.steeringWheelLock or 480}
  obj:queueGameEngineLua(string.format('if extensions.mininiTestBench then extensions.mininiTestBench.ingest(%d,%q) end',obj:getID(),jsonEncode(data)))
end
local function release(reason)
  local c=ecu();if c and c.setTestTorque then c.setTestTorque(nil) end
  if originalEvent then
    if input.event==blockedEvent then input.event=originalEvent end
    for _,name in ipairs({'throttle','brake','steering','parkingbrake'}) do originalEvent(name,0,FILTER_DIRECT,nil,nil,nil,'mininiTestBench') end
  end
  originalEvent,blockedEvent=nil,nil
  test=nil;lease=0;phase='idle';integral=0;settled=0
  if reason then publish(reason) end
end
local function request(encoded)
  local ok,data=pcall(jsonDecode,encoded)
  if not ok or type(data)~='table' then return end
  if data.op=='snapshot' then publish();return end
  if data.op=='stop' then release('Stopped');return end
  if data.op=='heartbeat' then if test then lease=1 end;return end
  if data.op=='update' then
    if not test or data.session~=session then return end
    local lock=v.data.input and v.data.input.steeringWheelLock or 480
    if data.mode~='exact' and data.mode~='additional' then return end
    if type(data.steering)~='number' or data.steering~=data.steering or math.abs(data.steering)>lock then return end
    local copy={}
    for _,n in ipairs(names) do
      local value=data.torque and data.torque[n]
      if type(value)~='number' or value~=value or math.abs(value)>1500 then return end
      if data.mode=='additional' and math.abs(value+(baseline[n] or 0))>5000 then publish('Baseline plus offset exceeds 5000 Nm');return end
      copy[n]=value
    end
    test.mode=data.mode;test.torque=copy;test.steering=data.steering
    publish('Settings updated');return
  end
  if data.op~='start' then return end
  release()
  session=data.session or 0
  local c=ecu()
  if not c or type(c.setTestTorque)~='function' then phase='unsupported';publish('Reapply the Companion patch to a four-motor Minini first.');return end
  for _,n in ipairs(names) do
    local motor=powertrain.getDevice('evMotor'..n)
    if not motor or motor.isBroken or motor.hasEnergy==false then phase='unsupported';publish('Four healthy powered Minini motors are required.');return end
  end
  if data.mode~='exact' and data.mode~='additional' then return end
  local function valid(x,limit)return type(x)=='number' and x==x and math.abs(x)<=limit end
  if not valid(data.speed,130) or data.speed<0 or not valid(data.steering,720) then return end
  local lock=v.data.input and v.data.input.steeringWheelLock or 480
  if math.abs(data.steering)>lock then phase='unsupported';publish('Steering angle exceeds this car steering-wheel lock.');return end
  for _,n in ipairs(names) do
    if not data.torque or not valid(data.torque[n],1500) then return end
    baseline[n]=powertrain.getDevice('evMotor'..n).outputTorque1 or 0
    if data.mode=='additional' and math.abs(baseline[n]+data.torque[n])>5000 then phase='unsupported';publish('Baseline plus offset exceeds 5000 Nm.');return end
  end
  test=data;lease=1;steeringElapsed=0;phase='steering'
  originalEvent=input.event
  blockedEvent=function(kind,value,filter,angle,lockType,clock,source)
    if source=='mininiTestBench' then return originalEvent(kind,value,filter,angle,lockType,clock,source) end
  end
  input.event=blockedEvent
  publish('Test started')
end
local function updateGFX(dt)
  sampleMotion(dt)
  if test then
    lease=lease-dt
    local c=ecu()
    if lease<=0 or not c or not c.setTestTorque then release('Test stopped: control lease expired');return end
    local values={}
    local steering=test.steering/(v.data.input and v.data.input.steeringWheelLock or 480)
    if phase=='steering' then
      steeringElapsed=steeringElapsed+dt
      for _,n in ipairs(names) do values[n]=0 end
      if steeringElapsed>=.3 then phase=test.speed>.1 and 'runup' or 'running' end
    end
    if phase=='runup' then
      local error=test.speed/3.6-obj:getVelocity():length()
      integral=math.max(-600,math.min(600,integral+error*dt*80))
      local drive=math.max(-600,math.min(600,error*160+integral))
      for _,n in ipairs(names) do values[n]=drive end
      if math.abs(error)<1/3.6 then settled=settled+dt else settled=0 end
      if settled>=.2 then
        phase='running'
        for _,n in ipairs(names) do baseline[n]=drive end
      end
    end
    if phase=='running' then
      steering=test.steering/(v.data.input and v.data.input.steeringWheelLock or 480)
      for _,n in ipairs(names) do values[n]=test.torque[n]+(test.mode=='additional' and baseline[n] or 0) end
    end
    for _,n in ipairs(names) do if math.abs(values[n])>5000 then release('Combined torque exceeds 5000 Nm');return end end
    if not c.setTestTorque(values) then release('ECU rejected test torque');return end
    for _,name in ipairs({'throttle','brake','steering','parkingbrake'}) do
      local value=name=='steering' and steering or 0
      originalEvent(name,value,FILTER_DIRECT,nil,nil,nil,'mininiTestBench')
      input[name]=value
      if input.state and input.state[name] then input.state[name].val=value end
    end
  end
  elapsed=elapsed+dt
  if elapsed>=.1 then elapsed=0;publish() end
end
M.request=request
M.updateGFX=updateGFX
M.onReset=function() previousHeading=nil;yawRate=0;rcDistance=nil;rotationSpeed=nil;release('Vehicle reset') end
M.onExtensionUnloaded=function() release() end
return M
