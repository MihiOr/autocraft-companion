<template>
  <div class="companion-balance">
    <header>WEIGHT BALANCE <span>FRONT &#9650;</span></header>
    <div class="balance-grid">
      <section v-for="name in names" :key="name" :class="['wheel', name]">
        <div class="fill" :style="{height: Math.min(100, (state.shares[name] || 0) * 2) + '%'}"></div>
        <div class="readings">
          <strong>{{ name }}</strong>
          <b>{{ kg(state.wheels[name]) }}</b>
          <small>{{ state.wheels[name] === null ? '--' : Math.round(state.wheels[name]) }} N</small>
          <em>{{ percent(state.shares[name]) }}</em>
        </div>
      </section>
      <section class="middle">
        <svg class="balance-dial" viewBox="0 0 280 180" role="img" aria-label="Wheel load balance: front top, rear bottom, left and right sides">
          <title>Center means 50/50 on both axes. The dot moves toward the more heavily loaded side and axle; this is not a G-meter.</title>
          <circle cx="140" cy="90" r="56" fill="#303943" stroke="#8091a3" />
          <circle cx="140" cy="90" r="28" fill="none" stroke="#5a6876" />
          <path d="M84 90H196 M140 34V146" stroke="#8091a3" stroke-width="1" />
          <circle cx="140" cy="90" r="2" fill="#cad4de" />
          <text x="140" y="12" class="dial-label">FRONT</text>
          <text x="140" y="29" class="dial-value">{{ percent(state.front) }}</text>
          <text x="140" y="162" class="dial-value">{{ percent(state.rear) }}</text>
          <text x="140" y="178" class="dial-label">REAR</text>
          <text x="40" y="83" class="dial-label">LEFT</text>
          <text x="40" y="104" class="dial-value">{{ percent(state.left) }}</text>
          <text x="240" y="83" class="dial-label">RIGHT</text>
          <text x="240" y="104" class="dial-value">{{ percent(state.right) }}</text>
          <circle v-if="state.dot" :cx="140 + state.dot.x * 51" :cy="90 + state.dot.y * 51" r="5" fill="#ff901f" stroke="#101820" stroke-width="2" />
          <text v-else x="140" y="95" class="dial-label">NO LOAD</text>
        </svg>
        <small>TOTAL WHEEL LOAD</small>
        <strong>{{ state.complete ? kg(state.total) : '--' }}</strong>
      </section>
    </div>
    <footer>{{ state.complete ? 'REAR | Live wheel loads, including weight transfer' : 'Waiting for FL / FR / RL / RR wheel telemetry' }}</footer>
  </div>
</template>

<script setup>
import { shallowRef } from 'vue'
import { useStreams } from '@/services/events'
import { calculateBalance } from './balance.js'

const names = ['FL', 'FR', 'RL', 'RR']
const state = shallowRef(calculateBalance({}))
useStreams(['wheelInfo', 'sensors'], streams => { state.value = calculateBalance(streams) })
const percent = value => value === null ? '--' : value.toFixed(1) + '%'
const kg = force => force === null || !state.value.gravity ? '-- kg' : Math.round(force / state.value.gravity) + ' kg'
</script>

<style scoped>
.companion-balance {height:100%;width:100%;box-sizing:border-box;display:flex;flex-direction:column;padding:10px;color:#f5f7fa;background:rgba(20,26,32,.85);border-radius:12px;font-family:Arial,sans-serif;}
header {font-size:12px;font-weight:bold;display:flex;justify-content:space-between;gap:6px;margin-bottom:8px;}
header span {color:#a8d7ff;}
.balance-grid {flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:minmax(85px,1fr) 200px minmax(85px,1fr);gap:8px 24px;}
.FL {grid-area:1/1;}.FR {grid-area:1/2;}.RL {grid-area:3/1;}.RR {grid-area:3/2;}
.wheel {position:relative;overflow:hidden;border:2px solid #d6dee7;border-radius:9px;background:#303943;}
.fill {position:absolute;bottom:0;width:100%;background:#db7215;opacity:.85;}
.readings {position:relative;display:flex;height:100%;flex-direction:column;align-items:center;justify-content:space-evenly;text-shadow:0 1px 3px #111;}
.readings strong {font-size:16px;}.readings b {font-size:16px;}.readings small {font-size:11px;}.readings em {font-style:normal;font-size:21px;font-weight:bold;}
.middle {grid-area:2/1/3/3;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;}
.middle small {font-size:10px;color:#bcc8d5;letter-spacing:1px;}.middle strong {font-size:14px;}
.balance-dial {width:100%;height:166px;flex-shrink:0;}
.balance-dial text {text-anchor:middle;fill:#f5f7fa;font-family:Arial,sans-serif;}
.balance-dial .dial-label {font-size:10px;fill:#bcc8d5;letter-spacing:1px;}
.balance-dial .dial-value {font-size:17px;font-weight:bold;}
footer {font-size:9px;text-align:center;color:#bcc8d5;margin-top:7px;}
</style>
