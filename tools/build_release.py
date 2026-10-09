"""Build the Windows release with the launcher, clean source and helper mods."""
import argparse
import hashlib
import io
from pathlib import Path
import re
import zipfile
from build_mods import main as build_mods

ROOT=Path(__file__).resolve().parents[1]
FILES=('src/steering_calibration.json', 'AutoCraft Companion.exe', 'docs/CIVETTA_MODE.md', 'tools/CompanionLauncher.cs', 'docs/DASHBOARD_SERIAL.md', 'INSTALL.txt', 'docs/MININI_DEBUG.md', 'docs/PRIMITIVE_ECU.md', 'README.md', 'Start Companion.vbs', 'src/app.py', 'tools/build_launcher.ps1', 'tools/build_mods.py', 'tools/build_release.py', 'src/capture_erc.py', 'src/civetta/custom_motor_control.lua', 'src/civetta_patch.py', 'src/companion.ico', 'src/companion.png', 'src/companion_custom_ecu.lua', 'src/companion_ev_ecu.lua', 'src/companion_ev_sound.lua', 'src/companion_imu.lua', 'src/companion_rc.lua', 'src/control_graphs.py', 'src/creator_watchdog.py', 'src/custom_control.py', 'src/custom_control_contract.lua', 'src/custom_motor_control.lua', 'src/dashboard_bridge.py', 'src/dashboard_dummy.py', 'src/dashboard_install.py', 'src/dashboard_protocol.py', 'src/debug_mod.py', 'src/electric_patch.py', 'src/ev_sound_patch.py', 'src/graph_editor.py', 'src/imu_patch.py', 'src/install_camera_speed.py', 'src/install_rotation_center.py', 'src/install_test_bench.py', 'src/install_yaw_widget.py', 'src/kingpin_patch.py', 'src/latch_patch.py', 'src/minini_debug.py', 'src/one_wheel_realistic_overdrive_dyno.csv', 'src/parking_brake_patch.py', 'src/patcher.py', 'src/performance_tires.json', 'src/rack_mount_patch.py', 'requirements.txt', 'settings.example.json', 'setup.ps1', 'src/site_client.py', 'src/spawn_heading_patch.py', 'src/steering_response_patch.py', 'src/storage.py', 'src/suspension_values.py', 'src/tire_ecu_patch.py', 'src/toe_stability_patch.py', 'src/weight_patch.py', 'src/wheel_attachment_patch.py', 'src/windows_identity.py')
FOLDERS=('src/widget_mod', 'src/debug_memory_mod', 'src/mouse_steering_mod', 'src/spawn_heading_mod', 'src/dashboard_mod', 'src/camera_speed_mod', 'src/rotation_center_mod', 'src/test_bench_mod', 'src/yaw_widget_mod', 'src/debug_mod', 'docs/screenshots')
MODS=('CompanionWeightBalance', 'CompanionDebugMemory', 'CompanionMouseSteering', 'CompanionSpawnHeading', 'CompanionDashboard', 'CompanionCameraSpeed', 'MininiRotationCenter', 'MininiTestBench', 'MiTVSDebug', 'MininiDebug')


def build(version='0.2.0'):
    if not re.fullmatch(r'\d+\.\d+\.\d+',version): raise ValueError('Use a version such as 0.1.0.')
    destination=ROOT/'dist';destination.mkdir(exist_ok=True)
    build_mods()
    files={name:(ROOT/name).read_bytes() for name in FILES}
    if not files['AutoCraft Companion.exe'].startswith(b'MZ'):
        raise ValueError('Build the Windows launcher with tools/build_launcher.ps1 first.')
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
    parser.add_argument('--version',default='0.2.0')
    build(parser.parse_args().version)
