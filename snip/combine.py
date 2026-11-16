"""Combine several captures into one image: side by side, stacked, or a grid."""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

BACKGROUNDS = {"transparent": None, "white": "#ffffff", "dark": "#161618"}


def combine(images, layout="row", gap=16, bg="transparent", radius=0):
    """images: list of QImage. layout: row | column | grid. Never upscales: pieces are scaled down to the
    smallest height (row), width (column) or cell (grid) so nothing gets blurry."""
    imgs = [i for i in images if i is not None and not i.isNull()]
    if not imgs:
        return QImage()
    if layout == "row":
        h = min(i.height() for i in imgs)
        sizes = [(i.width() * h / i.height(), h) for i in imgs]
        W = sum(w for w, _ in sizes) + gap * (len(imgs) + 1)
        H = h + 2 * gap
        x, rects = gap, []
        for w, hh in sizes:
            rects.append(QRectF(x, gap, w, hh))
            x += w + gap
    elif layout == "column":
        w = min(i.width() for i in imgs)
        sizes = [(w, i.height() * w / i.width()) for i in imgs]
        W = w + 2 * gap
        H = sum(h for _, h in sizes) + gap * (len(imgs) + 1)
        y, rects = gap, []
        for ww, h in sizes:
            rects.append(QRectF(gap, y, ww, h))
            y += h + gap
    else:
        n = len(imgs)
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        cw = min(i.width() for i in imgs)
        ch = min(i.height() for i in imgs)
        W = cols * cw + gap * (cols + 1)
        H = rows * ch + gap * (rows + 1)
        rects = []
        for k, i in enumerate(imgs):
            r, c = divmod(k, cols)
            s = min(cw / i.width(), ch / i.height())
            w, h = i.width() * s, i.height() * s
            cx = gap + c * (cw + gap) + (cw - w) / 2
            cy = gap + r * (ch + gap) + (ch - h) / 2
            rects.append(QRectF(cx, cy, w, h))
    out = QImage(max(1, round(W)), max(1, round(H)), QImage.Format_ARGB32_Premultiplied)
    col = BACKGROUNDS.get(bg)
    out.fill(QColor(col) if col else Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    for img, r in zip(imgs, rects):
        if radius:
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)
            p.save()
            p.setClipPath(path)
            p.drawImage(r, img)
            p.restore()
        else:
            p.drawImage(r, img)
    p.end()
    return out if col is None else out.convertToFormat(QImage.Format_RGB32)
