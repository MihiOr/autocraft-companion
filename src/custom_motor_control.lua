-- Primitive ECU: Interpreter -> TRC -> MiTVS -> motor commands.
-- Pedal request is normalized acceleration demand [-1,1], not measured m/s^2.
local names={'FL','FR','RL','RR'}
local function clamp(x,a,b) return math.max(a,math.min(b,x)) end
local function sign(x) return x<0 and -1 or 1 end
local function Interpreter(accelerator,brake)
  accelerator=clamp(accelerator or 0,0,1);brake=clamp(brake or 0,0,1)
  return brake>0 and -brake or accelerator
end

-- Steering never enters TRC. Local probes refine the selected peak; periodic
-- full-range sweeps cross falling sections instead of stopping at first peak.
local function searchPeak(w,slip,torque,omega,inertia,dt)
  w.age=(w.age or 0)+dt
  local alpha=w.omega and (omega-w.omega)/dt or 0
  local transmitted=math.max(0,sign(torque)*(torque-inertia*alpha))
  w.rawContact=transmitted
  w.contact=w.contact and w.contact+(transmitted-w.contact)*(1-math.exp(-dt/.04)) or transmitted
  w.omega=omega
  w.clock=(w.clock or 0)+dt
  local half=.3
  local phase=w.clock<half and 'low' or 'high'
  local phaseTime=w.clock<half and w.clock or w.clock-half
  -- Let torque/slip settle before measuring each probe's response.
  if math.abs(torque)>20 and slip<.5 and phaseTime>.1 then
    local observation=w[phase] or {force=0,slip=0,time=0};w[phase]=observation
    observation.force=observation.force+w.contact*dt
    observation.slip=observation.slip+slip*dt
    observation.time=observation.time+dt
  end
  -- Retain the observed local force/slip curve as a check on the probes. Probe
  -- phase alone can mislead during a spin recovery where slip lags the target.
  if w.previousSlip and math.abs(torque)>20 and slip>0 and slip<.4 then
    local observed=(slip+w.previousSlip)/2
    local index=math.floor(observed/.01+.5)
    w.curve=w.curve or {}
    local bin=w.curve[index] or {force=transmitted,count=0};w.curve[index]=bin
    bin.force=bin.force+(transmitted-bin.force)*.15;bin.count=bin.count+1;bin.seen=w.age
  end
  w.previousSlip=slip
  w.searchTime=(w.searchTime or 0)+dt
  if not w.sweep and w.searchTime>= (w.searched and 12 or 1.3) and math.abs(torque)>20 then
    w.sweep={time=0,bins={}};w.searchTime=0
  end
  if w.sweep then
    local sweep=w.sweep;sweep.time=sweep.time+dt
    -- Four seconds of bounded exploration, including valleys between peaks.
    -- Score actual measured slip, never the requested target that may lag it.
    local step=math.min(13,math.floor(sweep.time/.3))
    local target=.03+step*.02
    if sweep.time% .3>.1 and math.abs(torque)>20 and slip>=.02 and slip<=.33 then
      local index=math.floor(slip/.01+.5)
      local bin=sweep.bins[index] or {sum=0,time=0};sweep.bins[index]=bin
      bin.sum=bin.sum+w.contact*dt;bin.time=bin.time+dt
    end
    if sweep.time<4.2 then return target end
    local bestIndex,bestForce
    for index,bin in pairs(sweep.bins) do
      local force=bin.sum/math.max(bin.time,.001)
      if bin.time>=.03 and (not bestForce or force>bestForce) then bestIndex,bestForce=index,force end
    end
    if bestIndex then w.peak=clamp(bestIndex*.01,.03,.30) end
    w.sweep=nil;w.searched=true;w.searchTime=0;w.clock=0;w.low=nil;w.high=nil;w.curve=nil
    return w.peak
  end
  if w.clock>=2*half then
    local low,high=w.low,w.high
    if low and high and low.time>.05 and high.time>.05 then
      local dl=high.slip/high.time-low.slip/low.time
      local df=high.force/high.time-low.force/low.time
      local mean=(high.force/high.time+low.force/low.time)/2
      if math.abs(dl)>.003 and math.abs(df)>math.max(2,mean*.005) then
        w.peak=clamp(w.peak+(df/dl>0 and .008 or -.008),.03,.30)
      end
    end
    local bestIndex,bestForce
    for index,bin in pairs(w.curve or {}) do
      local left,right=w.curve[index-1],w.curve[index+1]
      if index>=3 and index<=30 and bin.count>=3 and left and right and left.count>=2 and right.count>=2
          and w.age-bin.seen<3 and w.age-left.seen<3 and w.age-right.seen<3
          and bin.force>=left.force and bin.force>=right.force and (not bestForce or bin.force>bestForce) then
        bestIndex,bestForce=index,bin.force
      end
    end
    if bestIndex then w.peak=clamp(w.peak+clamp(bestIndex*.01-w.peak,-.024,.024),.03,.30) end
    w.clock=w.clock-2*half;w.low=nil;w.high=nil
  end
  return clamp(w.peak+(w.clock<half and -.012 or .012),.02,.32)
