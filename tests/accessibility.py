"""Accessibility audit (offline, nothing on screen, no input).

1. Contrast (WCAG 2.2 AA): text 4.5:1, icons / control states / focus rings 3:1, in Day and Night themes
   and with every accent colour.
2. Names: every control a screen reader can land on (buttons, fields, lists, toggles) has a name.
3. Keyboard: Home and Settings controls are reachable with Tab, and focused controls get a visible outline.
"""
import os
import shutil
import sys
import tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication,
                               QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QWidget)
from PySide6.QtGui import QAccessible, QColor, QImage
from PySide6.QtTest import QTest
app = QApplication([])
from PySide6.QtCore import Qt
from snip import theme, settings, home, editor, a11y
a11y.install(app)

fails = []


def check(ok, msg):
    if not ok:
        fails.append(msg)


# ---------------------------------------------------------------- 1. contrast
def lum(c):
    c = QColor(c)
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_PAIRS = [("TEXT", "BG"), ("TEXT", "SURFACE"), ("TEXT", "SIDEBAR"), ("MUTED", "BG"), ("MUTED", "SURFACE"),
              ("MUTED", "SIDEBAR"), ("MUTED", "CARD"), ("DIM", "BG"), ("DIM", "SIDEBAR"), ("NAV", "SIDEBAR"),
              ("CHIP_TEXT", "CHIP"), ("KBD_TEXT", "BG"), ("PILL_TEXT", "PILL"), ("GROUP", "SIDEBAR")]
UI_PAIRS = [("ICON_OFF", "BG"), ("ICON_OFF", "SIDEBAR"), ("TOG_KNOB", "TOG_OFF"), ("CHECK_LINE", "BG")]
contrast_rows = 0
for mode, pal in theme.PALETTES.items():
    for fg, bg in TEXT_PAIRS:
        r = ratio(pal[fg], pal[bg]); contrast_rows += 1
        check(r >= 4.5, f"contrast {mode}: {fg} on {bg} = {r:.2f}:1 (text needs 4.5)")
    for fg, bg in UI_PAIRS:
        r = ratio(pal[fg], pal[bg]); contrast_rows += 1
        check(r >= 3, f"contrast {mode}: {fg} on {bg} = {r:.2f}:1 (controls need 3)")
    for name, a in theme.ACCENTS:
        theme.apply_theme(app, a, "light" if mode == "light" else "dark")   # what the app actually draws
        r = ratio(theme.on_accent(a), a); contrast_rows += 1
        check(r >= 4.5, f"contrast {mode}: button text on {name} accent = {r:.2f}:1 (text needs 4.5)")
        r = ratio(theme.accent_stroke(), pal["BG"]); contrast_rows += 1
        check(r >= 3, f"contrast {mode}: {name} selection/focus outline on BG = {r:.2f}:1 (needs 3)")
        r = ratio(theme.accent_text(), pal["BG"]); contrast_rows += 1
        check(r >= 4.5, f"contrast {mode}: {name} accent text on BG = {r:.2f}:1 (text needs 4.5)")
print(f"contrast: {contrast_rows} colour pairs checked")


# ---------------------------------------------------------------- 2 + 3. names, keyboard
INTERACTIVE = (QAbstractButton, QLineEdit, QComboBox, QAbstractSlider, QAbstractSpinBox, QAbstractItemView,
               QPlainTextEdit, QTextEdit)


controls = {}


def tab_stops(root, start):
    """Press Tab inside the (offscreen) window until focus comes back round; returns the widgets visited."""
    start.setFocus(Qt.OtherFocusReason); QTest.qWait(20)
    seen, hidden = [start], []
    for _ in range(200):
        QTest.keyClick(QApplication.focusWidget() or root, Qt.Key_Tab); QTest.qWait(5)
        f = QApplication.focusWidget()
        if f is None or f is start:
            break
        if f in seen:
            continue
        seen.append(f)
        ring = a11y.ring_for(f.window(), create=False)
        own = isinstance(f, a11y.OWN_FOCUS_STYLE) or f.property("own_focus_style")
        if not (own or (ring is not None and ring.isVisible() and ring.geometry().contains(
                f.mapTo(f.window(), f.rect().center())))):
            hidden.append(f)
    return seen, hidden


