"""Custom shortcuts: parsing any key combination, and recording one in Settings (offline, no real hotkeys).

The app object is a stub, so nothing is registered with Windows; it counts suspend / register calls instead.
"""
import os
import sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
app = QApplication([])
from snip import theme, settings, home, winapi

bad = 0


def check(ok, msg):
    global bad
    print(("PASS " if ok else "FAIL ") + msg)
    bad += not ok


W = winapi
# ---------------------------------------------------------------- parsing
for name, spec in [("Print Screen", (0, 0x2C)), ("Ctrl+Print Screen", (W.MOD_CONTROL, 0x2C)),
                   ("Ctrl+Shift+X", (W.MOD_CONTROL | W.MOD_SHIFT, ord("X"))),
                   ("Ctrl+Alt+=", (W.MOD_CONTROL | W.MOD_ALT, 0xBB)),
                   ("Win+Shift+S", (W.MOD_WIN | W.MOD_SHIFT, ord("S"))),
                   ("Alt+F13", (W.MOD_ALT, 0x7C)), ("Ctrl+Num Plus", (W.MOD_CONTROL, 0x6B)),
                   ("ctrl+alt+=", (W.MOD_CONTROL | W.MOD_ALT, 0xBB))]:
    check(W.parse_hotkey(name) == spec, f"parse {name!r}")
for name in ("None", "", None, "Ctrl+Nope", "Hyper+A"):
    check(W.parse_hotkey(name) is None, f"parse {name!r} -> None")
check(W.hotkey_name(W.MOD_ALT | W.MOD_CONTROL, 0xBB) == "Ctrl+Alt+=", "name puts modifiers in order")
check(W.hotkey_name(0, 0xFF) is None, "unknown key has no name")
for name in ("Print Screen", "Ctrl+Alt+=", "F9", "Ctrl+Shift+X", "Ctrl+Num Plus", "Win+Shift+S", "Ctrl+Alt+Win+Shift+Home"):
    check(W.parse_hotkey(W.hotkey_name(*W.parse_hotkey(name))) == W.parse_hotkey(name), f"round trip {name}")
check(W.hotkey_problem("Ctrl+Alt+=") is None, "Ctrl+Alt+= is allowed")
check(W.hotkey_problem("F9") is None, "F9 alone is allowed")
check(W.hotkey_problem("A") is not None, "A alone is refused")
check(W.hotkey_problem("Shift+=") is not None, "Shift+= alone is refused (it types +)")

# ---------------------------------------------------------------- recording in Settings


class St(settings.Settings):
    def save(self): pass


class A:
    settings = St()
    calls = []
    def is_pinned(self, w): return False
    def unregister_hotkeys(self): self.calls.append("suspend")
    def register_hotkeys(self, show_errors=False): self.calls.append("register")
    def __getattr__(self, n): return lambda *a, **k: None


a = A()
theme.apply_theme(app, appearance="dark")
win = home.HomeWindow(a); win.resize(1100, 760); win.show(); QTest.qWait(200)
sp = home.SettingsPage(win); sp.resize(900, 1200); sp.show(); QTest.qWait(100)
prim, sec = sp.hk[0], sp.hk[1]
check(prim.text() == "Print Screen", "shows the saved shortcut")

QTest.mouseClick(prim, Qt.LeftButton); QTest.qWait(20)
check(prim.recording and a.calls[-1] == "suspend", "click starts recording and releases global hotkeys")
QTest.keyPress(prim, Qt.Key_Control, Qt.ControlModifier)
QTest.keyPress(prim, Qt.Key_Alt, Qt.ControlModifier | Qt.AltModifier)
check(prim.text() == "Ctrl+Alt+…", f"shows modifiers while held ({prim.text()!r})")
QTest.keyClick(prim, Qt.Key_Equal, Qt.ControlModifier | Qt.AltModifier); QTest.qWait(20)
check(not prim.recording, "a full combination ends recording")
check(a.settings.hotkey_primary == "Ctrl+Alt+=", f"saved Ctrl+Alt+= ({a.settings.hotkey_primary!r})")
check(a.calls[-1] == "register", "hotkeys registered again")

QTest.mouseClick(prim, Qt.LeftButton)
QTest.keyClick(prim, Qt.Key_A); QTest.qWait(20)
check(prim.recording and prim.text() == "Try another", "a plain letter is refused and keeps recording")
QTest.keyClick(prim, Qt.Key_Escape); QTest.qWait(20)
check(not prim.recording and a.settings.hotkey_primary == "Ctrl+Alt+=", "Esc cancels and keeps the old one")
check(a.calls[-1] == "register", "Esc gives the hotkeys back")

QTest.mouseClick(sec, Qt.LeftButton)
QTest.keyClick(sec, Qt.Key_Tab, Qt.ControlModifier | Qt.AltModifier); QTest.qWait(20)
check(a.settings.hotkey_secondary == "Ctrl+Alt+Tab", "Tab is recorded, not used to move focus")

QTest.mouseClick(sec, Qt.LeftButton)
QTest.keyClick(sec, Qt.Key_Equal, Qt.ControlModifier | Qt.AltModifier); QTest.qWait(20)
check(a.settings.hotkey_secondary == "Ctrl+Alt+=" and a.settings.hotkey_primary == "None",
      "taking another row's shortcut clears that row")
check(prim.text() == "Not set", "cleared row shows Not set")

QTest.mouseClick(sec, Qt.LeftButton)
QTest.keyClick(sec, Qt.Key_Backspace); QTest.qWait(20)
check(a.settings.hotkey_secondary == "None", "Backspace clears the shortcut")

QTest.mouseClick(prim, Qt.LeftButton)
QTest.keyClick(prim, Qt.Key_F9); QTest.qWait(20)
check(a.settings.hotkey_primary == "F9", "a function key alone is accepted")

sys.exit(1 if bad else 0)