end
local function TRC(request,sensors,memory)
  local base,limits,levels={},{},{}
  local dt=clamp(sensors.dt or .01,.001,.1)
  local travel=sensors.travelSpeed or sensors.forwardSpeed or sensors.bodySpeed or 0
  local direction=math.abs(travel)>.5 and sign(travel) or sensors.gear
  for _,n in ipairs(names) do
    local motor=sensors.motorLimits and sensors.motorLimits[n] or {}
    local drive=math.max(0,motor.drive or 0);local regen=math.max(0,motor.regen or 0)
    local radius=motor.radius or .313
    local omega=(sensors.wheelRPM and sensors.wheelRPM[n] or 0)*math.pi/30
    local ground=math.abs(sensors.wheelGroundSpeed and sensors.wheelGroundSpeed[n] or travel)
    local rolling=math.abs(sensors.wheelSpeed and sensors.wheelSpeed[n] or omega*radius)
    -- Slip ratio is undefined at rest; only regularize the numerical singularity.
    local signedSlip=(rolling-ground)/math.max(ground,.05)
    local slip=math.abs(signedSlip)
    local w=memory[n] or {peak=.1,gain=0};memory[n]=w
    local torque=sensors.motorTorque and sensors.motorTorque[n] or 0
    local braking=request<0 or (request==0 and torque*direction<0)
    local mode=braking and 'braking' or 'driving'
    if w.mode and w.mode~=mode then
      w.modePeaks=w.modePeaks or {};w.modePeaks[w.mode]=w.peak
      w.peak=w.modePeaks[mode] or .1
      w.curve=nil;w.low=nil;w.high=nil;w.clock=0;w.filteredSlip=nil;w.previousSlip=nil
      w.sweep=nil;w.searchTime=0;w.searched=nil
    end
    w.mode=mode
    local controlSlip=braking and -signedSlip or signedSlip
    local target=searchPeak(w,math.max(0,controlSlip),torque,omega,motor.inertia or .611,dt)
    local requested=request>=0 and sensors.gear*request*drive or -direction*(-request)*regen
    if controlSlip>target+.005 then
      -- Discard unused capacity above the torque actually being requested or
      -- applied. This changes no shaft torque, but removes servo wind-up at
      -- partial pedal so it needn't chew through irrelevant full-motor headroom.
      local capacity=math.max(1,request>=0 and drive or regen)
      w.gain=math.min(w.gain,clamp(math.max(math.abs(requested),math.abs(torque))/capacity,0,1))
    end
    local previous=w.filteredSlip or controlSlip
    w.filteredSlip=previous+(controlSlip-previous)*(1-math.exp(-dt/.025))
    -- Continuous slip servo: add torque below target and remove it above.
    -- A mild rate term damps spin acceleration; no exponential grip cut.
    local change=dt*8*(target-w.filteredSlip)-.06*(w.filteredSlip-previous)
    local groundAcceleration=w.ground and (ground-w.ground)/dt or 0;w.ground=ground
    if math.abs(torque)>20 and w.filteredSlip>target*.5 then
      local capacity=math.max(1,braking and regen or drive)
      local tracking=(motor.inertia or .611)/radius*(ground*40*(target-w.filteredSlip)
        +(braking and -1 or 1)*groundAcceleration*(1+target))
      -- Contact-torque feedforward must not freeze the allowance at a weak
      -- starting value: restore torque from slip error at every road speed.
      tracking=tracking+capacity*.5*(target-w.filteredSlip)
      local desired=clamp((w.rawContact+tracking)/capacity,0,1)
      change=desired-w.gain
    end
    local runaway=controlSlip>math.max(.5,target*4)
    w.gain=clamp(w.gain+clamp(change,-dt*(runaway and 12 or 8),dt*3),0,1)
    local usage=slip/w.peak -- 1 = estimated peak; not clamped at 1.
    local positive=(direction>0 and drive or regen)*w.gain
    local negative=(direction>0 and regen or drive)*w.gain
    base[n]=clamp(requested,-negative,positive)
    limits[n]={low=-negative,high=positive,drive=drive,regen=regen,radius=radius,
      positiveMotor=direction>0 and drive or regen,negativeMotor=direction>0 and regen or drive,
      weight=math.max(.005,w.gain/(1+usage*usage))}
    levels[n]={usage=usage,slip=slip,controlSlip=controlSlip,peak=w.peak,target=target,gain=w.gain,contactTorque=w.contact}
  end
  return base,limits,levels
