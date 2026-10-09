"""Window icon and pin/relaunch metadata for the small Windows launcher."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import uuid

APP_ID = 'AutoCraft.Companion'


def process_identity():
    if hasattr(ctypes, 'windll'):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def configure_window(window):
    root = Path(__file__).resolve().parent
    icon = root / 'companion.ico'
    if icon.exists():
        window.iconbitmap(default=str(icon))
    if not hasattr(ctypes, 'windll'):
        return
    window.update_idletasks()

    class GUID(ctypes.Structure):
        _fields_ = [('data', ctypes.c_ubyte * 16)]
    def guid(value):
        return GUID((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))
    class KEY(ctypes.Structure):
        _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]
    class VALUE(ctypes.Union):
        _fields_ = [('text', ctypes.c_wchar_p), ('padding', ctypes.c_ubyte * 16)]
    class PROPVARIANT(ctypes.Structure):
        _fields_ = [('vt', ctypes.c_ushort), ('reserved', ctypes.c_ushort * 3), ('value', VALUE)]

    get_parent = ctypes.windll.user32.GetParent
    get_parent.argtypes = [wintypes.HWND]
    get_parent.restype = wintypes.HWND
    hwnd = get_parent(window.winfo_id()) or window.winfo_id()
    iid = guid('886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99')
    store = ctypes.c_void_p()
    get_store = ctypes.windll.shell32.SHGetPropertyStoreForWindow
    get_store.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    get_store.restype = ctypes.c_long
    if get_store(hwnd, ctypes.byref(iid), ctypes.byref(store)) < 0:
        return
    table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(KEY), ctypes.POINTER(PROPVARIANT))(table[6])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])
    fmtid = guid('9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3')
    try:
        # Relaunch command/icon/name precede AppUserModelID, per Shell contract.
        for pid, text in ((2, '"'+str(root/'AutoCraft Companion.exe')+'"'),
                          (3, str(icon)+',0'), (4, 'AutoCraft Companion'), (5, APP_ID)):
            key = KEY(fmtid, pid)
            value = PROPVARIANT()
            value.vt = 31  # VT_LPWSTR; Python owns the string during SetValue.
            value.value.text = text
            if set_value(store, ctypes.byref(key), ctypes.byref(value)) < 0:
                raise OSError('Windows could not set Companion taskbar metadata.')
    finally:
        release(store)
