"""Build standalone helper mods from source into dist/."""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src'
MODS={'widget_mod': 'CompanionWeightBalance', 'debug_memory_mod': 'CompanionDebugMemory', 'mouse_steering_mod': 'CompanionMouseSteering', 'spawn_heading_mod': 'CompanionSpawnHeading', 'dashboard_mod': 'CompanionDashboard', 'camera_speed_mod': 'CompanionCameraSpeed', 'rotation_center_mod': 'MininiRotationCenter', 'test_bench_mod': 'MininiTestBench', 'yaw_widget_mod': 'MiTVSDebug', 'debug_mod': 'MininiDebug'}


def main():
    destination=ROOT/'dist';destination.mkdir(exist_ok=True)
    for folder,name in MODS.items():
        target=destination/(name+'.zip')
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((SOURCE/folder).rglob('*')):
                if path.is_file():
                    data=path.read_bytes()
                    if path.name=='mininiDebugVehicle.lua':data=data.replace(b'-- __IMU__',(SOURCE/'companion_imu.lua').read_bytes())
                    archive.writestr(path.relative_to(SOURCE/folder).as_posix(),data)
        print(target.name)


if __name__=='__main__': main()
