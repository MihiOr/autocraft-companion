"""Build the standalone debug bridge with the same IMU hardware as the ECU."""
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent


def build(target, imu_config):
    target = Path(target)
    with ZipFile(target, 'w', ZIP_DEFLATED) as z:
        for path in sorted((ROOT / 'debug_mod').rglob('*')):
            if path.is_file():
                raw = path.read_bytes()
                if path.name == 'mininiDebugVehicle.lua':
                    raw = raw.replace(b'-- __IMU__', (ROOT / 'companion_imu.lua').read_bytes())
                z.writestr(path.relative_to(ROOT / 'debug_mod').as_posix(), raw)
        z.writestr('lua/vehicle/extensions/mininiDebugIMU.json', json.dumps(imu_config))
        z.writestr('mod_info/mininiDebug/info.json', json.dumps({
            'name': 'Minini Live Debugger', 'version': '1.0', 'author': 'MiNini',
            'description': 'Local control and motor/IMU diagnostics for Companion EVs.'}))
    with ZipFile(target) as z:
        assert z.testzip() is None
    return target
