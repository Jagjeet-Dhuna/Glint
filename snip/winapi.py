"""Thin ctypes wrappers around the Win32 calls Snip needs.

Everything here works in *physical* pixels (Qt makes the process per-monitor DPI aware).
"""
import ctypes
import os
import sys
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

# ---------------------------------------------------------------- structures
class RECT(ctypes.Structure):
    _fields_ = [("left", W.LONG), ("top", W.LONG), ("right", W.LONG), ("bottom", W.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", W.LONG), ("y", W.LONG)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", W.DWORD), ("szDevice", W.WCHAR * 32)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


# ---------------------------------------------------------------- signatures
user32.GetDC.argtypes = [W.HWND]
user32.GetDC.restype = W.HDC
user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.RegisterHotKey.argtypes = [W.HWND, ctypes.c_int, W.UINT, W.UINT]
user32.RegisterHotKey.restype = W.BOOL
user32.UnregisterHotKey.argtypes = [W.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsIconic.argtypes = [W.HWND]
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(RECT)]
user32.GetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowTextLengthW.argtypes = [W.HWND]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.GetMonitorInfoW.argtypes = [W.HMONITOR, ctypes.c_void_p]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.GetLayeredWindowAttributes.argtypes = [W.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

gdi32.CreateCompatibleDC.argtypes = [W.HDC]
gdi32.CreateCompatibleDC.restype = W.HDC
gdi32.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = W.HBITMAP
gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
gdi32.SelectObject.restype = W.HGDIOBJ
gdi32.BitBlt.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         W.HDC, ctypes.c_int, ctypes.c_int, W.DWORD]
gdi32.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p, ctypes.c_void_p, W.UINT]
gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
gdi32.DeleteDC.argtypes = [W.HDC]

kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.SetFileAttributesW.argtypes = [W.LPCWSTR, W.DWORD]

dwmapi.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
dwmapi.DwmSetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]

# ---------------------------------------------------------------- constants
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x20, 0x80000, 0x08000000
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 35, 36

HOTKEYS = {
    "Print Screen": (0, 0x2C),
    "Ctrl+Print Screen": (MOD_CONTROL, 0x2C),
    "Shift+Print Screen": (MOD_SHIFT, 0x2C),
    "Ctrl+Shift+X": (MOD_CONTROL | MOD_SHIFT, ord("X")),
    "Ctrl+Alt+S": (MOD_CONTROL | MOD_ALT, ord("S")),
    "Alt+Shift+S": (MOD_ALT | MOD_SHIFT, ord("S")),
    "Ctrl+Shift+2": (MOD_CONTROL | MOD_SHIFT, ord("2")),
    "None": None,
}


# ---------------------------------------------------------------- hotkeys
def register_hotkey(hotkey_id, name):
    spec = HOTKEYS.get(name)
    if not spec:
        return True
    mods, vk = spec
    return bool(user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk))


def unregister_hotkey(hotkey_id):
    user32.UnregisterHotKey(None, hotkey_id)


def hotkey_id_from_msg(message):
    """Return the hotkey id if the native MSG pointer is a WM_HOTKEY, else None."""
    msg = W.MSG.from_address(int(message))
    if msg.message == WM_HOTKEY:
        return int(msg.wParam)
    return None


# ---------------------------------------------------------------- screen capture
def virtual_screen():
    return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
            user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))


def grab_virtual_screen():
    """BitBlt the entire virtual desktop. Returns (x, y, w, h, bgra_bytes)."""
    x, y, w, h = virtual_screen()
    hdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        gdi32.BitBlt(mdc, 0, 0, w, h, hdc, x, y, SRCCOPY | CAPTUREBLT)
        gdi32.SelectObject(mdc, old)
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth, bi.biHeight = w, -h  # negative = top-down rows
        bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
        buf = ctypes.create_string_buffer(w * h * 4)
        lines = gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        if lines != h:
            raise OSError("Screen capture failed (GetDIBits)")
        return x, y, w, h, buf.raw
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, hdc)


