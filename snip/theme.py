"""Visual system: neutral monochrome, one accent used only for selection.

Icons are drawn in code as thin outlines on a 24-unit grid (no asset files).
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QIconEngine, QLinearGradient, QPainter, QPainterPath, QPalette,
                           QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QLabel

# ---------------------------------------------------------------- palettes
# Every colour the windows use comes from here, so Light / Dark / System can swap them live.
# (Floating HUDs drawn over the screen - capture overlay, thumbnail, pins - stay dark on purpose.)
PALETTES = {
    "dark": dict(
        BG="#141414", SURFACE="#1b1b1b", CANVAS="#0d0d0d", LINE="#262626", HOVER="#232323", ACTIVE="#2e2e2e",
        TEXT="#ececec", MUTED="#8b8b8b", DIM="#5f5f5f", STRONG="#ffffff",
        SIDEBAR="#0f0f0f", SIDEBAR_LINE="#1f1f1f", NAV="#b4b4b4", NAV_HOVER="#1a1a1a", GROUP="#d6d6d6",
        CARD="#1a1a1a", CARD_LINE="#232323", CARD_HOVER="#1f1f1f", WELL="#242424", TIP="#161616", TIP_LINE="#222222",
        KBD="#222222", KBD_LINE="#333333", KBD_TEXT="#c8c8c8",
        TILE_HOVER="#1a1a1a", THUMB="#1c1c1c", THUMB_EDGE="rgba(255,255,255,14)",
        EMPTY="#171717", EMPTY_LINE="#2c2c2c",
        FLOAT="rgba(30,30,30,242)", FLOAT_LINE="#3a3a3a",
        CHECK_LINE="#3a3a3a", SCROLL="#3a3a3a", SCROLL_HOVER="#4a4a4a",
        GROOVE="#333333", HANDLE="#f2f2f2", HANDLE_LINE="#f2f2f2",
        PILL="#1c1c1c", PILL_LINE="#2a2a2a", PILL_DIV="#2e2e2e", PILL_TEXT="#f2f2f2", PILL_HOVER="#2c2c2c",
        CHIP="#222222", CHIP_LINE="#2c2c2c", CHIP_TEXT="#bdbdbd", CHIP_HOVER="#2a2a2a",
        SWATCH_ON="#ffffff", SWATCH_HOVER="#8a8a8a",
        TOG_OFF="#1f1f1f", TOG_OFF_LINE="#3a3a3a", TOG_KNOB="#8a8a8a",
        ICON_OFF="#a3a3a3", ICON_ON="#ffffff", ICON_DISABLED="#4a4a4a",
        LIST_HOVER="#1b1b1b", LIST_SEL="#222222"),
    "light": dict(
        BG="#f6f6f7", SURFACE="#ffffff", CANVAS="#e6e6e9", LINE="#e0e0e4", HOVER="#ebebee", ACTIVE="#e0e0e5",
        TEXT="#1c1c20", MUTED="#686870", DIM="#9c9ca4", STRONG="#0d0d10",
        SIDEBAR="#efeff1", SIDEBAR_LINE="#e2e2e6", NAV="#4a4a52", NAV_HOVER="#e6e6ea", GROUP="#2a2a30",
        CARD="#ffffff", CARD_LINE="#e3e3e7", CARD_HOVER="#ffffff", WELL="#f0f0f3", TIP="#ffffff", TIP_LINE="#e3e3e7",
        KBD="#f5f5f7", KBD_LINE="#d4d4da", KBD_TEXT="#3a3a40",
        TILE_HOVER="#ececef", THUMB="#e4e4e8", THUMB_EDGE="rgba(0,0,0,22)",
        EMPTY="#fbfbfc", EMPTY_LINE="#d2d2d8",
        FLOAT="rgba(255,255,255,245)", FLOAT_LINE="#d6d6dc",
        CHECK_LINE="#bfbfc6", SCROLL="#c6c6cc", SCROLL_HOVER="#adadb5",
        GROOVE="#d2d2d8", HANDLE="#ffffff", HANDLE_LINE="#b8b8c0",
        PILL="#ffffff", PILL_LINE="#dcdce2", PILL_DIV="#e2e2e6", PILL_TEXT="#1c1c20", PILL_HOVER="#efeff2",
        CHIP="#ffffff", CHIP_LINE="#dcdce2", CHIP_TEXT="#3a3a40", CHIP_HOVER="#f0f0f3",
        SWATCH_ON="#1c1c20", SWATCH_HOVER="#9c9ca4",
        TOG_OFF="#e4e4e8", TOG_OFF_LINE="#c9c9cf", TOG_KNOB="#76767e",
        ICON_OFF="#55555d", ICON_ON="#0d0d10", ICON_DISABLED="#c4c4ca",
        LIST_HOVER="#ececef", LIST_SEL="#e2e2e6"),
}
MODE = "dark"           # resolved mode actually showing: "dark" | "light"
APPEARANCE = "system"   # the user's choice: "system" | "light" | "dark"
_ICON_GEN = 0           # bumps on every theme change so live icons redraw

globals().update(PALETTES["dark"])
ACCENT = "#4c8dff"     # set from settings by apply_theme()
ACCENTS = [("Blue", "#4c8dff"), ("Violet", "#8b6cff"), ("Teal", "#20b2a0"), ("Green", "#3fb950"),
           ("Amber", "#f29d1f"), ("Rose", "#ff5c8a"), ("Mono", "#e6e6e6")]


def rgba(c, a):
    q = QColor(c)
    return f"rgba({q.red()}, {q.green()}, {q.blue()}, {int(a * 255)})"


def on_accent(c):
    """Text colour that reads on top of the accent."""
    q = QColor(c)
    lin = [((v / 255) / 12.92 if v / 255 <= 0.04045 else (((v / 255) + 0.055) / 1.055) ** 2.4)
           for v in (q.red(), q.green(), q.blue())]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "#111111" if lum > 0.42 else "#ffffff"


def system_is_dark():
    """Windows' app mode (Settings > Personalisation > Colours)."""
    try:
        from PySide6.QtGui import QGuiApplication
        cs = QGuiApplication.styleHints().colorScheme()
        if cs == Qt.ColorScheme.Dark:
            return True
        if cs == Qt.ColorScheme.Light:
            return False
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return True


