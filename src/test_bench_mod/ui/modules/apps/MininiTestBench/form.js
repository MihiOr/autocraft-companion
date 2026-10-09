export const names=['FL','FR','RL','RR']
export function configuration(form,lock=480) {
  const number=(value,label,max) => {
    const text=String(value).trim().replace(',', '.')
    const n=text===''?NaN:Number(text)
    if (!Number.isFinite(n)||Math.abs(n)>max) throw new Error(`${label}: enter a number from ${-max} to ${max}`)
    return n
  }
  if (!['exact','additional'].includes(form.mode)) throw new Error('Choose a torque mode')
  const torque=Object.fromEntries(names.map(n=>[n,number(form[n],n+' torque',1500)]))
  const steering=number(form.steering,'Steering',lock)
  const speed=form.runup?number(form.speed,'Initial speed',130):0
  if(speed<0)throw new Error('Initial speed must be positive')
  return {mode:form.mode,torque,steering,speed}
}

export function normalizeForm(form,lock=480) {
  const clamp=(value,min,max,fallback=0)=>{
    const n=Number(String(value).replace(',', '.'))
    return Math.round(Math.max(min,Math.min(max,Number.isFinite(n)?n:fallback)))
  }
  return {mode:form.mode==='additional'?'additional':'exact',...Object.fromEntries(names.map(n=>[n,clamp(form[n],-1500,1500)])),steering:clamp(form.steering,-lock,lock),runup:!!form.runup,speed:clamp(form.speed,0,130,50)}
}
