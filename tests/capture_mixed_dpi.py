import os
import sys
"""Mixed-scaling capture test with fake monitors (Qt offscreen platform). Nothing touches the real screen.

Physical layout (what Windows reports to a per-monitor-DPI-aware app):
  A  1920x1080 @ (0, 0)        100%
  B  2560x1440 @ (1920, -200)  150%
  C  1920x1200 @ (-1920, 0)    125%
Every pixel of the fake desktop encodes its own physical coordinate, so a capture's corner pixels
tell us exactly which physical pixels were captured.
"""
import json, os, sys, tempfile
MONS = {"A": (0, 0, 1920, 1080, 1.0), "B": (1920, -200, 2560, 1440, 1.5), "C": (-1920, 0, 1920, 1200, 1.25)}
cfg = {"screens": [{"name": n, "x": x, "y": y, "width": round(w / d), "height": round(h / d), "logicalDpi": 96,
                    "logicalBaseDpi": 96, "dpr": d} for n, (x, y, w, h, d) in MONS.items()]}
os.chdir(tempfile.gettempdir()); path = "glint_screens.json"
json.dump(cfg, open(path, "w"))
os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={path}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
app = QApplication([])
from snip import overlay

for s in QGuiApplication.screens():
    print(f"Qt screen {s.name()}: logical {s.geometry().getRect()} dpr {s.devicePixelRatio()}")

vx = min(m[0] for m in MONS.values()); vy = min(m[1] for m in MONS.values())
vw = max(m[0] + m[2] for m in MONS.values()) - vx; vh = max(m[1] + m[3] for m in MONS.values()) - vy
ys, xs = np.mgrid[0:vh, 0:vw]
gx, gy = xs + vx, ys + vy
idx = ys * vw + xs                                  # unique 24-bit index per physical pixel
arr = np.zeros((vh, vw, 4), np.uint8)
arr[..., 0] = idx & 255; arr[..., 1] = (idx >> 8) & 255; arr[..., 2] = (idx >> 16) & 255; arr[..., 3] = 255
FULL = QImage(arr.data, vw, vh, vw * 4, QImage.Format_RGB32).copy()

def decode(img, x, y):
    i = img.pixel(x, y) & 0xFFFFFF
    return i % vw + vx, i // vw + vy

class FakeSession(overlay.CaptureSession):
    def __init__(self):
        super(overlay.CaptureSession, self).__init__()
        self.mode = "region"; self.full, self.vx, self.vy = FULL, vx, vy
        self.windows = []
        self.monitors = {n: QRect(x, y, w, h) for n, (x, y, w, h, _) in MONS.items()}
        self.overlays = []; self._done = False

fails = 0
screens = {s.name(): s for s in QGuiApplication.screens()}
for name, (mx, my, mw, mh, d) in MONS.items():
    sess = FakeSession()
    native = sess.native_rect_for(screens[name])
    ok_match = native == QRect(mx, my, mw, mh)
    if native is None:
        native = QRect(mx, my, mw, mh)
    ov = overlay.Overlay(sess, screens[name], native)
    got = []
    sess.finished.connect(lambda img, info: got.append(img))
    # drag in logical widget coords: from 10% to 60% of the screen
    lw, lh = ov.width(), ov.height()
    p1, p2 = QPoint(int(lw * 0.1), int(lh * 0.1)), QPoint(int(lw * 0.6), int(lh * 0.6))
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, p1)
    QTest.mouseMove(ov, (p1 + p2) / 2); QTest.mouseMove(ov, p2)
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, p2)
    img = got[0] if got else None
    exp_tl = (mx + int(p1.x() * d), my + int(p1.y() * d))
    exp_br = (mx + int(p2.x() * d), my + int(p2.y() * d))
    tl = decode(img, 0, 0) if img else None
    br = decode(img, img.width() - 1, img.height() - 1) if img else None
    ok = ok_match and tl == exp_tl and br == exp_br and abs(ov.dpr - d) < 1e-6
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} screen {name} ({int(d*100)}%): matched monitor={ok_match} overlay dpr={ov.dpr:.3f} "
          f"captured {tl}..{br} expected {exp_tl}..{exp_br} size {img.width() if img else 0}x{img.height() if img else 0}")
    # full-screen key on this monitor
    sess2 = FakeSession(); ov2 = overlay.Overlay(sess2, screens[name], QRect(mx, my, mw, mh)); g2 = []
    sess2.finished.connect(lambda img, info: g2.append(img))
    QTest.keyClick(ov2, Qt.Key_F)
    if g2:
        im = g2[0]
        okf = decode(im, 0, 0) == (mx, my) and (im.width(), im.height()) == (mw, mh)
        fails += not okf
        print(f"{'PASS' if okf else 'FAIL'}   F (this monitor): {im.width()}x{im.height()} from {decode(im, 0, 0)}")
    ov.close(); ov2.close()
print("ALL PASS" if not fails else f"{fails} FAILED")
