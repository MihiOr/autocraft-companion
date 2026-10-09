-- Virtual IMU hardware model. Geometry is internal to the sensor only.
-- The user's ECU receives specific force and angular rate, never pose/slip angles.
local function createIMUSampler(config)
  if not config or not config.mounts or not v or not v.data then return nil end
  local ids={}
  -- BeamNG adds section metadata and anonymous generated nodes to this table.
  for key,node in pairs(v.data.nodes or {}) do
    if type(node)=='table' and type(node.name)=='string' then
      ids[node.name]=node.cid or key
    end
  end
  local state={}
  for name,mount in pairs(config.mounts) do
    local nodes={}
    for i,node in ipairs(mount.nodes) do nodes[i]=ids[node] end
    if nodes[1]==nil or nodes[2]==nil or nodes[3]==nil then return nil end
    state[name]={nodes=nodes,mount=mount}
  end
  local function reset()
    for _,sensor in pairs(state) do sensor.previous=nil;sensor.history={} end
  end
  local function sample(dt)
    local out={}
    local function plain(p) return {x=p.x,y=p.y,z=p.z} end
    for name,sensor in pairs(state) do
      local mount=sensor.mount
      local p=obj:getNodePosition(sensor.nodes[1])
      local edge=obj:getNodePosition(sensor.nodes[2])-p
      local other=obj:getNodePosition(sensor.nodes[3])-p
      local normal=edge:cross(other)
      if edge:length()<.05 or normal:length()<.01 or dt<=0 or dt>.1 then
        out[name]={valid=false};sensor.previous=nil;sensor.history={}
      else
        edge:normalize();normal:normalize()
        local side=normal:cross(edge)
        local function basis(c) return edge*c[1]+normal*c[2]+side*c[3] end
        local f,l,u=basis(mount.forward),basis(mount.left),basis(mount.up)
        local velocity=obj:getNodeVelocityVector(sensor.nodes[1])
        local previous=sensor.previous
        if previous then
          -- Frame increments simulate a rate gyro, not a heading-angle input.
          local omega=(previous.f:cross(f)+previous.l:cross(l)+previous.u:cross(u))*(.5/dt)
          local gravity=obj:getGravityVector()
          local force=(velocity-previous.velocity)*(1/dt)-gravity
          local rawAcceleration={forward=force:dot(f),left=force:dot(l),up=force:dot(u)}
          local rawGyro={forward=omega:dot(f),left=omega:dot(l),up=omega:dot(u)}
          local history=sensor.history or {};sensor.history=history
          history[#history+1]={acceleration=rawAcceleration,gyro=rawGyro}
          if #history>3 then table.remove(history,1) end
          local function average(field)
            local value={forward=0,left=0,up=0}
            for _,reading in ipairs(history) do
              for axis in pairs(value) do value[axis]=value[axis]+reading[field][axis]/#history end
            end
            return value
          end
          out[name]={valid=true,acceleration=average('acceleration'),gyro=average('gyro'),
            rawAcceleration=rawAcceleration,rawGyro=rawGyro,smoothingSamples=#history,
            velocity={forward=velocity:dot(f),left=velocity:dot(l),up=velocity:dot(u)},offset=mount.offset,
            frame={forward=plain(f),left=plain(l),up=plain(u),position=plain(p)}}
        else out[name]={valid=false} end
        sensor.previous={f=f,l=l,u=u,velocity=velocity}
      end
    end
    return out
  end
  return {sample=sample,reset=reset}
end
