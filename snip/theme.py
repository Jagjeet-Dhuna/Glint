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
    # "ink": warm near-blacks, like a well-used workbench at night
    "dark": dict(
        BG="#171614", SURFACE="#1e1c19", CANVAS="#0f0e0d", LINE="#2c2a26", HOVER="#23211e", ACTIVE="#2e2b27",
        TEXT="#ebe5da", MUTED="#a39a8c", DIM="#928a7e", STRONG="#fbf6ec",
        SIDEBAR="#131211", SIDEBAR_LINE="#24221f", NAV="#b9b1a4", NAV_HOVER="#1c1a17", GROUP="#ebe5da",
        CARD="#1c1a17", CARD_LINE="#2a2824", CARD_HOVER="#211f1b", WELL="#26231f", TIP="#1a1816", TIP_LINE="#2a2824",
        KBD="transparent", KBD_LINE="#3a362f", KBD_TEXT="#cfc7ba",
        TILE_HOVER="#1d1b18", THUMB="#211f1b", THUMB_EDGE="rgba(255,240,220,16)",
        EMPTY="transparent", EMPTY_LINE="#34302a",
        FLOAT="rgba(30,28,25,245)", FLOAT_LINE="#3a362f",
        CHECK_LINE="#6e675a", SCROLL="#38342e", SCROLL_HOVER="#4b463d",
        GROOVE="#36322c", HANDLE="#f2ece1", HANDLE_LINE="#f2ece1",
        PILL="#1e1c19", PILL_LINE="#34302a", PILL_DIV="#34302a", PILL_TEXT="#f2ece1", PILL_HOVER="#2a2723",
        CHIP="#211f1b", CHIP_LINE="#34302a", CHIP_TEXT="#c4bcaf", CHIP_HOVER="#2a2723",
        SWATCH_ON="#fbf6ec", SWATCH_HOVER="#8f877a",
        TOG_OFF="#24221e", TOG_OFF_LINE="#3d3932", TOG_KNOB="#8f877a",
        ICON_OFF="#a79e91", ICON_ON="#fbf6ec", ICON_DISABLED="#4a463f",
        LIST_HOVER="#1e1c19", LIST_SEL="#26231f"),
    # "paper": warm off-whites and ink-black text
    "light": dict(
        BG="#f3efe7", SURFACE="#fbf9f4", CANVAS="#e5dfd3", LINE="#dcd5c7", HOVER="#e9e4da", ACTIVE="#e0d9cc",
        TEXT="#1f1c17", MUTED="#5c554a", DIM="#6d6559", STRONG="#110f0c",
        SIDEBAR="#ebe6dc", SIDEBAR_LINE="#ddd6c8", NAV="#4a443b", NAV_HOVER="#e3ddd1", GROUP="#1f1c17",
        CARD="#fbf9f4", CARD_LINE="#e0d9cb", CARD_HOVER="#fffdf8", WELL="#ece6db", TIP="#fbf9f4", TIP_LINE="#e0d9cb",
        KBD="transparent", KBD_LINE="#cfc7b8", KBD_TEXT="#3d372f",
        TILE_HOVER="#ebe6dc", THUMB="#e2dccf", THUMB_EDGE="rgba(40,30,10,26)",
        EMPTY="transparent", EMPTY_LINE="#cfc7b8",
        FLOAT="rgba(251,249,244,246)", FLOAT_LINE="#d6cfc1",
        CHECK_LINE="#8f8679", SCROLL="#cbc3b5", SCROLL_HOVER="#b3aa9b",
        GROOVE="#d3cbbd", HANDLE="#fbf9f4", HANDLE_LINE="#b3aa9b",
        PILL="#fbf9f4", PILL_LINE="#dcd5c7", PILL_DIV="#e2dccf", PILL_TEXT="#1f1c17", PILL_HOVER="#efeae0",
        CHIP="#fbf9f4", CHIP_LINE="#dcd5c7", CHIP_TEXT="#3d372f", CHIP_HOVER="#efeae0",
        SWATCH_ON="#1f1c17", SWATCH_HOVER="#9a9184",
        TOG_OFF="#e2dccf", TOG_OFF_LINE="#c9c1b2", TOG_KNOB="#776f62",
        ICON_OFF="#5a5348", ICON_ON="#110f0c", ICON_DISABLED="#c4bcae",
        LIST_HOVER="#e9e4da", LIST_SEL="#e0d9cc"),
}
MODE = "dark"           # resolved mode actually showing: "dark" | "light"
APPEARANCE = "system"   # the user's choice: "system" | "light" | "dark"
_ICON_GEN = 0           # bumps on every theme change so live icons redraw

