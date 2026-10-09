-- Local diagnostic bridge. Commands are data, never arbitrary Lua.
local M = {version=2}
local udp, currentID, timer, lease = nil, nil, 0, 0
local supportedID
local function send(data)
  if udp then udp:sendto(jsonEncode(data), '127.0.0.1', 28581) end
end
local function queue(id, text)
  local vehicle=id and be:getObjectByID(id)
  if vehicle then vehicle:queueLuaCommand(text) end
end
local function release(id)
  queue(id,"if extensions.mininiDebugVehicle then extensions.mininiDebugVehicle.release() end")
end
local function ensure(id)
  queue(id,"if extensions.mininiDebugVehicle and extensions.mininiDebugVehicle.version~=7 then extensions.unload('mininiDebugVehicle') end; if not extensions.mininiDebugVehicle then extensions.load('mininiDebugVehicle') end")
end
local function onExtensionLoaded()
  local candidate=socket.udp()
  candidate:settimeout(0)
  local ok,err=candidate:setsockname('127.0.0.1',28580)
  if not ok then
    candidate:close()
    log('W','mininiDebug','Local debug port unavailable: '..tostring(err))
    return
  end
  udp=candidate
end
local function ingest(id, encoded)
  if id~=currentID or type(encoded)~='string' or #encoded>48000 then return end
  local ok,data=pcall(jsonDecode,encoded)
  if ok and type(data)=='table' then
    supportedID=data.status=='ready' and id or nil
    data.schema=1;data.vehicleID=id;data.bridgeVersion=M.version
    send(data)
  end
end
local function replace(model)
  if type(model)~='string' or #model>100 or not model:match('^[%w_]+$') then
    send({schema=1,status='error',error='Invalid model identifier.'});return
  end
  local data=jsonReadFile('/vehicles/'..model..'/engine.jbeam')
  local engine=data and data.engine
  if not engine then send({schema=1,status='error',error='Companion model not installed.'});return end
  for _,name in ipairs({'FL','FR','RL','RR'}) do
    local motor=engine['evMotor'..name]
    if not motor or motor.electricsThrottleName~='companionCustom'..name then
      send({schema=1,status='error',error='Replacement must be a Companion EV.'});return
    end
  end
  release(currentID);lease=0
  send({schema=1,status='replacing',model=model})
  core_vehicles.replaceVehicle(model,{})
end
local function onUpdate(dtReal)
  if not udp then return end
  local vehicle=getPlayerVehicle(0)
  local id=vehicle and vehicle:getID() or nil
  if id~=currentID then
    release(currentID);currentID=id;supportedID=nil;lease=0;timer=.25
  end
  timer=timer+dtReal
  if lease>0 then
    lease=lease-dtReal
    if lease<=0 then release(id) end
  end
  if timer>=.25 then
    timer=0
    if id then ensure(id) else send({schema=1,status='no_vehicle'}) end
  end
  -- Limit work per frame even if a local sender floods the socket.
  for _=1,16 do
    local raw,ip=udp:receivefrom()
    if not raw then break end
    if ip=='127.0.0.1' and #raw<=2048 then
      local ok,packet=pcall(jsonDecode,raw)
      if ok and type(packet)=='table' and packet.schema==1 and
         packet.vehicleID==id and id and
         (packet.op=='control' or packet.op=='release' or packet.op=='snapshot' or
          packet.op=='replace' or packet.op=='reload') then
        if packet.op=='replace' or packet.op=='reload' then
          if supportedID==id then
            if packet.op=='replace' then replace(packet.model) else
              release(id);lease=0
              send({schema=1,status='reloading'})
              Lua:requestReload()
            end
          else send({schema=1,status='error',error='Select a Companion EV first.'}) end
        else
          ensure(id)
          queue(id,string.format("if extensions.mininiDebugVehicle then extensions.mininiDebugVehicle.request(%q) end",jsonEncode(packet)))
          if packet.op=='control' then lease=.5 elseif packet.op=='release' then lease=0 end
        end
      end
    end
  end
end
M.onExtensionLoaded=onExtensionLoaded
M.onUpdate=onUpdate
M.ingest=ingest
M.onExtensionUnloaded=function()
  release(currentID);currentID=nil;lease=0
  if udp then udp:close();udp=nil end
end
return M
