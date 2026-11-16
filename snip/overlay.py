"""Full-screen capture overlay: frozen screenshot, region/window selection, magnifier."""
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QApplication, QWidget

from . import theme, winapi

DIM = QColor(0, 0, 0, 125)
ACCENT = QColor(255, 255, 255, 235)


class CaptureSession(QObject):
    """One capture. Grabs all monitors at once, then shows one overlay per screen."""
    finished = Signal(QImage, dict)
    cancelled = Signal()
    message = Signal(str)

    def __init__(self, mode="region", last_region=None, window_style="clean", hide_icons=False):
        super().__init__()
        self.mode = mode
        self.last_region = QRect(*last_region) if last_region else None
        self.window_style = window_style
        restore_icons = winapi.hide_desktop_icons() if hide_icons else None
        from .capture import grabber
        try:
            self.full, self.vx, self.vy = grabber.grab()
        finally:
            if restore_icons:
                restore_icons()     # the overlay shows the frozen grab, so icons can come straight back
        self.windows = winapi.list_windows()
        self.monitors = {name: QRect(l, t, r - l, b - t) for name, (l, t, r, b) in winapi.monitors()}
        self.overlays = []
        self._done = False

    def start(self):
        cx, cy = winapi.cursor_pos()
        if self.mode == "all":
            QTimer.singleShot(0, lambda: self.finish(QRect(self.vx, self.vy, self.full.width(), self.full.height()), {}))
            return
        if self.mode == "fullscreen":
            mon = next((r for r in self.monitors.values() if r.contains(cx, cy)), None)
            mon = mon or QRect(self.vx, self.vy, self.full.width(), self.full.height())
            QTimer.singleShot(0, lambda: self.finish(mon, {}))
            return
        active = None
        for screen in QGuiApplication.screens():
            native = self.native_rect_for(screen)
            if native is None:
                g = screen.geometry()
                dpr = screen.devicePixelRatio()
                native = QRect(g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr))
            ov = Overlay(self, screen, native)
            self.overlays.append(ov)
            if native.contains(cx, cy):
                active = ov
        for ov in self.overlays:
            ov.show()
        active = active or (self.overlays[0] if self.overlays else None)
        if active:
            active.raise_()
            active.activateWindow()
            winapi.force_foreground(active.winId())
            active.setFocus()

    def native_rect_for(self, screen):
        """Physical monitor rect for a QScreen. Qt keeps each screen's top-left at its native position."""
        g = screen.geometry()
        best, dist = None, None
        for r in self.monitors.values():
            d = abs(r.x() - g.x()) + abs(r.y() - g.y())
            if dist is None or d < dist:
                best, dist = r, d
        return best if dist is not None and dist <= 2 else None

    def window_at(self, gx, gy):
        for w in self.windows:
            l, t, r, b = w["rect"]
            if l <= gx < r and t <= gy < b:
                return w
        return None

    def info_for_rect(self, rect):
        c = rect.center()
        w = self.window_at(c.x(), c.y())
        return {"title": w["title"], "app": w["app"], "exe": "", "hwnd": w["hwnd"]} if w else {}

    def _close_overlays(self):
        for ov in self.overlays:
            ov.close()
        self.overlays = []

    def finish(self, global_rect, info):
        if self._done:
            return
        self._done = True
        self.last_rect = QRect(global_rect)
        self._close_overlays()
        local = global_rect.translated(-self.vx, -self.vy).intersected(self.full.rect())
        if local.width() < 1 or local.height() < 1:
            self.cancelled.emit()
            return
        img = self.full.copy(local)
        info = dict(info or {})
        if info.pop("window", False):
            img = window_finish(img, info.get("hwnd"), info.pop("dpr", 1.0), self.window_style,
                                covers_monitor=any(m.intersected(global_rect) == m for m in self.monitors.values()))
        info.pop("dpr", None)
        self.finished.emit(img, info)

    def window_info(self, w, dpr):
        return {"title": w["title"], "app": w["app"], "exe": "", "hwnd": w["hwnd"], "window": True, "dpr": dpr}

    def cancel(self):
        if self._done:
            return
        self._done = True
        self._close_overlays()
        self.cancelled.emit()


