-- ECU-owned four-IMU velocity/gyro fusion. Display extensions consume this result.
local function createRCEstimator()
  local velocity
  local function reset() velocity=nil end
  local function sample(readings,dt)
    local a,g,w,p,f,l=vec3(0,0,0),vec3(0,0,0),vec3(0,0,0),vec3(0,0,0),vec3(0,0,0),vec3(0,0,0)
    local function vector(q) return vec3(q.x,q.y,q.z) end
    for _,name in ipairs({'FL','FR','RL','RR'}) do
      local s=readings[name]
      if not s or not s.valid or not s.frame then reset();return nil end
      local frame=s.frame
      local forward,left,up=vector(frame.forward),vector(frame.left),vector(frame.up)
      local function world(v) return forward*v.forward+left*v.left+up*v.up end
      a=a+world(s.acceleration);g=g+world(s.velocity);w=w+world(s.gyro)
      p=p+vector(frame.position);f=f+forward;l=l+left
    end
    a=a*.25+obj:getGravityVector();g=g*.25;w=w*.25;p=p*.25
    if not velocity or dt<=0 or dt>.25 then velocity=g
    else local predicted=velocity+a*dt;velocity=predicted+(g-predicted)*(1-math.exp(-dt/.5)) end
    f.z=0;l.z=0
    if f:length()<.1 or l:length()<.1 then return nil end
    f:normalize();l:normalize()
    if math.abs(w.z)<math.rad(.5) or velocity:length()>200 then return nil end
    local dx,dy=-velocity.y/w.z,velocity.x/w.z
    local distance=math.sqrt(dx*dx+dy*dy)
    if distance>200 then return nil end
    local origin=obj:getPosition()
    local cx,cy,cz=origin.x+p.x,origin.y+p.y,origin.z+p.z
    return {x=cx+dx,y=cy+dy,z=cz,distance=distance,yawRate=math.deg(w.z),yawRad=w.z,
      rotationSpeed=math.abs(w.z)*distance*3.6,center={x=cx,y=cy,z=cz},
      estimatedVelocity={x=velocity.x,y=velocity.y,z=velocity.z},
      averagedGyro={x=w.x,y=w.y,z=w.z},averagedAcceleration={x=a.x,y=a.y,z=a.z},
      velocityAid={x=g.x,y=g.y,z=g.z},
      forward={x=f.x,y=f.y,z=0},left={x=l.x,y=l.y,z=0},
      forwardSpeed=velocity:dot(f),lateralSpeed=velocity:dot(l),
      lateral=dx*l.x+dy*l.y,longitudinal=dx*f.x+dy*f.y}
  end
  return {reset=reset,sample=sample}
end
