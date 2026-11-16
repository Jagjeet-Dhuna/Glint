import os
import sys
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
app = QApplication([])
from snip import theme, settings, editor, render
theme.apply_theme(app, appearance="dark")
class A:
    settings = type("S", (settings.Settings,), {"save": lambda self: None})()
    def is_pinned(self, w): return False
    def __getattr__(self, n): return lambda *a, **k: None
img = QImage(900, 520, QImage.Format_RGB32); img.fill(QColor("#e9ecf1"))
ed = editor.EditorWindow(A(), image=img); ed.resize(1000, 640); ed.show(); QTest.qWait(200)
c = ed.canvas
for i, lab in enumerate(["✅", "❌", "⚠️", "🔥", "👀"]):
    c.insert_stamp(lab, QPointF(80 + i * 90, 80))
for i, lab in enumerate(["NEW", "BUG", "FIX", "TODO", "BEFORE"]):
    c.insert_stamp(lab, QPointF(100 + i * 150, 200))
# text box vs callout
s = c.new_shape("text", QPointF(120, 330)); s.update(pts=[[120, 330]], text="Text box, no tail", bubble="box", color="#ffd60a"); c.shapes.append(s)
s = c.new_shape("text", QPointF(520, 330)); s.update(pts=[[520, 330]], text="Callout bubble", bubble=True, color="#0a84ff"); c.shapes.append(s)
c.commit(); c.set_sel(None); QTest.qWait(100)
print("shapes:", [x["kind"] for x in c.shapes][:3], "... total", len(c.shapes))
print("box handles:", render.handles(c.shapes[-2]), "| callout handles:", len(render.handles(c.shapes[-1])))
render.render(c.base, c.shapes).save(OUT + "/stamps.png")
# menus build
from PySide6.QtWidgets import QMenu
m = QMenu(); c._stamp_menu(m, lambda l: None); print("stamp menu items:", len(m.actions()), "symbols:", len(m.actions()[0].menu().actions()))
