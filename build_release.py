"""Build the Windows release with the launcher, clean source and helper mods."""
import argparse
import hashlib
import io
from pathlib import Path
import re
import zipfile
from build_mods import main as build_mods

ROOT=Path(__file__).resolve().parent
FILES=(
    'app.py','creator_watchdog.py','custom_control.py','dashboard_bridge.py',
    'dashboard_dummy.py','dashboard_install.py','dashboard_protocol.py',
    'electric_patch.py','ev_sound_patch.py','kingpin_patch.py','latch_patch.py',
    'patcher.py','site_client.py','spawn_heading_patch.py','steering_response_patch.py',
    'storage.py','suspension_values.py','tire_ecu_patch.py','weight_patch.py','windows_identity.py',
    'companion_custom_ecu.lua','companion_ev_ecu.lua','companion_ev_sound.lua',
    'custom_control_contract.lua','custom_motor_control.lua',
    'one_wheel_realistic_overdrive_dyno.csv','companion.ico','companion.png',
    'AutoCraft Companion.exe','CompanionLauncher.cs','Start Companion.vbs',
    'requirements.txt','setup.ps1','build_launcher.ps1','build_mods.py',
    'build_release.py','settings.example.json','README.md','DASHBOARD_SERIAL.md',
    'INSTALL.txt',
)
FOLDERS=('dashboard_mod','debug_memory_mod','mouse_steering_mod','spawn_heading_mod','widget_mod','docs/screenshots')
MODS=('CompanionDashboard','CompanionDebugMemory','CompanionMouseSteering','CompanionSpawnHeading','CompanionWeightBalance')


def build(version='0.1.0'):
    if not re.fullmatch(r'\d+\.\d+\.\d+',version): raise ValueError('Use a version such as 0.1.0.')
    destination=ROOT/'dist';destination.mkdir(exist_ok=True)
    build_mods()
    files={name:(ROOT/name).read_bytes() for name in FILES}
    if not files['AutoCraft Companion.exe'].startswith(b'MZ'):
        raise ValueError('Build the Windows launcher with build_launcher.ps1 first.')
    for folder in FOLDERS:
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                files[path.relative_to(ROOT).as_posix()]=path.read_bytes()
    for mod in MODS:
        files['beamng-mods/'+mod+'.zip']=(destination/(mod+'.zip')).read_bytes()
    checks=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(files.items()))
    files['SHA256SUMS.txt']=checks.encode()
    target=destination/f'AutoCraft-Companion-v{version}-windows.zip'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()):
            entry=zipfile.ZipInfo('AutoCraft Companion/'+name,(2026,1,1,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=0o100644<<16
            archive.writestr(entry,data)
    target.write_bytes(output.getvalue())
    (destination/'SHA256SUMS.txt').write_text(hashlib.sha256(output.getvalue()).hexdigest()+'  '+target.name+'\n',encoding='utf-8')
    print('Built '+target.name)
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',default='0.1.0')
    build(parser.parse_args().version)