globals().update(PALETTES["dark"])
ACCENT = "#e8a33d"     # set from settings by apply_theme()
ACCENTS = [("Amber", "#e8a33d"), ("Blue", "#4c8dff"), ("Violet", "#8b6cff"), ("Teal", "#20b2a0"),
           ("Green", "#3fb950"), ("Rose", "#ff5c8a"), ("Ink", "#e6e1d8")]
UI_FONT = "IBM Plex Sans"
MONO_FONT = "IBM Plex Mono"
_fonts_loaded = False


def load_fonts():
    """Glint's own typefaces (IBM Plex, SIL Open Font License), shipped in assets/fonts."""
    global _fonts_loaded, UI_FONT, MONO_FONT
    if _fonts_loaded:
        return
    _fonts_loaded = True
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    d = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    fams = set()
    for p in sorted(d.glob("*.ttf")):
        i = QFontDatabase.addApplicationFont(str(p))
        if i >= 0:
            fams.update(QFontDatabase.applicationFontFamilies(i))
    if "IBM Plex Sans" not in fams:
        UI_FONT = "Segoe UI"            # fonts missing: fall back quietly
    if "IBM Plex Mono" not in fams:
        MONO_FONT = "Cascadia Mono"


FOLDER_COLORS = ["#e0805e", "#73b79a", "#a99ae0", "#d9b25c", "#7aaee0", "#d97aa5", "#9cb86a", "#c49a6c"]
LOOSE_COLOR = "#6a6358"
MODE_COLORS = {"full": "#d9b25c", "scroll": "#73b79a", "text": "#7aaee0", "timer": "#a99ae0", "game": "#b9b1a4"}


def folder_color(name):
    """A folder's colour: stable for its name (same colour every run, on every PC)."""
    if not name:
        return LOOSE_COLOR
    h = 0
    for ch in name.lower():
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return FOLDER_COLORS[h % len(FOLDER_COLORS)]


def dot_pixmap(color, size=16, dot=8, radius=2.0, dpr=2.0):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(dpr, dpr)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    o = (size - dot) / 2
    p.drawRoundedRect(QRectF(o, o, dot, dot), radius, radius)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def tile_icon_pixmap(name, color, size=30, filled=False, dpr=2.0):
    """A capture-mode swatch: the icon in its colour on a soft tint of it (or dark on the solid colour)."""
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(dpr, dpr)
    p.setPen(Qt.NoPen)
    bg = QColor(color)
    if not filled:
        bg.setAlpha(40)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0, 0, size, size), 6, 6)
    k = 16 / 24.0
    p.translate((size - 16) / 2, (size - 16) / 2)
    p.scale(k, k)
    _draw(name, p, QColor(on_accent(color)) if filled else QColor(color))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def sparkle_path(cx, cy, R, r=None):
    """Glint's mark: a four-point star with softly curved sides."""
    r = r if r is not None else R * 0.22
    pts = [(0, -R), (r, -r), (R, 0), (r, r), (0, R), (-r, r), (-R, 0), (-r, -r)]
    path = QPainterPath(QPointF(cx + pts[0][0], cy + pts[0][1]))
    for i in range(1, 9):
        a, prev = pts[i % 8], pts[(i - 1) % 8]
        path.quadTo(QPointF(cx + (a[0] + prev[0]) * 0.18, cy + (a[1] + prev[1]) * 0.18), QPointF(cx + a[0], cy + a[1]))
    return path


def sparkle_pixmap(size, color=None, dpr=2.0):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(dpr, dpr)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color or ACCENT))
    p.drawPath(sparkle_path(size / 2, size / 2, size / 2 - 0.5))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def rgba(c, a):
    q = QColor(c)
    return f"rgba({q.red()}, {q.green()}, {q.blue()}, {int(a * 255)})"


