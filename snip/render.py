"""Annotation shapes: plain dicts (easy to undo/serialize) + drawing and hit-testing.

shape = {"kind": str, "pts": [[x, y], ...], "color": "#rrggbb", "width": float,
         "fill": bool, "shadow": bool, "text": str, "font": int, "number": int}
All coordinates are image pixels.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF)

LINE_KINDS = {"arrow", "line"}
RECT_KINDS = {"rect", "ellipse", "highlight", "blur", "image", "spotlight", "magnify", "stamp"}

# Stamps: emoji/symbols drawn in colour, or short word badges drawn as a pill in the shape's colour.
STAMP_SYMBOLS = ["✅", "❌", "⚠️", "❓", "❗", "⭐", "👍", "👎", "🔥", "💡", "❤️", "🎯", "👀", "📌", "🚫", "🎉"]
STAMP_BADGES = ["NEW", "BUG", "FIX", "TODO", "DONE", "WIP", "OK", "NO", "BEFORE", "AFTER"]


def is_badge(label):
    return bool(label) and all(ch.isascii() for ch in label)
# Line kinds may carry a third point: pts = [start, bend, end] makes them curve.

# ---------------------------------------------------------------- embedded images
# Pasted images live inside the shape as base64 PNG (so undo/save "just work"); decoded once and cached.
_img_cache = {}


def encode_image(img):
    import base64
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(ba)).decode("ascii")


def shape_image(s):
    key = s.get("img", "")
    img = _img_cache.get(key)
    if img is None:
        import base64
        img = QImage.fromData(base64.b64decode(key)) if key else QImage()
        if len(_img_cache) > 64:
            _img_cache.clear()
        _img_cache[key] = img
    return img


def P(pt):
    return QPointF(pt[0], pt[1])


def norm_rect(s):
    (x1, y1), (x2, y2) = s["pts"][0], s["pts"][-1]
    return QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2), max(y1, y2)))


def is_light(color):
    c = QColor(color)
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 175


# ---------------------------------------------------------------- geometry builders
ARROW_HEADS = ("tapered", "classic", "double")


def arrow_path(x1, y1, x2, y2, w, head="tapered"):
    """tapered: swept-back barbs on a shaft that thins to the tail.
    classic: even shaft with a solid triangular head.  double: classic head on both ends."""
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    path = QPainterPath()
    if L < 1:
        return path
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    if head in ("classic", "double"):
        return _classic_arrow(x1, y1, x2, y2, ux, uy, nx, ny, L, w, head == "double")
    head_len = min(L * 0.7, max(14.0, w * 4.2))
    head_half = max(9.0, w * 3.0) / 2 + w * 0.6
    tail_half = max(0.8, w * 0.22)
    neck_half = max(1.2, w * 0.55)

    def at(d, off):
        return QPointF(x1 + ux * d + nx * off, y1 + uy * d + ny * off)

    base_d = L - head_len
    neck_d = L - head_len * 0.78
    poly = QPolygonF([
        at(0, tail_half), at(neck_d, neck_half), at(base_d, head_half),
        QPointF(x2, y2),
        at(base_d, -head_half), at(neck_d, -neck_half), at(0, -tail_half),
    ])
    path.addPolygon(poly)
    path.closeSubpath()
    return path


def _classic_arrow(x1, y1, x2, y2, ux, uy, nx, ny, L, w, double):
    path = QPainterPath()
    shaft = max(1.0, w / 2)
    head_half = max(7.0, w * 2.1)
    head_len = min(L * (0.45 if double else 0.8), max(13.0, w * 3.6))

    def at(d, off):
        return QPointF(x1 + ux * d + nx * off, y1 + uy * d + ny * off)

    b2 = L - head_len
    if double:
        pts = [QPointF(x1, y1), at(head_len, head_half), at(head_len, shaft), at(b2, shaft), at(b2, head_half),
               QPointF(x2, y2), at(b2, -head_half), at(b2, -shaft), at(head_len, -shaft), at(head_len, -head_half)]
    else:
        pts = [at(0, shaft), at(b2, shaft), at(b2, head_half), QPointF(x2, y2),
               at(b2, -head_half), at(b2, -shaft), at(0, -shaft)]
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


def curve_ctrl(s):
    """The bend (quadratic control point) of a curved arrow/line, or None when straight."""
    return P(s["pts"][1]) if len(s["pts"]) == 3 else None


def line_path(s):
    a, b, c = P(s["pts"][0]), curve_ctrl(s), P(s["pts"][-1])
    path = QPainterPath(a)
    if b is None:
        path.lineTo(c)
    else:
        path.quadTo(b, c)
    return path


def curve_mid(s):
    """Point halfway along the curve (where its bend handle sits)."""
    a, c = s["pts"][0], s["pts"][-1]
    b = s["pts"][1] if len(s["pts"]) == 3 else [(a[0] + c[0]) / 2, (a[1] + c[1]) / 2]
    return QPointF(0.25 * a[0] + 0.5 * b[0] + 0.25 * c[0], 0.25 * a[1] + 0.5 * b[1] + 0.25 * c[1])


def curved_arrow_path(pts, w, head="tapered"):
    (x0, y0), (cx, cy), (x1, y1) = pts[0], pts[1], pts[-1]
    N = 64
    samples = []
    for i in range(N + 1):
        t = i / N
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        samples.append((a * x0 + b * cx + c * x1, a * y0 + b * cy + c * y1))
    dist = [0.0]
    for i in range(N):
        dist.append(dist[-1] + math.hypot(samples[i + 1][0] - samples[i][0], samples[i + 1][1] - samples[i][1]))
    L = dist[-1]
    if L < 1:
        return QPainterPath()

    def at(d):
        d = max(0.0, min(L, d))
        i = 0
        while i < N - 1 and dist[i + 1] < d:
            i += 1
        seg = max(1e-9, dist[i + 1] - dist[i])
        f = (d - dist[i]) / seg
        (ax, ay), (bx, by) = samples[i], samples[i + 1]
        ux, uy = (bx - ax) / seg, (by - ay) / seg
        n = math.hypot(ux, uy) or 1
        return ax + (bx - ax) * f, ay + (by - ay) * f, ux / n, uy / n

    classic = head in ("classic", "double")
    double = head == "double"
    if classic:
        shaft = max(1.0, w / 2)
        head_half = max(7.0, w * 2.1)
        head_len = min(L * (0.45 if double else 0.8), max(13.0, w * 3.6))
        d0, d1 = (head_len * 0.9 if double else 0.0), L - head_len * 0.9

        def hw(_d):
            return shaft
    else:
        head_len = min(L * 0.7, max(14.0, w * 4.2))
        head_half = max(9.0, w * 3.0) / 2 + w * 0.6
        tail_half, neck_half = max(0.8, w * 0.22), max(1.2, w * 0.55)
        d0, d1 = 0.0, L - head_len * 0.75

        def hw(d):
            return tail_half + (neck_half - tail_half) * d / max(1.0, d1)

    left, right = [], []
    for i in range(41):
        d = d0 + (d1 - d0) * i / 40
        x, y, ux, uy = at(d)
        h = hw(d)
        left.append(QPointF(x - uy * h, y + ux * h))
        right.append(QPointF(x + uy * h, y - ux * h))
    path = QPainterPath()
    path.addPolygon(QPolygonF(left + right[::-1]))
    path.closeSubpath()

    def head_at(tx, ty, base_d):
        bx, by, _, _ = at(base_d)
        dx, dy = tx - bx, ty - by
        n = math.hypot(dx, dy) or 1
        ux, uy = dx / n, dy / n
        nx, ny = -uy, ux
        if classic:
            poly = [QPointF(bx + nx * head_half, by + ny * head_half), QPointF(tx, ty),
                    QPointF(bx - nx * head_half, by - ny * head_half)]
        else:
            k = head_len * 0.22
            mx, my = bx + ux * k, by + uy * k
            poly = [QPointF(tx, ty), QPointF(bx - nx * head_half, by - ny * head_half),
                    QPointF(mx - nx * neck_half, my - ny * neck_half),
                    QPointF(mx + nx * neck_half, my + ny * neck_half),
                    QPointF(bx + nx * head_half, by + ny * head_half)]
        hp = QPainterPath()
        hp.addPolygon(QPolygonF(poly))
        hp.closeSubpath()
        return hp

    path = path.united(head_at(x1, y1, L - head_len))
    if double:
        path = path.united(head_at(x0, y0, head_len))
    return path.simplified()


def bubble_geom(s):
    """Callout: padded box around the text plus the point its tail aims at."""
    fs = s.get("font", 24)
    pad = max(8.0, fs * 0.42)
    r = text_rect(s).adjusted(-pad, -pad * 0.75, pad, pad * 0.75)
    if s.get("bubble") == "box":       # text box: same padded box, no tail
        tail = None
    elif len(s["pts"]) > 1:
        tail = P(s["pts"][1])
    else:
        tail = QPointF(r.left() + r.width() * 0.22, r.bottom() + max(28.0, fs * 1.5))
    return r, tail


def bubble_path(s):
    r, tail = bubble_geom(s)
    rad = min(14.0, r.height() / 2)
    path = QPainterPath()
    path.addRoundedRect(r, rad, rad)
    if tail is not None and not r.contains(tail):
        c = r.center()
        dx, dy = tail.x() - c.x(), tail.y() - c.y()
        n = math.hypot(dx, dy) or 1
        bw = max(8.0, min(34.0, min(r.width(), r.height()) * 0.32)) / 2
        nx, ny = -dy / n * bw, dx / n * bw
        # tail base sits inside the box, a little in from the edge facing the tail
        k = 0.55
        bx, by = c.x() + dx / n * min(r.width(), r.height()) * k * 0.5, c.y() + dy / n * min(r.width(), r.height()) * k * 0.5
        tri = QPainterPath()
        tri.addPolygon(QPolygonF([QPointF(bx + nx, by + ny), tail, QPointF(bx - nx, by - ny)]))
        tri.closeSubpath()
        path = path.united(tri).simplified()
    return path


def outline_color(color):
    return QColor("#111111" if is_light(color) else "#ffffff")


def outline_width(w):
    return max(1.5, w * 0.35)


def pen_path(pts):
    path = QPainterPath(P(pts[0]))
    if len(pts) == 1:
        path.lineTo(pts[0][0] + 0.01, pts[0][1])
        return path
    for i in range(1, len(pts) - 1):
        mid = QPointF((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
        path.quadTo(P(pts[i]), mid)
    path.lineTo(P(pts[-1]))
    return path


def text_font(size):
    f = QFont("Segoe UI")
    f.setPixelSize(max(4, int(size)))
    f.setWeight(QFont.DemiBold)
    return f


def text_rect(s):
    font = text_font(s.get("font", 24))
    fm = QFontMetricsF(font)
    lines = (s.get("text") or " ").split("\n")
    w = max(fm.horizontalAdvance(l) for l in lines)
    h = len(lines) * fm.lineSpacing()
    x, y = s["pts"][0]
    return QRectF(x, y, max(w, 4), h)


def text_path(s):
    font = text_font(s.get("font", 24))
    fm = QFontMetricsF(font)
    x, y = s["pts"][0]
    path = QPainterPath()
    for i, line in enumerate((s.get("text") or "").split("\n")):
        path.addText(x, y + fm.ascent() + i * fm.lineSpacing(), font, line)
    return path


def step_radius(s):
    return 9 + s["width"] * 2.6


# ---------------------------------------------------------------- drawing
def draw_shape(p, s, base, shapes=None):
    """`shapes` (the whole list) lets spotlights share one dimmed backdrop and keeps
    magnifiers from revealing anything a pixelate box hides."""
    kind = s["kind"]
    if kind == "spotlight":
        _draw_spotlight(p, s, base, shapes or [s])
        return
    if kind == "magnify":
        _draw_magnify(p, s, base, shapes or [s])
        return
    if kind == "blur":
        _draw_pixelate(p, s, base)
        return
    if kind == "image":
        _draw_image(p, s)
        return
    if kind == "stamp":
        _draw_stamp(p, s)
        return
    if kind == "highlight":
        # Multiply looks like a real marker on light backgrounds; a translucent wash keeps it
        # visible on dark ones (dark themes, terminals).
        r = norm_rect(s)
        c = QColor(s["color"])
        p.save()
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.fillRect(r, c)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        c.setAlpha(70)
        p.fillRect(r, c)
        p.restore()
        return
    if s.get("shadow"):
        for dx, dy, a, extra in ((3.0, 4.5, 28, 2.5), (1.5, 2.5, 60, 0.0)):
            p.save()
            p.translate(dx, dy)
            _draw_core(p, s, QColor(0, 0, 0, a), extra)
            p.restore()
    _draw_core(p, s, None, 0)


def _spot_hole(s):
    r = norm_rect(s)
    path = QPainterPath()
    rad = min(14.0, r.width() / 4, r.height() / 4)
    if s.get("fill"):            # "Fill" on a spotlight = round spotlight
        path.addEllipse(r)
    else:
        path.addRoundedRect(r, rad, rad)
    return path


def _draw_spotlight(p, s, base, shapes):
    spots = [x for x in shapes if x["kind"] == "spotlight"]
    if spots and spots[0] is not s:
        return  # the first spotlight paints the shared backdrop for all of them
    dim = QPainterPath()
    dim.addRect(QRectF(base.rect()))
    holes = QPainterPath()
    for x in spots or [s]:
        holes = holes.united(_spot_hole(x))
    p.save()
    p.fillPath(dim.subtracted(holes), QColor(0, 0, 0, 150))
    for x in spots or [s]:
        if x.get("outline"):
            p.setPen(QPen(QColor(x["color"]), max(1.0, float(x["width"]) / 2)))
            p.setBrush(Qt.NoBrush)
            p.drawPath(_spot_hole(x))
    p.restore()


_safe_cache = {}


def _safe_base(base, shapes):
    """The base image with every pixelate box applied (a magnifier must not undo a redaction)."""
    blurs = [x for x in shapes if x["kind"] == "blur"]
    if not blurs:
        return base
    key = (base.cacheKey(), repr([(b["pts"], b["width"]) for b in blurs]))
    hit = _safe_cache.get(key)
    if hit is None:
        hit = base.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        q = QPainter(hit)
        for b in blurs:
            _draw_pixelate(q, b, base)
        q.end()
        _safe_cache.clear()
        _safe_cache[key] = hit
    return hit


def _draw_magnify(p, s, base, shapes):
    r = norm_rect(s)
    if r.width() < 4 or r.height() < 4:
        return
    zoom = float(s.get("zoom", 2.0))
    src_img = _safe_base(base, shapes)
    c = r.center()
    src = QRectF(c.x() - r.width() / zoom / 2, c.y() - r.height() / zoom / 2, r.width() / zoom, r.height() / zoom)
    lens = QPainterPath()
    if s.get("fill"):            # "Fill" = square lens
        lens.addRoundedRect(r, 10, 10)
    else:
        lens.addEllipse(r)
    w = float(s["width"])
    p.save()
    if s.get("shadow"):
        for grow, a in ((7, 22), (3, 38)):
            sh = QPainterPath()
            rr = r.adjusted(-grow + 2, -grow + 4, grow + 2, grow + 4)
            sh.addRoundedRect(rr, 10 + grow, 10 + grow) if s.get("fill") else sh.addEllipse(rr)
            p.fillPath(sh, QColor(0, 0, 0, a))
    p.setClipPath(lens)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.fillRect(r, QColor("#ffffff"))
    p.drawImage(r, src_img, src)
    p.setClipping(False)
    if s.get("outline"):
        p.setPen(QPen(outline_color(s["color"]), w + 2 * outline_width(w)))
        p.setBrush(Qt.NoBrush)
        p.drawPath(lens)
    p.setPen(QPen(QColor(s["color"]), w))
    p.setBrush(Qt.NoBrush)
    p.drawPath(lens)
    p.restore()


def _draw_image(p, s):
    r = norm_rect(s)
    img = shape_image(s)
    if img.isNull() or r.width() < 1 or r.height() < 1:
        return
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if s.get("shadow"):
        for grow, a in ((6, 18), (3, 28), (1, 40)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(r.adjusted(-grow + 2, -grow + 4, grow + 2, grow + 4), grow + 2, grow + 2)
    p.drawImage(r, img)
    p.restore()


def stamp_size(label, h):
    """Natural (w, h) of a stamp at height h."""
    if is_badge(label):
        f = QFont("Segoe UI")
        f.setPixelSize(max(6, int(h * 0.5)))
        f.setBold(True)
        from PySide6.QtGui import QFontMetricsF
        return QFontMetricsF(f).horizontalAdvance(label) + h * 0.9, h
    return h, h


def _draw_stamp(p, s):
    r = norm_rect(s)
    label = s.get("text") or "✅"
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    if is_badge(label):
        rad = r.height() * 0.3
        if s.get("shadow"):
            for grow, a in ((5, 22), (2, 40)):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, a))
                p.drawRoundedRect(r.adjusted(-grow + 1, -grow + 3, grow + 1, grow + 3), rad + grow, rad + grow)
        c = QColor(s["color"])
        p.setPen(QPen(QColor("#ffffff") if not is_light(s["color"]) else QColor("#111111"),
                      max(1.5, r.height() * 0.05)) if s.get("outline") else Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, rad, rad)
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(max(6, int(r.height() * 0.5)))
        from PySide6.QtGui import QFontMetricsF
        tw = QFontMetricsF(f).horizontalAdvance(label)
        if tw > r.width() * 0.88:      # squeezed: shrink the text to fit
            f.setPixelSize(max(6, int(f.pixelSize() * r.width() * 0.88 / tw)))
        p.setFont(f)
        p.setPen(QColor("#111111" if is_light(s["color"]) else "#ffffff"))
        p.drawText(r, Qt.AlignCenter, label)
    else:
        f = QFont("Segoe UI Emoji")
        f.setPixelSize(max(6, int(min(r.width(), r.height()) * 0.8)))
        p.setFont(f)
        p.setPen(QColor("#000000"))
        p.drawText(r, Qt.AlignCenter, label)
    p.restore()


def _draw_core(p, s, shadow, extra):
    kind = s["kind"]
    c = shadow if shadow is not None else QColor(s["color"])
    w = float(s["width"])
    pts = s["pts"]
    # Outline: a contrasting rim so the mark reads on any background (busy screenshots, dark UIs).
    ow = outline_width(w) if (s.get("outline") and kind in ("arrow", "line", "rect", "ellipse", "pen")) else 0
    if shadow is not None:
        extra += 2 * ow
    rim = outline_color(s["color"]) if (ow and shadow is None) else None

    def rimmed(draw, width):
        if rim is not None:
            p.setPen(QPen(rim, width + 2 * ow, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            draw()
        p.setPen(QPen(c, width + extra, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        draw()

    p.save()
    if kind == "arrow":
        if len(pts) == 3:
            path = curved_arrow_path(pts, w, s.get("head", "tapered"))
        else:
            path = arrow_path(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], w, s.get("head", "tapered"))
        if rim is not None:
            p.strokePath(path, QPen(rim, 1 + 2 * ow, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setPen(QPen(c, 1 + extra, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(c)
        p.drawPath(path)
    elif kind == "line":
        lp = line_path(s)
        p.setBrush(Qt.NoBrush)
        rimmed(lambda: p.drawPath(lp), w)
    elif kind in ("rect", "ellipse"):
        r = norm_rect(s)
        if s.get("fill") and shadow is None:
            fc = QColor(c)
            fc.setAlpha(70)
            p.setBrush(fc)
        else:
            p.setBrush(Qt.NoBrush)
        if rim is not None:
            brush = p.brush()
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(rim, w + 2 * ow, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            rad = min(w * 0.8, 6)
            p.drawRoundedRect(r, rad, rad) if kind == "rect" else p.drawEllipse(r)
            p.setBrush(brush)
        p.setPen(QPen(c, w + extra, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if kind == "rect":
            rad = min(w * 0.8, 6)
            p.drawRoundedRect(r, rad, rad)
        else:
            p.drawEllipse(r)
    elif kind == "pen":
        p.setBrush(Qt.NoBrush)
        path = pen_path(pts)
        rimmed(lambda: p.drawPath(path), w)
    elif kind == "text" and s.get("bubble"):
        bp = bubble_path(s)
        if shadow is not None:
            p.fillPath(bp, c)
        else:
            if s.get("outline"):
                p.strokePath(bp, QPen(outline_color(s["color"]), 2 * outline_width(w), Qt.SolidLine,
                                      Qt.RoundCap, Qt.RoundJoin))
            p.fillPath(bp, c)
            p.fillPath(text_path(s), QColor("#111111" if is_light(s["color"]) else "#ffffff"))
    elif kind == "text":
        path = text_path(s)
        fs = s.get("font", 24)
        ow = max(2.0, fs / 7.0)
        outline = c if shadow is not None else QColor("#111111" if is_light(s["color"]) else "#ffffff")
        p.strokePath(path, QPen(outline, ow + extra, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.fillPath(path, c)
    elif kind == "step":
        r = step_radius(s)
        ctr = P(pts[0])
        p.setPen(QPen(QColor("white") if shadow is None else c, 2.5 + extra))
        p.setBrush(c)
        p.drawEllipse(ctr, r, r)
        if shadow is None:
            f = QFont("Segoe UI")
            f.setPixelSize(max(6, int(r * 1.1)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#111111" if is_light(s["color"]) else "#ffffff"))
            p.drawText(QRectF(ctr.x() - r, ctr.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(s.get("number", 1)))
    p.restore()


def _draw_pixelate(p, s, base):
    r = norm_rect(s).toAlignedRect().intersected(base.rect())
    if r.width() < 1 or r.height() < 1:
        return
    block = max(6, int(s["width"] * 3))
    sub = base.copy(r)
    small = sub.scaled(max(1, r.width() // block), max(1, r.height() // block),
                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
    p.drawImage(QRectF(r), small)
    p.restore()


def render(base, shapes, frame=None):
    img = base.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    for s in shapes:
        draw_shape(p, s, base, shapes)
    p.end()
    if frame:
        return compose_frame(img, frame, base)
    return img.convertToFormat(QImage.Format_RGB32)


# ---------------------------------------------------------------- beautify frame
# frame = {"bg": key, "padding": percent, "radius": px, "shadow": bool, "aspect": "auto" | "16:9" | ...}
BACKGROUNDS = {
    "none": None,
    "blur": "blur",
    "graphite": ("#323235", "#111113"),
    "slate": ("#55627a", "#1b2130"),
    "ocean": ("#7db6d3", "#2b5a86"),
    "dusk": ("#7a7bb8", "#2a2b55"),
    "ember": ("#f5b27a", "#d65f47"),
    "sage": ("#dfe8d9", "#9fb59a"),
    "sand": ("#f1ebe0", "#d3c6b1"),
    "white": ("#ffffff", "#f1f1f1"),
}
DEFAULT_FRAME = {"bg": "graphite", "padding": 8, "radius": 12, "shadow": True, "aspect": "auto"}


def frame_layout(w, h, frame):
    """Output size and the image's offset inside it."""
    pad = round(max(w, h) * frame.get("padding", 8) / 100.0)
    ow, oh = w + 2 * pad, h + 2 * pad
    asp = frame.get("aspect", "auto")
    if asp and asp != "auto":
        a, b = (int(x) for x in asp.split(":"))
        r = a / b
        if ow / oh < r:
            ow = round(oh * r)
        else:
            oh = round(ow / r)
    return ow, oh, (ow - w) // 2, (oh - h) // 2


