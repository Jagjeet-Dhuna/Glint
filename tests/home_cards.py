import os
import sys
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtTest import QTest
app = QApplication([])
from snip import theme, settings, home
theme.apply_theme(app)
A = type("A", (), {"settings": settings.Settings()})
H = type("H", (QWidget,), {"refresh": lambda self: None, "edit_folder": lambda *a: None})
h = H(); h.app = A()
win = QWidget(); lay = QVBoxLayout(win); lay.setContentsMargins(0, 0, 0, 0)
page = home.LibraryPage(h); lay.addWidget(page); win.show(); page.load()
for w in (960, 700, 1500, 480):
    win.resize(w, 760); QTest.qWait(150)
    body, vp = page.scroll.widget(), page.scroll.viewport()
    compact = not page.cards_box.buttons["full"].name.isVisible()
    print(("PASS" if body.width() <= vp.width() else "FAIL") + f" {w}px wide: page fits ({body.width()} <= {vp.width()})"
          + ("  [compact capture row]" if compact else ""))
    win.grab().save(OUT + f"/cards_{w}.png")
