"""Scrolling-capture simulator (offline: no real windows are scrolled, no input is sent).

A fake web page: 5000 px of varied content under a 50 px sticky header, two videos that change every
frame, and a hover-preview thumbnail that animates whenever the mouse is over it. Scrolling is smooth
(eases in over several frames). Compares the stitched result with the true page."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
from snip import scroll

W, VH, HEAD, PAGE_H = 600, 700, 50, 5000
rng = np.random.default_rng(7)
page = np.full((PAGE_H, W, 4), 245, np.uint8); page[..., 3] = 255
y = 20
while y < PAGE_H - 40:                                  # "text lines" and "images"
    if rng.random() < 0.15:
        h = int(rng.integers(80, 200)); x0 = int(rng.integers(20, 300))
        page[y:y + h, x0:x0 + int(rng.integers(120, 260))] = rng.integers(40, 220, 3).tolist() + [255]
        y += h + 16
    else:
        x = 20
        while x < W - 60:
            wd = int(rng.integers(20, 90)); page[y:y + 14, x:x + wd, :3] = int(rng.integers(20, 90)); x += wd + 8
        y += 26
VIDEOS = [(1200, 60, 300, 420), (2600, 150, 260, 380)]     # (y, x, h, w) - play constantly
HOVER = (820, 300, 180, 260)                               # thumbnail preview that plays when hovered
header = np.zeros((HEAD, W, 4), np.uint8); header[..., :3] = (30, 60, 110); header[..., 3] = 255
header[15:35, 20:200, :3] = 230


CLOCK = {"ms": 0.0}      # simulated time: advanced by Glint's waits and by each screen grab
GRAB_MS = 26             # measured: one grab + analysis on a 5120x1440 desktop


class Sim:
    TAU = 60.0           # smooth scrolling time constant (ms): ~250 ms to finish, like a browser

    def __init__(self, cursor_on_page):
        self.off, self.target, self.t = 0.0, 0.0, 0
        self.cursor_on_page = cursor_on_page
        self.max_off = PAGE_H - (VH - HEAD)
        self.seen = CLOCK["ms"]

    def frame(self):
        self.t += 1
        CLOCK["ms"] += GRAB_MS
        dt = CLOCK["ms"] - self.seen
        self.seen = CLOCK["ms"]
        self.off += (self.target - self.off) * (1 - np.exp(-dt / self.TAU))     # smooth scrolling
        if abs(self.target - self.off) < 1:
            self.off = self.target
        o = int(round(self.off))
        fr = np.empty((VH, W, 4), np.uint8)
        fr[:HEAD] = header
        fr[HEAD:] = page[o:o + VH - HEAD]
        cy = o + (VH - HEAD) // 2                          # page row under the mouse (centre of view)
        for (vy, vx, vh, vw), live in [(v, True) for v in VIDEOS] + [(HOVER, None)]:
            if live is None:
                live = self.cursor_on_page and vy <= cy < vy + vh
            if not live:
                continue
            a, b = max(vy, o), min(vy + vh, o + VH - HEAD)
            if a < b:
                noise = np.random.default_rng(self.t * 31 + vy).integers(0, 255, (b - a, vw, 3), np.uint8)
                fr[HEAD + a - o:HEAD + b - o, vx:vx + vw, :3] = noise
                fr[HEAD + a - o:HEAD + b - o, vx:vx + vw, 3] = 255
        return fr

    def scroll(self, px):
        self.target = float(np.clip(self.target + px, 0, self.max_off))


def score(img_arr):
    """Share of stitched rows that exactly match the true page (rows crossing a video are skipped)."""
    body = img_arr[HEAD:]
    n = min(len(body), PAGE_H)
    vid = np.zeros(PAGE_H, bool)
    for vy, vx, vh, vw in VIDEOS + [HOVER]:
        vid[max(0, vy - 2):vy + vh + 2] = True
    rows = [i for i in range(n) if not vid[i]]
    good = sum(np.array_equal(body[i, :, :3], page[i, :, :3]) for i in rows)
    return good / max(1, len(rows)), n


def run(mode, cursor_on_page, user_speed=None):
    sim = Sim(cursor_on_page)
    sc = scroll.ScrollCapture(QRect(0, 0, W, VH), {}, mode=mode, allow_auto=True)
    sc._grab = sim.frame
    if mode == "freeze":
        sc._scroll_page = lambda frac: (sim.scroll(frac * VH), "uia")[1]
    def wait(ms):
        CLOCK["ms"] += ms
        QTimer.singleShot(0, sc._tick)
    sc.step_timer.start = wait
    got = []
    sc.finished.connect(lambda img, info: got.append(img))
    sc.src = None
    sc._first.__func__  # noqa
    sc._first = sc._first  # (start() would show windows; call the parts directly)
    sc_first = scroll.ScrollCapture._first
    sc.src_backup = None
    # _first creates a UIA source from the real screen - avoid touching real windows
    import snip.uia as uia
    uia.ScrollSource.at = classmethod(lambda cls, x, y: None)
    sc_first(sc)
    if mode == "freeze":
        for _ in range(400):                       # wait for the first keyframe
            app.processEvents()
            if sc._gen is None and sc.kf is not None:
                break
        t0 = CLOCK["ms"]
        sc.choose("auto")                          # Auto: step to the end by itself
        for _ in range(20000):
            app.processEvents()
            if not sc.auto_steps and sc._gen is None:
                break
        steps = len(sc.undo)
        run.ms_per_step = (CLOCK["ms"] - t0) / max(1, steps)
    else:
        sc.manual_timer.stop()
        lost_ticks = 0
        for i in range(1500):                      # the user scrolls the live page with the wheel
            if i % 6 == 0:
                sim.scroll(user_speed)
            CLOCK["ms"] += 40
            sc._manual_tick()
            lost_ticks += sc.lost
            if sim.off >= sim.max_off and sim.target >= sim.max_off and i > 50 and i % 6 == 5:
                break
        steps = lost_ticks
    sc.stop()
    img = got[0]
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :W * 4].reshape(img.height(), W, 4)
    acc, n = score(a)
    return acc, n, steps, sc


acc, n, steps, sc = run("freeze", cursor_on_page=False)
print(f"FROZEN (new):  {n} of {PAGE_H} page rows captured, {acc:.1%} of rows exact, {steps} steps, "
      f"~{run.ms_per_step:.0f} ms per step")
acc2, n2, lost, _ = run("manual", cursor_on_page=True, user_speed=160)
print(f"MANUAL (old, mouse on page, videos + hover preview): {n2} of {PAGE_H} rows, {acc2:.1%} exact, lost-track checks: {lost}")
ok = n >= PAGE_H - 5 and acc > 0.99
print("PASS" if ok else "FAIL")
