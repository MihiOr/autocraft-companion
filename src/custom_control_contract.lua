-- Shared by the in-game adapter and Companion's offline checker (Lua 5.1).
local function boundedCall(fn, ...)
  local previous, mask, count = debug.gethook()
  -- MiSim's bounded 81-case motor allocator executes at 100 Hz. Keep an
  -- instruction ceiling large enough for that finite solve, still trapping loops.
  debug.sethook(function() error('Custom controller instruction limit exceeded') end, '', 150000)
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
  assert(output.gear==nil or output.gear==-1 or output.gear==0 or output.gear==1,
    'gear must be -1 (R), 0 (N), or 1 (D)')
  if output.regen~=nil then
    assert(type(output.regen)=='table', 'regen must be a table with FL, FR, RL, RR')
    for _, wheel in ipairs({'FL','FR','RL','RR'}) do
      local value=output.regen[wheel]
      assert(type(value)=='number' and value==value and value>=0 and value<=1,
        wheel..' regen must be a finite number between 0 and 1')
      assert(value==0 or output[wheel]==0, wheel..' cannot request drive and regen together')
    end
  end
  return output
end