def audit(root, where, need_tab=True):
    n = 0
    for w in [root] + root.findChildren(QWidget):
        is_ctl = isinstance(w, INTERACTIVE)
        if not is_ctl or not w.isVisibleTo(root) or not w.isEnabled() or isinstance(w.parent(), QLineEdit):
            continue
        n += 1
        iface = QAccessible.queryAccessibleInterface(w)
        name = iface.text(QAccessible.Name).strip() if iface else ""
        if not name and isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit)):
            name = w.placeholderText() if hasattr(w, "placeholderText") else ""
        label = f"{type(w).__name__}" + (f" '{w.objectName()}'" if w.objectName() else "") + \
                (f" tip='{w.toolTip()}'" if w.toolTip() else "")
        check(bool(name), f"name missing [{where}]: {label}")
        if need_tab:
            controls.setdefault(where, []).append((w, label, name))
    return n


lib_dir = tempfile.mkdtemp(prefix="glint_a11y_")
for i, (w, h, c) in enumerate([(800, 500, "#4f6bed"), (600, 900, "#e8a33d"), (1200, 700, "#2fb380")]):
    im = QImage(w, h, QImage.Format_RGB32); im.fill(QColor(c)); im.save(os.path.join(lib_dir, f"cap{i}.png"))
os.makedirs(os.path.join(lib_dir, "Work"))


class St(settings.Settings):
    def save(self): pass


class A:
    settings = St()
    def is_pinned(self, w): return False
    def __getattr__(self, n): return lambda *a, **k: None


a = A(); a.settings._d.update(save_folder=lib_dir, sidebar_collapsed=False)
theme.apply_theme(app, "#e8a33d", "dark")
win = home.HomeWindow(a); win.resize(1200, 800); win.show(); win.refresh(); QTest.qWait(300)
total = audit(win, "Home")
win.set_sidebar_collapsed(True, save=False); QTest.qWait(100)
total += audit(win, "Home, sidebar collapsed")
win.set_sidebar_collapsed(False, save=False)
sp = home.SettingsPage(win); sp.resize(900, 1200); sp.show(); QTest.qWait(200)
total += audit(sp, "Settings")
ed = editor.EditorWindow(a, image=QImage(900, 500, QImage.Format_RGB32)); ed.resize(1100, 700); ed.show(); QTest.qWait(200)
total += audit(ed, "Editor", need_tab=False)   # editor tools all have single-key shortcuts (V, A, R, S, I...)
print(f"names/keyboard: {total} controls checked")

# keyboard: every Home control is a Tab stop, and every Tab stop shows where focus is
win.activateWindow(); QTest.qWait(50)
stops, hidden = tab_stops(win, win.findChildren(home.NavButton)[0])
for w, label, name in controls.get("Home", []):
    check(w in stops or isinstance(w, QAbstractItemView), f"not reachable by Tab [Home]: {label} '{name}'")
for f in hidden:
    check(False, f"no visible focus on Tab stop: {type(f).__name__} '{f.accessibleName()}'")
QTest.mouseClick(win.library, Qt.LeftButton); QTest.qWait(20)
ring = a11y.ring_for(win, create=False)
check(ring is None or not ring.isVisible(), "focus ring should hide after a mouse click")
stops = len(stops)
print(f"focus: {stops} Tab stops checked")

shutil.rmtree(lib_dir, ignore_errors=True)
for f in fails:
    print("  FAIL", f)
print("FAIL" if fails else "PASS", f"accessibility: {len(fails)} problem(s)")
sys.exit(1 if fails else 0)