def on_accent(c):
    """Text colour that reads on top of the accent."""
    q = QColor(c)
    lin = [((v / 255) / 12.92 if v / 255 <= 0.04045 else (((v / 255) + 0.055) / 1.055) ** 2.4)
           for v in (q.red(), q.green(), q.blue())]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    # whichever of near-black / white reads better (WCAG contrast), not a fixed brightness cut-off
    return "#111111" if (lum + 0.05) / (0.0056 + 0.05) >= 1.05 / (lum + 0.05) else "#ffffff"


def luminance(c):
    q = QColor(c)
    f = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(q.red()) + 0.7152 * f(q.green()) + 0.0722 * f(q.blue())


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(c, bg=None, need=4.5):
    """c nudged lighter (on dark backgrounds) or darker (on light ones) until it reaches `need`:1 against bg.
    4.5 for text, 3 for outlines/icons (WCAG AA)."""
    bg = bg or BG
    q = QColor(c)
    up = luminance(bg) < 0.18
    for _ in range(120):
        if contrast(q.name(), bg) >= need:
            break
        h, s, l, a = q.getHsl()
        q.setHsl(max(h, 0), s, min(255, l + 2) if up else max(0, l - 2), a)
    return q.name()


def accent_stroke():
    """Accent for outlines (selection, focus ring) that stays visible on the current background."""
    return readable(ACCENT, BG, 3)


