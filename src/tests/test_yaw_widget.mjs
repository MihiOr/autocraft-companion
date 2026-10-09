import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const folder = new URL('../yaw_widget_mod/ui/modules/apps/MininiYawControl/', import.meta.url)
const source = readFileSync(new URL('readings.js', folder), 'utf8')
const { yawReadings, rcReadings, wheelReadings, pedalReadings, signed } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
assert.equal(yawReadings({}).available, false)
const e = { companionTargetYawRate: 1, companionYawRate: 0.5, companionYawRateError: 0.5, companionYawCorrection: 6, companionYawTelemetryValid: 1 }
const state = yawReadings({ electrics: e })
assert.equal(state.available, true)
assert.equal(state.target, 180 / Math.PI)
assert.equal(state.error, 90 / Math.PI)
assert.equal(state.correction, 1080 / Math.PI)
assert.equal(yawReadings({ electrics: { ...e, companionYawTelemetryValid: 0 } }).available, false)
assert.equal(yawReadings({ electrics: { ...e, companionYawRate: NaN } }).available, false)
const legacy = yawReadings({ electrics: { companionTargetYawRate: 1, companionYawRate: 0.5 } })
assert.equal(legacy.error, 90 / Math.PI)
assert.equal(legacy.correction, null)
assert.equal(signed(null), '--')
assert.equal(signed(0), '0.00')
assert.equal(signed(-0.001), '0.00')
assert.equal(signed(1.234), '+1.23')
assert.equal(signed(-1.234), '-1.23')
const manifest = JSON.parse(readFileSync(new URL('app.json', folder), 'utf8'))
assert.equal(manifest.directive, 'mininiYawControl')
assert.equal(manifest.name, 'MiTVS Debug')
const channels = {...e, companionWheelCorrectionValid:1}
for (const [i,n] of ['FL','FR','RL','RR'].entries()) {
  for (const [k,v] of Object.entries({Share:i===3?0:1/3,MotorUse:i===0?-.8:.4,GripUse:.9,TorqueNm:100,DeltaNm:20,YawMomentNm:50,MotorLimitNm:250,GripLimitNm:300})) channels[`companionTV${n}${k}`]=v
}
let wheels=wheelReadings({electrics:channels})
assert.equal(wheels.available,true)
assert.equal(Object.values(wheels.wheels).reduce((s,r)=>s+Math.round(r.share*10),0),1000)
assert.equal(wheels.wheels.FL.motorUse,-80)
assert.equal(wheels.wheels.FL.gripUse,90)
assert.equal(wheels.wheels.FL.slipping,false)
channels.companionTVFLSlipping=1
channels.companionTVFLGripUse=1
assert.equal(wheelReadings({electrics:channels}).wheels.FL.slipping,true)
assert.equal(wheelReadings({electrics:channels}).wheels.FL.gripUse,100)
for(const n of ['FL','FR','RL','RR']) channels[`companionTV${n}Share`]=0
wheels=wheelReadings({electrics:channels})
assert.equal(Object.values(wheels.wheels).reduce((s,r)=>s+r.share,0),0)
assert.equal(wheelReadings({electrics:e}).available,false)
assert.deepEqual(pedalReadings({electrics:{...e,companionBrakePedal:.6,companionAcceleratorPedal:.8,companionPedalRequest:-.6}}),{brake:60,accelerator:80,request:-60})
assert.deepEqual(pedalReadings({}),{brake:null,accelerator:null,request:null})
assert.equal(pedalReadings({electrics:{...e,companionPedalRequest:2}}).request,100)
const vue = readFileSync(new URL('app.vue', folder), 'utf8')
for (const name of ['wantedRC', 'estimatedRC', 'rcError', 'wantedRS', 'estimatedRS', 'rsError']) assert.ok(vue.includes(name))
const rcChannels={...channels,companionRCControlValid:1,companionVectoringState:3,companionWantedRC:10,companionEstimatedRC:8,companionRCError:2,companionWantedRS:30,companionEstimatedRS:25,companionRSError:5,companionYawTelemetryValid:0}
assert.equal(rcReadings({electrics:rcChannels}).estimatedRS,25)
assert.equal(rcReadings({electrics:rcChannels}).active,true)
rcChannels.companionTVFLGripUse=1.4
assert.equal(wheelReadings({electrics:rcChannels}).wheels.FL.gripUse,140)
assert.equal(wheelReadings({electrics:rcChannels}).wheels.FL.torque,100)
assert.ok(vue.includes('MiTVS added torque'))
console.log('Yaw widget: conversion, invalid/legacy telemetry, formatting and app manifest passed.')

channels.companionTVFLLongitudinalSlip=.123
channels.companionTVFLLateralSlipDegrees=9.4
assert.equal(wheelReadings({electrics:channels}).wheels.FL.longitudinalSlip,12.3)
assert.equal(wheelReadings({electrics:channels}).wheels.FL.lateralSlip,9.4)
assert.ok(vue.includes(".FL .side-slip,.RL .side-slip,.FR .motor,.RR .motor {grid-column:2;}"))
