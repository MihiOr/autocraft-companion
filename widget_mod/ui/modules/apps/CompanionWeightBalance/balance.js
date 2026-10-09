export function calculateBalance(streams) {
  const names = ['FL', 'FR', 'RL', 'RR']
  const wheels = Object.fromEntries(names.map(name => [name, null]))
  const source = streams?.wheelInfo
  for (const row of Array.isArray(source) ? source : Object.values(source || {})) {
    if (!Array.isArray(row) || (row[14] && row[14] !== 'wheel')) continue
    const name = String(row[0] || '').toUpperCase()
    if (!names.includes(name)) continue
    if (typeof row[7] === 'number' && Number.isFinite(row[7])) wheels[name] = Math.max(0, row[7])
  }
  const complete = names.every(name => wheels[name] !== null)
  const gravity = Number.isFinite(streams?.sensors?.gravity) ? Math.abs(streams.sensors.gravity) : 9.81
  const total = names.reduce((sum, name) => sum + (wheels[name] || 0), 0)
  const loaded = complete && total > 0
  const left = loaded ? (wheels.FL + wheels.RL) / total * 100 : null
  const front = loaded ? (wheels.FL + wheels.FR) / total * 100 : null
  const biasX = loaded ? 1 - left / 50 : 0
  const biasY = loaded ? 1 - front / 50 : 0
  const scale = Math.max(1, Math.hypot(biasX, biasY))
  return { wheels, complete, total, gravity: gravity >= 0.1 ? gravity : null,
    left, right: left === null ? null : 100 - left,
    front, rear: front === null ? null : 100 - front,
    dot: loaded ? { x: biasX / scale, y: biasY / scale } : null,
    shares: Object.fromEntries(names.map(name => [name, loaded ? wheels[name] / total * 100 : null])) }
}