def accent_text():
    return readable(QColor(ACCENT).lighter(118).name() if MODE == "dark" else QColor(ACCENT).darker(130).name(),
                    BG, 4.5)


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
    elif name == "chevronleft":
        p.drawPolyline(L((14.5, 6), (8.5, 12), (14.5, 18)))
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
    A_HOVER = QColor(A).lighter(110).name()
    A_PRESS = QColor(A).darker(112).name()
    A_SOFT = rgba(A, 0.16)
    A_FAINT = rgba(A, 0.09)
    A_LINE = readable(A, BG, 3)          # focus borders: 3:1 against the window (WCAG 1.4.11)
    A_BRIGHT = readable(QColor(A).lighter(118).name() if MODE == "dark" else QColor(A).darker(130).name(), BG, 4.5)
    F, M = UI_FONT, MONO_FONT
    return f"""
* {{ font-family: "{F}", "Segoe UI"; font-size: 9.5pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#page, QWidget#bar {{ background: {BG}; }}
QWidget#bar {{ border-bottom: 1px solid {LINE}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {LINE}; padding: 5px 8px; border-radius: 4px; }}

QPushButton, QToolButton, QCheckBox, QAbstractButton {{ outline: none; }}  /* a11y.FocusRing shows keyboard focus */
QToolButton {{ background: transparent; border: none; border-radius: 5px; padding: 6px; }}
QToolButton:hover {{ background: {HOVER}; }}
QToolButton:pressed {{ background: {ACTIVE}; }}
QToolButton:checked {{ background: {rgba(A, 0.22)}; }}
QToolButton:checked:hover {{ background: {rgba(A, 0.30)}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#chip {{ padding: 5px 10px; color: {MUTED}; }}
QToolButton#chip:checked {{ color: {A_BRIGHT}; }}

QPushButton {{ background: transparent; border: 1px solid {LINE}; border-radius: 5px; padding: 6px 14px; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: {ACTIVE}; }}
QPushButton#primary {{ background: {A}; border: 1px solid {A}; color: {A_TEXT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {A_HOVER}; border-color: {A_HOVER}; }}
QPushButton#primary:pressed {{ background: {A_PRESS}; border-color: {A_PRESS}; }}
QPushButton#ghost {{ border: none; color: {MUTED}; padding: 4px 8px; }}
QPushButton#ghost:hover {{ color: {TEXT}; background: {HOVER}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 5px;
    padding: 5px 9px; selection-background-color: {rgba(A, 0.45)}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {A_LINE}; }}
QLineEdit#search {{ background: transparent; border: none; border-bottom: 1px solid {LINE}; border-radius: 0;
    padding: 6px 4px; }}
QLineEdit#search:focus {{ border-bottom: 1px solid {A}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {LINE}; outline: none; padding: 4px;
    selection-background-color: {ACTIVE}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 3px; border: 1px solid {CHECK_LINE}; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {A}; border-color: {A}; }}

QSlider::groove:horizontal {{ height: 2px; background: {GROOVE}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {A}; border-radius: 1px; }}
QSlider::handle:horizontal {{ background: {HANDLE}; border: 1px solid {HANDLE_LINE}; width: 10px; height: 10px; margin: -5px 0; border-radius: 6px; }}

QScrollArea {{ border: none; background: {CANVAS}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle {{ background: {SCROLL}; border-radius: 2px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {SCROLL_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}

QMenu {{ background: {SURFACE}; border: 1px solid {LINE}; padding: 4px; border-radius: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 3px; }}
QMenu::item:selected {{ background: {ACTIVE}; }}
QMenu::item:disabled {{ color: {DIM}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}

QListWidget {{ background: {BG}; border: none; outline: none; }}
QListWidget::item {{ border-radius: 4px; padding: 8px; color: {MUTED}; }}
QListWidget::item:hover {{ background: {LIST_HOVER}; }}
QListWidget::item:selected {{ background: {LIST_SEL}; color: {TEXT}; }}

QLabel#h1 {{ font-size: 13pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QFrame#codebar {{ background: {FLOAT}; border: 1px solid {FLOAT_LINE}; border-radius: 7px; }}
QFrame#codebar QLabel {{ background: transparent; }}
QLabel#codekind {{ color: {MUTED}; font-family: "{M}"; font-size: 8pt; }}
QLabel#toast {{ background: {FLOAT}; border: 1px solid {FLOAT_LINE}; border-radius: 6px; padding: 7px 14px; }}
QLabel#zoom {{ color: {MUTED}; background: transparent; padding: 4px 8px; font-family: "{M}"; font-size: 8pt; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {SIDEBAR_LINE}; }}
QWidget#sidebar_mid {{ background: {SIDEBAR}; }}
QScrollArea#sidebarscroll {{ background: {SIDEBAR}; border: none; }}
QWidget#holder {{ background: {CANVAS}; }}
QWidget#content {{ background: {BG}; }}
QLabel#brand {{ font-size: 12pt; font-weight: 600; letter-spacing: -0.2px; }}
QLabel#section {{ color: {DIM}; font-size: 8.5pt; font-weight: 500; padding: 0 12px; }}
QLabel#pagetitle {{ font-size: 19pt; font-weight: 600; letter-spacing: -0.4px; }}
QLabel#group {{ font-size: 10.5pt; font-weight: 600; color: {GROUP}; }}
QLabel#groupcount {{ color: {DIM}; font-family: "{M}"; font-size: 8.5pt; }}
QFrame#rule {{ background: {LINE}; border: none; }}
QPushButton#nav {{ text-align: left; border: none; border-left: 2px solid transparent; border-radius: 0;
    padding: 6px 10px 6px 12px; color: {NAV}; }}
QPushButton#nav:hover {{ color: {STRONG}; background: {NAV_HOVER}; }}
QPushButton#nav:checked {{ color: {STRONG}; background: transparent; border-left: 2px solid {A}; font-weight: 500; }}
QLabel#navcount {{ color: {DIM}; font-family: "{M}"; font-size: 8pt; background: transparent; }}
QToolButton#capbtn {{ border: 1px solid {LINE}; border-radius: 5px; padding: 6px 12px 6px 9px; color: {TEXT}; }}
QToolButton#capbtn:hover {{ border-color: {A_LINE}; background: {A_FAINT}; }}
QToolButton#capbtn[primary="true"] {{ background: {A}; border-color: {A}; color: {A_TEXT}; font-weight: 600; }}
QToolButton#capbtn[primary="true"]:hover {{ background: {A_HOVER}; border-color: {A_HOVER}; }}
#modetile {{ border: 1px solid {LINE}; border-radius: 6px; background: transparent; }}
#modetile:hover {{ border-color: {A_LINE}; background: {A_FAINT}; }}
#modetile[primary="true"] {{ border-color: {A}; background: {rgba(A, 0.10)}; }}
#modetile QLabel {{ background: transparent; border: none; }}
QLabel#modename {{ font-weight: 600; }}
QLabel#modenote {{ color: {MUTED}; font-family: "{M}"; font-size: 8pt; }}
QLabel#legendname {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QLabel#legendsize {{ color: {DIM}; font-family: "{M}"; font-size: 8pt; background: transparent; }}
QPushButton#collapse {{ border: 1px solid {LINE}; border-radius: 5px; color: {MUTED}; padding: 6px 8px; }}
QPushButton#collapse:hover {{ color: {TEXT}; background: {HOVER}; }}
QPushButton#nav[compact="true"] {{ padding: 7px 0; text-align: center; }}
QLabel#caphint {{ color: {DIM}; font-family: "{M}"; font-size: 8pt; background: transparent; }}
QFrame#capcard {{ background: {CARD}; border: 1px solid {CARD_LINE}; border-radius: 6px; }}
QFrame#capcard:hover {{ background: {CARD_HOVER}; border-color: {rgba(A, 0.40)}; }}
QLabel#captitle {{ font-weight: 600; background: transparent; }}
QLabel#capsub {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QLabel#iconwell {{ background: {WELL}; border-radius: 6px; }}
QLabel#kbd {{ background: {KBD}; border: 1px solid {KBD_LINE}; border-radius: 3px;
    padding: 0px 5px; color: {KBD_TEXT}; font-size: 8pt; font-family: "{M}"; }}
QFrame#tile {{ background: transparent; border: 1px solid transparent; border-radius: 6px; }}
QFrame#tile[kbd="true"] {{ border: 1px dashed {A_LINE}; }}
QWidget#band {{ background: {rgba(A, 0.12)}; border: 1px solid {rgba(A, 0.75)}; border-radius: 2px; }}
QLabel#tiletitle {{ background: transparent; }}
QLabel#tilemeta {{ color: {MUTED}; font-family: "{M}"; font-size: 8pt; background: transparent; }}
QFrame#card {{ background: transparent; border: none; border-top: 1px solid {LINE}; border-radius: 0; }}
QFrame#hair {{ background: {CARD_LINE}; }}
QLabel#rowtitle {{ background: transparent; }}
QLabel#rowdesc {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QFrame#tip {{ background: {TIP}; border: 1px solid {TIP_LINE}; border-radius: 6px; }}
QFrame#empty {{ border: none; background: transparent; }}
QScrollArea#lib {{ background: {BG}; }}
QFrame#pill {{ background: {PILL}; border: 1px solid {PILL_LINE}; border-radius: 6px; }}
QLabel#pilltext {{ color: {MUTED}; background: transparent; }}
QFrame#pilldiv {{ background: {PILL_DIV}; border: none; }}
QPushButton#pillbtn {{ background: transparent; color: {PILL_TEXT}; border: none; border-radius: 4px;
    padding: 0 10px; font-weight: 600; }}
QPushButton#pillbtn:hover {{ background: {PILL_HOVER}; }}
QPushButton#pillbtn:pressed {{ background: {ACTIVE}; }}
QPushButton#ghost[active="true"] {{ color: {A_BRIGHT}; background: {A_SOFT}; }}
QToolButton#appchip {{ background: {CHIP}; border: 1px solid {CHIP_LINE}; border-radius: 4px; padding: 4px 10px; color: {CHIP_TEXT}; }}
QToolButton#appchip:hover {{ background: {CHIP_HOVER}; }}
QToolButton#appchip:checked {{ background: {A}; border-color: {A}; color: {A_TEXT}; }}
QDateEdit {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 5px; padding: 5px 9px; }}
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
QFrame#popup {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 6px; }}
QFrame#popup QLabel {{ color: {MUTED}; }}
QFrame#vline {{ background: {LINE}; }}
"""


def apply_theme(app, accent=None, appearance=None):
    """Colours for every window. appearance = "system" | "light" | "dark" (None keeps the current choice)."""
    global ACCENT, APPEARANCE, MODE, _ICON_GEN
    load_fonts()
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


STYLESHEET = None   # (old name; the stylesheet is built per theme by stylesheet())


def vline(height=20):
    from PySide6.QtWidgets import QFrame
    f = QFrame()
    f.setObjectName("vline")
    f.setFixedSize(1, height)
    return f
