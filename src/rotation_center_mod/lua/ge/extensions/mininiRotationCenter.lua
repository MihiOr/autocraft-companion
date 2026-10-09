-- Horizontal instantaneous rotation center from actual vehicle motion.
-- Uses consecutive rigid-body poses, not steering input or MiTVS estimates.
local M={}
local enabled=true
local previous,marker
local estimated,requestElapsed=nil,0
local wanted
local traceSocket
local function center(px,py,x,y,angle,dt)
  if dt<=0 or dt>.25 or math.abs(angle)/dt<math.rad(.5) then return nil end
  local dx,dy=x-px,y-py
  if (dx*dx+dy*dy)/(dt*dt)>200*200 then return nil end -- teleport/reset
  local factor=1/(2*math.tan(angle/2))
  local cx,cy=(px+x)/2-dy*factor,(py+y)/2+dx*factor
  local distance=math.sqrt((cx-x)^2+(cy-y)^2)
  if distance>200 then return nil end -- straight travel has no nearby center
  return cx,cy,distance
end
local function reset() previous=nil;marker=nil;estimated=nil;wanted=nil;requestElapsed=0 end
local function draw()
  if marker then
    local pos=vec3(marker.x,marker.y,marker.z)
    debugDrawer:drawSphere(pos,.25,ColorF(.1,1,.15,.9))
    debugDrawer:drawTextAdvanced(pos+vec3(0,0,.4),'RC',ColorF(.1,1,.15,1),true,false,ColorI(0,0,0,180),false,true)
  end
  if estimated then
    local pos=vec3(estimated.x,estimated.y,estimated.z)
    debugDrawer:drawSphere(pos,.275,ColorF(1,1,.1,.65))
    debugDrawer:drawTextAdvanced(pos+vec3(0,0,.65),'ERC',ColorF(1,1,.1,1),true,false,ColorI(0,0,0,180),false,true)
  end
  if wanted then
    local pos=vec3(wanted.x,wanted.y,wanted.z)
    debugDrawer:drawSphere(pos,.25,ColorF(.1,.4,1,.9))
    debugDrawer:drawTextAdvanced(pos+vec3(0,0,.4),'WRC',ColorF(.1,.4,1,1),true,false,ColorI(0,0,0,180),false,true)
  end
end
local function onUpdate(dtReal,dtSim)
  if not enabled then reset();return end
  local vehicle=getPlayerVehicle(0)
  if not vehicle then reset();return end
  local id=vehicle:getID()
  local pos,dir=vehicle:getPosition(),vehicle:getDirectionVector()
  local length=math.sqrt(dir.x*dir.x+dir.y*dir.y)
  if length<.1 then reset();return end
  local current={id=id,x=pos.x,y=pos.y,z=pos.z,fx=dir.x/length,fy=dir.y/length}
  local dt=dtSim or dtReal or 0
  requestElapsed=requestElapsed+dt
  if requestElapsed>=.05 and vehicle.queueLuaCommand then
    requestElapsed=0
    vehicle:queueLuaCommand("if not extensions.mininiEstimatedRC then extensions.load('mininiEstimatedRC') end; if extensions.mininiEstimatedRC then extensions.mininiEstimatedRC.report(true) end")
  end
  if not previous or previous.id~=id then previous=current;marker=nil;estimated=nil;wanted=nil;return end
  if dt<=0 then draw();return end
  local angle=math.atan2(previous.fx*current.fy-previous.fy*current.fx,
    previous.fx*current.fx+previous.fy*current.fy)
  local x,y=center(previous.x,previous.y,current.x,current.y,angle,dt)
  previous=current
  marker=x and {x=x,y=y,z=current.z} or nil
  draw()
end
M.onUpdate=onUpdate
M.ingestWanted=function(id,data)
  local vehicle=getPlayerVehicle(0)
  if not enabled or not previous or not vehicle or vehicle:getID()~=id or previous.id~=id then return end
  wanted=type(data)=='table' and data or nil
end
M.ingestEstimated=function(id,data)
  local vehicle=getPlayerVehicle(0)
  if not enabled or not previous or not vehicle or vehicle:getID()~=id or previous.id~=id then return end
  estimated=type(data)=='table' and data or nil
end
M.ingestTrace=function(id,rows)
  local vehicle=getPlayerVehicle(0)
  if not vehicle or vehicle:getID()~=id or type(rows)~='table' then return end
  if not traceSocket then
    local ok,library=true,socket
    if not library then ok,library=pcall(require,'socket') end
    if not ok then return end
    traceSocket=library.udp();if not traceSocket then return end
    traceSocket:settimeout(0)
  end
  for _,row in ipairs(rows) do
    row.schema=1;row.vehicleID=id;row.actualRC=marker;row.displayedERC=estimated;row.wantedRC=wanted
    traceSocket:sendto(jsonEncode(row),'127.0.0.1',28610)
  end
end
M.onClientPreStartMission=reset
M.onClientEndMission=reset
M.onVehicleSpawned=reset
M.onVehicleReset=reset
M.onVehicleSwitched=reset
M.onExtensionUnloaded=function() reset();if traceSocket then traceSocket:close();traceSocket=nil end end
M.setEnabled=function(value) enabled=value==true;reset() end
M.toggle=function() enabled=not enabled;reset() end
return M
