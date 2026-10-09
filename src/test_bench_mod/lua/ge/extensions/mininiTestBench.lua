local M={}
local currentID,activeID,timer=nil,nil,0
local session=0
local function send(id,data)
  local car=id and getObjectByID(id)
  if car then car:queueLuaCommand(string.format("if not extensions.mininiTestBenchVehicle then extensions.load('mininiTestBenchVehicle') end; extensions.mininiTestBenchVehicle.request(%q)",jsonEncode(data))) end
end
local function stop()
  send(activeID,{op='stop'});activeID=nil
end
M.stop=stop
M.start=function(encoded)
  local ok,data=pcall(jsonDecode,encoded)
  if not ok or type(data)~='table' then return end
  stop()
  local car=getPlayerVehicle(0)
  if not car then guihooks.trigger('MininiTestBenchState',{phase='unsupported',reason='No active vehicle'});return end
  session=session+1;data.session=session
  currentID=car:getID();activeID=currentID;data.op='start';send(activeID,data)
end
M.update=function(encoded)
  if not activeID then return end
  local ok,data=pcall(jsonDecode,encoded)
  if not ok or type(data)~='table' then return end
  data.op='update';data.session=session;send(activeID,data)
end
M.ingest=function(id,encoded)
  if id~=currentID then return end
  local ok,data=pcall(jsonDecode,encoded)
  if ok and type(data)=='table' and (data.session==session or not activeID) then
    if data.phase=='idle' or data.phase=='unsupported' then activeID=nil end
    guihooks.trigger('MininiTestBenchState',data)
  end
end
M.onUpdate=function(dtReal)
  local car=getPlayerVehicle(0)
  local id=car and car:getID()
  if id~=currentID then stop();currentID=id;guihooks.trigger('MininiTestBenchState',{phase='idle',reason='Vehicle changed'}) end
  timer=timer+(dtReal or 0)
  if activeID and timer>=.1 then timer=0;send(activeID,{op='heartbeat'})
  elseif not activeID and id and timer>=.25 then timer=0;send(id,{op='snapshot'}) end
end
M.onClientPreStartMission=stop
M.onClientEndMission=stop
M.onExtensionUnloaded=stop
return M