def is_dark():
    return MODE == "dark"


# ---------------------------------------------------------------- icons
def _draw(name, p, c):
    """Draw icon `name` on a 24x24 grid with colour c."""
    pen = QPen(c, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    L = lambda *pts: QPolygonF([QPointF(x, y) for x, y in pts])  # noqa: E731

    if name == "select":
        p.drawPolygon(L((6, 3.5), (6, 18.5), (10, 14.8), (12.6, 20.3), (15, 19.2), (12.4, 13.8), (17.6, 13.6)))
    elif name == "arrow":
        p.drawLine(QPointF(5, 19), QPointF(18.5, 5.5))
        p.drawPolyline(L((10, 5.5), (18.5, 5.5), (18.5, 14)))
    elif name == "rect":
        p.drawRoundedRect(QRectF(4, 6, 16, 12), 1.5, 1.5)
    elif name == "ellipse":
        p.drawEllipse(QRectF(3.5, 5.5, 17, 13))
    elif name == "line":
        p.drawLine(QPointF(5, 19), QPointF(19, 5))
    elif name == "pen":
        path = QPainterPath(QPointF(4, 16))
        path.cubicTo(7, 8, 10, 8, 11, 13)
        path.cubicTo(12, 18, 16, 18, 20, 8)
        p.drawPath(path)
    elif name == "highlight":
        p.drawPolygon(L((14.5, 4), (19.5, 9), (11, 17.5), (6, 12.5)))
        p.drawLine(QPointF(6, 12.5), QPointF(4, 19))
        p.drawLine(QPointF(4, 19), QPointF(11, 17.5))
        p.drawLine(QPointF(13, 20), QPointF(20, 20))
    elif name == "text":
        p.drawLine(QPointF(5.5, 5.5), QPointF(18.5, 5.5))
        p.drawLine(QPointF(12, 5.5), QPointF(12, 19))
        p.drawLine(QPointF(9.5, 19), QPointF(14.5, 19))
    elif name == "step":
        p.drawEllipse(QRectF(4, 4, 16, 16))
        p.drawPolyline(L((10.3, 9.2), (12.6, 7.8), (12.6, 16.2)))
    elif name == "blur":
        for x, y in ((4, 4), (12, 4), (8, 8), (16, 8), (4, 12), (12, 12), (8, 16), (16, 16)):
            p.fillRect(QRectF(x, y, 4, 4), c)
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 1.5, 1.5)
    elif name == "crop":
        p.drawPolyline(L((7, 3), (7, 17), (21, 17)))
        p.drawPolyline(L((3, 7), (17, 7), (17, 21)))
    elif name == "undo":
        path = QPainterPath(QPointF(8, 14))
        path.lineTo(4, 10)
        path.lineTo(8, 6)
        path.moveTo(4, 10)
        path.lineTo(14, 10)
        path.cubicTo(18, 10, 20, 12.5, 20, 15)
        path.cubicTo(20, 17.5, 18, 19, 15, 19)
        path.lineTo(11, 19)
        p.drawPath(path)
    elif name == "redo":
        p.save()
        p.translate(24, 0)
        p.scale(-1, 1)
        _draw("undo", p, c)
        p.restore()
    elif name == "redact":
        path = QPainterPath(QPointF(12, 3))
        path.lineTo(19.5, 6)
        path.cubicTo(19.5, 13, 17, 18, 12, 21)
        path.cubicTo(7, 18, 4.5, 13, 4.5, 6)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(9, 10.5), QPointF(15, 10.5))
        p.drawLine(QPointF(9, 14), QPointF(13, 14))
    elif name == "ocr":
        for pts in (((3.5, 8), (3.5, 3.5), (8, 3.5)), ((16, 3.5), (20.5, 3.5), (20.5, 8)),
                    ((20.5, 16), (20.5, 20.5), (16, 20.5)), ((8, 20.5), (3.5, 20.5), (3.5, 16))):
            p.drawPolyline(L(*pts))
        p.drawLine(QPointF(8.5, 8.5), QPointF(15.5, 8.5))
        p.drawLine(QPointF(12, 8.5), QPointF(12, 15.5))
    elif name == "pin":
        p.drawPolygon(L((9, 3.5), (15, 3.5), (14, 9), (17, 13), (7, 13), (10, 9)))
        p.drawLine(QPointF(12, 13), QPointF(12, 20.5))
    elif name == "copy":
        p.drawRoundedRect(QRectF(8, 8, 12, 12), 2, 2)
        p.drawPolyline(L((16, 8), (16, 4), (4, 4), (4, 16), (8, 16)))
    elif name == "more":
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        for x in (6, 12, 18):
            p.drawEllipse(QPointF(x, 12), 1.5, 1.5)
    elif name == "qr":
        for x, y in ((3.5, 3.5), (13.5, 3.5), (3.5, 13.5)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 1.2, 1.2)
        for x, y in ((14, 14), (18, 14), (14, 18), (18, 18), (16, 16)):
            p.drawRect(QRectF(x, y, 1.6, 1.6))
    elif name == "close":
        p.drawLine(QPointF(7, 7), QPointF(17, 17))
        p.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name == "edit":
        p.drawPolygon(L((15.5, 4.5), (19.5, 8.5), (9, 19), (5, 19), (5, 15)))
    elif name == "plus":
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "search":
        p.drawEllipse(QRectF(4.5, 4.5, 11, 11))
        p.drawLine(QPointF(14, 14), QPointF(19.5, 19.5))
    elif name == "region":
        for pts in (((3.5, 8), (3.5, 3.5), (8, 3.5)), ((16, 3.5), (20.5, 3.5), (20.5, 8)),
                    ((20.5, 16), (20.5, 20.5), (16, 20.5)), ((8, 20.5), (3.5, 20.5), (3.5, 16))):
            p.drawPolyline(L(*pts))
        p.setPen(QPen(c, 1.6, Qt.DotLine, Qt.RoundCap))
        p.drawRect(QRectF(8, 8, 8, 8))
    elif name == "window":
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
        p.drawLine(QPointF(3.5, 9), QPointF(20.5, 9))
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        for x in (6.2, 8.4):
            p.drawEllipse(QPointF(x, 7), 0.8, 0.8)
    elif name == "monitor":
        p.drawRoundedRect(QRectF(3, 4.5, 18, 12), 2, 2)
        p.drawLine(QPointF(12, 16.5), QPointF(12, 19.5))
        p.drawLine(QPointF(8, 19.5), QPointF(16, 19.5))
    elif name == "screens":
        p.drawRoundedRect(QRectF(2.5, 6, 11, 8), 1.5, 1.5)
        p.drawRoundedRect(QRectF(10.5, 9, 11, 8), 1.5, 1.5)
        p.drawLine(QPointF(8, 14), QPointF(8, 18))
    elif name == "timer":
        p.drawEllipse(QRectF(4.5, 6, 15, 15))
        p.drawLine(QPointF(12, 13.5), QPointF(12, 9.5))
        p.drawLine(QPointF(12, 13.5), QPointF(14.5, 15))
        p.drawLine(QPointF(10, 3.5), QPointF(14, 3.5))
    elif name == "gamepad":
        path = QPainterPath(QPointF(7.5, 7.5))
        path.lineTo(16.5, 7.5)
        path.cubicTo(20, 7.5, 21.5, 11, 21.5, 15)
        path.cubicTo(21.5, 18.5, 18.5, 19, 17, 17)
        path.lineTo(15.5, 15)
        path.lineTo(8.5, 15)
        path.lineTo(7, 17)
        path.cubicTo(5.5, 19, 2.5, 18.5, 2.5, 15)
        path.cubicTo(2.5, 11, 4, 7.5, 7.5, 7.5)
        p.drawPath(path)
        p.drawLine(QPointF(6.5, 11.2), QPointF(9.5, 11.2))
        p.drawLine(QPointF(8, 9.7), QPointF(8, 12.7))
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(15.5, 10.5), 1, 1)
        p.drawEllipse(QPointF(17.5, 12.5), 1, 1)
    elif name == "grid":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 1.5, 1.5)
    elif name == "today":
        p.drawEllipse(QRectF(4, 4, 16, 16))
        p.drawPolyline(L((12, 7.5), (12, 12), (15, 14)))
    elif name == "week":
        p.drawRoundedRect(QRectF(3.5, 5, 17, 15), 2, 2)
        p.drawLine(QPointF(3.5, 9.5), QPointF(20.5, 9.5))
        p.drawLine(QPointF(8, 3), QPointF(8, 6.5))
        p.drawLine(QPointF(16, 3), QPointF(16, 6.5))
    elif name == "app":
        p.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 3.5, 3.5)
    elif name == "folder":
        path = QPainterPath(QPointF(3.5, 6.5))
        path.lineTo(9, 6.5)
        path.lineTo(11, 8.5)
        path.lineTo(20.5, 8.5)
        path.lineTo(20.5, 18.5)
        path.lineTo(3.5, 18.5)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "sparkle":
        def star(cx, cy, R, r):
            pts = [(0, -R), (r, -r), (R, 0), (r, r), (0, R), (-r, r), (-R, 0), (-r, -r)]
            return QPolygonF([QPointF(cx + x, cy + y) for x, y in pts])
        p.drawPolygon(star(10, 13, 7, 1.8))
        p.setBrush(c)
        p.drawPolygon(star(18, 5.5, 3, 0.8))
    elif name == "scroll":
        p.drawRoundedRect(QRectF(5.5, 3.5, 13, 17), 2, 2)
        p.drawPolyline(L((9, 9), (12, 6.5), (15, 9)))
        p.drawPolyline(L((9, 15), (12, 17.5), (15, 15)))
    elif name == "folderauto":
        path = QPainterPath(QPointF(3.5, 6.5))
        path.lineTo(9, 6.5)
        path.lineTo(11, 8.5)
        path.lineTo(20.5, 8.5)
        path.lineTo(20.5, 18.5)
        path.lineTo(3.5, 18.5)
        path.closeSubpath()
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        sp = QPainterPath(QPointF(12, 10.2))
        for x, y in ((12.9, 12.6), (15.3, 13.5), (12.9, 14.4), (12, 16.8), (11.1, 14.4), (8.7, 13.5), (11.1, 12.6)):
            sp.lineTo(x, y)
        sp.closeSubpath()
        p.drawPath(sp)
    elif name == "settings":
        import math
        p.drawEllipse(QPointF(12, 12), 3, 3)
        poly = []
        for i in range(16):
            a = math.pi * 2 * i / 16
            r = 8.5 if i % 2 == 0 else 6.6
            poly.append((12 + r * math.cos(a), 12 + r * math.sin(a)))
        p.drawPolygon(L(*poly))
    elif name == "image":
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2, 2)
        p.drawEllipse(QPointF(9, 9.5), 1.6, 1.6)
        p.drawPolyline(L((4, 17), (10, 12.5), (14, 15.5), (16.5, 13.5), (20, 16.5)))
    elif name == "stamp":
        p.drawRoundedRect(QRectF(9, 3.5, 6, 7), 2.5, 2.5)
        p.drawLine(QPointF(12, 10.5), QPointF(12, 13))
        p.drawRoundedRect(QRectF(4, 13, 16, 4.5), 1.5, 1.5)
        p.drawLine(QPointF(6, 20.5), QPointF(18, 20.5))
    elif name == "picker":
        p.drawLine(QPointF(5, 19), QPointF(12.5, 11.5))
        p.drawPolygon(L((10.5, 9.5), (14.5, 13.5), (19.5, 8.5), (15.5, 4.5)))
        p.drawLine(QPointF(9.2, 11.8), QPointF(12.2, 14.8))
    elif name == "ruler":
        p.drawPolygon(L((3.5, 15), (15, 3.5), (20.5, 9), (9, 20.5)))
        for i in range(4):
            x, y = 6.5 + i * 3, 12 - i * 3
            p.drawLine(QPointF(x, y), QPointF(x + 1.8, y + 1.8))
    elif name == "tag":
        p.drawPolygon(L((4, 4), (11.5, 4), (20, 12.5), (12.5, 20), (4, 11.5)))
        p.drawEllipse(QPointF(8.3, 8.3), 1.4, 1.4)
    elif name == "sort":
        p.drawLine(QPointF(5, 7), QPointF(19, 7))
        p.drawLine(QPointF(5, 12), QPointF(15, 12))
        p.drawLine(QPointF(5, 17), QPointF(11, 17))
    elif name == "chevron":
        p.drawPolyline(L((9.5, 6), (15.5, 12), (9.5, 18)))


