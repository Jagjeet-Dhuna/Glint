import sys
import os; src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scroll_sim.py"), encoding="utf-8").read()
src = src[:src.index('acc, n, steps, sc = run("freeze"')]
g = {"__name__": "x", "__file__": os.path.join(os.path.dirname(os.path.abspath(__file__)), "scroll_sim.py")}
exec(compile(src, "t_freeze", "exec"), g)
import numpy as np
from PySide6.QtCore import QTimer
run, Sim, app, scroll = g["run"], g["Sim"], g["app"], g["scroll"]
fails = 0


def check(name, ok, extra=""):
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + name + ("  " + extra if extra else ""))


# 1. slower, longer smooth scrolling
Sim.TAU = 220.0                                   # ~0.9 s smooth scroll
acc, n, steps, _ = run("freeze", False)
check("slow smooth scrolling", n >= 4995 and acc > 0.99, f"{n} rows, {acc:.1%}, {steps} steps")
Sim.TAU = 60.0

# 2. scroll by window message: unknown pixels per notch (100 px per notch in this fake app)
def msg_scroll(sc, sim):
    def f(frac):
        px = sc.wheel_px or 100.0
        notches = max(1, int(abs(frac) * 700 / px))
        sc._notches = notches
        sim.scroll((1 if frac > 0 else -1) * notches * 100)
        return "msg"
    return f
orig_run = run
def run_msg():
    sim_holder = {}
    OrigSim = g["Sim"]
    class S2(OrigSim):
        def __init__(self, c):
            super().__init__(c); sim_holder["s"] = self
    g["Sim"] = S2
    orig_init = scroll.ScrollCapture._first
    def first(sc):
        orig_init(sc)
        sc._scroll_page = msg_scroll(sc, sim_holder["s"])
    scroll.ScrollCapture._first = first
    try:
        return orig_run("freeze", False)
    finally:
        scroll.ScrollCapture._first = orig_init
        g["Sim"] = OrigSim
acc, n, steps, sc = run_msg()
check("scroll messages (learns px per notch)", n >= 4995 and acc > 0.99, f"{n} rows, {acc:.1%}, {steps} steps, learned {sc.wheel_px} px/notch")

# 3. a huge video filling most of the view
g["VIDEOS"].append((3300, 10, 520, 580))
acc, n, steps, _ = run("freeze", False)
check("huge video (520 of 650 visible rows)", n >= 4995 and acc > 0.98, f"{n} rows, {acc:.1%}, {steps} steps")
g["VIDEOS"].pop()

# 4. undo
sim = Sim(False)
sc = scroll.ScrollCapture(scroll.QRect(0, 0, 600, 700), {}, mode="freeze", allow_auto=True)
sc._grab = sim.frame
sc._scroll_page = lambda frac: (sim.scroll(frac * 700), "uia")[1]
sc.step_timer.start = lambda ms: (g['CLOCK'].__setitem__('ms', g['CLOCK']['ms'] + ms), QTimer.singleShot(0, sc._tick))
scroll.ScrollCapture._first(sc)
def settle():
    for _ in range(3000):
        app.processEvents()
        if sc._gen is None:
            return
settle()
for _ in range(3):
    sc.request_step(); settle()
t3 = sc.total
sc.request_back(); settle()
t2 = sc.total
sc.request_step(); settle()
check("undo a step, then continue", t2 < t3 and sc.total == t3 and len(sc.undo) == 3, f"{t3} -> undo {t2} -> {sc.total}")
got = []
sc.finished.connect(lambda im, i: got.append(im)); sc.stop()
img = got[0]
a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :2400].reshape(img.height(), 600, 4)
acc, n = g["score"](a)
check("after undo the result is still exact", acc > 0.99, f"{acc:.1%}")

# 5. an app that ignores scroll requests -> falls back to Manual instead of hanging
sim = Sim(False)
sc = scroll.ScrollCapture(scroll.QRect(0, 0, 600, 700), {}, mode="freeze", allow_auto=True)
sc._grab = sim.frame
sc._scroll_page = lambda frac: "msg"           # request "sent" but nothing happens
sc.target = None
sc.step_timer.start = lambda ms: (g['CLOCK'].__setitem__('ms', g['CLOCK']['ms'] + ms), QTimer.singleShot(0, sc._tick))
scroll.ScrollCapture._first(sc); settle()
sc.request_step(); settle()
check("unscrollable app -> switches to Manual", sc.mode == "manual", sc.bar.hint.text())
sc.cancel()
print("ALL PASS" if not fails else f"{fails} FAILED")