end

-- Bounded weighted allocation of added longitudinal force and yaw moment.
-- Saturated motors leave the solve; remaining wheels take over.
local function allocate(force,moment,limits,geometry)
  local delta,free,arm={},{},{}
  for _,n in ipairs(names) do
    delta[n]=0;free[n]=true
    local track=(n:sub(1,1)=='F' and geometry.trackFront or geometry.trackRear) or 1.6
    arm[n]=(n:sub(2,2)=='L' and 1 or -1)*track/2
  end
  for _=1,5 do
    local a,b,c=0,0,0
    for _,n in ipairs(names) do
      if free[n] then
        local w=limits[n].weight;local x=1/limits[n].radius;local y=-arm[n]*x
        a=a+w*x*x;b=b+w*x*y;c=c+w*y*y
      end
    end
    local determinant=a*c-b*b
    local u,v=0,0
    if determinant>1e-9 then u=(force*c-moment*b)/determinant;v=(moment*a-force*b)/determinant
    elseif c>1e-9 then v=moment/c -- one side left: prioritize turning correction
    elseif a>1e-9 then u=force/a end
    local clipped=false;local proposed={}
    for _,n in ipairs(names) do
      if free[n] then
        local lim=limits[n];local change=lim.weight*(u-arm[n]*v)/lim.radius
        proposed[n]=change
        local bounded=clamp(change,lim.deltaLow,lim.deltaHigh)
        if math.abs(change-bounded)>1e-6 then
          delta[n]=bounded;free[n]=false;clipped=true
          force=force-bounded/lim.radius;moment=moment+arm[n]*bounded/lim.radius
        end
      end
    end
    if not clipped then for n,value in pairs(proposed) do delta[n]=value end;break end
  end
  return delta,arm
end

