"""Install the standalone MiTVS yaw UI app without modifying a vehicle ZIP."""
from pathlib import Path
import os
import zipfile
import shutil
from datetime import datetime

ROOT=Path(__file__).resolve().parent


def install(mods=None):
    mods=Path(mods) if mods else Path(os.environ['LOCALAPPDATA'])/'BeamNG/BeamNG.drive/current/mods'
    mods.mkdir(parents=True,exist_ok=True)
    target=mods/'MiTVSDebug.zip'
    staging=target.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(staging,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted((ROOT/'yaw_widget_mod').rglob('*')):
                if path.is_file():z.write(path,path.relative_to(ROOT/'yaw_widget_mod').as_posix())
        with zipfile.ZipFile(staging) as z:
            if z.testzip():raise ValueError('Yaw widget ZIP integrity check failed.')
        staging.replace(target)
        old=mods/'MininiYawControl.zip'
        if old.exists():
            backup=ROOT/'backups'/('yaw_widget_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
            backup.mkdir(parents=True,exist_ok=True)
            shutil.move(str(old),str(backup/old.name))
    finally:
        staging.unlink(missing_ok=True)
    return target


if __name__=='__main__':print(install())
