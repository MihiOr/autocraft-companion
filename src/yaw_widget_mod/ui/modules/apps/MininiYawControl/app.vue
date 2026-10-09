<template>
  <div class="debug">
    <header>MiTVS DEBUG <span>SOFTWARE COMMANDS</span></header>
    <div class="panels">
      <div class="yaw-panel"><div class="panel-title">RC / RS CONTROL</div>
        <div class="readings">
          <section v-for="row in rcRows" :key="row.key" :class="row.key"><label>{{ row.label }}</label><b>{{ signed(state[row.key]) }}</b><small>{{ row.unit }}</small></section>
        </div>
        <div class="note">{{ state.active ? 'MiTVS active: ERC below 15 m' : 'MiTVS inactive' }} | RC error: wanted - estimated, left positive</div>
      </div>
      <div class="wheel-panel"><div class="panel-title">WHEEL ALLOCATION  FRONT </div>
        <div class="wheel-zone"><div class="wheel-grid">
          <article v-for="name in wheelNames" :key="name" :class="['wheel',name]" :title="wheelTitle(name)">
            <strong class="wheel-name">{{ name }}</strong>
            <div class="share"><small>Correction</small><b>{{ percent(wheels.wheels[name].share) }}</b></div>
            <div class="command"><div class="zero"></div>
              <div v-if="wheels.wheels[name].motorUse !== null" :class="['bar', wheels.wheels[name].motorUse >= 0 ? 'forward' : 'reverse']" :style="{height: Math.min(100,Math.abs(wheels.wheels[name].motorUse))/2 + '%'}"></div>
              <b>{{ signedPercent(wheels.wheels[name].motorUse) }}</b>
            </div>
            <div class="limits"><span class="motor">M {{ percentAbs(wheels.wheels[name].motorUse) }}</span><span class="side-slip" :class="{saturated: (wheels.wheels[name].gripUse || 0) > 100}">TRC {{ percent(wheels.wheels[name].gripUse) }}</span></div>
          </article>
        </div><div class="pedals">
          <div v-for="pedal in pedalRows" :key="pedal.key" class="pedal" :title="pedal.title">
            <small>{{ pedal.label }}</small>
            <div class="pedal-track">
              <div v-if="pedal.key === 'request'" class="zero"></div>
              <div v-if="pedals[pedal.key] !== null" :class="['pedal-fill', pedal.key === 'request' ? (pedals.request >= 0 ? 'forward' : 'reverse') : pedal.key]" :style="{height: Math.abs(pedals[pedal.key]) / (pedal.key === 'request' ? 2 : 1) + '%'}"></div>
            </div>
            <span>{{ pedals[pedal.key] === null ? '--' : Math.round(pedals[pedal.key]) + '%' }}</span>
          </div>
        </div></div>
        <div class="note">Correction moment request {{ signed(wheels.requested) }} / allocated {{ signed(wheels.allocated) }} Nm</div>
      </div>
    </div>
    <footer>{{ !state.available ? 'Waiting for Minini ECU telemetry' : 'Bars = MiTVS added torque only; M = motor capacity used by that correction' }}</footer>
    <div class="note">Shares = absolute added Nm. TRC: 100% = estimated peak slip; above 100% = overshoot.</div>
  </div>
