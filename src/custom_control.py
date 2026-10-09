"""Package/check the user's Lua, using the same contract as the vehicle adapter."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
USER_FILE = ROOT / 'custom_motor_control.lua'


def source_for_export():
    """Package the applied profile, never an editor draft or stale graph table."""
    source=USER_FILE.read_text(encoding='utf-8-sig')
    from control_graphs import ACTIVE,load,lua_source
    if ACTIVE.exists() and '-- BEGIN_MEASURED_STEERING' in source and '-- BEGIN_YAW_CORRECTION_GRAPH' in source:
        source=lua_source(source,load(ACTIVE))
    return source


def verify_motor_wiring(entries):
    """Refuse an EV package that would let the default throttle drive the motors."""
    for name, raw in entries.items():
        if not name.endswith('/engine.jbeam'):
            continue
        engine = json.loads(raw).get('engine', {})
        if 'evMotorFL' not in engine:
            continue
        prefix = name[:-len('engine.jbeam')]
        controllers = [r[0] for r in engine.get('controller', []) if isinstance(r, list) and r]
        if 'companion_custom_ecu' not in controllers or 'companion_ev_ecu' in controllers:
            raise ValueError('EV export lacks exclusive custom Lua motor control. Restart Companion and reapply.')
        for wheel in ('FL', 'FR', 'RL', 'RR'):
            motor = engine['evMotor'+wheel]
            for key, expected in dict(electricsThrottleName='companionCustom'+wheel,
                                     electricsThrottleFactorName='companionCustomFactor',
                                     electricsRegenThrottleName='companionCustomRegen'+wheel).items():
                if motor.get(key) != expected:
                    raise ValueError('Unsafe default motor input on '+wheel+': '+key)
        for suffix in ('custom_motor_control.lua', 'lua/controller/companion_custom_ecu.lua'):
            if prefix+suffix not in entries:
                raise ValueError('Missing packaged custom motor code: '+suffix)
        adapter = entries[prefix+'lua/controller/companion_custom_ecu.lua'].decode('utf-8')
        if '-- __IMU__' in adapter or '__USER_SOURCE__' in adapter or '-- __CONTRACT__' in adapter:
            raise ValueError('Incomplete custom ECU package. Restart Companion and reapply.')
        if 'createIMUSampler(' in adapter and 'local function createIMUSampler(' not in adapter:
            raise ValueError('Missing IMU implementation. Restart Companion and reapply.')


def build_controller(source):
    marker = '='
    while ']' + marker + ']' in source:
        marker += '='
    literal = '[' + marker + '[\n' + source + ']' + marker + ']'
    return (ROOT / 'companion_custom_ecu.lua').read_text(encoding='utf-8').replace(
        '-- __CONTRACT__', (ROOT / 'custom_control_contract.lua').read_text(encoding='utf-8')).replace(
        '-- __IMU__', (ROOT / 'companion_imu.lua').read_text(encoding='utf-8')).replace(
        '-- __RC__', (ROOT / 'companion_rc.lua').read_text(encoding='utf-8')).replace(
        '__USER_SOURCE__', literal)


def check_code(source=None):
    if source is None:
        source = USER_FILE.read_text(encoding='utf-8-sig')
    python = Path(sys.executable)
    if python.name.lower() == 'pythonw.exe':
        python = python.with_name('python.exe')
    try:
        result = subprocess.run([str(python), str(Path(__file__).resolve()), '--check'],
                                input=source, text=True, encoding='utf-8', capture_output=True,
                                timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise ValueError('Lua check timed out (possible endless loop).') from None
    if result.returncode:
        raise ValueError((result.stdout or result.stderr).strip()[-3000:])
    return result.stdout.strip()


def _check(source):
    # Bundled locally with Companion's existing Lua test runtime; no game needed.
    sys.path.insert(0, str(ROOT / 'tests' / '_runtime'))
    from lupa.luajit21 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True, max_memory=32 * 1024 * 1024)
    contract = (ROOT / 'custom_control_contract.lua').read_text(encoding='utf-8')
    load, evaluate = lua.execute(contract + '\nreturn loadUser,evaluateUser')
    fn = load(source)
    memory = lua.table()
    total = 0
    for gear, speed, gas, brake in [(0,0,1,0),(1,0,0,0),(1,0,1,1),
                                   (1,0,1,0),(1,10,1,0),(1,30,.5,0),
                                   (1,20,0,1),(-1,0,1,0),(-1,5,.5,0)]:
        active = armed = False
        for tick in range(30):
            motion_sign=-1 if gear<0 else 1
            rolling={n:(0 if brake and tick>10 and n=='FL' else speed+(5 if n=='FL' and tick>10 else 0))*motion_sign
                     for n in ('FL','FR','RL','RR')}
            state = dict(dt=.01,time=total*.01,bodySpeed=speed,forwardSpeed=speed*(1 if gear>=0 else -1),
                         throttle=gas,brake=brake,parkingBrake=0,steering=0,gear=gear,
                         gearName='R' if gear<0 else ('N' if gear==0 else 'D'),
                         launchActive=active,launchArmed=armed,acceleration=dict(x=0,y=0,z=9.81),
                         wheelSpeed=rolling,wheelGroundSpeed={n:speed for n in rolling},
                         wheelRPM={n:v*30 for n,v in rolling.items()},
                         motorRPM={n:v*30 for n,v in rolling.items()},
                         imu={n:dict(valid=True,acceleration=dict(forward=0,left=0,up=9.81),
                                     gyro=dict(forward=0,left=0,up=0),offset=dict(forward=0,left=0,up=0))
                              for n in rolling},geometry=dict(wheelbase=3,trackFront=2,trackRear=2))
            out = evaluate(fn,lua.table_from(state,recursive=True),memory)
            active,armed = out['launchActive'] is True,out['launchArmed'] is True
            total += 1
    # Exercise both turn directions, excess/missing yaw, braking wheel lock,
    # coasting and reverse with the same four-IMU contract used in the vehicle.
    vector_steps=0
    for steer,yaw,brake,gas,gear in [(-.2,1,0,1,1),(.2,-1,0,1,1),(-.5,.2,0,1,1),
                                    (-.2,1,1,0,1),(.2,-1,1,0,1),(-.5,0,1,0,1),
                                    (.2,1,0,0,1),(.2,1,0,1,-1)]:
        memory=lua.table()
        for tick in range(40):
            state.update(gear=gear,throttle=gas,brake=brake,steering=steer,bodySpeed=20,time=(total+vector_steps)*.01,
                         wheelSpeed={n:0 if brake and yaw==0 and n.startswith('F') else (20 if gear>0 else -20)
                                     for n in ('FL','FR','RL','RR')},
                         imu={n:dict(valid=True,acceleration=dict(forward=0,left=6*(1 if yaw>=0 else -1),up=9.81),
                                     gyro=dict(forward=0,left=0,up=yaw),offset=dict(forward=0,left=0,up=0))
                              for n in ('FL','FR','RL','RR')})
            evaluate(fn,lua.table_from(state,recursive=True),memory)
            vector_steps+=1
    # Compile the complete packaged adapter as well.
    lua.compile(build_controller(source))
    return f'Passed: Lua syntax, {total} basic and {vector_steps} four-IMU/vectoring control steps. In-game handling still needs testing.'


if __name__ == '__main__':
    try:
        print(_check(sys.stdin.buffer.read().decode('utf-8')))
    except Exception as exc:
        print(str(exc))
        sys.exit(1)
