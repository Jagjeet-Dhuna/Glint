import os
import sys
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
os.makedirs(OUT, exist_ok=True)
import numpy as np, zxingcpp
from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QImage, QPainter, QColor, QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication([])
from snip import theme, settings, editor
theme.apply_theme(app)

class A:
    settings = settings.Settings()
    def is_pinned(self, w): return False
    def __getattr__(self, n): return lambda *a, **k: None

def make(text):
    try:
        arr = np.array(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.QRCode, text, width=220, height=220))
    except Exception:
        arr = np.array(zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6))
    arr = np.ascontiguousarray(arr.astype(np.uint8))
    q = QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0], QImage.Format_Grayscale8).copy()
    img = QImage(900, 560, QImage.Format_RGB32); img.fill(QColor("#2b2d31"))
    p = QPainter(img); p.fillRect(320, 150, q.width() + 40, q.height() + 40, Qt.white); p.drawImage(340, 170, q); p.end()
    return img

S = OUT
for name, text in (("link", "https://www.example.com/test-qr"), ("plain", "WIFI:S:Home;T:WPA;P:secret;;")):
    ed = editor.EditorWindow(A(), image=make(text)); ed.resize(1000, 700); ed.show()
    QTest.qWait(600)
    b = ed.code_bar
    print(name, "| visible:", b.isVisible(), "| open btn:", b.open_btn.isVisible(), "|", b.kind.text(), "|", b.text.text())
    app.sendEvent(b, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    print("   marks on hover:", len(ed.canvas.code_marks))
    QTest.qWait(50); ed.grab().save(f"{S}/codebar_{name}.png")
    app.sendEvent(b, QEvent(QEvent.Leave)); print("   marks after leave:", len(ed.canvas.code_marks))
    ed.dismiss_codes(); ed.canvas.update(); QTest.qWait(50)
    ed._scan_codes(); print("   stays dismissed:", not b.isVisible())
    ed.close()

ed = editor.EditorWindow(A(), image=QImage(800, 500, QImage.Format_RGB32)); ed.show(); QTest.qWait(500)
print("no code -> bar hidden:", not ed.code_bar.isVisible())
