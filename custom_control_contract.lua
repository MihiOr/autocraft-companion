-- Shared by the in-game adapter and Companion's offline checker (Lua 5.1).
local function boundedCall(fn, ...)
  local previous, mask, count = debug.gethook()
  debug.sethook(function() error('Custom controller instruction limit exceeded') end, '', 50000)
  local ok, result = pcall(fn, ...)
  debug.sethook(previous, mask, count)
  if not ok then error(result) end
  return result
end
local function loadUser(source)
  local fn, err = loadstring(source, '@custom_motor_control.lua')
  if not fn then error(err) end
  local safeMath = {}
  for k,v in pairs(math) do safeMath[k]=v end
  setfenv(fn, {math=safeMath, pairs=pairs, ipairs=ipairs, next=next,
    tonumber=tonumber, tostring=tostring, type=type, assert=assert, error=error,
    select=select, unpack=unpack})
  if jit then jit.off(fn, true) end
  local user = boundedCall(fn)
  assert(type(user)=='function', 'File must return function(s, memory)')
  if jit then jit.off(user, true) end
  return user
end
local function evaluateUser(fn, state, memory)
  local output = boundedCall(fn, state, memory)
  assert(type(output)=='table', 'Return a table with FL, FR, RL, RR')
  for _, wheel in ipairs({'FL','FR','RL','RR'}) do
    local value = output[wheel]
    assert(type(value)=='number' and value==value and value>=-1 and value<=1,
      wheel..' torque must be a finite number between -1 and 1')
  end
  for _, key in ipairs({'launchActive','launchArmed'}) do
    assert(output[key]==nil or type(output[key])=='boolean', key..' must be boolean')
  end
  return output
end
