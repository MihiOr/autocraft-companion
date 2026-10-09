"""Build and install the standalone rotation-center visualization."""
from pathlib import Path
import io
import os
import zipfile
from datetime import datetime
from storage import atomic_bytes
ROOT=Path(__file__).resolve().parent

def install(mods=None):
    mods=Path(mods) if mods else Path(os.environ['LOCALAPPDATA'])/'BeamNG/BeamNG.drive/current/mods'
    mods.mkdir(parents=True,exist_ok=True)
    target=mods/'MininiRotationCenter.zip'
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted((ROOT/'rotation_center_mod').rglob('*')):
            if path.is_file():z.write(path,path.relative_to(ROOT/'rotation_center_mod').as_posix())
    data=buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if z.testzip():raise ValueError('Rotation-center ZIP integrity failed')
    if target.exists() and target.read_bytes()!=data:
        backup=ROOT/'backups'/('rotation_center_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        backup.mkdir(parents=True,exist_ok=True)
        (backup/target.name).write_bytes(target.read_bytes())
    atomic_bytes(target,data)
    return target

if __name__=='__main__':print(install())
