"""Install the standalone telemetry mod without repacking any car."""
import io
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from storage import atomic_bytes, ROOT


def install(mods):
    root=ROOT/'dashboard_mod'
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file(): archive.write(path,path.relative_to(root).as_posix())
    target=Path(mods)/'CompanionDashboard.zip'
    if target.exists() and target.read_bytes()!=data.getvalue():
        backup=ROOT/'backups'/'dashboard';backup.mkdir(parents=True,exist_ok=True)
        shutil.copy2(target,backup/(datetime.now().strftime('%Y%m%d_%H%M%S_%f_')+target.name))
    atomic_bytes(target,data.getvalue())
    return target