def frame_radius(w, h, frame):
    return frame.get("radius", 12) * max(1.0, max(w, h) / 1400.0)


def frame_background(w, h, frame, base):
    """Background + drop shadow (everything except the image itself)."""
    ow, oh, ox, oy = frame_layout(w, h, frame)
    img = QImage(ow, oh, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    bg = BACKGROUNDS.get(frame.get("bg"), None)
    if bg == "blur":
        small = base.scaled(max(1, ow // 28), max(1, oh // 28), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p.drawImage(QRectF(0, 0, ow, oh), small.scaled(max(1, ow // 4), max(1, oh // 4), Qt.IgnoreAspectRatio,
                                                         Qt.SmoothTransformation))
        p.fillRect(QRectF(0, 0, ow, oh), QColor(0, 0, 0, 50))
    elif isinstance(bg, tuple):
        from PySide6.QtGui import QLinearGradient
        g = QLinearGradient(0, 0, ow, oh)
        g.setColorAt(0, QColor(bg[0]))
        g.setColorAt(1, QColor(bg[1]))
        p.fillRect(QRectF(0, 0, ow, oh), g)
    if frame.get("shadow", True) and (ox > 0 or oy > 0):
        k = max(4, int(max(w, h) / 120))
        sw, sh = max(1, ow // k + 1), max(1, oh // k + 1)
        sm = QImage(sw, sh, QImage.Format_ARGB32_Premultiplied)
        sm.fill(Qt.transparent)
        sp = QPainter(sm)
        sp.setRenderHint(QPainter.Antialiasing)
        sp.setPen(Qt.NoPen)
        sp.setBrush(QColor(0, 0, 0, 120))
        drop = h * 0.015
        sp.drawRoundedRect(QRectF(ox / k, (oy + drop) / k, w / k, h / k), 2, 2)
        sp.end()
        p.drawImage(QRectF(0, 0, sw * k, sh * k), sm)
    p.end()
    return img


def compose_frame(annotated, frame, base):
    w, h = annotated.width(), annotated.height()
    out = frame_background(w, h, frame, base)
    _, _, ox, oy = frame_layout(w, h, frame)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    r = frame_radius(w, h, frame)
    clip.addRoundedRect(QRectF(ox, oy, w, h), r, r)
    p.setClipPath(clip)
    p.drawImage(ox, oy, annotated)
    p.end()
    if BACKGROUNDS.get(frame.get("bg")) is None:
        return out  # transparent background - keep alpha
    return out.convertToFormat(QImage.Format_RGB32)


# ---------------------------------------------------------------- hit testing / editing
def hit_path(s):
    k = s["kind"]
    st = QPainterPathStroker()
    st.setCapStyle(Qt.RoundCap)
    st.setJoinStyle(Qt.RoundJoin)
    w = float(s["width"])
    path = QPainterPath()
    if k in LINE_KINDS:
        path = line_path(s)
        st.setWidth(max(w * (3 if k == "arrow" else 1), 4) + 10)
        return st.createStroke(path)
    if k in ("rect", "ellipse"):
        r = norm_rect(s)
        if k == "rect":
            path.addRect(r)
        else:
            path.addEllipse(r)
        if s.get("fill"):
            return path
        st.setWidth(w + 12)
        return st.createStroke(path)
    if k in ("highlight", "blur", "image", "magnify", "spotlight", "stamp"):
        path.addRect(norm_rect(s))
        return path
    if k == "pen":
        st.setWidth(w + 10)
        return st.createStroke(pen_path(s["pts"]))
    if k == "text":
        if s.get("bubble"):
            return bubble_path(s)
        path.addRect(text_rect(s).adjusted(-6, -6, 6, 6))
        return path
    if k == "step":
        r = step_radius(s) + 3
        path.addEllipse(P(s["pts"][0]), r, r)
        return path
    return path


def bounds(s):
    return hit_path(s).boundingRect()


def handles(s):
    if s["kind"] in LINE_KINDS:
        return [P(s["pts"][0]), P(s["pts"][-1]), curve_mid(s)]
    if s["kind"] == "text" and s.get("bubble") and s.get("bubble") != "box":
        return [bubble_geom(s)[1]]
    if s["kind"] in RECT_KINDS:
        r = norm_rect(s)
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
    return []


def set_handle(s, i, pt, free=False):
    """Move handle i to pt. Images keep their proportions unless `free` (Shift)."""
    if s["kind"] in ("image", "stamp") and not free:
        opp = handles(s)[(i + 2) % 4]
        if s["kind"] == "image":
            img = shape_image(s)
            ar = img.width() / max(1, img.height()) if not img.isNull() else 1.0
        else:     # stamps keep their shape (emoji stay square, badges stay a pill); Shift = free
            r0 = norm_rect(s)
            ar = r0.width() / max(1.0, r0.height())
        dx, dy = pt.x() - opp.x(), pt.y() - opp.y()
        w = max(abs(dx), abs(dy) * ar, 4)
        hgt = w / ar
        sx = 1 if dx >= 0 else -1
        sy = 1 if dy >= 0 else -1
        s["pts"] = [[opp.x(), opp.y()], [opp.x() + sx * w, opp.y() + sy * hgt]]
        return
    _set_handle(s, i, pt)


def _set_handle(s, i, pt):
    if s["kind"] in LINE_KINDS:
        if i == 2:   # bend handle: the curve passes through it
            a, c = s["pts"][0], s["pts"][-1]
            mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
            ctrl = [2 * pt.x() - mx, 2 * pt.y() - my]
            straight = math.hypot(pt.x() - mx, pt.y() - my) < max(4.0, float(s["width"]))
            s["pts"] = [a, c] if straight else [a, ctrl, c]
        else:
            s["pts"][0 if i == 0 else -1] = [pt.x(), pt.y()]
    elif s["kind"] == "text":
        if len(s["pts"]) > 1:
            s["pts"][1] = [pt.x(), pt.y()]
        else:
            s["pts"].append([pt.x(), pt.y()])
    elif s["kind"] in RECT_KINDS:
        opp = handles(s)[(i + 2) % 4]
        s["pts"] = [[opp.x(), opp.y()], [pt.x(), pt.y()]]


def translate(s, dx, dy):
    s["pts"] = [[x + dx, y + dy] for x, y in s["pts"]]