MonitorEnumProc = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, ctypes.POINTER(RECT), W.LPARAM)
user32.EnumDisplayMonitors.argtypes = [W.HDC, ctypes.c_void_p, MonitorEnumProc, W.LPARAM]


def monitors():
    """List of (device_name, (l, t, r, b)) in physical pixels."""
    out = []

    def cb(hmon, _hdc, _rect, _lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            out.append((mi.szDevice, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
    return out


def cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ---------------------------------------------------------------- windows
EnumWindowsProc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, W.LPARAM]

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", W.LONG), ("dwFlags", W.DWORD),
                ("szExeFile", W.WCHAR * 260)]


kernel32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = W.HANDLE
kernel32.Process32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def process_table():
    """pid -> (exe name, parent pid), from the system process list (no process handles opened)."""
    table = {}
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == W.HANDLE(-1).value:
        return table
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            table[e.th32ProcessID] = (e.szExeFile, e.th32ParentProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return table


def process_names():
    """pid -> exe name from the system process list.

    Anti-cheat friendly: this never opens a handle to any other process (unlike OpenProcess),
    so games are never touched."""
    names = {}
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == W.HANDLE(-1).value:
        return names
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            names[e.th32ProcessID] = e.szExeFile
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return names


user32.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]
user32.GetClassLongPtrW.argtypes = [W.HWND, ctypes.c_int]
user32.GetClassLongPtrW.restype = ctypes.c_size_t


def window_icon(hwnd):
    """HICON for a window, asked of the window itself (what the taskbar does) - no process access."""
    if not hwnd:
        return 0
    res = ctypes.c_size_t(0)
    for kind in (1, 2, 0):  # ICON_BIG, ICON_SMALL2, ICON_SMALL
        if user32.SendMessageTimeoutW(hwnd, 0x7F, kind, 0, 0x2, 100, ctypes.byref(res)) and res.value:
            return res.value
    for idx in (-14, -34):  # GCLP_HICON, GCLP_HICONSM
        v = user32.GetClassLongPtrW(hwnd, idx)
        if v:
            return v
    return 0


def list_windows():
    """Visible top-level windows in Z order (topmost first).

    Each item: dict(hwnd, rect=(l, t, r, b) physical, title, cls, app).
    """
    out = []
    names = process_names()

    def cb(hwnd, _lp):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            cloaked = ctypes.c_int(0)
            dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if cloaked.value:
                return True
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if ex & WS_EX_TRANSPARENT:
                return True
            if ex & WS_EX_LAYERED:
                alpha = ctypes.c_ubyte(255)
                flags = W.DWORD(0)
                if user32.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), ctypes.byref(flags)):
                    if flags.value & 0x2 and alpha.value == 0:  # LWA_ALPHA fully transparent
                        return True
            r = RECT()
            if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
                user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left < 8 or r.bottom - r.top < 8:
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            tb = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, tb, n + 1)
            cb_ = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cb_, 256)
            pid = W.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append(dict(hwnd=hwnd, rect=(r.left, r.top, r.right, r.bottom), title=tb.value,
                            cls=cb_.value, app=app_name_for(pid.value, names), exe=""))
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


user32.GetForegroundWindow.restype = W.HWND


def foreground_window():
    """dict(rect, title, app) for the active window, or None."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    r = RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    n = user32.GetWindowTextLengthW(hwnd)
    tb = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, tb, n + 1)
    cb_ = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cb_, 256)
    pid = W.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return dict(hwnd=hwnd, rect=(r.left, r.top, r.right, r.bottom), title=tb.value, cls=cb_.value,
                app=app_name_for(pid.value, process_names()), exe="")


def app_name_for(pid, names):
    """Program name for a window's process. Glint itself runs as pythonw.exe - call it Glint."""
    if pid == os.getpid():
        return "Glint.exe"
    return names.get(pid, "")


# ---------------------------------------------------------------- Print Screen ownership
_KB_KEY = r"Control Panel\Keyboard"


