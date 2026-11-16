"""Home window: sidebar + capture modes + library grouped by date + settings page."""
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QDrag, QFontMetrics, QIcon, QImage, QKeySequence, QImageReader, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog,
                               QFileDialog, QFrame, QGridLayout, QMessageBox,
                               QHBoxLayout, QLabel, QLayout, QLineEdit, QMainWindow, QMenu, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import library, storage, theme, winapi

MIME = "application/x-glint-captures"

TW, TH = 232, 146  # thumbnail size


def kbd(text):
    l = QLabel(text)
    l.setObjectName("kbd")
    l.setFixedHeight(21)
    l.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return l


from .library import pretty_app  # noqa: E402


_icon_cache = {}


def app_icon_for(name, exe=""):
    """Icon cached from the app's window when it was captured (falls back to old exe paths)."""
    if name == "Glint":
        return theme.app_icon()
    p = library.icon_path(name) if name else None
    if p is not None and p.exists():
        from PySide6.QtGui import QIcon
        return QIcon(str(p))
    return exe_icon(exe)


def exe_icon(path):
    if not path:
        return None
    if path not in _icon_cache:
        from PySide6.QtCore import QFileInfo
        from PySide6.QtWidgets import QFileIconProvider
        ic = QFileIconProvider().icon(QFileInfo(path)) if Path(path).exists() else None
        _icon_cache[path] = ic if ic and not ic.isNull() else None
    return _icon_cache[path]


def icon_label(name, size=18, well=0):
    l = theme.IconLabel(name, size, theme.QIcon.Active)
    l.setAlignment(Qt.AlignCenter)
    if well:
        l.setObjectName("iconwell")
        l.setFixedSize(well, well)
    return l


def hotkey_parts(name):
    return [p.replace("Print Screen", "PrtScn") for p in name.split("+")] if name and name != "None" else []


# ---------------------------------------------------------------- layout helpers
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=10):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        h = self._do(rect, False)
        # Qt's box layouts don't reliably ask a nested widget for its height-for-width, so a group
        # with two rows of captures got one row's height (the second row was cut off). Tell it directly.
        w = self.parentWidget()
        if w is not None and h > 0 and w.minimumHeight() != h:
            w.setMinimumHeight(h)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            sz = it.sizeHint()
            if x + sz.width() > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._sp
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y()


class Toggle(QAbstractButton):
    def __init__(self, checked=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 22)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.NoPen if on else QPen(QColor(theme.TOG_OFF_LINE), 1))
        p.setBrush(QColor(theme.ACCENT) if on else QColor(theme.TOG_OFF))
        p.drawRoundedRect(QRectF(0.5, 0.5, 37, 21), 10.5, 10.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.on_accent(theme.ACCENT)) if on else QColor(theme.TOG_KNOB))
        cx = 27 if on else 11
        p.drawEllipse(QRectF(cx - 7, 4, 14, 14))


# ---------------------------------------------------------------- pieces
class ElideLabel(QLabel):
    """A label that shrinks with "…" instead of forcing its parent wider."""

    def __init__(self, text):
        super().__init__(text)
        self._full = text
        self.setToolTip(text)
        self.setMinimumWidth(20)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set_full(self, text):
        self._full = text
        self.setToolTip(text)
        super().setText(self.fontMetrics().elidedText(text, Qt.ElideRight, max(20, self.width())))

    def resizeEvent(self, e):
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, self.width()))
        super().resizeEvent(e)


class CardGrid(QWidget):
    """Capture cards in one row when there's room, otherwise wrapped into rows of 3 (or 2)."""
    MIN_W, GAP = 172, 12

    def __init__(self, cards):
        super().__init__()
        self.cards = cards
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 28)
        self.grid.setSpacing(self.GAP)
        self._cols = 0
        self._place(len(cards))

    def _cols_for(self, w):
        n = len(self.cards)
        for cols in (n, 3, 2):
            if w >= cols * self.MIN_W + (cols - 1) * self.GAP:
                return cols
        return 1

    def _place(self, cols):
        if cols == self._cols:
            return
        self._cols = cols
        for c in self.cards:
            self.grid.removeWidget(c)
        for i in range(max(self.grid.columnCount(), len(self.cards))):
            self.grid.setColumnStretch(i, 0)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols)
        for i in range(cols):
            self.grid.setColumnStretch(i, 1)

    def minimumSizeHint(self):
        return QSize(self.MIN_W, super().minimumSizeHint().height())

    def resizeEvent(self, e):
        self._place(self._cols_for(e.size().width()))
        super().resizeEvent(e)


class ModeTile(QFrame):
    """One capture mode: coloured icon swatch, name, and a short mono note."""
    clicked = Signal()

    def __init__(self, key, icon, name, note, primary=False, menu=None):
        super().__init__()
        self.key, self.icon_name, self.primary, self.menu = key, icon, primary, menu
        self.setObjectName("modetile")
        self.setProperty("primary", primary)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(50)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 0, 9, 0)
        lay.setSpacing(10)
        self.swatch = QLabel()
        self.swatch.setFixedSize(30, 30)
        lay.addWidget(self.swatch)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.setContentsMargins(0, 0, 0, 0)
        self.name = ElideLabel(name)
        self.name.setObjectName("modename")
        self.note = ElideLabel(note)
        self.note.setObjectName("modenote")
        col.addStretch(1)
        col.addWidget(self.name)
        col.addWidget(self.note)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.refresh_colors()

    def refresh_colors(self):
        color = theme.ACCENT if self.primary else theme.MODE_COLORS.get(self.key, theme.MUTED)
        self.swatch.setPixmap(theme.tile_icon_pixmap(self.icon_name, color, 30, filled=self.primary))

    def set_compact(self, on):
        self.name.setVisible(not on)
        self.note.setVisible(not on)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            if self.menu:
                self.menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))
            else:
                self.clicked.emit()