_pm_cache = {}


def _icon_color(mode, state):
    if mode == QIcon.Disabled:
        return ICON_DISABLED
    if mode == QIcon.Normal and state == QIcon.Off:
        return ICON_OFF
    return ICON_ON


def icon_pixmap(name, size, mode=QIcon.Normal, state=QIcon.Off, scale=2.0):
    """The icon drawn in the current theme's colours (cached per theme)."""
    w, h = (size.width(), size.height()) if isinstance(size, QSize) else (size, size)
    key = (name, w, h, mode.value, state.value, round(scale, 2), _ICON_GEN)
    pm = _pm_cache.get(key)
    if pm is None:
        pw, ph = max(1, round(w * scale)), max(1, round(h * scale))
        pm = QPixmap(pw, ph)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(pw, ph)
        p.translate((pw - side) / 2, (ph - side) / 2)
        p.scale(side / 24.0, side / 24.0)
        _draw(name, p, QColor(_icon_color(mode, state)))
        p.end()
        pm.setDevicePixelRatio(scale)
        if len(_pm_cache) > 2000:
            _pm_cache.clear()
        _pm_cache[key] = pm
    return pm




class _LiveIcon(QIconEngine):
    """Draws the outline icon at paint time, so a theme switch recolours every icon already on screen."""

    def __init__(self, name, size):
        super().__init__()
        self.name, self.size = name, size

    def clone(self):
        return _LiveIcon(self.name, self.size)

    def actualSize(self, size, mode, state):
        return size

    def pixmap(self, size, mode, state):
        return icon_pixmap(self.name, size, mode, state, 1.0)

    def scaledPixmap(self, size, mode, state, scale):
        return icon_pixmap(self.name, size, mode, state, scale)

    def paint(self, painter, rect, mode, state):
        dpr = painter.device().devicePixelRatioF() if painter.device() else 1.0
        painter.drawPixmap(rect, icon_pixmap(self.name, rect.size(), mode, state, dpr))

    def availableSizes(self, mode=QIcon.Normal, state=QIcon.Off):
        return [QSize(self.size, self.size)]


