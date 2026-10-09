const degrees = 180 / Math.PI
const finite = value => typeof value === 'number' && Number.isFinite(value)

export function yawReadings(streams) {
  const e = streams?.electrics || {}
  // Legacy Minini cars have yaw rates but not the newer graph-output channel.
  const available = finite(e.companionTargetYawRate) && finite(e.companionYawRate)
    && e.companionYawTelemetryValid !== 0
  if (!available) return { available: false, target: null, measured: null, error: null, correction: null }
  const error = finite(e.companionYawRateError)
    ? e.companionYawRateError : e.companionTargetYawRate - e.companionYawRate
  return {
    available: true,
    target: e.companionTargetYawRate * degrees,
    measured: e.companionYawRate * degrees,
    error: error * degrees,
    correction: finite(e.companionYawCorrection) ? e.companionYawCorrection * degrees : null,
  }
}

export function signed(value) {
  if (!finite(value)) return '--'
  const rounded = Math.abs(value) < 0.005 ? 0 : value
  return (rounded > 0 ? '+' : '') + rounded.toFixed(2)
}

export function rcReadings(streams) {
  const e=streams?.electrics || {}
  return {available:e.companionRCControlValid===1,
    wantedRC:finite(e.companionWantedRC)?e.companionWantedRC:null,
    estimatedRC:finite(e.companionEstimatedRC)?e.companionEstimatedRC:null,
    rcError:finite(e.companionRCError)?e.companionRCError:null,
    wantedRS:finite(e.companionWantedRS)?e.companionWantedRS:null,
    estimatedRS:finite(e.companionEstimatedRS)?e.companionEstimatedRS:null,
    rsError:finite(e.companionRSError)?e.companionRSError:null,
    active:(e.companionVectoringState || 0)>0}
}

export const wheelNames = ['FL', 'FR', 'RL', 'RR']
export function pedalReadings(streams) {
  const e = streams?.electrics || {}
  const read = (key, lo) => (rcReadings(streams).available || yawReadings(streams).available) && finite(e[key]) ? Math.max(lo, Math.min(1, e[key])) * 100 : null
  return { brake: read('companionBrakePedal', 0), accelerator: read('companionAcceleratorPedal', 0), request: read('companionPedalRequest', -1) }
}
export function wheelReadings(streams) {
  const e = streams?.electrics || {}
  const missing = { available: false, wheels: Object.fromEntries(wheelNames.map(n => [n, { share: null, motorUse: null, gripUse: null, longitudinalSlip: null, lateralSlip: null, torque: null }])), requested: null, allocated: null }
  if (!(rcReadings(streams).available || yawReadings(streams).available) || e.companionWheelCorrectionValid !== 1) return missing
  const rows = wheelNames.map(n => ({ name: n, longitudinalSlip: finite(e[`companionTV${n}LongitudinalSlip`]) ? Math.abs(e[`companionTV${n}LongitudinalSlip`]) * 100 : null, lateralSlip: finite(e[`companionTV${n}LateralSlipDegrees`]) ? Math.abs(e[`companionTV${n}LateralSlipDegrees`]) : null, slipping: e[`companionTV${n}Slipping`] === 1, share: e[`companionTV${n}Share`], motorUse: e[`companionTV${n}MotorUse`], gripUse: e[`companionTV${n}GripUse`], torque: e[`companionTV${n}TorqueNm`], delta: e[`companionTV${n}DeltaNm`], yawMoment: e[`companionTV${n}YawMomentNm`], motorLimit: e[`companionTV${n}MotorLimitNm`], gripLimit: e[`companionTV${n}GripLimitNm`] }))
  if (rows.some(r => !['share', 'motorUse', 'gripUse', 'torque', 'delta', 'yawMoment', 'motorLimit', 'gripLimit'].every(k => finite(r[k])))) return missing
  // Largest remainder rounding keeps the displayed total at exactly 100%.
  const total = rows.reduce((s, r) => s + Math.max(0, r.share), 0)
  const ticks = rows.map(r => total > 1e-8 ? Math.max(0, r.share) / total * 1000 : 0)
  const rounded = ticks.map(Math.floor)
  const order = ticks.map((v, i) => i).sort((a, b) => (ticks[b] - rounded[b]) - (ticks[a] - rounded[a]))
  const remaining = total > 1e-8 ? 1000 - rounded.reduce((a, b) => a + b, 0) : 0
  for (let i = 0; i < remaining; i++) rounded[order[i % 4]]++
  const wheels = Object.fromEntries(rows.map((r, i) => [r.name, { ...r, share: rounded[i] / 10, motorUse: r.motorUse * 100, gripUse: Math.max(0, r.gripUse) * 100 }]))
  return { available: true, wheels, requested: finite(e.companionRequestedYawMoment) ? e.companionRequestedYawMoment : null, allocated: finite(e.companionAllocatedYawMoment) ? e.companionAllocatedYawMoment : null }
}