class CaptureStrip(QWidget):
    """The six capture modes as one row of coloured tiles (shortcuts in the notes and tooltips)."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        app = page.app
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 26)
        grid.setSpacing(8)
        delay_menu = QMenu(self)
        for sec in (3, 5, 10):
            delay_menu.addAction(f"In {sec} seconds", lambda sec=sec: app.start_capture(delay=sec, hide_home=True))
        spec = [
            ("region", "region", "Capture", "", lambda: app.start_capture(hide_home=True), None, True),
            ("full", "monitor", "Screen", "monitor", lambda: app.start_capture("fullscreen", hide_home=True), None, False),
            ("scroll", "scroll", "Scrolling", "long pages", lambda: app.start_capture("scroll", hide_home=True), None, False),
            ("text", "ocr", "Text", "copy words", lambda: app.start_capture("text", hide_home=True), None, False),
            ("timer", "timer", "Timer", "3 · 5 · 10 s", None, delay_menu, False),
            ("game", "gamepad", "Instant", "games", lambda: QTimer.singleShot(250, app.instant_capture), None, False),
        ]
        self.buttons = {}
        for i, (key, icon, name, note, fn, menu, primary) in enumerate(spec):
            t = ModeTile(key, icon, name, note, primary, menu)
            if fn:
                t.clicked.connect(fn)
            grid.addWidget(t, 0, i)
            grid.setColumnStretch(i, 1)
            self.buttons[key] = t
        self._compact = None
        self.update_keys()

    def minimumSizeHint(self):
        return QSize(len(self.buttons) * 50, 76)

    def resizeEvent(self, e):
        compact = e.size().width() < 680
        if compact != self._compact:
            self._compact = compact
            for t in self.buttons.values():
                t.set_compact(compact)
        super().resizeEvent(e)

    def refresh_colors(self):
        for t in self.buttons.values():
            t.refresh_colors()

    def update_keys(self):
        s = self.page.app.settings
        k = s.hotkey_primary if s.hotkey_primary and s.hotkey_primary != "None" else ""
        short = {"Print Screen": "PrtScn", "Ctrl+Print Screen": "Ctrl+PrtScn", "Shift+Print Screen": "Shift+PrtScn"}
        self.buttons["region"].note.set_full(short.get(k, k) or "drag an area")
        tips = {
            "region": f"Drag an area, or click a window    {k}",
            "full": "The whole monitor under your mouse",
            "scroll": "Long pages and chats, stitched into one image",
            "text": "Copy the words in an area - nothing is saved",
            "timer": "Wait a few seconds, then capture (for menus and hovers)",
            "game": f"Active window or game, no overlay    {s.hotkey_instant}",
        }
        for key, t in tips.items():
            self.buttons[key].setToolTip(t)


class CaptureCard(QFrame):
    clicked = Signal()

    def __init__(self, icon, title, sub, keys=None, menu=None):
        super().__init__()
        self.setObjectName("capcard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(CardGrid.MIN_W)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(104)
        self.menu = menu
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 13, 14, 12)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(icon_label(icon, 18, well=34), 0, Qt.AlignTop)
        top.addStretch(1)
        self.keys = QHBoxLayout()
        self.keys.setSpacing(3)
        top.addLayout(self.keys)
        top.setAlignment(self.keys, Qt.AlignTop)
        lay.addLayout(top)
        lay.addStretch(1)
        t = ElideLabel(title)
        t.setObjectName("captitle")
        s = ElideLabel(sub)
        s.setObjectName("capsub")
        lay.addWidget(t)
        lay.addSpacing(1)
        lay.addWidget(s)
        self.set_keys(keys)

    def set_keys(self, keys):
        while self.keys.count():
            w = self.keys.takeAt(0).widget()
            if w:
                w.deleteLater()
        for k in hotkey_parts(keys) if keys else []:
            self.keys.addWidget(kbd(k))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            if self.menu:
                self.menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))
            else:
                self.clicked.emit()


class Tile(QFrame):
    def __init__(self, rec, page):
        super().__init__()
        self.rec = rec
        self.page = page
        self.setObjectName("tile")
        self.setProperty("selected", False)
        self.setProperty("kbd", False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(TW + 16, TH + 60)
        self.pm = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(0)
        self.img = QLabel()
        self.img.setFixedSize(TW, TH)
        lay.addWidget(self.img)
        lay.addSpacing(7)
        fm = QFontMetrics(self.font())
        t = QLabel(fm.elidedText(rec["title"], Qt.ElideRight, TW - 18))
        t.setObjectName("tiletitle")
        dot = QLabel()
        dot.setPixmap(theme.dot_pixmap(theme.folder_color(rec.get("folder", "")), 10, 7))
        dot.setFixedSize(10, 10)
        dot.setToolTip(rec.get("folder") or "Not in a folder")
        trow = QHBoxLayout()
        trow.setContentsMargins(0, 0, 0, 0)
        trow.setSpacing(6)
        trow.addWidget(dot, 0, Qt.AlignVCenter)
        trow.addWidget(t, 1)
        meta = rec["meta"]
        q = page.search.text().strip().lower()
        txt = rec.get("text") or ""
        i = txt.lower().find(q) if q and q not in rec["key"] else -1
        if i >= 0:  # matched inside the image - show where
            a = max(0, i - 18)
            snippet = " ".join(txt[a:i + len(q) + 28].split())
            meta = fm.elidedText(("…" if a else "") + f"“{snippet}”", Qt.ElideRight, TW - 4)
        if rec.get("hidden"):
            meta = f"{meta}  ·  {rec['hidden']} hidden"
        if rec.get("tags"):
            meta = fm.elidedText("  ".join("#" + t for t in rec["tags"]) + "  ·  " + meta, Qt.ElideRight, TW - 4)
        m = QLabel(meta)
        m.setObjectName("tilemeta")
        lay.addLayout(trow)
        lay.addSpacing(2)
        m.setContentsMargins(16, 0, 0, 0)
        lay.addWidget(m)
        self.setToolTip(rec["tooltip"])
        self.set_pixmap(page.thumbs.get(rec["path"]))

    def set_pixmap(self, pm):
        self.pm = pm
        sel = bool(self.property("selected"))
        hover = getattr(self, "_hover", False)
        canvas = QPixmap(int(TW * self.devicePixelRatioF()), int(TH * self.devicePixelRatioF()))
        canvas.setDevicePixelRatio(self.devicePixelRatioF())
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, TW, TH), 4, 4)
        p.fillPath(path, QColor(theme.THUMB))
        p.setClipPath(path)
        if pm is not None:
            dpr = pm.devicePixelRatio()
            w, h = pm.width() / dpr, pm.height() / dpr
            p.drawPixmap(QRectF((TW - w) / 2, (TH - h) / 2, w, h), pm, QRectF(pm.rect()))
        if hover and not sel:
            p.fillRect(QRectF(0, 0, TW, TH), QColor(255, 255, 255, 18) if theme.is_dark() else QColor(255, 255, 255, 50))
        p.setClipping(False)
        if sel:
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, TW - 2, TH - 2), 4, 4)
        else:
            edge = QColor(255, 240, 220, 16) if theme.is_dark() else QColor(40, 30, 10, 26)
            p.setPen(QPen(edge, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, TW - 1, TH - 1), 4, 4)
        p.end()
        self.img.setPixmap(canvas)

    def set_selected(self, on):
        self.setProperty("selected", on)
        self.set_pixmap(self.pm)

    def enterEvent(self, e):
        self._hover = True
        self.set_pixmap(self.pm)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.set_pixmap(self.pm)
        super().leaveEvent(e)

    def _set_kbd(self, on):
        if self.property("kbd") != on:
            self.setProperty("kbd", on)
            self.style().unpolish(self)
            self.style().polish(self)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        keyboard = e.reason() != Qt.MouseFocusReason
        self._set_kbd(keyboard)
        if e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason) and self.rec["path"] not in self.page.selected:
            self.page.select(self)
        if keyboard:
            self.page.scroll.ensureWidgetVisible(self, 0, 30)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self._set_kbd(False)

    def event(self, e):
        # Tab / Shift+Tab step through the captures (selecting each) instead of jumping to other widgets
        if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            if self.page.step_focus(self, -1 if e.key() == Qt.Key_Backtab else 1):
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        nav = {Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
               Qt.Key_Home: "home", Qt.Key_End: "end"}
        if k in nav:
            self.page.navigate(self, nav[k], mods)
        elif k == Qt.Key_Space:
            self.page.select(self, additive=True)
        elif k == Qt.Key_A and mods & Qt.ControlModifier:
            self.page.select_all()
        elif k == Qt.Key_Escape and self.page.selected:
            self.page.set_selection(set())
        elif k == Qt.Key_Menu or (k == Qt.Key_F10 and mods & Qt.ShiftModifier):
            if self.rec["path"] not in self.page.selected:
                self.page.select(self)
            self.page.context_menu(self, self.mapToGlobal(self.rect().center()))
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        self._press = None
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
            ctrl = bool(e.modifiers() & Qt.ControlModifier)
            if e.modifiers() & Qt.ShiftModifier:
                self.page.select(self, additive=ctrl, extend=True)
            elif self.rec["path"] not in self.page.selected or ctrl:
                self.page.select(self, additive=ctrl)
        elif e.button() == Qt.RightButton:
            if self.rec["path"] not in self.page.selected:
                self.page.select(self)
            self.page.context_menu(self, e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if getattr(self, "_press", None) is None:
            return
        if (e.position().toPoint() - self._press).manhattanLength() < 10:
            return
        self._press = None
        paths = [p for p in self.page.selected] or [self.rec["path"]]
        mime = QMimeData()
        mime.setData(MIME, "\n".join(paths).encode("utf-8"))
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])  # also drops into Discord, Explorer...
        drag = QDrag(self)
        drag.setMimeData(mime)
        if self.pm is not None:
            pm = self.pm.scaled(int(120 * self.pm.devicePixelRatio()), int(76 * self.pm.devicePixelRatio()),
                                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            drag.setPixmap(pm)
            drag.setHotSpot(QPoint(20, 20))
        drag.exec(Qt.CopyAction | Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if getattr(self, "_press", None) is not None and not e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            self.page.select(self)
        self._press = None

    def mouseDoubleClickEvent(self, e):
        self.page.app.open_editor(path=self.rec["path"])


class _LibBody(QWidget):
    """The library's scrolling content. Dragging on empty space draws a selection box over the tiles.
    Ctrl+drag toggles tiles, Shift+drag adds to the current selection."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self._origin = None
        self._last = QPoint()
        self._base = set()
        self._toggle = False
        self.setFocusPolicy(Qt.ClickFocus)
        self.band = QWidget(self)
        self.band.setObjectName("band")
        self.band.setAttribute(Qt.WA_StyledBackground)
        self.band.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.band.hide()
        self._auto = QTimer(self)
        self._auto.setInterval(30)
        self._auto.timeout.connect(self._autoscroll)

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        cards = self.page.cards_box
        if e.button() != Qt.LeftButton or (cards.isVisible() and cards.geometry().contains(pos)):
            return super().mousePressEvent(e)
        mods = e.modifiers()
        self._toggle = bool(mods & Qt.ControlModifier)
        self._base = set(self.page.selected) if mods & (Qt.ControlModifier | Qt.ShiftModifier) else set()
        if not self._base:
            self.page.set_selection(set())
        self._origin = self._last = pos
        self.setFocus(Qt.MouseFocusReason)
        self._auto.start()
        e.accept()

    def mouseMoveEvent(self, e):
        if self._origin is None:
            return super().mouseMoveEvent(e)
        self._last = e.position().toPoint()
        self._update_band()

    def mouseReleaseEvent(self, e):
        if self._origin is None:
            return super().mouseReleaseEvent(e)
        self._origin = None
        self._auto.stop()
        self.band.hide()

    def _update_band(self):
        r = QRect(self._origin, self._last).normalized()
        if r.width() < 4 and r.height() < 4:
            self.band.hide()
            return
        self.band.setGeometry(r)
        self.band.show()
        self.band.raise_()
        hit = set()
        for p, t in self.page.tiles.items():
            if QRect(t.mapTo(self, QPoint(0, 0)), t.size()).intersects(r):
                hit.add(p)
        self.page.set_selection(self._base ^ hit if self._toggle else self._base | hit)

    def _autoscroll(self):
        """Keep the box growing while the mouse is held near (or past) the top/bottom edge."""
        if self._origin is None:
            return self._auto.stop()
        vp = self.page.scroll.viewport()
        y = self.mapTo(vp, self._last).y()
        edge = 36
        dy = y - edge if y < edge else y - (vp.height() - edge) if y > vp.height() - edge else 0
        if not dy:
            return
        sb = self.page.scroll.verticalScrollBar()
        old = sb.value()
        sb.setValue(old + max(-40, min(40, dy // 2 or (1 if dy > 0 else -1))))
        moved = sb.value() - old
        if moved:
            self._last += QPoint(0, moved)
            self._update_band()


# ---------------------------------------------------------------- pages
SORTS = {   # key: (menu label, button label)
    "newest": ("Newest first", "Newest"),
    "oldest": ("Oldest first", "Oldest"),
    "app": ("By app", "By app"),
    "folder": ("By folder", "By folder"),
    "size": ("Largest files first", "Largest"),
    "name": ("By name (A–Z)", "A–Z"),
}


class LibraryPage(QWidget):
    def __init__(self, home):
        super().__init__()
        self.home = home
        self.app = home.app
        self.thumbs = {}
        self.records = []
        self.tiles = {}
        self.selected = set()
        self.anchor = None      # where Shift+click / Shift+arrow ranges start
        self.filter = ("all", None)
        self._queue = []
        self._loader = QTimer(self)
        self._loader.timeout.connect(self._load_some)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.rebuild)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("lib")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        self.scroll = scroll
        body = _LibBody(self)
        body.setObjectName("content")
        self.body = QVBoxLayout(body)
        self.body.setSizeConstraint(QLayout.SetMinimumSize)   # never squeeze a date group below its rows
        self.body.setContentsMargins(32, 26, 32, 32)
        self.body.setSpacing(0)
        scroll.setWidget(body)

        head = QHBoxLayout()
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self.title = QLabel("Captures")
        self.title.setObjectName("pagetitle")
        tcol.addWidget(self.title)
        self.subtitle_row = QHBoxLayout()
        self.subtitle_row.setSpacing(8)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("capsub")
        self.edit_folder_btn = QPushButton("Edit folder")
        self.edit_folder_btn.setObjectName("ghost")
        self.edit_folder_btn.clicked.connect(lambda: self.home.edit_folder(self.filter[1]))
        self.subtitle.hide()
        self.edit_folder_btn.hide()
        self.subtitle_row.addWidget(self.subtitle)
        self.subtitle_row.addWidget(self.edit_folder_btn)
        self.subtitle_row.addStretch(1)
        tcol.addLayout(self.subtitle_row)
        head.addLayout(tcol)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search, including text inside images")
        self.search.addAction(theme.icon("search", 16), QLineEdit.LeadingPosition)
        self.search.setMinimumWidth(120)
        self.search.setMaximumWidth(300)
        self.search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search.textChanged.connect(lambda: self._search_timer.start(120))
        self.sort_btn = QToolButton()
        self.sort_btn.setObjectName("chip")
        self.sort_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.sort_btn.setIcon(theme.icon("sort", 16))
        self.sort_btn.setPopupMode(QToolButton.InstantPopup)
        self.sort_btn.setCursor(Qt.PointingHandCursor)
        self.sort_btn.setToolTip("Sort and group your captures")
        sm = QMenu(self.sort_btn)
        self._sort_actions = {}
        for key in SORTS:
            act = sm.addAction(SORTS[key][0], lambda k=key: self.set_sort(k))
            act.setCheckable(True)
            self._sort_actions[key] = act
        self.sort_btn.setMenu(sm)
        tools = QToolButton()
        tools.setIcon(theme.icon("more", 18))
        tools.setPopupMode(QToolButton.InstantPopup)
        tools.setCursor(Qt.PointingHandCursor)
        tools.setToolTip("Library tools")
        tm = QMenu(tools)
        tm.addAction(theme.icon("copy", 16), "Find duplicates…", lambda: DuplicatesDialog(self.home).exec())
        tm.addAction("Select all", lambda: (self.select_all(), self._focus_first()), QKeySequence("Ctrl+A"))
        tm.addSeparator()
        tm.addAction(theme.icon("folder", 16), "Open save folder",
                     lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.app.settings.save_folder)))
        tools.setMenu(tm)
        head.addWidget(self.sort_btn, 0, Qt.AlignVCenter)
        head.addSpacing(2)
        head.addWidget(tools, 0, Qt.AlignVCenter)
        head.addSpacing(8)
        head.addWidget(self.search)
        self.sort = self.app.settings.library_sort if self.app.settings.library_sort in SORTS else "newest"
        self._sync_sort_btn()
        self.body.addLayout(head)
        self.body.addSpacing(22)

        # capture modes: one slim strip
        self.cards_box = CaptureStrip(self)
        self.body.addWidget(self.cards_box)

        self.sections = QVBoxLayout()
        self.sections.setSpacing(26)
        self.body.addLayout(self.sections)
        self.body.addStretch(1)

    # ---- data
    def load(self):
        recs = []
        for p in storage.list_captures(self.app.settings.save_folder):
            try:
                st = p.stat()
            except OSError:
                continue
            data = storage.read_meta(p)
            info = data.get("info", {})
            ts = datetime.fromtimestamp(st.st_mtime)
            app_name = pretty_app(info.get("app"), info.get("title") or "")
            title = (info.get("title") or "").strip()
            sz = QImageReader(str(p)).size()
            dims = f"{sz.width()}×{sz.height()}" if sz.isValid() else ""
            meta = " · ".join(x for x in (app_name, dims) if x)
            root = Path(self.app.settings.save_folder)
            folder = p.parent.name if p.parent != root else ""
            recs.append(dict(path=str(p), ts=ts, app=app_name, exe=info.get("exe", ""), folder=folder,
                             size=st.st_size, name=(title or app_name or "Screenshot").lower(),
                             tags=list(data.get("tags") or []),
                             title=title or app_name or "Screenshot",
                             meta=meta, tooltip=f"{title}\n{p.name}".strip(),
                             key=(f"{p.name} {app_name} {title} {folder} "
                                  + " ".join("#" + t for t in data.get("tags") or [])).lower(),
                             text=(data.get("text") or ""),
                             hidden=sum(1 for s in data.get("shapes") or [] if s.get("redact"))))
        self.records = recs
        self.thumbs = {k: v for k, v in self.thumbs.items() if any(r["path"] == k for r in recs)}
        self.selected &= {r["path"] for r in recs}
        self.rebuild()

    def refresh_text(self):
        """Pick up newly indexed text without rebuilding the grid (keeps scroll position)."""
        for r in self.records:
            r["text"] = storage.read_meta(r["path"]).get("text") or ""
        if self.search.text().strip():
            self.rebuild()

    def visible_records(self):
        kind, val = self.filter
        now = datetime.now()
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        out = []
        q = self.search.text().lower().strip()
        for r in self.records:
            if kind == "today" and r["ts"] < start_today:
                continue
            if kind == "week" and r["ts"] < start_today - timedelta(days=6):
                continue
            if kind == "app" and r["app"] != val:
                continue
            if kind == "folder" and r["folder"] != val:
                continue
            if kind == "tag" and val not in r.get("tags", []):
                continue
            if kind == "untagged" and r.get("tags"):
                continue
            if q and q not in r["key"] and q not in r["text"].lower():
                continue
            out.append(r)
        return out

    # ---- sorting
    def set_sort(self, key):
        self.sort = key
        self.app.settings.set(library_sort=key)
        self._sync_sort_btn()
        self.rebuild()

    def _sync_sort_btn(self):
        self.sort_btn.setText(SORTS[self.sort][1])
        for k, a in self._sort_actions.items():
            a.setChecked(k == self.sort)

    def _focus_first(self):
        if self.tiles:
            next(iter(self.tiles.values())).setFocus(Qt.OtherFocusReason)

    def _sorted(self, recs):
        """(records in display order, function giving each record's section heading)."""
        k = self.sort
        if k == "oldest":
            return sorted(recs, key=lambda r: r["ts"]), lambda r: ""
        if k == "app":
            out = sorted(recs, key=lambda r: ((r["app"] or "~").lower(), -r["ts"].timestamp()))
            return out, lambda r: r["app"] or "Other"
        if k == "folder":
            out = sorted(recs, key=lambda r: (r["folder"] == "", r["folder"].lower(), -r["ts"].timestamp()))
            return out, lambda r: r["folder"] or "Not in a folder"
        if k == "size":
            def band(r):
                mb = r["size"] / 1e6
                return "Over 5 MB" if mb > 5 else "1 – 5 MB" if mb > 1 else "Under 1 MB"
            return sorted(recs, key=lambda r: -r["size"]), band
        if k == "name":
            def letter(r):
                c = (r["name"][:1] or "#").upper()
                return c if c.isalpha() else "#"
            return sorted(recs, key=lambda r: r["name"]), letter
        return sorted(recs, key=lambda r: r["ts"], reverse=True), lambda r: ""

    @staticmethod
    def _group(ts):
        today = datetime.now().date()
        d = ts.date()
        if d == today:
            return "Today"
        if d == today - timedelta(days=1):
            return "Yesterday"
        if d > today - timedelta(days=7):
            return "This week"
        if d.year == today.year:
            return ts.strftime("%B")
        return ts.strftime("%B %Y")

    def rebuild(self):
        while self.sections.count():
            item = self.sections.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.tiles = {}
        recs = self.visible_records()
        is_home = self.filter[0] == "all" and not self.search.text().strip()
        self.cards_box.setVisible(self.filter[0] == "all")
        if not self.records:
            self.sections.addWidget(self._empty_state())
            return
        if not recs:
            l = QLabel("Nothing matches.")
            l.setObjectName("muted")
            self.sections.addWidget(l)
            return
        recs, group_of = self._sorted(recs)
        groups = {}
        order = []
        for r in recs:
            g = group_of(r)
            if g not in groups:
                groups[g] = []
                order.append(g)
            groups[g].append(r)
        self._queue = []
        for g in order:
            sec = QWidget()
            v = QVBoxLayout(sec)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(10)
            h = QHBoxLayout()
            h.setSpacing(8)
            gl = QLabel(g)
            gl.setObjectName("group")
            gc = QLabel(str(len(groups[g])))
            gc.setObjectName("groupcount")
            rule = QFrame()
            rule.setObjectName("rule")
            rule.setFixedHeight(1)
            h.addWidget(gl)
            h.addWidget(gc)
            h.addSpacing(6)
            h.addWidget(rule, 1, Qt.AlignVCenter)
            if g:                       # flat list (newest / oldest): no heading at all
                v.addLayout(h)
            else:
                for w_ in (gl, gc, rule):
                    w_.hide()
            grid = QWidget()
            flow = FlowLayout(grid, spacing=6)
            grid.setLayout(flow)
            for r in groups[g]:
                t = Tile(r, self)
                t.set_selected(r["path"] in self.selected)
                flow.addWidget(t)
                self.tiles[r["path"]] = t
                if r["path"] not in self.thumbs:
                    self._queue.append(r["path"])
            v.addWidget(grid)
            self.sections.addWidget(sec)
        if self._queue:
            self._loader.start(0)
        _ = is_home

    def _empty_state(self):
        box = QFrame()
        box.setObjectName("empty")
        box.setMinimumHeight(260)
        v = QVBoxLayout(box)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(12)
        mark = QLabel()
        lp = theme.app_pixmap(96)
        lp.setDevicePixelRatio(2.0)
        mark.setPixmap(lp)
        mark.setAlignment(Qt.AlignCenter)
        v.addWidget(mark)
        k = self.app.settings.hotkey_primary
        t = QLabel(f"Nothing here yet. Press {k} and drag over anything." if k and k != "None"
                   else "Nothing here yet. Click Capture above and drag over anything.")
        t.setObjectName("muted")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        return box

    def _load_some(self):
        dpr = self.devicePixelRatioF()
        for _ in range(6):
            if not self._queue:
                self._loader.stop()
                return
            path = self._queue.pop(0)
            r = QImageReader(path)
            sz = r.size()
            if sz.isValid():
                sz.scale(QSize(int(TW * dpr), int(TH * dpr)), Qt.KeepAspectRatioByExpanding)
                r.setScaledSize(sz)
            img = r.read()
            if img.isNull():
                continue
            tw, th = int(TW * dpr), int(TH * dpr)
            img = img.copy(max(0, (img.width() - tw) // 2), 0, min(tw, img.width()), min(th, img.height()))
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            self.thumbs[path] = pm
            t = self.tiles.get(path)
            if t is not None:
                try:
                    t.set_pixmap(pm)
                except RuntimeError:
                    pass

    # ---- selection / actions
    def select(self, tile, additive=False, extend=False):
        p = tile.rec["path"]
        if extend and self.anchor in self.tiles:
            order = list(self.tiles)
            a, b = sorted((order.index(self.anchor), order.index(p)))
            rng = set(order[a:b + 1])
            self.set_selection(self.selected | rng if additive else rng)
            return
        if additive:
            self.selected ^= {p}
        else:
            self.selected = {p}
        self.anchor = p
        self.set_selection(self.selected)

    def set_selection(self, paths):
        self.selected = set(paths)
        for path, t in self.tiles.items():
            on = path in self.selected
            if bool(t.property("selected")) != on:
                t.set_selected(on)

    def select_all(self):
        self.set_selection(self.tiles.keys())

    def step_focus(self, tile, step):
        order = list(self.tiles.values())
        j = order.index(tile) + step
        if not 0 <= j < len(order):
            return False
        self.select(order[j])
        order[j].setFocus(Qt.OtherFocusReason)
        return True

    def navigate(self, tile, where, mods):
        """Arrows / Home / End. Shift extends the selection, Ctrl moves without selecting (Space toggles)."""
        order = list(self.tiles.values())
        i = order.index(tile)
        target = None
        if where == "left" and i > 0:
            target = order[i - 1]
        elif where == "right" and i + 1 < len(order):
            target = order[i + 1]
        elif where == "home":
            target = order[0]
        elif where == "end":
            target = order[-1]
        elif where in ("up", "down"):
            body = self.scroll.widget()
            pos = {t: t.mapTo(body, t.rect().center()) for t in order}
            cur = pos[tile]
            down = where == "down"
            cands = [t for t in order if (pos[t].y() > cur.y() + 5 if down else pos[t].y() < cur.y() - 5)]
            if cands:
                row_y = (min if down else max)(pos[t].y() for t in cands)
                row = [t for t in cands if abs(pos[t].y() - row_y) < 5]
                target = min(row, key=lambda t: abs(pos[t].x() - cur.x()))
        if target is None or target is tile:
            return
        if mods & Qt.ShiftModifier:
            self.select(target, additive=bool(mods & Qt.ControlModifier), extend=True)
        elif not mods & Qt.ControlModifier:
            self.select(target)
        target.setFocus(Qt.OtherFocusReason)

    def context_menu(self, tile, pos):
        p = tile.rec["path"]
        paths = list(self.selected) or [p]
        m = QMenu(self)
        m.addAction("Edit", lambda: self.app.open_editor(path=p))
        m.addAction("Copy", lambda: QApplication.clipboard().setImage(QImage(p)))
        m.addAction("Copy text", lambda: self.copy_text(p))
        m.addAction("Pin to screen", lambda: self.app.pin_image(QImage(p), key=("file", str(Path(p)))))
        m.addAction("Show in folder", lambda: subprocess.Popen(["explorer", "/select,", str(Path(p))]))
        hidden = [x for x in paths if any(r["path"] == x and r["hidden"] for r in self.records)]
        if hidden:
            m.addAction(theme.icon("redact", 16), "Unhide sensitive info", lambda: self.unhide(hidden))
        m.addAction(theme.icon("tag", 16), "Tags…", lambda: TagDialog(self, paths).exec())
        if len(paths) >= 2:
            m.addAction(theme.icon("grid", 16), f"Combine {len(paths)} captures…",
                        lambda: CombineDialog(self, [x for x in self.tiles if x in set(paths)]).exec())
        mv = m.addMenu("Move to folder")
        for d in library.folder_dirs(self.app.settings.save_folder):
            mv.addAction(theme.icon("folder", 16), d.name, lambda n=d.name: self.home.move_paths(paths, n))
        if mv.actions():
            mv.addSeparator()
        mv.addAction("New folder…", lambda: self.home.edit_folder(None, paths))
        if any(Path(x).parent != Path(self.app.settings.save_folder) for x in paths):
            m.addAction("Remove from folder", lambda: self.home.move_paths(paths, ""))
        m.addSeparator()
        m.addAction("Delete" if len(paths) == 1 else f"Delete {len(paths)} captures", lambda: self.delete(paths))
        m.exec(pos)

    def unhide(self, paths):
        for p in paths:
            try:
                storage.unhide(p)
            except Exception:
                pass
            self.thumbs.pop(p, None)
        self.home.refresh()

    def copy_text(self, p):
        text = (storage.read_meta(p) or {}).get("text")
        if text is None:   # not indexed yet: read it now
            from . import ocr
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                text = ocr.lines_to_text(ocr.recognize(QImage(str(p))))
            except Exception:
                text = ""
            finally:
                QApplication.restoreOverrideCursor()
        if text.strip():
            QApplication.clipboard().setText(text)
            n = len(text.strip().splitlines())
            self.app.tray.showMessage("Glint", f"Copied {n} line{'s' if n != 1 else ''} of text",
                                      self.app.tray.MessageIcon.Information, 1500)
        else:
            self.app.tray.showMessage("Glint", "No text found in that capture",
                                      self.app.tray.MessageIcon.Information, 1500)

    def delete(self, paths):
        for p in paths:
            try:
                storage.delete_capture(p)
            except Exception:
                pass
        self.selected -= set(paths)
        self.home.refresh()

    def update_hotkeys(self):
        self.cards_box.update_keys()


class SettingsPage(QWidget):
    def __init__(self, home):
        super().__init__()
        self.home = home
        self.app = home.app
        s = self.app.settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("lib")
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("content")
        v = QVBoxLayout(body)
        v.setContentsMargins(32, 26, 32, 32)
        v.setSpacing(10)
        scroll.setWidget(body)
        t = QLabel("Settings")
        t.setObjectName("pagetitle")
        v.addWidget(t)
        v.addSpacing(14)

        self.after = QComboBox()
        for label, val in (("Show thumbnail", "thumbnail"), ("Open editor", "editor"), ("Do nothing", "nothing")):
            self.after.addItem(label, val)
        self.after.setCurrentIndex(max(0, self.after.findData(s.after_capture)))
        self.copy = Toggle(s.auto_copy)
        self.save = Toggle(s.auto_save)
        self.folder_btn = QPushButton(self._short(s.save_folder))
        self.folder_btn.clicked.connect(self._browse)
        self.win_style = QComboBox()
        for label, val in (("Clean corners", "clean"), ("Clean corners + shadow", "shadow"), ("As on screen", "plain")):
            self.win_style.addItem(label, val)
        self.win_style.setCurrentIndex(max(0, self.win_style.findData(s.window_style)))
        self.hide_icons = Toggle(s.hide_desktop_icons)
        self.hk = []
        for cur in (s.hotkey_primary, s.hotkey_secondary, s.hotkey_instant, s.hotkey_repeat):
            cb = QComboBox()
            cb.addItems(list(winapi.HOTKEYS.keys()))
            cb.setCurrentText(cur)
            cb.setMinimumWidth(170)
            self.hk.append(cb)
        self.startup = Toggle(s.start_with_windows)
        self.appearance = QWidget()
        apl = QHBoxLayout(self.appearance)
        apl.setContentsMargins(0, 0, 0, 0)
        apl.setSpacing(0)
        self.appear_group = QButtonGroup(self)
        modes = (("system", "System"), ("light", "Day"), ("dark", "Night"))
        for i, (key, label) in enumerate(modes):
            b = QToolButton()
            b.setObjectName("seg")
            b.setText(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(s.appearance == key)
            r = 7
            b.setStyleSheet("QToolButton#seg { border-top-left-radius: %dpx; border-bottom-left-radius: %dpx;"
                            " border-top-right-radius: %dpx; border-bottom-right-radius: %dpx; %s }"
                            % (r if i == 0 else 0, r if i == 0 else 0, r if i == len(modes) - 1 else 0,
                               r if i == len(modes) - 1 else 0, "" if i == 0 else "margin-left: -1px;"))
            b.clicked.connect(lambda _=False, k=key: self._set_appearance(k))
            self.appear_group.addButton(b)
            apl.addWidget(b)
        self.accent = QWidget()
        al = QHBoxLayout(self.accent)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        self.swatches = QButtonGroup(self)
        for name, col in theme.ACCENTS:
            b = QToolButton()
            b.setObjectName("swatch")
            b.setCheckable(True)
            b.setFixedSize(24, 24)
            b.setToolTip(name)
            b.setCursor(Qt.PointingHandCursor)
            pm = QPixmap(32, 32)
            pm.fill(Qt.transparent)
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.Antialiasing)
            pp.setPen(Qt.NoPen)
            pp.setBrush(QColor(col))
            pp.drawEllipse(QRectF(1, 1, 30, 30))
            pp.end()
            pm.setDevicePixelRatio(2)
            b.setIcon(QIcon(pm))
            b.setIconSize(QSize(16, 16))
            b.setChecked(col.lower() == (s.accent or "").lower())
            b.clicked.connect(lambda _=False, c=col: self._set_accent(c))
            self.swatches.addButton(b)
            al.addWidget(b)
        self.redact = Toggle(s.auto_redact)

        v.addWidget(self._card("Capture", [
            ("After capturing", "What appears once a capture is taken", self.after),
            ("Copy to clipboard", "Every capture is ready to paste", self.copy),
            ("Save automatically", "Keep every capture in your library", self.save),
            ("Save location", "Where captures are stored", self.folder_btn),
            ("Window captures", "When you click a window: trim the rounded corners, optionally add a shadow",
             self.win_style),
            ("Hide desktop icons", "Clean desktop shots - icons come back as soon as the screen is grabbed",
             self.hide_icons),
        ]))
        v.addSpacing(12)
        v.addWidget(self._card("Privacy", [
            ("Hide sensitive info automatically",
             "Pixelate emails, phone numbers, card numbers, IPs and keys as you capture. "
             "Unhide any time.", self.redact),
        ]))
        v.addSpacing(12)
        v.addWidget(self._card("Shortcuts", [
            ("Capture", "Region or window", self.hk[0]),
            ("Capture (alternate)", "A second shortcut for the same thing", self.hk[1]),
            ("Instant capture", "Active window or game, no overlay - fullscreen games keep focus", self.hk[2]),
            ("Repeat last area", "Capture the same area as last time, no overlay (R in the overlay too)", self.hk[3]),
        ]))
        v.addSpacing(12)
        v.addWidget(self._card("General", [
            ("Start with Windows", "Run quietly in the tray when you sign in", self.startup),
            ("Appearance", "System follows Windows' light or dark setting", self.appearance),
            ("Accent colour", "Buttons, selection and highlights", self.accent),
        ]))
        v.addStretch(1)

        self.after.currentIndexChanged.connect(self._apply)
        self.win_style.currentIndexChanged.connect(self._apply)
        self.hide_icons.toggled.connect(self._apply)
        for w in (self.copy, self.save, self.startup, self.redact):
            w.toggled.connect(self._apply)
        for cb in self.hk:
            cb.currentIndexChanged.connect(self._apply_hotkeys)

    @staticmethod
    def _short(path):
        p = Path(path)
        try:
            s = "~\\" + str(p.relative_to(Path.home()))
        except ValueError:
            s = str(p)
        return s if len(s) <= 34 else s[:12] + "…" + s[-20:]

    def _card(self, title, rows):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        h = QLabel(title)
        h.setObjectName("group")
        v.addWidget(h)
        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        for i, (t, d, w) in enumerate(rows):
            if i:
                hair = QFrame()
                hair.setObjectName("hair")
                hair.setFixedHeight(1)
                cv.addWidget(hair)
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 12, 16, 12)
            tv = QVBoxLayout()
            tv.setSpacing(1)
            tl = QLabel(t)
            tl.setObjectName("rowtitle")
            dl = QLabel(d)
            dl.setObjectName("rowdesc")
            tv.addWidget(tl)
            tv.addWidget(dl)
            rl.addLayout(tv, 1)
            rl.addWidget(w, 0, Qt.AlignVCenter)
            cv.addWidget(row)
        v.addWidget(card)
        return wrap

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save captures to", self.app.settings.save_folder)
        if d:
            self.app.settings.set(save_folder=d)
            self.folder_btn.setText(self._short(d))
            self.home.refresh()

    def _apply(self):
        s = self.app.settings
        startup = self.startup.isChecked()
        if startup != s.start_with_windows:
            try:
                winapi.set_start_with_windows(startup)
            except Exception:
                startup = s.start_with_windows
                self.startup.setChecked(startup)
        s.set(after_capture=self.after.currentData(), auto_copy=self.copy.isChecked(),
              auto_save=self.save.isChecked(), start_with_windows=startup, auto_redact=self.redact.isChecked(),
              window_style=self.win_style.currentData(), hide_desktop_icons=self.hide_icons.isChecked())

    def _set_appearance(self, key):
        self.app.settings.set(appearance=key)
        theme.apply_theme(QApplication.instance(), appearance=key)
        if hasattr(self.app, "theme_changed"):
            self.app.theme_changed()

    def _set_accent(self, col):
        self.app.settings.set(accent=col)
        theme.apply_theme(QApplication.instance(), col)
        if hasattr(self.app, "theme_changed"):
            self.app.theme_changed()

    def _apply_hotkeys(self):
        # one key can only do one thing: if the key just picked is already used by another row, that row
        # gives it up (set to None) - otherwise Windows silently refuses the second registration
        changed = self.sender()
        if changed in self.hk and changed.currentText() != "None":
            for cb in self.hk:
                if cb is not changed and cb.currentText() == changed.currentText():
                    cb.blockSignals(True)
                    cb.setCurrentText("None")
                    cb.blockSignals(False)
        hk = [cb.currentText() for cb in self.hk]
        self.app.settings.set(hotkey_primary=hk[0], hotkey_secondary=hk[1], hotkey_instant=hk[2],
                              hotkey_repeat=hk[3])
        if "Print Screen" in hk and winapi.printscreen_owned_by_windows():
            try:
                winapi.release_printscreen_from_windows()
            except Exception:
                pass
        self.app.register_hotkeys(show_errors=True)
        self.home.library.update_hotkeys()


# ---------------------------------------------------------------- window
class NavButton(QPushButton):
    def __init__(self, icon_name, text):
        super().__init__(text)
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setIcon(theme.icon(icon_name, 16))
        self.setIconSize(QSize(16, 16))
        self.setCursor(Qt.PointingHandCursor)
        self.count = QLabel(self)
        self.count.setObjectName("navcount")

    def set_count(self, n):
        self.count.setText(str(n) if n else "")
        self.count.adjustSize()
        self._place()

    def set_dot(self, color):
        self.setIcon(QIcon(theme.dot_pixmap(color, 16, 8)))

    def set_compact(self, on):
        if not hasattr(self, "_full"):
            self._full = self.text()
        self.setText("" if on else self._full)
        self.setToolTip(self._full if on else "")
        self.count.setVisible(not on)
        self.setProperty("compact", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def _place(self):
        self.count.move(self.width() - self.count.width() - 10, (self.height() - self.count.height()) // 2)


class FolderNav(NavButton):
    """Sidebar folder: click to view, drop captures on it to move them in."""

    def __init__(self, home, name, auto):
        super().__init__("folder", name)
        self.home = home
        self.name = name
        if auto:
            self.setIcon(theme.icon("folderauto", 16))
            self.setToolTip("Auto-sorts: " + library.describe(home.app.settings.folder_rules.get(name, {})))
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
            self.setDown(True)

    def dragLeaveEvent(self, e):
        self.setDown(False)

    def dropEvent(self, e):
        self.setDown(False)
        paths = bytes(e.mimeData().data(MIME)).decode("utf-8").split("\n")
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.home.move_paths(paths, self.name))

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Edit folder…", lambda: self.home.edit_folder(self.name))
        rule = self.home.app.settings.folder_rules.get(self.name)
        if library.has_conditions(rule):
            m.addAction("Sort matching captures now", lambda: self.home.sort_into(self.name))
        m.addAction("Show in Explorer", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(self.home.app.settings.save_folder) / self.name))))
        m.addSeparator()
        m.addAction("Delete folder (keeps captures)", lambda: self.home.delete_folder(self.name))
        m.exec(e.globalPos())