class Overlay(QWidget):
    def __init__(self, session, screen, native):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.s = session
        self.native = native
        self.img = session.full.copy(native.translated(-session.vx, -session.vy))
        geo = screen.geometry()
        # Qt rounds logical sizes to whole pixels (2560 px at 150% -> 1707), so native/logical is slightly off
        # (1.4997) and selections drift by a pixel or two. Use the screen's exact scale when it agrees.
        ratio = native.width() / max(1, geo.width())
        exact = screen.devicePixelRatio()
        self.dpr = exact if abs(exact - ratio) < 0.01 else ratio
        self.create()
        if self.windowHandle():
            self.windowHandle().setScreen(screen)
        self.setGeometry(geo)
        self.press = None      # physical local QPoint where mouse went down
        self.cur = None        # physical local QPoint of cursor
        self.dragging = False
        self.hover = None      # hovered window dict
        self.show_hint = True
        self.measuring = False     # M: ruler mode
        self.ruler = None          # (QPoint, QPoint) physical local
        p = QCursor.pos()
        if self.geometry().contains(p):
            self.cur = self._to_phys(QPointF(self.mapFromGlobal(p)))

    # ---- coordinate helpers (physical local <-> logical local)
    def _to_phys(self, pos):
        x = min(max(int(pos.x() * self.dpr), 0), self.img.width() - 1)
        y = min(max(int(pos.y() * self.dpr), 0), self.img.height() - 1)
        return QPoint(x, y)

    def _to_logical(self, rect):
        return QRectF(rect.x() / self.dpr, rect.y() / self.dpr, rect.width() / self.dpr, rect.height() / self.dpr)

    def _sel_phys(self):
        """Current selection in physical *local* pixels, or None."""
        if self.dragging and self.press and self.cur:
            x1, x2 = sorted((self.press.x(), self.cur.x()))
            y1, y2 = sorted((self.press.y(), self.cur.y()))
            return QRect(x1, y1, x2 - x1 + 1, y2 - y1 + 1)
        if self.hover:
            l, t, r, b = self.hover["rect"]
            return QRect(l, t, r - l, b - t).translated(-self.native.x(), -self.native.y()).intersected(self.img.rect())
        return None

    def _update_hover(self):
        if self.cur is None or self.dragging or self.measuring:
            self.hover = None
            return
        g = self.cur + self.native.topLeft()
        self.hover = self.s.window_at(g.x(), g.y())

    # ---- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawImage(QRectF(self.rect()), self.img)
        sel = self._sel_phys()
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        if sel:
            lr = self._to_logical(sel)
            hole = QPainterPath()
            hole.addRect(lr)
            p.fillPath(full.subtracted(hole), DIM)
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setPen(QPen(ACCENT, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(lr.adjusted(-0.5, -0.5, 0.5, 0.5))
            self._draw_label(p, lr, f"{sel.width()} × {sel.height()}"
                             + ("" if self.dragging or not self.hover or not self.hover.get("title") else
                                f"   {self.hover['title'][:60]}"))
        else:
            p.fillPath(full, DIM)
        if self.measuring:
            p.fillPath(full, QColor(0, 0, 0, 40)) if not sel else None
            self._draw_ruler(p)
        if self.cur is not None:
            self._draw_crosshair(p)
            self._draw_magnifier(p)
        if self.show_hint and self.cur is not None:
            self._draw_hint(p)

    def _draw_label(self, p, lr, text):
        f = QFont(theme.UI_FONT)
        f.setPixelSize(12)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 16, fm.height() + 8
        x = lr.x()
        y = lr.y() - h - 6
        if y < 4:
            y = lr.y() + 6
        x = min(max(4, x), self.width() - w - 4)
        box = QRectF(x, y, w, h)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, 235))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_ruler(self, p):
        if self.measuring and self.press is not None and self.cur is not None:
            a, b = self.press, self.cur
        elif self.ruler:
            a, b = self.ruler
        else:
            return
        import math
        la = QPointF((a.x() + 0.5) / self.dpr, (a.y() + 0.5) / self.dpr)
        lb = QPointF((b.x() + 0.5) / self.dpr, (b.y() + 0.5) / self.dpr)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawLine(la, lb)
        p.setPen(QPen(QColor("#ffd23f"), 1.5))
        p.drawLine(la, lb)
        for pt in (la, lb):
            p.drawEllipse(pt, 3, 3)
        dx, dy = abs(b.x() - a.x()), abs(b.y() - a.y())
        dist = math.hypot(dx, dy)
        text = f"{dist:.0f} px" + (f"   ↔ {dx}   ↕ {dy}" if dx and dy else "")
        mid = (la + lb) / 2
        self._draw_label(p, QRectF(mid.x() + 10, mid.y() + 4, 1, 1), text)

    def _draw_crosshair(self, p):
        x = (self.cur.x() + 0.5) / self.dpr
        y = (self.cur.y() + 0.5) / self.dpr
        p.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(255, 255, 255, 70), 1)
        p.setPen(pen)
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.drawLine(QPointF(0, y), QPointF(self.width(), y))

    def _draw_magnifier(self, p):
        n, cell = 15, 8
        size = n * cell
        cx, cy = self.cur.x(), self.cur.y()
        src = self.img.copy(QRect(cx - n // 2, cy - n // 2, n, n))
        lx, ly = cx / self.dpr, cy / self.dpr
        ox = lx + 24 if lx + 24 + size < self.width() else lx - 24 - size
        oy = ly + 24 if ly + 24 + size + 30 < self.height() else ly - 24 - size - 30
        box = QRectF(ox, oy, size, size)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(box, 8, 8)
        p.setClipPath(clip)
        p.fillRect(box, QColor("black"))
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawImage(box, src)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 8, 8)
        c = QRectF(ox + (n // 2) * cell, oy + (n // 2) * cell, cell, cell)
        p.setPen(QPen(QColor("white"), 1))
        p.drawRect(c)
        color = QColor(self.img.pixel(cx, cy))
        hexs = color.name().upper()
        f = QFont("Cascadia Mono")
        f.setStyleHint(QFont.Monospace)
        f.setPixelSize(11)
        label = f"{hexs}  {cx},{cy}"
        info_w = max(size, QFontMetrics(f).horizontalAdvance(label) + 34)
        info = QRectF(ox, oy + size + 4, info_w, 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, 230))
        p.drawRoundedRect(info, 5, 5)
        p.setBrush(color)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))
        p.drawRoundedRect(QRectF(info.x() + 5, info.y() + 5, 14, 14), 3, 3)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(info.adjusted(24, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        p.restore()

    def _draw_hint(self, p):
        if self.s.mode == "scroll":
            text = "Scrolling capture  ·  Select the area to scroll       Esc  Cancel"
        elif self.s.mode == "text":
            text = "Grab text  ·  Drag over the words to copy them       Esc  Cancel"
        elif self.measuring:
            text = "Measure  ·  Drag between two points       C  Copy colour       M  Back to capture       Esc  Cancel"
        else:
            text = ("Drag to capture     Click a window     F  Full screen     "
                    + ("R  Last area     " if self.s.last_region else "")
                    + "S  Scrolling     T  Text     M  Measure     C  Colour     Esc  Cancel")
        f = QFont(theme.UI_FONT)
        f.setPixelSize(13)
        p.setFont(f)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 36, 32
        box = QRectF((self.width() - w) / 2, 18, w, h)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.setBrush(QColor(20, 20, 20, 235))
        p.drawRoundedRect(box, 9, 9)
        p.setPen(QColor("#bdbdbd"))
        p.drawText(box, Qt.AlignCenter, text)

    # ---- input
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            if self.dragging:
                self.dragging = False
                self.press = None
                self.update()
            else:
                self.s.cancel()
            return
        if e.button() == Qt.LeftButton:
            self.press = self._to_phys(e.position())
            self.cur = self.press
            self.dragging = False
            self.show_hint = False
            self.update()

    def mouseMoveEvent(self, e):
        self.cur = self._to_phys(e.position())
        if self.press is not None and not self.dragging:
            if (self.cur - self.press).manhattanLength() > 3 * self.dpr:
                self.dragging = True
        self._update_hover()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.press is None:
            return
        self.cur = self._to_phys(e.position())
        if self.measuring:
            self.ruler = (self.press, self.cur) if self.dragging else None
            self.press = None
            self.dragging = False
            self.update()
            return
        sel = None
        info = {}
        if self.dragging:
            sel = self._sel_phys()
            if sel.width() < 3 or sel.height() < 3:
                sel = None
            else:
                info = self.s.info_for_rect(sel.translated(self.native.topLeft()))
        else:
            self._update_hover()
            if self.hover:
                l, t, r, b = self.hover["rect"]
                g = QRect(l, t, r - l, b - t)
                self.s.finish(g, self.s.window_info(self.hover, self.dpr))
                return
        self.press = None
        self.dragging = False
        if sel is not None:
            self.s.finish(sel.translated(self.native.topLeft()), info)
        else:
            self.update()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape:
            self.s.cancel()
        elif k in (Qt.Key_S, Qt.Key_T):
            self.s.mode = "scroll" if k == Qt.Key_S else "text"
            for ov in self.s.overlays:
                ov.show_hint = True
                ov.update()
        elif k in (Qt.Key_F, Qt.Key_Space) and self.s.mode != "scroll":
            self.s.finish(QRect(self.native), {})
        elif k == Qt.Key_R and self.s.last_region is not None and not self.measuring:
            r = self.s.last_region
            self.s.finish(QRect(r), self.s.info_for_rect(r))
        elif k == Qt.Key_M and self.s.mode in ("region",):
            for ov in self.s.overlays:
                ov.measuring = not ov.measuring
                ov.ruler = None
                ov.press = None
                ov.dragging = False
                ov.show_hint = True
                ov.update()
        elif k == Qt.Key_A and self.s.mode != "scroll":
            self.s.finish(QRect(self.s.vx, self.s.vy, self.s.full.width(), self.s.full.height()), {})
        elif k == Qt.Key_C and self.cur is not None:
            hexs = QColor(self.img.pixel(self.cur.x(), self.cur.y())).name().upper()
            QApplication.clipboard().setText(hexs)
            self.s.message.emit(f"Copied color {hexs}")
            self.s.cancel()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.hover:
            l, t, r, b = self.hover["rect"]
            self.s.finish(QRect(l, t, r - l, b - t), self.s.window_info(self.hover, self.dpr))
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if e.modifiers() & Qt.ShiftModifier else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            QCursor.setPos(QCursor.pos() + QPoint(dx, dy))

    def enterEvent(self, e):
        self.activateWindow()
        self.setFocus()

    def leaveEvent(self, e):
        if self.press is None:
            self.cur = None
            self.hover = None
            self.update()


def window_finish(img, hwnd, dpr, style, covers_monitor=False):
    """Window captures on Windows 11: the window has rounded corners, so the plain rectangle includes
    bits of whatever is behind it. "clean" makes those corners transparent; "shadow" also adds a soft
    drop shadow around the window (like macOS window shots)."""
    if style == "plain" or not winapi.rounded_windows() or covers_monitor or winapi.is_maximized(hwnd):
        return img
    w, h = img.width(), img.height()
    r = 8.0 * max(1.0, dpr)
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), r, r)
    p.setClipPath(clip)
    p.drawImage(0, 0, img)
    p.end()
    if style != "shadow":
        return out
    pad = max(20, int(28 * dpr))
    big = QImage(w + 2 * pad, h + 2 * pad, QImage.Format_ARGB32_Premultiplied)
    big.fill(Qt.transparent)
    # soft shadow: draw a dark rounded rect small, scale it up (cheap blur)
    k = 6
    sm = QImage(max(1, big.width() // k), max(1, big.height() // k), QImage.Format_ARGB32_Premultiplied)
    sm.fill(Qt.transparent)
    sp = QPainter(sm)
    sp.setRenderHint(QPainter.Antialiasing)
    sp.setPen(Qt.NoPen)
    sp.setBrush(QColor(0, 0, 0, 110))
    drop = pad * 0.25
    sp.drawRoundedRect(QRectF((pad) / k, (pad + drop) / k, w / k, h / k), r / k, r / k)
    sp.end()
    p = QPainter(big)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, big.width(), big.height()), sm.scaled(sm.width() * 2, sm.height() * 2,
                                                                  Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    p.drawImage(pad, pad, out)
    p.end()
    return big