local function MiTVS(base,limits,levels,state)
  local e,w=state.estimatedRC,state.wantedRC
  local active=e~=nil and w~=nil and e.distance<15
  local force,moment,rcError,rsError=0,0,0,0
  if active then
    local dx,dy=w.x-e.x,w.y-e.y -- WRC - ERC, chassis axes.
    rcError=dx*e.left.x+dy*e.left.y
    rsError=(state.wantedRotationSpeed or 30)-e.rotationSpeed -- WRS - ERS, km/h
    local targetLeft=((e.x-e.center.x)+dx)*e.left.x+((e.y-e.center.y)+dy)*e.left.y
    local targetForward=((e.x-e.center.x)+dx)*e.forward.x+((e.y-e.center.y)+dy)*e.forward.y
    local radius2=math.max(1,targetLeft*targetLeft+targetForward*targetForward)
    local direction=sign(math.abs(e.forwardSpeed)>.5 and e.forwardSpeed or state.gear)
    local targetYaw=direction*((state.wantedRotationSpeed or 30)/3.6)*targetLeft/radius2
    local mass=state.geometry.mass or 715
    local inertia=mass*((state.geometry.wheelbase or 2.6)^2+((state.geometry.trackFront or 1.6))^2)/12
    moment=inertia*6*(targetYaw-e.yawRad)
    force=mass*.6*(rsError/3.6)*direction
  end
  for _,n in ipairs(names) do limits[n].deltaLow=limits[n].low-base[n];limits[n].deltaHigh=limits[n].high-base[n] end
  local delta,arm=allocate(force,moment,limits,state.geometry or {})
  local total,allocated=0,0
  for _,n in ipairs(names) do total=total+math.abs(delta[n]);allocated=allocated-arm[n]*delta[n]/limits[n].radius end
  local rows={}
  for _,n in ipairs(names) do
    local lim=limits[n];local d=delta[n]
    local motorLimit=math.max(1,d>=0 and lim.positiveMotor or lim.negativeMotor)
    rows[n]={share=total>1e-8 and math.abs(d)/total or 0,motorUse=d/motorLimit,
      gripUse=levels[n].usage,longitudinalSlip=levels[n].usage,lateralSlip=0,
      commandedTorqueNm=d,deltaTorqueNm=d,yawMomentNm=-arm[n]*d/lim.radius,
      motorLimitNm=motorLimit,gripLimitNm=math.max(math.abs(lim.low),lim.high),slipping=levels[n].usage>1}
  end
  return delta,{active=active,axle='all',rcError=rcError,rsError=rsError,
    requestedYawMoment=moment,allocatedYawMoment=allocated,wheelCorrection=rows,
    wantedRC=w and w.distance,estimatedRC=e and e.distance,
    wantedRS=state.wantedRotationSpeed or 30,estimatedRS=e and e.rotationSpeed}
end

return function(s,m)
  m.trc=m.trc or {}
  local gear=(s.gear or 1)<0 and -1 or 1
  local request=Interpreter(s.throttle,s.brake)
  -- Sensor-only boundary: steering and WRC/ERC never enter TRC.
  local sensorState={dt=s.dt,gear=gear,travelSpeed=s.travelSpeed,forwardSpeed=s.forwardSpeed,
    bodySpeed=s.bodySpeed,wheelSpeed=s.wheelSpeed,wheelRPM=s.wheelRPM,
    wheelGroundSpeed=s.wheelGroundSpeed,motorTorque=s.motorTorque,motorLimits=s.motorLimits}
  local base,limits,levels=TRC(request,sensorState,m.trc)
  local delta,tv=MiTVS(base,limits,levels,{estimatedRC=s.estimatedRC,wantedRC=s.wantedRC,
    wantedRotationSpeed=s.wantedRotationSpeed,steering=s.steering,gear=gear,geometry=s.geometry or {}})
  tv.pedalRequest=request
  local out={FL=0,FR=0,RL=0,RR=0,regen={FL=0,FR=0,RL=0,RR=0},gear=gear,vectoring=tv,
    trc={request=request,torques=base,slip=levels},mitvsDelta=delta}
  local travel=s.travelSpeed or s.forwardSpeed or 0
  local motion=math.abs(travel)>.5 and sign(travel) or gear
  for _,n in ipairs(names) do
    local torque=base[n]+delta[n]
    if torque*motion<0 then out.regen[n]=clamp(math.abs(torque)/math.max(1,limits[n].regen),0,1)
    else out[n]=clamp(torque/math.max(1,limits[n].drive),-1,1) end
  end
  return out
end
