"""Floating thumbnail shown after each capture. Drag it into any app, or click to edit."""
import tempfile
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDrag, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from . import storage, theme

W, H = 240, 150


class Thumb(QWidget):
    clicked = Signal()

    def __init__(self, img, owner):
        super().__init__()
        self.owner = owner
        self.set_image(img)
        self.setFixedSize(W, H)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag into any app · Click to edit")
        self._press = None

    def set_image(self, img):
        self.img = img
        dpr = self.devicePixelRatioF()
        self.pm = QPixmap.fromImage(img).scaled(int(W * dpr), int(H * dpr), Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation)
        self.pm.setDevicePixelRatio(dpr)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        p.fillPath(path, QColor("#0d0d0d"))
        p.setClipPath(path)
        dpr = self.pm.devicePixelRatio()
        w, h = self.pm.width() / dpr, self.pm.height() / dpr
        p.drawPixmap(int((W - w) / 2), int((H - h) / 2), self.pm)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 8:
            return
        self._press = None
        path = self.owner.ensure_file()
        mime = QMimeData()
        mime.setImageData(self.img)
        if path:
            mime.setUrls([QUrl.fromLocalFile(str(path))])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.pm.scaled(int(self.pm.width() * 0.5), int(self.pm.height() * 0.5),
                                      Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.setHotSpot(QPoint(30, 20))
        self.owner.timer.stop()
        drag.exec(Qt.CopyAction)
        self.owner.dismiss()

    def mouseReleaseEvent(self, e):
        if self._press is not None:
            self._press = None
            self.clicked.emit()


class QuickPanel(QWidget):
    def __init__(self, app, img, path, original=None, hidden=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.app = app
        self.img = img
        self.original = original if original is not None else img
        self.hidden = list(hidden or [])
        self.path = Path(path) if path else None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.thumb = Thumb(img, self)
        self.thumb.clicked.connect(self.edit)
        lay.addWidget(self.thumb)
        if self.hidden:
            from .widgets import HiddenPill
            self.pill = HiddenPill()
            self.pill.set_count(len(self.hidden))
            self.pill.unhide.connect(self.unhide)
            lay.addWidget(self.pill, 0, Qt.AlignLeft)
        row = QHBoxLayout()
        row.setSpacing(2)
        for name, tip, fn in (("edit", "Edit", self.edit), ("copy", "Copy", self.copy), ("pin", "Pin", self.pin)):
            b = QToolButton()
            b.setIcon(theme.icon(name))
            b.setIconSize(QSize(16, 16))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        close = QToolButton()
        close.setIcon(theme.icon("close"))
        close.setIconSize(QSize(16, 16))
        close.setToolTip("Dismiss")
        close.clicked.connect(self.dismiss)
        row.addWidget(close)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self._lay = lay
        QTimer.singleShot(0, self, self._find_codes)   # after the panel is on screen - never delays it
        self.adjustSize()
        scr = QApplication.screenAt(self.app.last_cursor_pos()) or QApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.right() - self.width() - 16, g.bottom() - self.height() - 16)

    def _find_codes(self):
        from . import qr
        codes = qr.decode(self.original)
        if not codes:
            return
        text, kind = codes[0]
        row = QHBoxLayout()
        row.setSpacing(4)
        lbl = QLabel(f"{kind}: {text}" if len(codes) == 1 else f"{len(codes)} codes · {text}")
        lbl.setObjectName("muted")
        lbl.setToolTip(text)
        lbl.setMaximumWidth(W - 90)
        lbl.setText(lbl.fontMetrics().elidedText(lbl.text(), Qt.ElideRight, W - 90))
        row.addWidget(lbl, 1)
        if qr.is_link(text):
            op = QPushButton("Open")
            op.setToolTip(text)
            op.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(text.strip())), self.dismiss()))
            row.addWidget(op)
        cp = QPushButton("Copy")
        cp.clicked.connect(lambda: (QApplication.clipboard().setText("\n".join(c for c, _ in codes)),
                                    cp.setText("Copied")))
        row.addWidget(cp)
        self._lay.insertLayout(self._lay.count() - 1, row)
        bottom = self.geometry().bottom()
        self.adjustSize()
        self.move(self.x(), bottom - self.height() + 1)
        self.timer.start(9000)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(QColor(24, 24, 24, 248))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def showEvent(self, e):
        super().showEvent(e)
        from . import winapi
        winapi.exclude_from_capture(self.winId())   # never shows up in the next screenshot
        self.timer.start(7000)

    def enterEvent(self, e):
        self.timer.stop()

    def leaveEvent(self, e):
        self.timer.start(4000)

    def ensure_file(self):
        if self.path and self.path.exists():
            return self.path
        p = storage.new_capture_path(Path(tempfile.gettempdir()) / "Snip")
        try:
            storage.atomic_save(self.img, p)
            return p
        except Exception:
            return None

    def edit(self):
        if self.path and self.path.exists():
            self.app.open_editor(path=self.path)
        else:
            self.app.open_editor(image=self.original, shapes=self.hidden)
        self.dismiss()

    def unhide(self):
        """Swap in the uncensored capture: file, clipboard and thumbnail."""
        if self.path and self.path.exists():
            try:
                storage.unhide(self.path)
            except Exception:
                pass
        self.img = self.original
        self.hidden = []
        if self.app.settings.auto_copy:
            QApplication.clipboard().setImage(self.img)
        self.thumb.set_image(self.img)
        self.pill.set_done("Showing original")
        self.app.library_changed()
        self.timer.start(4000)

    def copy(self):
        QApplication.clipboard().setImage(self.img)
        self.dismiss()

    def pin(self):
        self.app.pin_image(self.img, key=("file", str(self.path)) if self.path else None)
        self.dismiss()

    def dismiss(self):
        self.timer.stop()
        self.close()