def icon(name, size=24):
    return QIcon(_LiveIcon(name, size))


class IconLabel(QLabel):
    """A label showing one of our icons; repaints in the new colours when the theme changes."""

    def __init__(self, name, size=18, mode=QIcon.Normal, parent=None):
        super().__init__(parent)
        self._name, self._size, self._mode = name, size, mode
        self.setMinimumSize(size, size)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        pm = icon_pixmap(self._name, self._size, self._mode, QIcon.Off, self.devicePixelRatioF())
        x = (self.width() - self._size) / 2
        y = (self.height() - self._size) / 2
        p.drawPixmap(QPointF(x, y), pm)
        p.end()


tool_icon = icon  # backwards name


def dot_icon(color, size=24, ring=False):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    r = size * 0.32
    c = QColor(color)
    p.setPen(QPen(QColor(255, 255, 255, 60), 1) if c.lightness() < 60 else Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(size / 2, size / 2), r, r)
    if ring:
        p.setPen(QPen(QColor("white"), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(size / 2, size / 2), r + 3, r + 3)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


swatch_icon = dot_icon


def app_pixmap(size=256):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 24.0
    p.scale(s, s)
    # tile: near-black with a faint top highlight and hairline edge
    tile = QRectF(1, 1, 22, 22)
    g = QLinearGradient(0, 1, 0, 23)
    g.setColorAt(0, QColor("#2a2a2c"))
    g.setColorAt(1, QColor("#121213"))
    p.setPen(QPen(QColor(255, 255, 255, 28), 0.5))
    p.setBrush(g)
    p.drawRoundedRect(tile.adjusted(0.25, 0.25, -0.25, -0.25), 5.5, 5.5)
    small = size <= 24
    # capture brackets
    p.setPen(QPen(QColor(255, 255, 255, 235), 2.1 if small else 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    k = 4.2
    for (x, y), (dx, dy) in (((6, 6), (1, 1)), ((18, 6), (-1, 1)), ((18, 18), (-1, -1)), ((6, 18), (1, -1))):
        p.drawPolyline(QPolygonF([QPointF(x, y + dy * k), QPointF(x, y), QPointF(x + dx * k, y)]))
    # the glint: a four-point star, warm white
    cx, cy, R, r = 12, 12, (4.4 if small else 4.0), (1.0 if small else 0.85)
    pts =[(0, -R), (r, -r), (R, 0), (r, r), (0, R), (-r, r), (-R, 0), (-r, -r)]
    star = QPainterPath(QPointF(cx + pts[0][0], cy + pts[0][1]))
    for i in range(1, 9):
        a = pts[i % 8]
        prev = pts[(i - 1) % 8]
        # curve the star's sides inward for a soft sparkle
        star.quadTo(QPointF(cx + (a[0] + prev[0]) * 0.18, cy + (a[1] + prev[1]) * 0.18), QPointF(cx + a[0], cy + a[1]))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#fff4dc"))
    p.drawPath(star)
    p.end()
    return pm


def write_ico(path):
    """Multi-resolution .ico (PNG-compressed entries) for shortcuts / packaging."""
    import struct
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    blobs = []
    for sz in sizes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        app_pixmap(sz).toImage().save(buf, "PNG")
        buf.close()
        blobs.append(bytes(ba))
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for sz, b in zip(sizes, blobs):
        out += struct.pack("<BBBBHHII", sz % 256, sz % 256, 0, 0, 1, 32, len(b), offset)
        offset += len(b)
    with open(path, "wb") as f:
        f.write(out + b"".join(blobs))


def app_icon():
    ic = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        ic.addPixmap(app_pixmap(sz))
    return ic


# ---------------------------------------------------------------- stylesheet
def stylesheet(accent=None):
    A = accent or ACCENT
    A_TEXT = on_accent(A)
    A_HOVER = QColor(A).lighter(112).name()
    A_PRESS = QColor(A).darker(115).name()
    A_SOFT = rgba(A, 0.16)
    A_FAINT = rgba(A, 0.10)
    A_LINE = rgba(A, 0.55)
    A_BRIGHT = QColor(A).lighter(125).name() if MODE == "dark" else QColor(A).darker(118).name()
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 9.5pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#page, QWidget#bar {{ background: {BG}; }}
QWidget#bar {{ border-bottom: 1px solid {LINE}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px 7px; border-radius: 6px; }}

QToolButton {{ background: transparent; border: none; border-radius: 7px; padding: 6px; }}
QToolButton:hover {{ background: {HOVER}; }}
QToolButton:pressed {{ background: {ACTIVE}; }}
QToolButton:checked {{ background: {rgba(A, 0.24)}; }}
QToolButton:checked:hover {{ background: {rgba(A, 0.32)}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#chip {{ padding: 5px 10px; color: {MUTED}; }}
QToolButton#chip:checked {{ color: {A_BRIGHT}; }}

QPushButton {{ background: transparent; border: 1px solid {LINE}; border-radius: 7px; padding: 6px 14px; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: {ACTIVE}; }}
QPushButton#primary {{ background: {A}; border: 1px solid {A}; color: {A_TEXT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {A_HOVER}; border-color: {A_HOVER}; }}
QPushButton#primary:pressed {{ background: {A_PRESS}; border-color: {A_PRESS}; }}
QPushButton#ghost {{ border: none; color: {MUTED}; padding: 4px 8px; }}
QPushButton#ghost:hover {{ color: {TEXT}; background: {HOVER}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 7px;
    padding: 5px 9px; selection-background-color: {rgba(A, 0.45)}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {A_LINE}; }}
QLineEdit#search {{ background: {SURFACE}; border: 1px solid transparent; padding: 6px 10px; }}
QLineEdit#search:focus {{ border-color: {A_LINE}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {LINE}; outline: none; padding: 4px;
    selection-background-color: {ACTIVE}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {CHECK_LINE}; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {A}; border-color: {A}; }}

QSlider::groove:horizontal {{ height: 2px; background: {GROOVE}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {A}; border-radius: 1px; }}
QSlider::handle:horizontal {{ background: {HANDLE}; border: 1px solid {HANDLE_LINE}; width: 10px; height: 10px; margin: -5px 0; border-radius: 6px; }}

QScrollArea {{ border: none; background: {CANVAS}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle {{ background: {SCROLL}; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {SCROLL_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}

QMenu {{ background: {SURFACE}; border: 1px solid {LINE}; padding: 5px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACTIVE}; }}
QMenu::item:disabled {{ color: {DIM}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}

QListWidget {{ background: {BG}; border: none; outline: none; }}
QListWidget::item {{ border-radius: 10px; padding: 8px; color: {MUTED}; }}
QListWidget::item:hover {{ background: {LIST_HOVER}; }}
QListWidget::item:selected {{ background: {LIST_SEL}; color: {TEXT}; }}

QLabel#h1 {{ font-size: 12pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QFrame#codebar {{ background: {FLOAT}; border: 1px solid {FLOAT_LINE}; border-radius: 11px; }}
QFrame#codebar QLabel {{ background: transparent; }}
QLabel#codekind {{ color: {MUTED}; font-size: 8.5pt; }}
QLabel#toast {{ background: {FLOAT}; border: 1px solid {FLOAT_LINE}; border-radius: 9px; padding: 7px 14px; }}
QLabel#zoom {{ color: {MUTED}; background: transparent; padding: 4px 8px; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {SIDEBAR_LINE}; }}
QWidget#sidebar_mid {{ background: {SIDEBAR}; }}
QScrollArea#sidebarscroll {{ background: {SIDEBAR}; border: none; }}
QWidget#holder {{ background: {CANVAS}; }}
QWidget#content {{ background: {BG}; }}
QLabel#brand {{ font-size: 11pt; font-weight: 600; }}
QLabel#section {{ color: {DIM}; font-size: 8pt; font-weight: 600; letter-spacing: 0.6px; padding: 0 10px; }}
QLabel#pagetitle {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 17pt; font-weight: 600; }}
QLabel#group {{ font-size: 10pt; font-weight: 600; color: {GROUP}; }}
QLabel#groupcount {{ color: {DIM}; }}
QPushButton#nav {{ text-align: left; border: none; border-radius: 7px; padding: 7px 10px; color: {NAV}; }}
QPushButton#nav:hover {{ background: {NAV_HOVER}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {A_FAINT}; color: {STRONG}; }}
QLabel#navcount {{ color: {DIM}; font-size: 8.5pt; background: transparent; }}
QFrame#capcard {{ background: {CARD}; border: 1px solid {CARD_LINE}; border-radius: 12px; }}
QFrame#capcard:hover {{ background: {CARD_HOVER}; border-color: {rgba(A, 0.40)}; }}
QLabel#captitle {{ font-weight: 600; background: transparent; }}
QLabel#capsub {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QLabel#iconwell {{ background: {WELL}; border-radius: 9px; }}
QLabel#kbd {{ background: {KBD}; border: 1px solid {KBD_LINE}; border-bottom: 2px solid {KBD_LINE}; border-radius: 5px;
    padding: 1px 6px; color: {KBD_TEXT}; font-size: 8pt; font-family: "Segoe UI"; }}
QFrame#tile {{ background: transparent; border: 1px solid transparent; border-radius: 12px; }}
QFrame#tile:hover {{ background: {TILE_HOVER}; border-color: {CARD_LINE}; }}
QFrame#tile[selected="true"] {{ background: {A_FAINT}; border-color: {A_LINE}; }}
QFrame#tile[kbd="true"] {{ border-color: {A}; }}
QWidget#band {{ background: {rgba(A, 0.15)}; border: 1px solid {rgba(A, 0.7)}; border-radius: 3px; }}
QLabel#tiletitle {{ background: transparent; }}
QLabel#tilemeta {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QFrame#card {{ background: {CARD}; border: 1px solid {CARD_LINE}; border-radius: 12px; }}
QFrame#hair {{ background: {CARD_LINE}; }}
QLabel#rowtitle {{ background: transparent; }}
QLabel#rowdesc {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QFrame#tip {{ background: {TIP}; border: 1px solid {TIP_LINE}; border-radius: 10px; }}
QFrame#empty {{ border: 1.5px dashed {EMPTY_LINE}; border-radius: 16px; background: {EMPTY}; }}
QScrollArea#lib {{ background: {BG}; }}
QFrame#pill {{ background: {PILL}; border: 1px solid {PILL_LINE}; border-radius: 15px; }}
QLabel#pilltext {{ color: {MUTED}; background: transparent; }}
QFrame#pilldiv {{ background: {PILL_DIV}; border: none; }}
QPushButton#pillbtn {{ background: transparent; color: {PILL_TEXT}; border: none; border-radius: 11px;
    padding: 0 10px; font-weight: 600; }}
QPushButton#pillbtn:hover {{ background: {PILL_HOVER}; }}
QPushButton#pillbtn:pressed {{ background: {ACTIVE}; }}
QPushButton#ghost[active="true"] {{ color: {A_BRIGHT}; background: {A_SOFT}; }}
QToolButton#appchip {{ background: {CHIP}; border: 1px solid {CHIP_LINE}; border-radius: 13px; padding: 4px 10px; color: {CHIP_TEXT}; }}
QToolButton#appchip:hover {{ background: {CHIP_HOVER}; }}
QToolButton#appchip:checked {{ background: {A}; border-color: {A}; color: {A_TEXT}; }}
QDateEdit {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 7px; padding: 5px 9px; }}
QDateEdit:disabled {{ color: {DIM}; }}
QDateEdit::drop-down {{ border: none; width: 20px; }}
QCalendarWidget QWidget {{ alternate-background-color: {SURFACE}; }}
QCalendarWidget QToolButton {{ color: {TEXT}; }}
QCalendarWidget QAbstractItemView:enabled {{ background: {SURFACE}; selection-background-color: {A}; selection-color: {A_TEXT}; }}
QToolButton#swatch {{ border-radius: 12px; padding: 0; border: 2px solid transparent; }}
QToolButton#swatch:checked {{ border-color: {SWATCH_ON}; }}
QToolButton#swatch:hover {{ border-color: {SWATCH_HOVER}; }}
QToolButton#seg {{ border: 1px solid {LINE}; border-radius: 0; padding: 5px 12px; color: {MUTED}; }}
QToolButton#seg:checked {{ background: {A_SOFT}; color: {STRONG}; border-color: {A_LINE}; }}
QFrame#popup {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#popup QLabel {{ color: {MUTED}; }}
QFrame#vline {{ background: {LINE}; }}
"""


def apply_theme(app, accent=None, appearance=None):
    """Colours for every window. appearance = "system" | "light" | "dark" (None keeps the current choice)."""
    global ACCENT, APPEARANCE, MODE, _ICON_GEN
    if accent:
        ACCENT = accent
    if appearance:
        APPEARANCE = appearance
    MODE = ("dark" if system_is_dark() else "light") if APPEARANCE == "system" else APPEARANCE
    globals().update(PALETTES[MODE])
    _ICON_GEN += 1
    app.setStyle("Fusion")
    pal = QPalette()
    for role, col in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, SURFACE),
                      (QPalette.AlternateBase, BG), (QPalette.Text, TEXT), (QPalette.Button, SURFACE),
                      (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT),
                      (QPalette.HighlightedText, on_accent(ACCENT)), (QPalette.ToolTipBase, SURFACE),
                      (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, DIM)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())
    from . import winapi
    from PySide6.QtWidgets import QDialog, QMainWindow
    for w in app.topLevelWidgets():    # custom-painted bits (toggles, icons, title bars) pick up the change
        if isinstance(w, (QMainWindow, QDialog)) and w.testAttribute(Qt.WA_WState_Created):
            winapi.style_window(w.winId())
        for c in [w] + w.findChildren(QLabel):
            c.update()
        w.update()


_watching = False


def follow_system(app, on_change=None):
    """Re-theme when Windows switches between light and dark (only matters in "system" mode)."""
    global _watching
    if _watching:
        return
    _watching = True

    def changed(*_):
        if APPEARANCE == "system":
            apply_theme(app)
            if on_change:
                on_change()
    try:
        app.styleHints().colorSchemeChanged.connect(changed)
    except Exception:
        pass


STYLESHEET = stylesheet()   # backwards name


def vline(height=20):
    from PySide6.QtWidgets import QFrame
    f = QFrame()
    f.setObjectName("vline")
    f.setFixedSize(1, height)
    return f
