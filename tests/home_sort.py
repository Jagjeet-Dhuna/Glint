import os
import sys
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
app = QApplication([])
from snip import theme, settings, home
class St(settings.Settings):
    def save(self): pass
class A:
    settings = St()
    def is_pinned(self, w): return False
    def __getattr__(self, n): return lambda *a, **k: None
theme.apply_theme(app, appearance="dark")
w = home.HomeWindow(A()); w.resize(1100, 760); w.show(); QTest.qWait(300)
lib = w.library
for k in home.SORTS:
    lib.set_sort(k); QTest.qWait(50)
    heads = [l.text() for l in lib.findChildren(QLabel, "group") if l.isVisible()]
    print(k, len(lib.tiles), "|", lib.sort_btn.text(), "|", heads[:6])
lib.set_sort("app"); QTest.qWait(100)
w.grab().save(OUT + "/sort_app.png")
