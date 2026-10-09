<template>
  <div class="bench">
    <header>MININI TEST BENCH <span>No MiTVS / traction assistance</span></header>
    <div class="status">{{ state.phase }} | {{ Number(state.speed || 0).toFixed(1) }} km/h
      <small>RS: {{ state.rotationSpeed == null ? '--' : Number(state.rotationSpeed).toFixed(1) }} km/h | ERS: {{ state.estimatedRotationSpeed == null ? '--' : Number(state.estimatedRotationSpeed).toFixed(1) }} km/h | WRS: {{ Number(state.wantedRotationSpeed ?? 30).toFixed(1) }} km/h</small>
      <small>{{ state.reason || '' }}</small>
    </div>
    <div class="motion">Yaw rate: {{ Number(state.yawRate || 0).toFixed(2) }} d/s | RC distance: {{ state.rcDistance == null ? '--' : Number(state.rcDistance).toFixed(2) }} m</div>
    <div class="motion">AVG (20): {{ averageYaw.toFixed(2) }} d/s | {{ averageRC == null ? '--' : averageRC.toFixed(2) }} m</div>
    <fieldset>
      <label>Torque mode</label>
      <div class="mode-buttons"><button type="button" :class="{selected:form.mode==='exact'}" :aria-pressed="form.mode==='exact'" @click="form.mode='exact'">Exact torque</button><button type="button" :class="{selected:form.mode==='additional'}" :aria-pressed="form.mode==='additional'" @click="form.mode='additional'">Additional torque</button></div>
      <div class="wheels"><label v-for="n in names" :key="n">{{ n }}: {{ form[n] }} Nm | current {{ Number(state.torques?.[n] || 0).toFixed(1) }} Nm<input v-model.number="form[n]" type="range" min="-1500" max="1500" step="1"><div class="adjust"><button type="button" @click="form[n]=Math.max(-1500,form[n]-10)">-10</button><button type="button" @click="form[n]=Math.max(-1500,form[n]-1)">-1</button><button type="button" @click="form[n]=0">Zero</button><button type="button" @click="form[n]=Math.min(1500,form[n]+1)">+1</button><button type="button" @click="form[n]=Math.min(1500,form[n]+10)">+10</button></div></label></div>
      <label>Steering wheel: {{ form.steering }} d (+ right / - left)<input v-model.number="form.steering" type="range" :min="-steeringLock" :max="steeringLock" step="1"></label>
      <div class="adjust"><button type="button" @click="form.steering=Math.max(-steeringLock,form.steering-1)">-1 d</button><button type="button" @click="form.steering=0">Center</button><button type="button" @click="form.steering=Math.min(steeringLock,form.steering+1)">+1 d</button></div>
      <label class="check"><input v-model="form.runup" :disabled="running" type="checkbox">Reach initial speed first</label>
      <label v-if="form.runup">Initial speed: {{ form.speed }} km/h<input v-model.number="form.speed" :disabled="running" type="range" min="0" max="130" step="1"></label>
    </fieldset>
    <div class="buttons"><button @click="start" :disabled="running">Start</button><button class="stop" @click="stop">Stop / release controls</button></div>
    <p v-if="error" class="error">{{ error }}</p>
    <footer>Positive Nm = forward; negative Nm = reverse torque. Exact mode bypasses motor torque curves. Additional mode adds to the captured baseline. Steering is applied first, then speed is matched. Mode and torque can change live; the run-up baseline is remembered. Driving inputs are blocked during the test.</footer>
  </div>
