"""Package/check the user's Lua, using the same contract as the vehicle adapter."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
USER_FILE = ROOT / 'custom_motor_control.lua'


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
                                     electricsRegenThrottleName='companionCustomRegen').items():
                if motor.get(key) != expected:
                    raise ValueError('Unsafe default motor input on '+wheel+': '+key)
        for suffix in ('custom_motor_control.lua', 'lua/controller/companion_custom_ecu.lua'):
            if prefix+suffix not in entries:
                raise ValueError('Missing packaged custom motor code: '+suffix)


def build_controller(source):
    marker = '='
    while ']' + marker + ']' in source:
        marker += '='
    literal = '[' + marker + '[\n' + source + ']' + marker + ']'
    return (ROOT / 'companion_custom_ecu.lua').read_text(encoding='utf-8').replace(
        '-- __CONTRACT__', (ROOT / 'custom_control_contract.lua').read_text(encoding='utf-8')).replace(
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
    # Run the same Lua contract used by the vehicle adapter.
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
            state = dict(dt=.01,time=total*.01,bodySpeed=speed,forwardSpeed=speed*(1 if gear>=0 else -1),
                         throttle=gas,brake=brake,parkingBrake=0,steering=0,gear=gear,
                         gearName='R' if gear<0 else ('N' if gear==0 else 'D'),
                         launchActive=active,launchArmed=armed,acceleration=dict(x=0,y=0,z=9.81),
                         wheelSpeed={n:speed+(5 if n=='FL' and tick>10 else 0) for n in ('FL','FR','RL','RR')},
                         wheelRPM={n:speed*30 for n in ('FL','FR','RL','RR')},
                         motorRPM={n:speed*30 for n in ('FL','FR','RL','RR')})
            out = evaluate(fn,lua.table_from(state,recursive=True),memory)
            active,armed = out['launchActive'] is True,out['launchArmed'] is True
            total += 1
    # Compile the complete packaged adapter as well.
    lua.compile(build_controller(source))
    return f'Passed: Lua syntax and {total} simulated control steps. In-game handling still needs testing.'


if __name__ == '__main__':
    try:
        print(_check(sys.stdin.buffer.read().decode('utf-8')))
    except Exception as exc:
        print(str(exc))
        sys.exit(1)
