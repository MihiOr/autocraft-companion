import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const url=new URL('../test_bench_mod/ui/modules/apps/MininiTestBench/',import.meta.url)
const source=readFileSync(new URL('form.js',url),'utf8')
const {configuration,normalizeForm}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
const form={mode:'exact',FL:'100,5',FR:'-20',RL:'0',RR:'200',steering:'120',runup:true,speed:'50'}
assert.deepEqual(configuration(form),{mode:'exact',torque:{FL:100.5,FR:-20,RL:0,RR:200},steering:120,speed:50})
for(const change of [{FL:''},{FR:'NaN'},{RL:'1501'},{steering:481},{speed:-1},{mode:'other'}])assert.throws(()=>configuration({...form,...change}))
assert.equal(configuration({...form,runup:false}).speed,0)
const manifest=JSON.parse(readFileSync(new URL('app.json',url),'utf8'));assert.equal(manifest.vue,true);assert.equal(manifest.interactive,'yes')
console.log('Test bench GUI configuration checks passed')

const vue=readFileSync(new URL('app.vue',url),'utf8')
assert.ok(!vue.includes('<select'))
assert.ok(!vue.includes('type="text"'))
assert.ok(vue.includes('min="0" max="130" step="1"'))
assert.ok(vue.includes(':min="-steeringLock" :max="steeringLock" step="1"'))
assert.ok([...vue].every(c=>c.charCodeAt(0)<128))
assert.equal(normalizeForm({...form,speed:200,steering:900}).speed,130)
assert.equal(normalizeForm({...form,steering:900},360).steering,360)
assert.throws(()=>configuration({...form,speed:131}))

assert.ok(!vue.includes('<fieldset :disabled="running">'))
assert.ok(vue.includes('Nm | current'))
assert.ok(vue.includes('extensions.mininiTestBench.update('))

assert.ok(vue.includes('min="-1500" max="1500"'))
assert.ok(vue.includes('>-10</button>') && vue.includes('>+10</button>'))
assert.equal(normalizeForm({...form,FL:5000}).FL,1500)

assert.equal(configuration({...form,FL:1500,FR:-1500}).torque.FL,1500)
assert.equal(configuration({...form,FL:1500,FR:-1500}).torque.FR,-1500)
