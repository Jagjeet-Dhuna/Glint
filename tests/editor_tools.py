import os
import sys
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtCore import QPointF, QPoint, Qt
from PySide6.QtTest import QTest
app = QApplication([])
from snip import theme, settings, editor, render
theme.apply_theme(app, appearance="dark")
class A:
    settings = type("S", (settings.Settings,), {"save": lambda self: None})()
    def is_pinned(self, w): return False
    def __getattr__(self, n): return lambda *a, **k: None
img = QImage(800, 500, QImage.Format_RGB32); img.fill(QColor("#e9ecf1"))
p = QPainter(img); p.fillRect(100, 100, 120, 80, QColor("#12a4d9")); p.end()
ed = editor.EditorWindow(A(), image=img); ed.resize(1000, 700); ed.show(); QTest.qWait(300)
c = ed.canvas
def ok(n, v): print(("PASS " if v else "FAIL ") + n)
def wpt(x, y):  # image -> widget point
    s = c.scale(); return QPoint(int(x * s), int(y * s)) if not c.frame else None
c.zoom = 1.0; c.update_size(); QTest.qWait(100)
# stamp tool: place
ed._stamp_chosen = True; ed.set_tool("stamp"); ed.choose_stamp("BUG")
QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, wpt(400, 300))
st = c.shapes[-1]; ok("stamp tool places BUG", st["kind"] == "stamp" and st["text"] == "BUG")
r0 = render.norm_rect(st)
# move it with the select tool
ed.set_tool("select"); ctr = r0.center()
QTest.mousePress(c, Qt.LeftButton, Qt.NoModifier, wpt(ctr.x(), ctr.y()))
QTest.mouseMove(c, wpt(ctr.x() + 60, ctr.y() + 40)); QTest.mouseRelease(c, Qt.LeftButton, Qt.NoModifier, wpt(ctr.x() + 60, ctr.y() + 40))
r1 = render.norm_rect(c.shapes[-1]); ok(f"stamp moves ({r0.x():.0f},{r0.y():.0f}) -> ({r1.x():.0f},{r1.y():.0f})", abs(r1.x() - r0.x() - 60) < 8 and abs(r1.y() - r0.y() - 40) < 8)
# resize via bottom-right handle, aspect kept
br = r1.bottomRight(); ar = r1.width() / r1.height()
QTest.mousePress(c, Qt.LeftButton, Qt.NoModifier, wpt(br.x(), br.y()))
QTest.mouseMove(c, wpt(br.x() + 80, br.y() + 10)); QTest.mouseRelease(c, Qt.LeftButton, Qt.NoModifier, wpt(br.x() + 80, br.y() + 10))
r2 = render.norm_rect(c.shapes[-1]); ok(f"stamp resizes, keeps shape {r1.width():.0f}x{r1.height():.0f} -> {r2.width():.0f}x{r2.height():.0f}", r2.width() > r1.width() + 40 and abs(r2.width() / r2.height() - ar) < 0.05)
# with the arrow tool, clicking a stamp moves it (doesn't draw)
ed.set_tool("arrow"); n = len(c.shapes); ctr = r2.center()
QTest.mousePress(c, Qt.LeftButton, Qt.NoModifier, wpt(ctr.x(), ctr.y())); QTest.mouseMove(c, wpt(ctr.x() + 20, ctr.y()))
QTest.mouseRelease(c, Qt.LeftButton, Qt.NoModifier, wpt(ctr.x() + 20, ctr.y()))
ok("arrow tool drags stamp instead of drawing", len(c.shapes) == n)
# picker
ed.set_tool("arrow"); ed.set_tool("picker")
QTest.mouseMove(c, wpt(150, 130)); QTest.qWait(30); ed.grab().save(OUT + "/picker.png")
QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, wpt(150, 130))
ok(f"picker sets colour + copies ({QApplication.clipboard().text()}), back to arrow ({c.tool})", ed._color.lower() == "#12a4d9" and QApplication.clipboard().text() == "#12A4D9" and c.tool == "arrow")
ed.set_tool("picker"); QTest.mouseClick(c, Qt.LeftButton, Qt.ShiftModifier, wpt(150, 130))
ok("shift+click copies rgb()", QApplication.clipboard().text() == "rgb(18, 164, 217)")
# measure
ed.set_tool("measure"); QTest.mousePress(c, Qt.LeftButton, Qt.NoModifier, wpt(100, 400))
QTest.mouseMove(c, wpt(400, 400)); QTest.mouseRelease(c, Qt.LeftButton, Qt.NoModifier, wpt(400, 400))
ok(f"measure 300px copied ({QApplication.clipboard().text()})", QApplication.clipboard().text() == "300" and len(c.shapes) == n)
ed.grab().save(OUT + "/measure.png")
QTest.keyClick(c, Qt.Key_Escape); ok("Esc ends measure", c.measure is None and c.tool != "measure")
# hex entry
ed.popup.hex.setText("ff00aa"); ed.popup._hex_entered(); ok("hex entry", ed._color.lower() == "#ff00aa")
# copy as data uri
ed.copy_as("datauri"); t = QApplication.clipboard().text(); ok("data URI", t.startswith("data:image/png;base64,iVBOR"))
# resize 50%
ed.resize_image = lambda: None
w0 = c.base.width(); sw0 = c.shapes[-1]["pts"]; c.scale_image(0.5)
ok(f"resize 50% -> {c.base.width()}x{c.base.height()}", c.base.width() == w0 // 2)
# pixel grid at 12x
c.set_zoom(12.0); QTest.qWait(100); ed.grab().save(OUT + "/pixgrid.png")
# stamp popup builds
pop = editor.StampPopup(ed, ed.tool_buttons["stamp"]); pop.show(); QTest.qWait(50); pop.grab().save(OUT + "/stamp_popup.png"); pop.close()
ok("toolbar has stamp + picker", "stamp" in ed.tool_buttons and "picker" in ed.tool_buttons)
