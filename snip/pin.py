"""Pin an image to the screen as an always-on-top floating window."""
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

BTN = 24     # close button size (logical px)
EDGE = 8     # resize grab margin


class PinWindow(QWidget):
    def __init__(self, app, img):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.app = app
        self.img = img
        self.key = None
        self.on_close = None
        self.locked = False
        self.click_through = False
        self.pm = QPixmap.fromImage(img)
        self._drag = None
        self._resize_edges = None
        self._start_geo = None
        self._start_pos = None
        self._hover = False
        self._over_close = False
        self._flash = False
        self.setToolTip("Drag to move · Drag edges to resize · Scroll to zoom · Ctrl+scroll for opacity · "
                        "× or Esc to unpin")
        # open centred on the screen the user is working on, shrunk to fit if it's big
        scr = QApplication.screenAt(app.last_cursor_pos()) or QApplication.primaryScreen()
        avail = scr.availableGeometry()
        dpr = scr.devicePixelRatio()
        iw, ih = img.width() / dpr, img.height() / dpr
        k = min(1.0, avail.width() * 0.6 / max(1, iw), avail.height() * 0.6 / max(1, ih))
        w, h = max(60, int(iw * k)), max(40, int(ih * k))
        self.setGeometry(QRect(avail.center().x() - w // 2, avail.center().y() - h // 2, w, h))
        self.setCursor(Qt.SizeAllCursor)

    @property
    def aspect(self):
        return self.img.width() / max(1, self.img.height())

    # ---------------------------------------------------------------- painting
    def flash(self):
        """Briefly highlight - used when the user pins something that's already pinned."""
        self._flash = True
        self.update()
        QTimer.singleShot(450, self, self._unflash)

    def _unflash(self):
        self._flash = False
        self.update()

    def _close_rect(self):
        return QRectF(self.width() - BTN - 6, 6, BTN, BTN)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(self.rect().adjusted(1, 1, -1, -1), self.pm)
        p.setPen(QPen(QColor(255, 255, 255, 230), 3) if self._flash else QPen(QColor(255, 255, 255, 50), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        if self._hover and not self.click_through:
            r = self._close_rect()
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.setBrush(QColor(200, 40, 40, 235) if self._over_close else QColor(20, 20, 20, 225))
            p.drawEllipse(r)
            c = r.center()
            p.setPen(QPen(QColor("white"), 1.6, Qt.SolidLine, Qt.RoundCap))
            d = 4.5
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
            if self.locked:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(20, 20, 20, 210))
                p.drawRoundedRect(QRectF(6, 6, 52, 20), 10, 10)
                p.setPen(QColor("#ddd"))
                p.drawText(QRectF(6, 6, 52, 20), Qt.AlignCenter, "Locked")

    # ---------------------------------------------------------------- hit areas
    def _edges_at(self, pos):
        if self.locked:
            return None
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        edges = 0
        if x <= EDGE:
            edges |= Qt.LeftEdge
        elif x >= w - EDGE:
            edges |= Qt.RightEdge
        if y <= EDGE:
            edges |= Qt.TopEdge
        elif y >= h - EDGE:
            edges |= Qt.BottomEdge
        return edges or None

    @staticmethod
    def _cursor_for(edges):
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if edges in (Qt.LeftEdge, Qt.RightEdge):
            return Qt.SizeHorCursor
        return Qt.SizeVerCursor

    # ---------------------------------------------------------------- mouse
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = self._over_close = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self._close_rect().contains(pos):
            self.close()
            return
        edges = self._edges_at(pos)
        if edges:
            self._resize_edges = edges
            self._start_geo = self.geometry()
            self._start_pos = e.globalPosition()
        elif not self.locked:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._resize_edges:
            self._do_resize(e.globalPosition())
            return
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
            return
        pos = e.position()
        over = self._close_rect().contains(pos)
        if over != self._over_close:
            self._over_close = over
            self.update()
        edges = self._edges_at(pos)
        if over:
            self.setCursor(Qt.PointingHandCursor)
        elif edges:
            self.setCursor(self._cursor_for(edges))
        else:
            self.setCursor(Qt.ArrowCursor if self.locked else Qt.SizeAllCursor)

    def _do_resize(self, gpos):
        """Resize from any edge/corner with the image's proportions locked; the opposite side stays put."""
        g, d, ed = self._start_geo, gpos - self._start_pos, self._resize_edges
        ar = self.aspect
        dw = d.x() if ed & Qt.RightEdge else -d.x() if ed & Qt.LeftEdge else 0
        dh = d.y() if ed & Qt.BottomEdge else -d.y() if ed & Qt.TopEdge else 0
        # follow whichever direction the user pulled further (in matching units)
        w = g.width() + dw if abs(dw) >= abs(dh) * ar else (g.height() + dh) * ar
        w = max(60.0, min(w, 8000.0))
        h = w / ar
        x = g.right() - w + 1 if ed & Qt.LeftEdge else g.x()
        y = g.bottom() - h + 1 if ed & Qt.TopEdge else g.y()
        if not ed & (Qt.LeftEdge | Qt.RightEdge):      # top/bottom only: grow around the centre
            x = g.center().x() - w / 2
        if not ed & (Qt.TopEdge | Qt.BottomEdge):      # left/right only
            y = g.center().y() - h / 2
        self.setGeometry(QRect(int(x), int(y), int(w), int(h)))

    def mouseReleaseEvent(self, e):
        self._drag = None
        self._resize_edges = None

    def mouseDoubleClickEvent(self, e):
        if not self._edges_at(e.position()):
            self.close()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Delete):
            self.close()
        elif e.matches(QKeySequence.Copy):
            QApplication.clipboard().setImage(self.img)

    def wheelEvent(self, e):
        up = e.angleDelta().y() > 0
        if e.modifiers() & Qt.ControlModifier:
            self.setWindowOpacity(max(0.2, min(1.0, self.windowOpacity() + (0.1 if up else -0.1))))
        elif not self.locked:
            c = self.geometry().center()
            w = max(60, min(8000, int(self.width() * (1.1 if up else 1 / 1.1))))
            h = int(w / self.aspect)
            self.setGeometry(QRect(c.x() - w // 2, c.y() - h // 2, w, h))

    def actual_size(self):
        dpr = self.devicePixelRatioF()
        c = self.geometry().center()
        w, h = int(self.img.width() / dpr), int(self.img.height() / dpr)
        self.setGeometry(QRect(c.x() - w // 2, c.y() - h // 2, w, h))

    # ---------------------------------------------------------------- modes
    def set_locked(self, on):
        self.locked = on
        self.update()

    def set_click_through(self, on):
        """Clicks pass through to the window underneath. Turn off from the tray menu."""
        self.click_through = on
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowTransparentForInput, on)
        self.setGeometry(geo)
        self.show()
        if on and self.windowOpacity() > 0.85:
            self.setWindowOpacity(0.7)
        elif not on:
            self.setWindowOpacity(1.0)
        self.app.pins_changed()

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Copy", lambda: QApplication.clipboard().setImage(self.img))
        m.addAction("Edit", lambda: (self.app.open_editor(image=self.img), self.close()))
        m.addAction("Actual size", self.actual_size)
        op = m.addMenu("Opacity")
        for v in (100, 80, 60, 40):
            op.addAction(f"{v}%", lambda v=v: self.setWindowOpacity(v / 100))
        m.addSeparator()
        lock = m.addAction("Lock position")
        lock.setCheckable(True)
        lock.setChecked(self.locked)
        lock.toggled.connect(self.set_locked)
        m.addAction("Click-through (turn off from tray)", lambda: self.set_click_through(True))
        m.addSeparator()
        m.addAction("Unpin", self.close)
        if len(getattr(self.app, "pins", [])) > 1:
            m.addAction("Unpin all", self.app.close_pins)
        m.exec(e.globalPos())