</template>
<script setup>
import { shallowRef } from 'vue'
import { useStreams } from '@/services/events'
import { rcReadings, wheelReadings, pedalReadings, wheelNames, signed } from './readings.js'
const rcRows = [
  {key:'wantedRC',label:'WRC',unit:'m'},
  {key:'estimatedRC',label:'ERC',unit:'m'},
  {key:'rcError',label:'RC side error',unit:'m'},
  {key:'wantedRS',label:'WRS',unit:'km/h'},
  {key:'estimatedRS',label:'ERS',unit:'km/h'},
  {key:'rsError',label:'RS error',unit:'km/h'},
]
const state = shallowRef(rcReadings({}))
const wheels = shallowRef(wheelReadings({}))
const pedals = shallowRef(pedalReadings({}))
const pedalRows = [
  {key:'brake',label:'BRK',title:'Brake pedal input'},
  {key:'accelerator',label:'ACC',title:'Accelerator pedal input'},
  {key:'request',label:'REQ',title:'Interpreter acceleration request: brake overrides accelerator and is negative.'},
]
useStreams(['electrics'], streams => { state.value = rcReadings(streams); wheels.value = wheelReadings(streams); pedals.value = pedalReadings(streams) })
const percent = value => value === null ? '--' : value.toFixed(1) + '%'
const percentAbs = value => value === null ? '--' : Math.abs(value).toFixed(1) + '%'
const signedPercent = value => value === null ? '--' : (value > 0 ? '+' : '') + value.toFixed(1) + '%'
const wheelTitle = name => {
  const w = wheels.value.wheels[name]
  return `${name}: MiTVS added torque ${signed(w.delta)} Nm; correction moment ${signed(w.yawMoment)} Nm; motor capacity ${signed(w.motorLimit)} Nm; TRC estimated peak-slip usage ${percent(w.gripUse)}`
}
</script>
<style scoped>
.debug {box-sizing:border-box;width:100%;height:100%;display:flex;flex-direction:column;gap:8px;padding:12px;background:rgba(20,26,32,.88);color:#f5f7fa;border-radius:12px;font-family:Arial,sans-serif;}
header {display:flex;justify-content:space-between;font-size:14px;font-weight:bold;} header span {color:#a8d7ff;font-size:11px;letter-spacing:1px;}
.panels {display:grid;grid-template-columns:1fr 1.35fr;gap:16px;flex:1;min-height:0;}
.yaw-panel,.wheel-panel {display:flex;flex-direction:column;gap:7px;min-width:0;}.panel-title {font-size:10px;color:#bcc8d5;letter-spacing:1px;}
.readings,.wheel-grid {flex:1;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:8px;min-height:0;}
.readings section {display:grid;grid-template-columns:1fr auto;align-content:center;gap:3px;padding:8px;background:#303943;border-radius:7px;border-left:3px solid;}
.readings label {grid-column:1 / 3;font-size:11px;color:#d6dee7;} b {font:600 20px Consolas,monospace;font-variant-numeric:tabular-nums;} .readings small {font-size:11px;align-self:end;}
.target {border-color:#a8d7ff;}.measured {border-color:#5dd9fa;}.error {border-color:#ffa64d;}.correction {border-color:#c59bff;}
.wheel {position:relative;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 22px;background:#303943;border:1px solid #afbecb;border-radius:7px;overflow:hidden;padding-top:17px;}
.wheel-name {position:absolute;top:2px;left:0;right:0;text-align:center;font-size:12px;z-index:2;}
.share {display:flex;flex-direction:column;align-items:center;justify-content:center;background:#253849;grid-row:1;gap:4px;}.share small {font-size:9px;color:#bed5e5;}.share b {font-size:17px;color:#91dbff;}
.FL .share,.RL .share {grid-column:2;}.FR .share,.RR .share {grid-column:1;}
.command {position:relative;background:#1b242d;grid-row:1;min-height:40px;}.FL .command,.RL .command {grid-column:1;}.FR .command,.RR .command {grid-column:2;}
.zero {position:absolute;left:0;right:0;top:50%;height:1px;background:#ccd6df;z-index:1;}.bar {position:absolute;left:0;right:0;}.forward {bottom:50%;background:#26c75a;}.reverse {top:50%;background:#e84747;}
.command b {position:absolute;bottom:2px;left:0;right:0;text-align:center;font-size:12px;text-shadow:0 1px 3px #000;z-index:2;}
.limits {grid-column:1 / 3;grid-row:2;display:grid;grid-template-columns:1fr 1fr;align-items:center;text-align:center;font-size:8px;background:#202a34;}.limits span {grid-row:1;}.FL .motor,.RL .motor,.FR .side-slip,.RR .side-slip {grid-column:1;}.long-slip {grid-column:2;}.FL .side-slip,.RL .side-slip,.FR .motor,.RR .motor {grid-column:2;}.saturated {color:#ffa64d;font-weight:bold;}
footer,.note {text-align:center;font-size:10px;color:#c1cbd7;}.note {font-size:9px;}
.wheel-zone {display:flex;gap:8px;flex:1;min-height:0;}.wheel-grid {min-width:0;}.pedals {display:flex;gap:5px;width:91px;flex-shrink:0;}.pedal {display:flex;flex-direction:column;align-items:center;gap:4px;width:27px;min-width:0;}.pedal small {font-size:9px;color:#bcc8d5;}.pedal span {font:10px Consolas,monospace;}.pedal-track {position:relative;width:15px;flex:1;border:1px solid #758695;border-radius:3px;background:#1b242d;overflow:hidden;}.pedal-fill {position:absolute;left:0;right:0;}.pedal-fill.brake {bottom:0;background:#e84747;}.pedal-fill.accelerator {bottom:0;background:#26c75a;}
</style>
<style scoped>.readings{grid-template-rows:repeat(3,1fr)}</style>
