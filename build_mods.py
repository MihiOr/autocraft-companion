"""Build standalone helper mods from source into dist/."""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
MODS={
    'dashboard_mod':'CompanionDashboard',
    'debug_memory_mod':'CompanionDebugMemory',
    'mouse_steering_mod':'CompanionMouseSteering',
    'spawn_heading_mod':'CompanionSpawnHeading',
    'widget_mod':'CompanionWeightBalance',
}


def main():
    destination=ROOT/'dist';destination.mkdir(exist_ok=True)
    for folder,name in MODS.items():
        target=destination/(name+'.zip')
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((ROOT/folder).rglob('*')):
                if path.is_file(): archive.write(path,path.relative_to(ROOT/folder).as_posix())
        print(target.name)


if __name__=='__main__': main()
