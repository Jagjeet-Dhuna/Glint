import os
import sys
import os, sys, json, tempfile
os.chdir(tempfile.gettempdir())
json.dump({"screens": [{"name": "A", "x": 0, "y": 0, "width": 1707, "height": 960, "logicalDpi": 96,
                        "logicalBaseDpi": 96, "dpr": 1.5}]}, open("glint_one.json", "w"))
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=glint_one.json"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication, QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
app = QApplication([])
from snip import overlay, winapi
FULL = QImage(2560, 1440, QImage.Format_RGB32); FULL.fill(QColor("#3366aa"))
WIN = {"hwnd": 0, "rect": (400, 300, 1400, 1000), "title": "Notepad", "app": "Notepad", "cls": "x"}
class FS(overlay.CaptureSession):
    def __init__(self, style="clean", last=None):
        super(overlay.CaptureSession, self).__init__()
        self.mode = "region"; self.full, self.vx, self.vy = FULL, 0, 0
        self.windows = [WIN]; self.monitors = {"A": QRect(0, 0, 2560, 1440)}
        self.overlays = []; self._done = False
        self.last_region = QRect(*last) if last else None; self.window_style = style
scr = QGuiApplication.screens()[0]
def run(style, action):
    s = FS(style, last=[100, 100, 300, 200]); ov = overlay.Overlay(s, scr, QRect(0, 0, 2560, 1440)); s.overlays = [ov]
    got = []; s.finished.connect(lambda im, inf: got.append((im, inf)))
    ov.show(); action(ov); return got, ov
def ok(n, c): print(("PASS " if c else "FAIL ") + n)
# window click, each style
for style in ("plain", "clean", "shadow"):
    got, ov = run(style, lambda ov: (QTest.mouseMove(ov, QPoint(600, 400)), QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(600, 400))))
    im, inf = got[0]
    corner = QColor.fromRgba(im.pixel(0, 0)).alpha() if im.hasAlphaChannel() else 255
    print(f"  {style}: size {im.width()}x{im.height()} corner alpha {corner} info keys {sorted(inf)}")
    if style == "plain": ok("plain keeps rectangle", (im.width(), corner) == (1000, 255))
    if style == "clean": ok("clean: transparent corner, same size", im.width() == 1000 and corner == 0 and QColor.fromRgba(im.pixel(500, 350)).alpha() == 255)
    if style == "shadow": ok("shadow: padded with soft shadow", im.width() > 1000 and corner == 0)
    ok(f"{style}: no internal keys leak", "window" not in inf and "dpr" not in inf)
# R = last area
got, ov = run("clean", lambda ov: QTest.keyClick(ov, Qt.Key_R))
ok("R captures last area 300x200", got and got[0][0].size().toTuple() == (300, 200))
# M = measure: dragging must NOT capture
def measure(ov):
    QTest.keyClick(ov, Qt.Key_M)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
    QTest.mouseMove(ov, QPoint(200, 150)); QTest.mouseMove(ov, QPoint(300, 200))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(300, 200))
got, ov = run("clean", measure)
ok(f"M measure: no capture, ruler kept {ov.ruler}", not got and ov.ruler is not None)
ov.grab().save(OUT + "/ruler.png")
QTest.keyClick(ov, Qt.Key_M)
ok("M again returns to capture mode", not ov.measuring)
print("desktop icon view found:", bool(winapi._desktop_listview()), "| Win11 rounded:", winapi.rounded_windows())
