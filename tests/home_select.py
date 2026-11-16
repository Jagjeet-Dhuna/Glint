import os
import sys
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # no visible window; events are Qt-internal only
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
app = QApplication([])
from snip import theme, settings, home
theme.apply_theme(app)

A = type("A", (), {"settings": settings.Settings()})
H = type("H", (QWidget,), {"refresh": lambda self: None, "edit_folder": lambda *a: None})
h = H(); h.app = A()
win = QWidget(); lay = QVBoxLayout(win); lay.setContentsMargins(0, 0, 0, 0)
page = home.LibraryPage(h); lay.addWidget(page)
win.resize(1100, 800); win.show()
page.load()
for _ in range(30): app.processEvents()
QTest.qWait(200)
tiles = list(page.tiles.values()); paths = list(page.tiles)
print("tiles:", len(tiles))
body = page.scroll.widget()

def ok(name, cond): print(("PASS " if cond else "FAIL ") + name)

# 1. rubber band from empty space (left gutter beside first tiles) across the first row
t0, t2 = tiles[0], tiles[2]
p0 = t0.mapTo(body, QPoint(0, 0))
start = QPoint(8, p0.y() - 6)
end = t2.mapTo(body, QPoint(30, 30))
QTest.mousePress(body, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(body, (start + end) / 2); QTest.mouseMove(body, end)
band_vis = body.band.isVisible()
QTest.mouseRelease(body, Qt.LeftButton, Qt.NoModifier, end)
ok(f"box select first 3 (got {len(page.selected)}, band shown {band_vis})", page.selected == set(paths[:3]) and band_vis)
win.grab().save(OUT + "/sel_box.png") if len(sys.argv) > 1 else None

# 2. click on empty space clears
QTest.mouseClick(body, Qt.LeftButton, Qt.NoModifier, QPoint(8, p0.y() + 40))
ok("empty click clears", not page.selected)

# 3. click tile, shift+click range
QTest.mouseClick(tiles[1], Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
QTest.mouseClick(tiles[5], Qt.LeftButton, Qt.ShiftModifier, QPoint(40, 40))
ok("shift-click range 1..5", page.selected == set(paths[1:6]))
QTest.mouseClick(tiles[3], Qt.LeftButton, Qt.ControlModifier, QPoint(40, 40))
ok("ctrl-click toggles off", paths[3] not in page.selected and len(page.selected) == 4)

# 4. keyboard
tiles[0].setFocus(Qt.OtherFocusReason); page.select(tiles[0])
QTest.keyClick(tiles[0], Qt.Key_Right)
ok("Right moves+selects", page.selected == {paths[1]} and tiles[1].hasFocus())
QTest.keyClick(tiles[1], Qt.Key_Tab)
ok("Tab moves+selects", page.selected == {paths[2]} and tiles[2].hasFocus())
QTest.keyClick(tiles[2], Qt.Key_Backtab)
ok("Shift+Tab back", page.selected == {paths[1]} and tiles[1].hasFocus())
QTest.keyClick(tiles[1], Qt.Key_Right, Qt.ShiftModifier); QTest.keyClick(tiles[2], Qt.Key_Right, Qt.ShiftModifier)
ok("Shift+Right extends", page.selected == set(paths[1:4]))
QTest.keyClick(tiles[3], Qt.Key_Down)
f = next(t for t in tiles if t.hasFocus())
ok(f"Down goes to next row (now idx {tiles.index(f)})",
   f.mapTo(body, QPoint()).y() > tiles[3].mapTo(body, QPoint()).y() and page.selected == {f.rec['path']})
QTest.keyClick(f, Qt.Key_Up)
up = next(t for t in tiles if t.hasFocus())
fx, ux = f.mapTo(body, QPoint()).x(), up.mapTo(body, QPoint()).x()
ok("Up goes to the tile directly above", up.mapTo(body, QPoint()).y() < f.mapTo(body, QPoint()).y() and ux == fx)
# rows must never overlap (a group with 2+ rows used to be cut to one row)
ys = sorted({t.mapTo(body, QPoint()).y() for t in tiles})
ok("rows don't overlap", all(b - a >= tiles[0].height() for a, b in zip(ys, ys[1:])))
tiles[3].setFocus(Qt.OtherFocusReason); page.select(tiles[3])
QTest.keyClick(tiles[3], Qt.Key_Right, Qt.ControlModifier); QTest.keyClick(tiles[4], Qt.Key_Space)
ok("Ctrl+Right then Space adds", page.selected == {paths[3], paths[4]})
QTest.keyClick(tiles[4], Qt.Key_A, Qt.ControlModifier)
ok("Ctrl+A all", len(page.selected) == len(tiles))
QTest.keyClick(tiles[4], Qt.Key_Escape)
ok("Esc clears", not page.selected)
QTest.keyClick(tiles[4], Qt.Key_End)
ok("End", tiles[-1].hasFocus() and page.selected == {paths[-1]})
ok("kbd focus ring property", tiles[-1].property("kbd") is True)
win.grab().save(OUT + "/sel_kbd.png") if len(sys.argv) > 1 else None
