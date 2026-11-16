"""Self-install / uninstall for the portable build.

The portable folder is   <root>/runtime (a private copy of Python)  +  <root>/app (Glint).
`Install Glint.cmd` runs  runtime\\pythonw.exe app\\Glint.pyw --install, which copies <root> to
%LOCALAPPDATA%\\Programs\\Glint and creates Start menu + desktop shortcuts.
Everything that runs is Microsoft/PSF/Qt-signed, so Smart App Control lets it through; an unsigned
setup.exe would be blocked on PCs where Smart App Control is on.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from . import theme, winapi

APP_NAME = "Glint"


def source_root():
    return Path(sys.executable).resolve().parent.parent


def install_dir():
    return Path(os.environ.get("GLINT_INSTALL_DIR") or
                Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME)


def shortcut_dirs():
    if os.environ.get("GLINT_SHORTCUT_DIR"):
        return [Path(os.environ["GLINT_SHORTCUT_DIR"])]
    appdata = Path(os.environ["APPDATA"])
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    return [appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs", desktop]


AUMID = "Glint.ScreenCapture"     # must match SetCurrentProcessExplicitAppUserModelID in app.main


def _property_store():
    """Minimal IPropertyStore (comtypes has no binding) - enough to set the shortcut's AppUserModel.ID."""
    import ctypes
    from ctypes import wintypes
    import comtypes
    from comtypes import GUID, COMMETHOD, HRESULT, IUnknown

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]

    class IPropertyStore(IUnknown):
        _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetCount", (["out"], ctypes.POINTER(wintypes.DWORD), "c")),
            COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD, "i"),
                      (["out"], ctypes.POINTER(PROPERTYKEY), "k")),
            COMMETHOD([], HRESULT, "GetValue", (["in"], ctypes.POINTER(PROPERTYKEY), "k"),
                      (["out"], ctypes.POINTER(PROPVARIANT), "v")),
            COMMETHOD([], HRESULT, "SetValue", (["in"], ctypes.POINTER(PROPERTYKEY), "k"),
                      (["in"], ctypes.POINTER(PROPVARIANT), "v")),
            COMMETHOD([], HRESULT, "Commit"),
        ]
    key = PROPERTYKEY(GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)   # PKEY_AppUserModel_ID
    return IPropertyStore, PROPVARIANT, key, comtypes


def set_shortcut_app_id(lnk, app_id=AUMID):
    """Stamp the taskbar identity onto an existing .lnk. Returns True if it was changed."""
    import comtypes.client
    from comtypes.persist import IPersistFile
    from comtypes.shelllink import ShellLink, IShellLinkW
    IPropertyStore, PROPVARIANT, key, comtypes = _property_store()
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    link = comtypes.client.CreateObject(ShellLink, interface=IShellLinkW)
    pf = link.QueryInterface(IPersistFile)
    pf.Load(str(lnk), 2)                       # STGM_READWRITE
    store = link.QueryInterface(IPropertyStore)
    cur = store.GetValue(key)
    if cur.vt == 31 and cur.pwszVal == app_id:
        return False
    v = PROPVARIANT()
    v.vt = 31                                  # VT_LPWSTR
    v.pwszVal = app_id
    store.SetValue(key, v)
    store.Commit()
    pf.Save(str(lnk), True)
    return True


def stamp_own_shortcuts():
    """Glint's Start menu / desktop shortcuts need the same taskbar identity as the running app, or
    Windows can't match the taskbar button to Glint and shows a blank icon. Cheap; runs at startup."""
    for d in shortcut_dirs():
        lnk = d / f"{APP_NAME}.lnk"
        if lnk.exists():
            try:
                set_shortcut_app_id(lnk)
            except Exception:
                pass


