"""QR code and barcode reading (zxing-cpp, fully offline)."""
from PySide6.QtGui import QImage


def _array(img):
    import numpy as np
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return buf[:, : w * 3].reshape(h, w, 3).copy()


def _name(fmt):
    n = getattr(fmt, "name", None) or str(fmt).split(".")[-1]
    return {"QRCode": "QR code", "MicroQRCode": "QR code", "DataMatrix": "Data Matrix"}.get(n, n)


def find(img):
    """[(text, kind, corners)] for every readable code; corners = 4 (x, y) image points. Never raises."""
    if img is None or img.isNull():
        return []
    try:
        import zxingcpp
        out, seen = [], set()
        for r in zxingcpp.read_barcodes(_array(img)):
            if getattr(r, "valid", True) and r.text and r.text not in seen:
                seen.add(r.text)
                try:
                    pos = r.position
                    corners = [(c.x, c.y) for c in (pos.top_left, pos.top_right, pos.bottom_right, pos.bottom_left)]
                except Exception:
                    corners = []
                out.append((r.text, _name(r.format), corners))
        return out
    except Exception:
        return []


def decode(img):
    """[(text, kind)] for every readable code in the image. Never raises."""
    return [(t, k) for t, k, _ in find(img)]


def is_link(text):
    t = text.strip().lower()
    return t.startswith(("http://", "https://")) and " " not in t