</template>
<script setup>
import { reactive, ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useBridge } from '@/bridge'
import { useEvents } from '@/services/events'
import { configuration, normalizeForm, names } from './form.js'
const { api }=useBridge()
const events=useEvents()
const form=reactive({mode:'exact',FL:'0',FR:'0',RL:'0',RR:'0',steering:'0',runup:false,speed:'50'})
try {Object.assign(form,JSON.parse(localStorage.getItem('mininiTestBench')||'{}'))} catch {}
Object.assign(form,normalizeForm(form))
const state=ref({phase:'idle',reason:'Ready'})
const motionReadings=ref([])
const averageYaw=computed(()=>motionReadings.value.length ? motionReadings.value.reduce((sum,r)=>sum+r.yaw,0)/motionReadings.value.length : 0)
const averageRC=computed(()=>{
  if (state.value.rcDistance == null) return null
  const readings=motionReadings.value.filter(r=>r.rc != null)
  return readings.length ? readings.reduce((sum,r)=>sum+r.rc,0)/readings.length : null
})
const steeringLock=computed(()=>state.value.steeringLock || 480)
const error=ref('')
const running=computed(()=>['steering','runup','running','starting'].includes(state.value.phase))
function start(){
  try {
    const data=configuration(form,state.value.steeringLock || 480)
    localStorage.setItem('mininiTestBench',JSON.stringify(form))
    error.value='';state.value={...state.value,phase:'starting',reason:'Waiting for vehicle'}
    api.engineLua(`extensions.mininiTestBench.start(${JSON.stringify(JSON.stringify(data))})`)
  } catch(e){error.value=e.message}
}
function stop(){api.engineLua('if extensions.mininiTestBench then extensions.mininiTestBench.stop() end');state.value={...state.value,phase:'idle',reason:'Stopped'}}
let updateTimer=null
watch(()=>JSON.stringify([form.mode,form.FL,form.FR,form.RL,form.RR,form.steering]),()=>{
  if (!running.value) return
  clearTimeout(updateTimer)
  updateTimer=setTimeout(()=>{
    if (!running.value) return
    try {
      const data=configuration(form,steeringLock.value)
      localStorage.setItem('mininiTestBench',JSON.stringify(form))
      error.value=''
      api.engineLua(`extensions.mininiTestBench.update(${JSON.stringify(JSON.stringify(data))})`)
    } catch(e){error.value=e.message}
  },60)
})
function receive(data){
  if (data.reason==='Vehicle reset') motionReadings.value=[]
  motionReadings.value.push({yaw:Number(data.yawRate || 0),rc:data.rcDistance == null ? null : Number(data.rcDistance)})
  if (motionReadings.value.length>20) motionReadings.value.shift()
  state.value=data;Object.assign(form,normalizeForm(form,data.steeringLock || 480))
}
onMounted(()=>{api.engineLua("if not extensions.mininiTestBench then extensions.load('mininiTestBench') end");events.on('MininiTestBenchState',receive)})
onUnmounted(()=>{clearTimeout(updateTimer);stop();events.off('MininiTestBenchState',receive)})
</script>
<style scoped>
.bench{height:100%;box-sizing:border-box;overflow:auto;background:#18232eed;color:#eef4fa;padding:12px;border-radius:10px;font:13px Arial;display:flex;flex-direction:column;gap:8px}header{font-weight:bold}header span{display:block;color:#89d5ff;font-size:11px;margin-top:4px}.status{padding:7px;background:#2e4050;border-radius:5px}.status small{display:block}fieldset{border:0;padding:0;display:flex;flex-direction:column;gap:8px}label{display:flex;flex-direction:column;gap:3px}input{width:100%;box-sizing:border-box;background:#344454;color:white;border:1px solid #758da0;border-radius:4px;padding:5px}.wheels{display:grid;grid-template-columns:1fr 1fr;gap:8px}.wheels small{color:#a8c5db}.check{flex-direction:row;align-items:center}.check input{width:auto}.buttons{display:flex;gap:8px}button{flex:1;background:#227744;color:white;border:0;border-radius:5px;padding:9px;cursor:pointer}.stop{background:#a93737}button:disabled{opacity:.4}footer{font-size:11px;line-height:1.4;color:#aec4d6}.error{color:#ff9a9a;margin:0}
</style>

<style scoped>
input[type=range]{padding:0;accent-color:#62c5ff;height:22px;cursor:pointer;touch-action:none}.mode-buttons,.adjust{display:flex;gap:5px}.mode-buttons button{background:#344454;border:1px solid #758da0}.mode-buttons .selected{background:#256d9c;border-color:#9bdcff}.adjust button{padding:3px 5px;background:#344454;font-size:11px}.wheels label{min-width:0}
</style>
