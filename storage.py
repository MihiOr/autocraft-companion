"""Small, atomic on-disk settings store. Password is local, not logged."""
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / 'settings.json'


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_settings():
    if not SETTINGS.exists():
        return {}
    return json.loads(SETTINGS.read_text(encoding='utf-8'))


def save_settings(settings):
    atomic_bytes(SETTINGS, (json.dumps(settings, indent=2) + '\n').encode())