def printscreen_owned_by_windows():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KB_KEY) as k:
            v, _ = winreg.QueryValueEx(k, "PrintScreenKeyForSnippingEnabled")
            return bool(v)
    except FileNotFoundError:
        return True  # Windows 11 default is ON when the value is missing
    except Exception:
        return False


def release_printscreen_from_windows():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KB_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "PrintScreenKeyForSnippingEnabled", 0, winreg.REG_DWORD, 0)
    res = W.DWORD()
    user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, ctypes.c_wchar_p(_KB_KEY), 2, 2000, ctypes.byref(res))


# ---------------------------------------------------------------- misc
def force_foreground(hwnd):
    try:
        user32.SetForegroundWindow(W.HWND(int(hwnd)))
    except Exception:
        pass


def style_window(hwnd, dark=None, round_corners=True):
    """Title bar matching Glint's light/dark theme + Windows 11 rounded corners (no-ops on older Windows)."""
    try:
        from . import theme
        if dark is None:
            dark = theme.is_dark()
        h = W.HWND(int(hwnd))
        v = ctypes.c_int(1 if dark else 0)
        dwmapi.DwmSetWindowAttribute(h, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(v), ctypes.sizeof(v))
        if round_corners:
            c = ctypes.c_int(2)  # DWMWCP_ROUND
            dwmapi.DwmSetWindowAttribute(h, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(c), ctypes.sizeof(c))
        if True:
            # Solid title bar in Glint's own background colour. Without this Windows 11 uses its translucent
            # material, which picks up a tint from the wallpaper (purple, green... changing with it).
            from PySide6.QtGui import QColor
            bg = QColor(theme.BG if dark == theme.is_dark() else ("#141414" if dark else "#f6f6f7"))
            fg = QColor(theme.TEXT if dark == theme.is_dark() else ("#ececec" if dark else "#1c1c20"))
            for attr, q in ((DWMWA_CAPTION_COLOR, bg), (DWMWA_TEXT_COLOR, fg)):
                col = W.DWORD(q.red() | q.green() << 8 | q.blue() << 16)   # COLORREF = 0x00BBGGRR
                dwmapi.DwmSetWindowAttribute(h, attr, ctypes.byref(col), ctypes.sizeof(col))
    except Exception:
        pass


def hide_file(path):
    try:
        kernel32.SetFileAttributesW(str(path), 0x2)
    except Exception:
        pass


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    script = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{script}"'


def set_start_with_windows(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, "Glint", 0, winreg.REG_SZ, launch_command() + " --background")
        else:
            try:
                winreg.DeleteValue(k, "Glint")
            except FileNotFoundError:
                pass


def ensure_start_with_windows():
    """Point the Run entry at this copy of Glint (new installs start with Windows by default, and a
    moved or reinstalled copy keeps working). Only writes when the entry is missing or stale."""
    import winreg
    want = launch_command() + " --background"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if winreg.QueryValueEx(k, "Glint")[0] == want:
                return
    except OSError:
        pass
    set_start_with_windows(True)


user32.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
user32.MonitorFromWindow.restype = W.HMONITOR


def is_fullscreen(hwnd):
    """True for borderless/exclusive fullscreen windows (games, F11 apps): no caption + covers its monitor."""
    if not hwnd:
        return False
    try:
        style = user32.GetWindowLongPtrW(hwnd, -16)  # GWL_STYLE
        if style & 0x00C00000 == 0x00C00000:          # has a title bar -> normal window
            return False
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:
        return False


# Window classes used by game engines / game frameworks.
GAME_CLASSES = ("unitywndclass", "unrealwindow", "launchunrealue", "sdl_app", "glfw", "valve001", "cryengine",
                "frostbite", "riotwindowclass", "gamewindow", "d3d", "ogre", "godot", "minecraft", "lwjgl",
                "cocos", "raylib", "renpy", "pygame", "id tech", "bethesda")
