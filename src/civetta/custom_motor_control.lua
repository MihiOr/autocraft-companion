-- Direct pedal control. No MiTVS, traction, launch or stability assistance.
-- Reverse swaps accelerator/brake roles to retain Minini's existing convention.
return function(s,m)
  local gear=(s.gear or 1)<0 and -1 or 1
  local gas=math.max(0,math.min(1,s.throttle or 0))
  local brake=math.max(0,math.min(1,s.brake or 0))
  if gear<0 then gas,brake=brake,gas end
  local out={FL=0,FR=0,RL=0,RR=0,regen={FL=0,FR=0,RL=0,RR=0},gear=gear}
  for _,n in ipairs({'FL','FR','RL','RR'}) do
    if brake>0 then out.regen[n]=brake else out[n]=gear*gas end
  end
  return out
end