class FolderDialog(QDialog):
    """Create / edit a folder and its auto-sort rule."""

    def __init__(self, home, name=None, preselect=None):
        super().__init__(home)
        self.home = home
        self.app = home.app
        self.orig = name
        self.preselect = preselect or []
        rule = dict(self.app.settings.folder_rules.get(name, {})) if name else {}
        self.setWindowTitle("Edit folder" if name else "New folder")
        self.setMinimumWidth(500)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)

        t = QLabel("Name")
        t.setObjectName("rowtitle")
        v.addWidget(t)
        self.name = QLineEdit(name or "")
        self.name.setPlaceholderText("e.g. Discord, Valorant, Receipts")
        v.addWidget(self.name)
        v.addSpacing(8)

        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(1)
        a = QLabel("Auto-sort")
        a.setObjectName("rowtitle")
        b = QLabel("Captures that match these rules are filed here automatically")
        b.setObjectName("rowdesc")
        col.addWidget(a)
        col.addWidget(b)
        row.addLayout(col, 1)
        self.auto = Toggle(library.has_conditions(rule))
        row.addWidget(self.auto)
        v.addLayout(row)

        self.rules = QFrame()
        self.rules.setObjectName("card")
        rv = QVBoxLayout(self.rules)
        rv.setContentsMargins(14, 12, 14, 14)
        rv.setSpacing(8)
        l1 = QLabel("From these apps")
        l1.setObjectName("rowdesc")
        rv.addWidget(l1)
        chips = QWidget()
        flow = FlowLayout(chips, spacing=4)
        chips.setLayout(flow)
        self.app_chips = {}
        recs = home.library.records
        known = Counter(r["app"] for r in recs if r["app"])
        exes = {r["app"]: r["exe"] for r in recs if r.get("exe")}
        for app_name in sorted(set(known) | set(rule.get("apps", [])), key=lambda n: (-known.get(n, 0), n)):
            c = QToolButton()
            c.setObjectName("appchip")
            c.setText(app_name)
            c.setCheckable(True)
            c.setChecked(app_name in rule.get("apps", []))
            ic = app_icon_for(app_name, exes.get(app_name))
            if ic:
                c.setIcon(ic)
                c.setIconSize(QSize(14, 14))
                c.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            c.toggled.connect(self._update_preview)
            flow.addWidget(c)
            self.app_chips[app_name] = c
        if not self.app_chips:
            none = QLabel("Apps show up here after you capture them.")
            none.setObjectName("rowdesc")
            flow.addWidget(none)
        rv.addWidget(chips)
        rv.addSpacing(4)
        l2 = QLabel("Window title contains")
        l2.setObjectName("rowdesc")
        rv.addWidget(l2)
        self.title_kw = QLineEdit(rule.get("title", ""))
        self.title_kw.setPlaceholderText("Optional, e.g. #general, Valorant, invoice")
        self.title_kw.textChanged.connect(self._update_preview)
        rv.addWidget(self.title_kw)
        rv.addSpacing(4)
        dr = QHBoxLayout()
        l3 = QLabel("Only between dates")
        l3.setObjectName("rowdesc")
        dr.addWidget(l3, 1)
        self.use_dates = Toggle(bool(rule.get("from") or rule.get("to")))
        self.use_dates.toggled.connect(self._update_preview)
        dr.addWidget(self.use_dates)
        rv.addLayout(dr)
        dates = QHBoxLayout()
        dates.setContentsMargins(0, 0, 0, 0)
        today = QDate.currentDate()
        self.d_from = QDateEdit(QDate.fromString(rule["from"], "yyyy-MM-dd") if rule.get("from") else today.addDays(-30))
        self.d_to = QDateEdit(QDate.fromString(rule["to"], "yyyy-MM-dd") if rule.get("to") else today.addDays(30))
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("MMM d, yyyy")
            d.dateChanged.connect(self._update_preview)
        dates.addWidget(self.d_from, 1)
        to = QLabel("to")
        to.setObjectName("rowdesc")
        dates.addWidget(to)
        dates.addWidget(self.d_to, 1)
        self.dates_row = QWidget()
        self.dates_row.setLayout(dates)
        rv.addWidget(self.dates_row)
        v.addWidget(self.rules)

        mrow = QHBoxLayout()
        mrow.setContentsMargins(2, 4, 0, 0)
        self.preview = QLabel()
        self.preview.setObjectName("rowdesc")
        mrow.addWidget(self.preview, 1)
        ml = QLabel("Move them now")
        ml.setObjectName("rowdesc")
        mrow.addWidget(ml)
        self.move_now = Toggle(True)
        mrow.addWidget(self.move_now)
        self.move_row = QWidget()
        self.move_row.setLayout(mrow)
        v.addWidget(self.move_row)

        v.addSpacing(6)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Save" if name else "Create folder")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        v.addLayout(btns)
        self.auto.toggled.connect(self._update_preview)
        self._update_preview()
        winapi.style_window(self.winId())

    def rule(self):
        if not self.auto.isChecked():
            return {}
        r = {"apps": [n for n, c in self.app_chips.items() if c.isChecked()],
             "title": self.title_kw.text().strip()}
        if self.use_dates.isChecked():
            r["from"] = self.d_from.date().toString("yyyy-MM-dd")
            r["to"] = self.d_to.date().toString("yyyy-MM-dd")
        return r

    def matches(self):
        r = self.rule()
        target = library.clean_name(self.name.text()) or self.orig
        return [x["path"] for x in self.home.library.records
                if x["folder"] != target and library.rule_matches(r, x["app"], x["title"], x["ts"])]

    def _update_preview(self):
        on = self.auto.isChecked()
        self.rules.setVisible(on)
        self.dates_row.setEnabled(self.use_dates.isChecked())
        n = len(self.matches()) if on else 0
        self.move_row.setVisible(on and n > 0)
        self.preview.setText(f"{n} existing capture{'s' if n != 1 else ''} match")
        QTimer.singleShot(0, self.adjustSize)

    def _ok(self):
        name = library.clean_name(self.name.text())
        if not name:
            self.name.setFocus()
            return
        root = Path(self.app.settings.save_folder)
        rules = dict(self.app.settings.folder_rules or {})
        try:
            if self.orig and self.orig != name:
                if (root / name).exists():
                    QMessageBox.warning(self, "Glint", f"There's already a folder called “{name}”.")
                    return
                (root / self.orig).rename(root / name)
                rules.pop(self.orig, None)
            (root / name).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Glint", f"Couldn't create the folder.\n\n{e}")
            return
        r = self.rule()
        if library.has_conditions(r):
            rules[name] = r
        else:
            rules.pop(name, None)
        self.app.settings.set(folder_rules=rules)
        to_move = list(self.preselect)
        if self.move_row.isVisible() and self.move_now.isChecked():
            to_move += self.matches()
        self.accept()
        self.home.move_paths(to_move, name, open_folder=True)


