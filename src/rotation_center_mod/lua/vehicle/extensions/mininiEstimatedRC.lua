-- Four-IMU inertial estimate, corrected by the existing corner velocity sensors.
-- Independent of the GE actual-pose rotation-center calculation; display only.
local M={}
local velocity,lastTime,estimate
local recording=false
local pending={}
local function plain(vector) return {x=vector.x,y=vector.y,z=vector.z} end
local function reset() velocity=nil;lastTime=nil;estimate=nil;pending={} end
local function sample()
  local model=tostring(v.vehicleDirectory or v.data.vehicleDirectory or v.data.jbeam or ''):lower()
  if model:find('civetta',1,true) then reset();return end
  local ecu=controller.getController('companion_custom_ecu')
  local state=ecu and ecu.getDebugState and ecu.getDebugState().input
  if not state or not state.geometry or not state.geometry.mounts then reset();return end
  if state.rcEstimatorVersion==1 then
    estimate=state.estimatedRC
    local stamp=state.imuSampleTime or state.time
    if recording and stamp~=lastTime then
      local debug=ecu.getDebugState()
      pending[#pending+1]={time=stamp,ecuTime=state.time,sensorDt=state.imuSampleDt,
        dt=lastTime and stamp-lastTime or 0,corners=state.imu,
        radius=estimate and estimate.distance,estimatedVelocity=estimate and estimate.estimatedVelocity,
        averagedGyro=estimate and estimate.averagedGyro,
        averagedAcceleration=estimate and estimate.averagedAcceleration,
        velocityAid=estimate and estimate.velocityAid,origin=plain(obj:getPosition()),
        heading=obj.getDirectionVector and plain(obj:getDirectionVector()) or nil,
        wantedRC=state.wantedRC,steering=state.steering,throttle=state.throttle,brake=state.brake,
        trc=debug.output and debug.output.trc,mitvsDelta=debug.output and debug.output.mitvsDelta}
      if #pending>120 then table.remove(pending,1) end
    end
    lastTime=stamp;return
  end
  local sampleTime=state.imuSampleTime or state.time
  if sampleTime==lastTime then return end
  local dt=lastTime and sampleTime-lastTime or 0
  lastTime=sampleTime
  local ids={}
  for key,node in pairs(v.data.nodes or {}) do
    if type(node)=='table' and node.name then ids[node.name]=node.cid or key end
  end
  local acceleration,gps,omega,position=vec3(0,0,0),vec3(0,0,0),vec3(0,0,0),vec3(0,0,0)
  local corners={}
  for _,name in ipairs({'FL','FR','RL','RR'}) do
    local sensor=state.imu and state.imu[name]
    local mount=state.geometry.mounts[name]
    if not sensor or not sensor.valid or not sensor.acceleration or not sensor.gyro or not sensor.velocity or not mount then reset();return end
    local a,b,c=ids[mount.nodes[1]],ids[mount.nodes[2]],ids[mount.nodes[3]]
    if not a or not b or not c then reset();return end
    local p=obj:getNodePosition(a)
    local edge=obj:getNodePosition(b)-p
    local normal=edge:cross(obj:getNodePosition(c)-p)
    if edge:length()<.05 or normal:length()<.01 then reset();return end
    edge:normalize();normal:normalize()
    local side=normal:cross(edge)
    local function basis(coeff) return edge*coeff[1]+normal*coeff[2]+side*coeff[3] end
    local f,l,u=basis(mount.forward),basis(mount.left),basis(mount.up)
    if sensor.frame then
      -- Transform with the frame in which the reading was sampled, not a later
      -- chassis pose from the asynchronous reporter.
      local function vector(q) return vec3(q.x,q.y,q.z) end
      f,l,u=vector(sensor.frame.forward),vector(sensor.frame.left),vector(sensor.frame.up)
      p=vector(sensor.frame.position)
    end
    local function world(reading) return f*reading.forward+l*reading.left+u*reading.up end
    if recording then corners[name]={raw=sensor,nodes=mount.nodes,position=plain(p),
      forward=plain(f),left=plain(l),up=plain(u),gyroWorld=plain(world(sensor.gyro)),
      accelerationWorld=plain(world(sensor.acceleration)),velocityWorld=plain(world(sensor.velocity))} end
    acceleration=acceleration+world(sensor.acceleration)
    gps=gps+world(sensor.velocity)
    omega=omega+world(sensor.gyro)
    position=position+p
  end
  acceleration=acceleration*.25+obj:getGravityVector()
  gps=gps*.25;omega=omega*.25;position=position*.25
  local before=velocity and plain(velocity) or nil
  if not velocity or dt<=0 or dt>.25 then velocity=gps
  else
    local predicted=velocity+acceleration*dt
    local blend=1-math.exp(-dt/.5)
    velocity=predicted+(gps-predicted)*blend
  end
  if recording then
    -- Keep every estimator sample, not only the 20 Hz rendered-marker reports.
    pending[#pending+1]={time=sampleTime,ecuTime=state.time,dt=dt,sensorDt=state.imuSampleDt or state.dt,corners=corners,
      averagedGyro=plain(omega),averagedAcceleration=plain(acceleration),
      velocityBefore=before,estimatedVelocity=plain(velocity),velocityAid=plain(gps),
      mountCenter=plain(position),origin=plain(obj:getPosition()),
      heading=obj.getDirectionVector and plain(obj:getDirectionVector()) or nil,
      steering=state.steering,throttle=state.throttle,brake=state.brake,
      radius=math.abs(omega.z)>=math.rad(.5) and math.sqrt(velocity.x*velocity.x+velocity.y*velocity.y)/math.abs(omega.z) or nil}
    if #pending>120 then table.remove(pending,1) end
  end
  if math.abs(omega.z)<math.rad(.5) or velocity:length()>200 then estimate=nil;return end
  -- For horizontal yaw: v = omega cross (position - center).
  local x,y=-velocity.y/omega.z,velocity.x/omega.z
  local distance=math.sqrt(x*x+y*y)
  if distance>200 then estimate=nil;return end
  local origin=obj:getPosition()
  estimate={x=origin.x+position.x+x,y=origin.y+position.y+y,z=origin.z+position.z,
    distance=distance,yawRate=math.deg(omega.z),rotationSpeed=math.abs(omega.z)*distance*3.6}
end
function M.report(record)
  recording=record==true
  sample()
  local ecu=controller.getController('companion_custom_ecu')
  local state=ecu and ecu.getDebugState and ecu.getDebugState().input
  local wanted=state and state.wantedRC
  obj:queueGameEngineLua(string.format('if extensions.mininiRotationCenter then extensions.mininiRotationCenter.ingestWanted(%d,%s) end',obj:getID(),serialize(wanted)))
  obj:queueGameEngineLua(string.format('if extensions.mininiRotationCenter then extensions.mininiRotationCenter.ingestEstimated(%d,%s) end',obj:getID(),serialize(estimate)))
  if recording and #pending>0 then
    obj:queueGameEngineLua(string.format('if extensions.mininiRotationCenter then extensions.mininiRotationCenter.ingestTrace(%d,%s) end',obj:getID(),serialize(pending)))
    pending={}
  end
end
M.onReset=reset
M.onExtensionUnloaded=reset
M.updateGFX=sample
M.getState=function() return estimate end
return M