# Launchers that start games: anything they spawn is treated as a game.
GAME_LAUNCHERS = {"steam.exe", "epicgameslauncher.exe", "riotclientservices.exe", "battle.net.exe", "ealauncher.exe",
                  "eadesktop.exe", "origin.exe", "upc.exe", "ubisoftconnect.exe", "galaxyclient.exe",
                  "gamingservices.exe", "xboxpcapp.exe", "rockstarlauncher.exe", "minecraftlauncher.exe",
                  "launcher.exe", "itch.exe", "heroiclauncher.exe", "playnite.desktopapp.exe"}
NOT_GAMES = {"steamwebhelper.exe", "steam.exe", "epicgameslauncher.exe", "riotclientux.exe",
             "riotclientservices.exe", "battle.net.exe", "eadesktop.exe", "galaxyclient.exe"}


def is_game(hwnd):
    """Best-effort: is this window a game, in ANY display mode (windowed, borderless, fullscreen)?
    Uses only window class, the process list and window geometry - never touches the game process."""
    if not hwnd:
        return False
    try:
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        c = cls.value.lower()
        if c in ("progman", "workerw", "shell_traywnd", "shell_secondarytraywnd"):
            return False  # the desktop / taskbar
        pid = W.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        table = process_table()
        exe, parent = table.get(pid.value, ("", 0))
        if exe.lower() in NOT_GAMES or exe.lower() == "explorer.exe":
            return False  # launchers' own UI, File Explorer
        if is_fullscreen(hwnd) or any(g in c for g in GAME_CLASSES):
            return True
        seen = 0
        while parent and seen < 4:  # walk up a few levels: launcher -> bootstrapper -> game
            pexe, parent = table.get(parent, ("", 0))
            if pexe.lower() in GAME_LAUNCHERS:
                return True
            seen += 1
    except Exception:
        pass
    return False


user32.SetWindowDisplayAffinity.argtypes = [W.HWND, W.DWORD]
user32.SetWindowDisplayAffinity.restype = W.BOOL


def exclude_from_capture(hwnd):
    """Keep one of Glint's own windows (control bar, outline, thumbnail) out of every screen capture
    - including Glint's own - while it stays visible on screen. Windows 10 2004+ (WDA_EXCLUDEFROMCAPTURE)."""
    try:
        return bool(user32.SetWindowDisplayAffinity(W.HWND(int(hwnd)), 0x11))
    except Exception:
        return False


# ---------------------------------------------------------------- desktop icons / window state
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.FindWindowW.restype = W.HWND
user32.FindWindowExW.argtypes = [W.HWND, W.HWND, W.LPCWSTR, W.LPCWSTR]
user32.FindWindowExW.restype = W.HWND
user32.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
user32.IsZoomed.argtypes = [W.HWND]


def _desktop_listview():
    """The desktop's icon view (lives under Progman, or under a WorkerW when a wallpaper engine is active)."""
    def view_in(top):
        dv = user32.FindWindowExW(top, None, "SHELLDLL_DefView", None)
        return user32.FindWindowExW(dv, None, "SysListView32", None) if dv else None
    lv = view_in(user32.FindWindowW("Progman", None))
    if lv:
        return lv
    w = None
    while True:
        w = user32.FindWindowExW(None, w, "WorkerW", None)
        if not w:
            return None
        lv = view_in(w)
        if lv:
            return lv


def hide_desktop_icons():
    """Hide the desktop icons; returns a function that brings them back (no-op if they were hidden)."""
    try:
        lv = _desktop_listview()
        if not lv or not user32.IsWindowVisible(lv):
            return lambda: None
        user32.ShowWindow(lv, 0)       # SW_HIDE

        def restore():
            try:
                user32.ShowWindow(lv, 5)   # SW_SHOW
            except Exception:
                pass
        return restore
    except Exception:
        return lambda: None


def is_maximized(hwnd):
    try:
        return bool(hwnd) and bool(user32.IsZoomed(W.HWND(int(hwnd))))
    except Exception:
        return False


def rounded_windows():
    """Windows 11 draws windows with rounded corners."""
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False