def make_shortcut(lnk, target, args, workdir, icon):
    import comtypes
    import comtypes.client
    from comtypes.persist import IPersistFile
    from comtypes.shelllink import ShellLink, IShellLinkW
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    link = comtypes.client.CreateObject(ShellLink, interface=IShellLinkW)
    link.SetPath(str(target))
    link.SetArguments(args)
    link.SetWorkingDirectory(str(workdir))
    link.SetIconLocation(str(icon), 0)
    link.SetDescription("Glint screen capture")
    lnk.parent.mkdir(parents=True, exist_ok=True)
    link.QueryInterface(IPersistFile).Save(str(lnk), True)
    try:
        set_shortcut_app_id(lnk)
    except Exception:
        pass


def _stop_running_copy():
    from PySide6.QtNetwork import QLocalSocket
    from .app import INSTANCE_KEY
    s = QLocalSocket()
    s.connectToServer(INSTANCE_KEY)
    if s.waitForConnected(300):
        s.write(b"quit")
        s.flush()
        s.waitForBytesWritten(300)
        s.disconnectFromServer()
        import time
        for _ in range(30):     # give it up to 3 s to exit and release its files
            time.sleep(0.1)
            t = QLocalSocket()
            t.connectToServer(INSTANCE_KEY)
            if not t.waitForConnected(100):
                return
            t.disconnectFromServer()


class _Progress(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setWindowTitle("Installing Glint")
        self.setWindowIcon(theme.app_icon())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 20)
        self.label = QLabel("Copying files…")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        self.setFixedWidth(380)
        self.show()
        winapi.style_window(self.winId())


def install():
    src, dest = source_root(), install_dir()
    if not (src / "runtime" / "pythonw.exe").exists() or not (src / "app" / "Glint.pyw").exists():
        QMessageBox.warning(None, "Glint", "Run this from the extracted Glint folder (it needs the 'runtime' "
                                           "and 'app' folders next to it).")
        return 1
    _stop_running_copy()
    same = src.resolve() == dest.resolve() if dest.exists() else False
    if not same:
        files = [p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        ui = _Progress()
        ui.bar.setRange(0, len(files))
        try:
            if dest.exists():
                for sub in ("app", "runtime"):
                    shutil.rmtree(dest / sub, ignore_errors=True)
            for i, f in enumerate(files):
                out = dest / f.relative_to(src)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
                if i % 25 == 0:
                    ui.bar.setValue(i)
                    QApplication.processEvents()
        except Exception as e:
            ui.close()
            QMessageBox.critical(None, "Glint", f"Install failed while copying files:\n\n{e}")
            return 1
        ui.close()
    pyw = dest / "runtime" / "pythonw.exe"
    script = dest / "app" / "Glint.pyw"
    icon = dest / "app" / "assets" / "glint.ico"
    for d in shortcut_dirs():
        try:
            make_shortcut(d / f"{APP_NAME}.lnk", pyw, f'"{script}"', script.parent, icon)
        except Exception:
            pass
    subprocess.Popen([str(pyw), str(script)], cwd=str(script.parent), close_fds=True)
    QMessageBox.information(None, "Glint", "Glint is installed.\n\nIt's in your Start menu and on your desktop, "
                                           "and it's now running in the tray. You can delete the folder you "
                                           "installed from.")
    return 0


def uninstall():
    r = QMessageBox.question(None, "Glint", "Remove Glint from this PC?\n\nYour captures and settings are kept.")
    if r != QMessageBox.Yes:
        return 0
    _stop_running_copy()
    for d in shortcut_dirs():
        try:
            (d / f"{APP_NAME}.lnk").unlink(missing_ok=True)
        except Exception:
            pass
    try:
        winapi.set_start_with_windows(False)
    except Exception:
        pass
    dest = install_dir()
    if source_root() == dest.resolve():
        # can't delete the folder we're running from: let cmd do it a moment after we exit
        subprocess.Popen(f'cmd /c timeout /t 2 /nobreak >nul & rmdir /s /q "{dest}"',
                         creationflags=0x08000000, close_fds=True)
    return 0
