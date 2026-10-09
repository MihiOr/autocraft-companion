"""Opt-in spawn-heading marker and standalone GE helper installer."""
from pathlib import Path
import io
import shutil
import zipfile


def apply(entries, prefix):
    result = dict(entries)
    result[prefix+'companion_spawn_heading.json'] = b'{"rightDegrees":90}\n'
    return result


def install_helper(mods, backup_root):
    from storage import atomic_bytes
    root = Path(__file__).with_name('spawn_heading_mod')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(root.rglob('*')):
            if path.is_file(): z.write(path, path.relative_to(root).as_posix())
    target = Path(mods)/'CompanionSpawnHeading.zip'
    data = buffer.getvalue()
    if target.exists():
        if target.read_bytes() == data: return
        backup = Path(backup_root)/'spawn_heading'
        backup.mkdir(parents=True,exist_ok=True)
        from datetime import datetime
        shutil.copy2(target,backup/(datetime.now().strftime('%Y%m%d_%H%M%S_')+target.name))
    atomic_bytes(target,data)