class StorageView(QWidget):
    """Space used, split by folder. Glint's library has no limit (it's your disk), so the bar is always
    full: it shows what's taking the room, not how close to "full" you are."""

    def __init__(self):
        super().__init__()
        self.parts = []          # [(name, colour, bytes)]
        self.total = 0
        self.compact = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 4)
        lay.setSpacing(8)
        top = QHBoxLayout()
        self.head = QLabel("Space used")
        self.head.setObjectName("rowtitle")
        self.amount = QLabel()
        self.amount.setObjectName("navcount")
        top.addWidget(self.head)
        top.addStretch(1)
        top.addWidget(self.amount)
        lay.addLayout(top)
        self.bar = QWidget()
        self.bar.setFixedHeight(6)
        self.bar.paintEvent = self._paint_bar
        lay.addWidget(self.bar)
        self.legend_w = QWidget()
        self.legend = FlowLayout(self.legend_w, spacing=4)
        lay.addWidget(self.legend_w)
        self.vbar = QWidget()
        self.vbar.setFixedSize(6, 70)
        self.vbar.paintEvent = self._paint_vbar
        self.vbar.hide()
        lay.addWidget(self.vbar, 0, Qt.AlignHCenter)

    @staticmethod
    def _mb(n):
        mb = n / 1e6
        return f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB" if mb >= 1 else f"{max(1, round(n / 1e3))} KB"

    def set_data(self, by_folder):
        items = sorted(by_folder.items(), key=lambda kv: -kv[1])
        if len(items) > 5:          # keep the key short: the four biggest, then everything else
            rest = sum(v for _, v in items[4:])
            items = items[:4] + [("\x00other", rest)]
        self.parts = [(("Loose" if k == "" else "Other" if k == "\x00other" else k),
                       (theme.LOOSE_COLOR if k == "" else theme.DIM if k == "\x00other" else theme.folder_color(k)), v)
                      for k, v in items if v > 0]
        self.total = sum(v for _, _, v in self.parts)
        self.amount.setText(self._mb(self.total))
        while self.legend.count():
            w = self.legend.takeAt(0).widget()
            if w:
                w.deleteLater()
        for name, color, v in self.parts:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 8, 0)
            rl.setSpacing(5)
            d = QLabel()
            d.setPixmap(theme.dot_pixmap(color, 10, 7))
            n = QLabel(name)
            n.setObjectName("legendname")
            sz = QLabel(self._mb(v).replace(" MB", "").replace(" KB", "k"))
            sz.setObjectName("legendsize")
            for w in (d, n, sz):
                rl.addWidget(w)
            self.legend.addWidget(row)
        self.setToolTip("\n".join(f"{n}: {self._mb(v)}" for n, _, v in self.parts))
        self.bar.update()
        self.vbar.update()

    def set_compact(self, on):
        self.compact = on
        for w in (self.head, self.amount, self.bar, self.legend_w):
            w.setVisible(not on)
        self.vbar.setVisible(on)

    def _segments(self, length):
        out, pos, gap = [], 0.0, 2.0
        usable = length - gap * max(0, len(self.parts) - 1)
        for i, (_, color, v) in enumerate(self.parts):
            ln = max(2.0, usable * v / max(1, self.total))
            out.append((pos, ln, color))
            pos += ln + gap
        return out

    def _paint_bar(self, _e):
        p = QPainter(self.bar)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.bar.rect()), 3, 3)
        p.setClipPath(clip)
        if not self.parts:
            p.fillRect(self.bar.rect(), QColor(theme.LINE))
        for x, w, color in self._segments(self.bar.width()):
            p.fillRect(QRectF(x, 0, w, self.bar.height()), QColor(color))
        p.end()

    def _paint_vbar(self, _e):
        p = QPainter(self.vbar)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.vbar.rect()), 3, 3)
        p.setClipPath(clip)
        if not self.parts:
            p.fillRect(self.vbar.rect(), QColor(theme.LINE))
        for y, h, color in self._segments(self.vbar.height()):
            p.fillRect(QRectF(0, y, self.vbar.width(), h), QColor(color))
        p.end()


class HomeWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Glint")
        self.setWindowIcon(theme.app_icon())
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setAttribute(Qt.WA_StyledBackground)
        side.setFixedWidth(228)
        self.side = side
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 18, 12, 14)
        sv.setSpacing(2)
        self.side_layout = sv
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        logo = QLabel()
        lp = theme.app_pixmap(52)
        lp.setDevicePixelRatio(2.0)
        logo.setPixmap(lp)
        bt = QLabel("Glint")
        self.brand_text = bt
        bt.setObjectName("brand")
        brand.addWidget(logo)
        brand.addSpacing(4)
        brand.addWidget(bt)
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_home = self._nav(sv, "grid", "Captures", ("all", None))
        self.nav_dupes = NavButton("copy", "Duplicates")
        self.nav_dupes.setCheckable(False)
        self.nav_dupes.clicked.connect(lambda: DuplicatesDialog(self).exec())
        sv.addWidget(self.nav_dupes)
        sv.addSpacing(10)

        # scrollable middle: folders + apps
        mid_scroll = QScrollArea()
        mid_scroll.setWidgetResizable(True)
        mid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        mid_scroll.setObjectName("sidebarscroll")
        mid = QWidget()
        mid.setObjectName("sidebar_mid")
        mid.setAttribute(Qt.WA_StyledBackground, True)
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(2)
        fh = QHBoxLayout()
        fl = QLabel("Folders")
        fl.setObjectName("section")
        self.folders_label = fl
        self.folder_add = None
        fh.addWidget(fl)
        fh.addStretch(1)
        add = QToolButton()
        add.setIcon(theme.icon("plus", 14))
        add.setIconSize(QSize(14, 14))
        add.setToolTip("New folder")
        add.setStyleSheet("QToolButton { padding: 3px; }")
        add.clicked.connect(lambda: self.edit_folder(None))
        fh.addWidget(add)
        self.folder_add = add
        mv.addLayout(fh)
        mv.addSpacing(2)
        self.folders_box = QVBoxLayout()
        self.folders_box.setSpacing(2)
        mv.addLayout(self.folders_box)
        self.folder_hint = QPushButton("New folder")
        self.folder_hint.setObjectName("nav")
        self.folder_hint.setIcon(theme.icon("plus", 16))
        self.folder_hint.setIconSize(QSize(16, 16))
        self.folder_hint.clicked.connect(lambda: self.edit_folder(None))
        mv.addWidget(self.folder_hint)
        self.folder_navs = []
        mv.addSpacing(14)
        self.tags_label = QLabel("Tags")
        self.tags_label.setObjectName("section")
        mv.addWidget(self.tags_label)
        mv.addSpacing(4)
        self.tags_box = QVBoxLayout()
        self.tags_box.setSpacing(2)
        mv.addLayout(self.tags_box)
        self.tag_navs = []
        mv.addSpacing(14)
        self.apps_label = QLabel("Apps")
        self.apps_label.setObjectName("section")
        mv.addWidget(self.apps_label)
        mv.addSpacing(4)
        self.apps_box = QVBoxLayout()
        self.apps_box.setSpacing(2)
        mv.addLayout(self.apps_box)
        self.app_navs = []
        mv.addStretch(1)
        mid_scroll.setWidget(mid)
        sv.addWidget(mid_scroll, 1)
        sv.addSpacing(6)
        self.nav_settings = NavButton("settings", "Settings")
        self.nav_group.addButton(self.nav_settings)
        self.nav_settings.clicked.connect(lambda: self.stack.setCurrentWidget(self.settings_page))
        sv.addWidget(self.nav_settings)
        sv.addSpacing(6)
        self.storage = StorageView()
        sv.addWidget(self.storage)
        sv.addSpacing(8)
        self.collapse_btn = QPushButton("Collapse")
        self.collapse_btn.setObjectName("collapse")
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.clicked.connect(lambda: self.set_sidebar_collapsed(not self._collapsed))
        sv.addWidget(self.collapse_btn)
        self._collapsed = False
        h.addWidget(side)

        self.stack = QStackedWidget()
        self.library = LibraryPage(self)
        self.settings_page = SettingsPage(self)
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.settings_page)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.nav_home.setChecked(True)
        winapi.style_window(self.winId())
        self.refresh()
        self.set_sidebar_collapsed(bool(app.settings.sidebar_collapsed), save=False)

    def set_sidebar_collapsed(self, on, save=True):
        """Fold the sidebar down to an icon strip (and back). Remembered between runs."""
        self._collapsed = on
        self.side.setFixedWidth(64 if on else 228)
        self.side_layout.setContentsMargins(10 if on else 12, 18, 10 if on else 12, 14)
        self.brand_text.setVisible(not on)
        for lab in (self.folders_label, self.tags_label, self.apps_label):
            lab.setVisible(not on and lab.property("wanted") is not False)
        if self.folder_add is not None:
            self.folder_add.setVisible(not on)
        for b in self.side.findChildren(NavButton):
            b.set_compact(on)
        self.folder_hint.setText("" if on else "New folder")
        self.storage.set_compact(on)
        self.collapse_btn.setIcon(theme.icon("chevron" if on else "chevronleft", 14))
        self.collapse_btn.setText("" if on else "Collapse")
        self.collapse_btn.setToolTip("Expand the sidebar" if on else "")
        if save:
            self.app.settings.set(sidebar_collapsed=on)

    def _nav(self, layout, icon_name, text, flt):
        b = NavButton(icon_name, text)
        self.nav_group.addButton(b)
        b.clicked.connect(lambda: self._set_filter(flt, text))
        layout.addWidget(b)
        return b

    def _set_filter(self, flt, title):
        self.stack.setCurrentWidget(self.library)
        lib = self.library
        lib.filter = flt
        lib.title.setText(title)
        sub = ""
        if flt[0] == "folder":
            sub = library.describe(self.app.settings.folder_rules.get(flt[1], {}))
            sub = f"Auto-sorting  {sub}" if sub else "Drag captures here, or right-click a capture → Move to folder"
        lib.subtitle.setText(sub)
        lib.subtitle.setVisible(bool(sub))
        lib.edit_folder_btn.setVisible(flt[0] == "folder")
        lib.rebuild()

    # ---------------------------------------------------------------- folders
    def edit_folder(self, name, preselect=None):
        FolderDialog(self, name, preselect).exec()

    def move_paths(self, paths, folder, open_folder=False):
        root = Path(self.app.settings.save_folder)
        dest = root / folder if folder else root
        for p in paths:
            try:
                if Path(p).exists():
                    library.move_capture(p, dest)
            except OSError:
                pass
        self.library.selected = set()
        self.refresh()
        if open_folder and folder:
            for b in self.folder_navs:
                if b.name == folder:
                    b.setChecked(True)
            self._set_filter(("folder", folder), folder)
        elif self.library.filter[0] == "folder":
            self._set_filter(self.library.filter, self.library.filter[1])

    def sort_into(self, name):
        rule = self.app.settings.folder_rules.get(name, {})
        paths = [r["path"] for r in self.library.records
                 if r["folder"] != name and library.rule_matches(rule, r["app"], r["title"], r["ts"])]
        self.move_paths(paths, name)

    def delete_folder(self, name):
        r = QMessageBox.question(self, "Glint", f"Delete the folder “{name}”?\n\n"
                                 "Its captures are kept and moved back to your library.")
        if r != QMessageBox.Yes:
            return
        library.remove_folder(self.app.settings.save_folder, name)
        rules = dict(self.app.settings.folder_rules)
        rules.pop(name, None)
        self.app.settings.set(folder_rules=rules)
        if self.library.filter == ("folder", name):
            self.nav_home.setChecked(True)
            self._set_filter(("all", None), "Captures")
        self.refresh()

    def refresh(self):
        self.library.load()
        recs = self.library.records
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self.nav_home.set_count(len(recs))
        _ = (now, start)
        # space used, split by folder (no limit - it's local - so the bar shows what's taking the room)
        by = Counter()
        for r in recs:
            by[r["folder"] or ""] += r.get("size", 0)
        self.storage.set_data(by)
        # rebuild app list
        for b in self.app_navs:
            self.nav_group.removeButton(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        self.app_navs = []
        counts = Counter(r["app"] for r in recs if r["app"])
        exes = {r["app"]: r["exe"] for r in recs if r.get("exe")}
        for name, n in counts.most_common(6):
            b = NavButton("app", name)
            ic = app_icon_for(name, exes.get(name))
            if ic:
                b.setIcon(ic)
            b.set_count(n)
            self.nav_group.addButton(b)
            b.clicked.connect(lambda _=False, nm=name: self._set_filter(("app", nm), nm))
            if self.library.filter == ("app", name):
                b.setChecked(True)
            self.apps_box.addWidget(b)
            self.app_navs.append(b)
        self.apps_label.setProperty("wanted", bool(counts))
        self.apps_label.setVisible(bool(counts) and not getattr(self, "_collapsed", False))
        # folders
        for b in self.folder_navs:
            self.nav_group.removeButton(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        self.folder_navs = []
        fcounts = Counter(r["folder"] for r in recs if r["folder"])
        rules = self.app.settings.folder_rules or {}
        for d in library.folder_dirs(self.app.settings.save_folder):
            b = FolderNav(self, d.name, library.has_conditions(rules.get(d.name)))
            b.set_dot(theme.folder_color(d.name))
            b.set_count(fcounts.get(d.name, 0))
            self.nav_group.addButton(b)
            b.clicked.connect(lambda _=False, nm=d.name: self._set_filter(("folder", nm), nm))
            if self.library.filter == ("folder", d.name):
                b.setChecked(True)
            self.folders_box.addWidget(b)
            self.folder_navs.append(b)
        self.folder_hint.setVisible(not self.folder_navs)
        # tags
        for b in self.tag_navs:
            self.nav_group.removeButton(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        self.tag_navs = []
        tcounts = Counter(t for r in recs for t in r.get("tags", []))
        entries = [(("tag", t), "#" + t, n) for t, n in sorted(tcounts.items(), key=lambda kv: kv[0].lower())]
        if tcounts:
            entries.append((("untagged", None), "Untagged", sum(1 for r in recs if not r.get("tags"))))
        for flt, label, n in entries:
            b = NavButton("tag" if flt[0] == "tag" else "image", label if flt[0] == "tag" else label)
            b.set_dot(theme.DIM if flt[0] == "tag" else theme.LINE)
            b.set_count(n)
            self.nav_group.addButton(b)
            b.clicked.connect(lambda _=False, f=flt, lb=label: self._set_filter(f, lb))
            if self.library.filter == flt:
                b.setChecked(True)
            self.tags_box.addWidget(b)
            self.tag_navs.append(b)
        self.tags_label.setProperty("wanted", bool(tcounts))
        self.tags_label.setVisible(bool(tcounts) and not getattr(self, "_collapsed", False))
        if getattr(self, "_collapsed", False):        # new buttons made while folded: fold them too
            for b in self.app_navs + self.folder_navs + self.tag_navs:
                b.set_compact(True)

    def keyPressEvent(self, e):
        lib = self.library
        if e.key() == Qt.Key_Delete and lib.selected and self.stack.currentWidget() is lib:
            lib.delete(list(lib.selected))
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and len(lib.selected) == 1:
            self.app.open_editor(path=next(iter(lib.selected)))
        elif e.key() == Qt.Key_F and e.modifiers() & Qt.ControlModifier:
            lib.search.setFocus()
        elif (self.stack.currentWidget() is lib and not lib.search.hasFocus() and lib.tiles
              and e.key() == Qt.Key_A and e.modifiers() & Qt.ControlModifier):
            lib.select_all()
        elif self.stack.currentWidget() is lib and e.key() == Qt.Key_Escape and lib.selected:
            lib.set_selection(set())
        elif (self.stack.currentWidget() is lib and not lib.search.hasFocus() and lib.tiles
              and e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End)):
            first = next((lib.tiles[p] for p in lib.tiles if p in lib.selected), next(iter(lib.tiles.values())))
            if not lib.selected:
                lib.select(first)
            first.setFocus(Qt.OtherFocusReason)
        elif e.key() == Qt.Key_V and e.modifiers() & Qt.ControlModifier and not lib.search.hasFocus():
            self.app.new_from_clipboard()
        else:
            super().keyPressEvent(e)

    def open_image(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open image", self.app.settings.save_folder,
                                            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if fn:
            if fn.lower().endswith(".png"):
                self.app.open_editor(path=fn)
            else:
                self.app.open_editor(image=QImage(fn))

    def closeEvent(self, e):
        e.ignore()
        self.hide()


class DuplicatesDialog(QDialog):
    """Groups of captures that look identical; the oldest of each group is kept by default."""

    def __init__(self, home):
        super().__init__(home)
        from . import dupes
        self.home = home
        self.app = home.app
        self.setWindowTitle("Duplicates")
        self.resize(780, 580)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        title = QLabel("Find duplicates")
        title.setObjectName("h1")
        lay.addWidget(title)
        self.info = QLabel("Scanning your captures…")
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(14)
        self.list.addStretch(1)
        area.setWidget(inner)
        lay.addWidget(area, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.del_btn = QPushButton("Move to Recycle Bin")
        self.del_btn.setObjectName("primary")
        self.del_btn.setEnabled(False)
        self.del_btn.clicked.connect(self.delete)
        row.addWidget(close)
        row.addWidget(self.del_btn)
        lay.addLayout(row)
        self.checks = {}
        paths = storage.list_captures(self.app.settings.save_folder, limit=100000)
        self.total = len(paths)
        self.scanner = dupes.Scanner(paths)
        self.scanner.progress.connect(lambda i, n: self.info.setText(f"Scanning your captures… {i} of {n}"))
        self.scanner.done.connect(self.show_groups)
        self.scanner.start()
        winapi.style_window(self.winId())

    def show_groups(self, groups):
        if not groups:
            self.info.setText(f"No duplicates among your {self.total} captures.")
            return
        extra = sum(len(g) - 1 for g in groups)
        self.info.setText(f"{len(groups)} group{'s' if len(groups) != 1 else ''} of matching captures "
                          f"({extra} extra cop{'ies' if extra != 1 else 'y'}). The oldest in each group is kept; "
                          "tick or untick what to remove. Removed captures go to the Recycle Bin.")
        for g in groups:
            g = sorted(g, key=lambda x: Path(x).stat().st_mtime if Path(x).exists() else 0)
            card = QFrame()
            card.setObjectName("card")
            h = QHBoxLayout(card)
            h.setContentsMargins(12, 12, 12, 12)
            h.setSpacing(12)
            for i, path in enumerate(g):
                col = QVBoxLayout()
                col.setSpacing(6)
                thumb = QLabel()
                r = QImageReader(path)
                sz = r.size()
                if sz.isValid():
                    sz.scale(QSize(170, 110), Qt.KeepAspectRatio)
                    r.setScaledSize(sz)
                thumb.setPixmap(QPixmap.fromImage(r.read()))
                thumb.setFixedSize(170, 110)
                thumb.setAlignment(Qt.AlignCenter)
                thumb.setToolTip(path)
                col.addWidget(thumb)
                when = datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%d %b %Y, %H:%M")
                lbl = QLabel(f"{Path(path).parent.name} · {when}" if Path(path).parent != Path(
                    self.app.settings.save_folder) else when)
                lbl.setObjectName("muted")
                col.addWidget(lbl)
                cb = QCheckBox("Remove" if i else "Remove (oldest)")
                cb.setChecked(i > 0)
                cb.toggled.connect(self._update_btn)
                col.addWidget(cb)
                self.checks[path] = cb
                h.addLayout(col)
            h.addStretch(1)
            self.list.insertWidget(self.list.count() - 1, card)
        self._update_btn()

    def _update_btn(self):
        n = sum(cb.isChecked() for cb in self.checks.values())
        self.del_btn.setEnabled(n > 0)
        self.del_btn.setText(f"Move {n} to Recycle Bin" if n else "Move to Recycle Bin")

    def delete(self):
        paths = [p for p, cb in self.checks.items() if cb.isChecked()]
        for p in paths:
            try:
                storage.delete_capture(p)
            except Exception:
                pass
        self.home.refresh()
        self.accept()

    def done(self, r):
        self.scanner.stopped = True
        super().done(r)


class TagDialog(QDialog):
    """Add / remove tags on one or more captures. Tags already used anywhere show as chips."""

    def __init__(self, page, paths):
        super().__init__(page)
        self.page, self.paths = page, list(paths)
        self.setWindowTitle("Tags")
        self.setMinimumWidth(420)
        recs = {r["path"]: r for r in page.records}
        mine = [set(recs.get(p, {}).get("tags", [])) for p in self.paths]
        self.all_on = set.intersection(*mine) if mine else set()
        self.some_on = set.union(*mine) if mine else set()
        known = sorted({t for r in page.records for t in r.get("tags", [])}, key=str.lower)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        t = QLabel("Tags" if len(self.paths) == 1 else f"Tags for {len(self.paths)} captures")
        t.setObjectName("h1")
        lay.addWidget(t)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type a tag and press Enter  (e.g. work, receipts, bug)")
        self.edit.returnPressed.connect(self._add_typed)
        lay.addWidget(self.edit)
        self.chips_w = QWidget()
        self.chips = FlowLayout(self.chips_w, spacing=6)
        lay.addWidget(self.chips_w)
        self.buttons = {}
        for tag in known:
            self._chip(tag, tag in self.all_on)
        hint = QLabel("Click a tag to add or remove it. Tags show in the sidebar and search finds #tag.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Save")
        ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        winapi.style_window(self.winId())
        self.edit.setFocus()

    def _chip(self, tag, on):
        if tag in self.buttons:
            self.buttons[tag].setChecked(on)
            return
        b = QToolButton()
        b.setObjectName("appchip")
        b.setCheckable(True)
        b.setChecked(on)
        b.setText("#" + tag)
        if tag in self.some_on and tag not in self.all_on:
            b.setToolTip("On some of the selected captures - click to put it on all")
        self.chips.addWidget(b)
        self.buttons[tag] = b

    def _add_typed(self):
        for part in self.edit.text().replace(",", " ").split():
            tag = part.strip().lstrip("#")
            if tag:
                self._chip(tag, True)
        self.edit.clear()

    def _save(self):
        self._add_typed()
        on = {t for t, b in self.buttons.items() if b.isChecked()}
        recs = {r["path"]: r for r in self.page.records}
        for p in self.paths:
            cur = set(recs.get(p, {}).get("tags", []))
            # checked -> on every capture. Unchecked -> removed only if it was on all of them to begin with;
            # a tag that was on just some of them and wasn't clicked stays exactly as it was.
            removed = {t for t, b in self.buttons.items() if not b.isChecked() and t in self.all_on}
            new = (cur | on) - removed
            try:
                storage.set_tags(p, new)
            except Exception:
                pass
        self.accept()
        self.page.home.refresh()


class CombineDialog(QDialog):
    """Put the selected captures together: side by side, stacked or a grid. Opens the result in the editor."""

    def __init__(self, page, paths):
        super().__init__(page)
        from . import combine
        self.page, self.combine = page, combine
        self.images = [QImage(p) for p in paths]
        self.setWindowTitle("Combine captures")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        t = QLabel(f"Combine {len(paths)} captures")
        t.setObjectName("h1")
        lay.addWidget(t)
        opts = QHBoxLayout()
        opts.setSpacing(8)
        self.layout_cb = QComboBox()
        for label, val in (("Side by side", "row"), ("Stacked", "column"), ("Grid", "grid")):
            self.layout_cb.addItem(label, val)
        self.bg_cb = QComboBox()
        for label, val in (("Transparent", "transparent"), ("White", "white"), ("Dark", "dark")):
            self.bg_cb.addItem(label, val)
        self.gap_cb = QComboBox()
        for label, val in (("No gap", 0), ("Small gap", 12), ("Large gap", 32)):
            self.gap_cb.addItem(label, val)
        self.gap_cb.setCurrentIndex(1)
        self.round_cb = QCheckBox("Rounded corners")
        for w in (self.layout_cb, self.bg_cb, self.gap_cb):
            w.currentIndexChanged.connect(self._preview)
            opts.addWidget(w)
        self.round_cb.toggled.connect(self._preview)
        opts.addWidget(self.round_cb)
        opts.addStretch(1)
        lay.addLayout(opts)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumHeight(340)
        self.view.setObjectName("empty")
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.size_lbl = QLabel()
        self.size_lbl.setObjectName("muted")
        row.addWidget(self.size_lbl)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Open in editor")
        ok.setObjectName("primary")
        ok.clicked.connect(self._open)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        winapi.style_window(self.winId())
        self._preview()

    def result(self):
        g = self.gap_cb.currentData()
        return self.combine.combine(self.images, self.layout_cb.currentData(), g, self.bg_cb.currentData(),
                                    radius=10 if self.round_cb.isChecked() else 0)

    def _preview(self):
        img = self.result()
        self.size_lbl.setText(f"{img.width()} × {img.height()}")
        dpr = self.devicePixelRatioF()
        box = QSize(max(100, self.view.width() - 24), max(100, self.view.height() - 24))
        pm = QPixmap.fromImage(img).scaled(box * dpr, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.view.setPixmap(pm)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._preview()

    def _open(self):
        img = self.result()
        self.accept()
        self.page.app.open_editor(image=img, info={"title": "Combined capture", "app": "Glint"})
