"""The annotation editor window."""
import copy
import json
import math
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QCursor, QFont, QFontMetrics, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QColorDialog, QDialog, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

from . import render, storage, theme, winapi

TOOLS = [
    ("select", "Select / move", "V"),
    ("arrow", "Arrow", "A"),
    ("rect", "Rectangle", "R"),
    ("ellipse", "Ellipse", "E"),
    ("line", "Line", "L"),
    ("pen", "Pen", "P"),
    ("highlight", "Highlighter", "H"),
    ("text", "Text", "T"),
    ("step", "Numbered step", "N"),
    ("stamp", "Stamp - click to place, click again to pick a different one", "S"),
    ("blur", "Pixelate / hide", "B"),
    ("crop", "Crop", "C"),
    ("picker", "Colour picker - click the image to use / copy a colour", "I"),
]
SHAPES_MIME = "application/x-glint-shapes"
PALETTE = ["#ff3b30", "#ff9500", "#ffd60a", "#34c759", "#0a84ff", "#bf5af2", "#ffffff", "#1c1c1e"]
# Built-in style presets (the popup's dropdown). User presets are stored in settings.style_presets.
PRESETS = [
    {"name": "Glint default", "color": "#ff3b30", "width": 4, "font": 28, "fill": False, "shadow": True,
     "head": "tapered", "outline": False},
    {"name": "Classic red arrow", "color": "#ff3b30", "width": 6, "font": 28, "fill": False, "shadow": True,
     "head": "classic", "outline": False},
    {"name": "Bold callout", "color": "#ffd60a", "width": 8, "font": 36, "fill": False, "shadow": True,
     "head": "classic", "outline": True},
    {"name": "Outlined (busy screens)", "color": "#ff3b30", "width": 5, "font": 30, "fill": False, "shadow": False,
     "head": "classic", "outline": True},
    {"name": "Thin and clean", "color": "#0a84ff", "width": 2, "font": 22, "fill": False, "shadow": False,
     "head": "tapered", "outline": False},
    {"name": "Measure / double arrow", "color": "#ffffff", "width": 3, "font": 22, "fill": False, "shadow": False,
     "head": "double", "outline": True},
    {"name": "Soft highlight box", "color": "#ff9500", "width": 3, "font": 28, "fill": True, "shadow": False,
     "head": "tapered", "outline": False},
]
STYLE_KEYS = ("color", "width", "font", "fill", "shadow", "head", "outline")
HEAD_TIPS = {"tapered": "Tapered", "classic": "Classic", "double": "Double-headed"}


def arrow_icon(head, size=34, color="#e8e8e8"):
    from PySide6.QtGui import QIcon, QPixmap
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    path = render.arrow_path(5, size - 7, size - 5, 7, 3, head)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)
    p.end()
    return QIcon(pm)


HIGHLIGHT_COLORS = {"#ff3b30": "#ffb3ae", "#ff9500": "#ffd08a", "#ffd60a": "#fff176", "#34c759": "#a6f0b4",
                    "#0a84ff": "#9fd0ff", "#bf5af2": "#e2b8fa", "#ffffff": "#ffffff", "#1c1c1e": "#bbbbbb"}


class InlineText(QPlainTextEdit):
    done = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFrameStyle(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._finished = False
        self.textChanged.connect(self.fit)

    def fit(self):
        fm = self.fontMetrics()
        lines = (self.toPlainText() or " ").split("\n")
        w = max(fm.horizontalAdvance(l) for l in lines) + fm.averageCharWidth() * 3 + 12
        h = fm.lineSpacing() * len(lines) + 14
        self.resize(int(w), int(h))

    def finish(self):
        if not self._finished:
            self._finished = True
            self.done.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape or (e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier):
            self.finish()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.finish()


class Canvas(QWidget):
    changed = Signal()
    selection_changed = Signal()
    zoom_changed = Signal(float)

    def __init__(self, editor, base, shapes, frame=None):
        super().__init__()
        self.ed = editor
        self.base = base.convertToFormat(QImage.Format_RGB32)
        self.shapes = copy.deepcopy(shapes)
        self.frame = copy.deepcopy(frame) if frame else None
        self._bg_key = None
        self._bg = None
        self.tool = "arrow"
        self.sel = None
        self.zoom = 1.0
        self.drag = None
        self.temp = None
        self.crop_rect = None
        self.text_edit = None
        self.next_bubble = False     # Insert > Callout: the next text becomes a speech bubble
        self.hover_pt = None         # image point under the mouse (colour picker loupe)
        self.measure = None          # (QPointF, QPointF) ruler line, image coords
        self.pixel_grid = True       # draw pixel grid when zoomed in a lot
        self.grab_mode = False       # Copy text from area: the next drag selects text instead of drawing
        self._ocr_cache = (None, None)
        self.editing_idx = None
        self.pan = None
        self.pan_moved = 0
        self.space_down = False
        self.guides = []
        self.setAcceptDrops(True)
        self.history = [self._snapshot()]
        self.hidx = 0
        self.dirty = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.update_size()

    # ---------------------------------------------------------------- history
    def _snapshot(self):
        return (self.base, copy.deepcopy(self.shapes), copy.deepcopy(self.frame))

    def commit(self):
        self.history = self.history[: self.hidx + 1] + [self._snapshot()]
        if len(self.history) > 200:
            self.history.pop(0)
        self.hidx = len(self.history) - 1
        self.dirty = True
        self.changed.emit()
        self.update()

    def _restore(self, i):
        self.hidx = i
        base, shapes, frame = self.history[i]
        size_changed = base.size() != self.base.size() or frame != self.frame
        self.base = base
        self.shapes = copy.deepcopy(shapes)
        self.frame = copy.deepcopy(frame)
        self.set_sel(None)
        self.dirty = True
        if size_changed:
            self.update_size()
        self.changed.emit()
        self.update()

    def undo(self):
        self.finish_text()
        if self.hidx > 0:
            self._restore(self.hidx - 1)

    def redo(self):
        if self.hidx < len(self.history) - 1:
            self._restore(self.hidx + 1)

    # ---------------------------------------------------------------- geometry
    def scale(self):
        return self.zoom / max(0.1, self.devicePixelRatioF())

    def layout(self):
        """(out_w, out_h, ox, oy): the image's offset inside the Beautify frame."""
        w, h = self.base.width(), self.base.height()
        if not self.frame:
            return w, h, 0, 0
        return render.frame_layout(w, h, self.frame)

    def update_size(self):
        s = self.scale()
        ow, oh, _, _ = self.layout()
        self.setFixedSize(max(1, math.ceil(ow * s)), max(1, math.ceil(oh * s)))
        self.update()

    def set_frame(self, frame, commit=True):
        self.frame = copy.deepcopy(frame) if frame else None
        self.update_size()
        if commit:
            self.commit()
        else:
            self.update()

    def _frame_bg(self):
        key = (self.base.cacheKey(), json.dumps(self.frame, sort_keys=True))
        if key != self._bg_key:
            self._bg = render.frame_background(self.base.width(), self.base.height(), self.frame, self.base)
            self._bg_key = key
        return self._bg

    def set_zoom(self, z):
        self.zoom = max(0.05, min(8.0, z))
        self.update_size()
        if self.text_edit:
            self.finish_text()
        self.zoom_changed.emit(self.zoom)

    def to_img(self, pos):
        s = self.scale()
        _, _, ox, oy = self.layout()
        return QPointF(pos.x() / s - ox, pos.y() / s - oy)

    def set_sel(self, idx):
        self.sel = idx
        self.selection_changed.emit()
        self.update()

    def selected(self):
        if self.sel is not None and 0 <= self.sel < len(self.shapes):
            return self.shapes[self.sel]
        return None

    def final_image(self):
        self.finish_text()
        return render.render(self.base, self.shapes, self.frame)

    def hit(self, pt):
        for i in range(len(self.shapes) - 1, -1, -1):
            if render.hit_path(self.shapes[i]).contains(pt):
                return i
        return None

    def handle_at(self, pt):
        s = self.selected()
        if not s:
            return None
        r = 7 / self.scale()
        for i, h in enumerate(render.handles(s)):
            if abs(h.x() - pt.x()) <= r and abs(h.y() - pt.y()) <= r:
                return i
        return None

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        s = self.scale()
        p.scale(s, s)
        p.setRenderHint(QPainter.Antialiasing)
        if self.frame:
            _, _, ox, oy = self.layout()
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawImage(0, 0, self._frame_bg())
            p.translate(ox, oy)
            clip = QPainterPath()
            rad = render.frame_radius(self.base.width(), self.base.height(), self.frame)
            clip.addRoundedRect(QRectF(self.base.rect()), rad, rad)
            p.setClipPath(clip)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom < 1.0)
        p.drawImage(0, 0, self.base)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for i, sh in enumerate(self.shapes):
            if i == self.editing_idx:
                continue
            render.draw_shape(p, sh, self.base, self.shapes)
        if self.temp:
            render.draw_shape(p, self.temp, self.base, self.shapes + [self.temp])
        if self.crop_rect is not None:
            r = self.crop_rect
            full = QPainterPath()
            full.addRect(QRectF(self.base.rect()))
            hole = QPainterPath()
            hole.addRect(r)
            p.fillPath(full.subtracted(hole), QColor(0, 0, 0, 140))
            p.setPen(QPen(QColor("white"), 1.5 / s, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        for poly in getattr(self, "code_marks", ()):
            pad = 6 / s
            r = poly.boundingRect().adjusted(-pad, -pad, pad, pad)
            p.setPen(QPen(QColor(theme.ACCENT), 2.5 / s))
            p.setBrush(QColor(110, 140, 255, 28))
            p.drawRoundedRect(r, 6 / s, 6 / s)
        if self.guides:
            p.setPen(QPen(QColor("#ff4fa3"), 1 / s))
            for kind, v in self.guides:
                if kind == "v":
                    p.drawLine(QPointF(v, -10000), QPointF(v, 10000))
                else:
                    p.drawLine(QPointF(-10000, v), QPointF(10000, v))
        p.setClipping(False)
        sel = self.selected()
        if sel and self.editing_idx is None:
            p.setPen(QPen(QColor(theme.ACCENT), 1.2 / s, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            if sel["kind"] not in render.LINE_KINDS:
                p.drawRect(render.bounds(sel))
            hs = 5 / s
            p.setPen(QPen(QColor(theme.ACCENT), 1.5 / s))
            p.setBrush(QColor("white"))
            for h in render.handles(sel):
                p.drawEllipse(h, hs, hs)
        self._paint_dev(p, s, _e)

    def _paint_dev(self, p, s, e):
        """Pixel grid (zoomed in), measuring line and the colour-picker loupe."""
        if self.pixel_grid and s >= 8 and not self.frame:
            vis = QRectF(e.rect().x() / s, e.rect().y() / s, e.rect().width() / s, e.rect().height() / s)
            vis = vis.intersected(QRectF(self.base.rect()))
            pen = QPen(QColor(128, 128, 128, 110), 0)
            pen.setCosmetic(True)
            p.setPen(pen)
            x0, x1 = int(vis.left()), int(vis.right()) + 1
            y0, y1 = int(vis.top()), int(vis.bottom()) + 1
            for x in range(x0, x1 + 1):
                p.drawLine(QPointF(x, y0), QPointF(x, y1))
            for y in range(y0, y1 + 1):
                p.drawLine(QPointF(x0, y), QPointF(x1, y))
        if self.measure is not None:
            a, b = self.measure
            p.setPen(QPen(QColor(0, 0, 0, 170), 3.5 / s))
            p.drawLine(a, b)
            p.setPen(QPen(QColor("#ffd23f"), 1.6 / s))
            p.drawLine(a, b)
            for q in (a, b):
                p.drawEllipse(q, 3 / s, 3 / s)
            dx, dy = abs(b.x() - a.x()), abs(b.y() - a.y())
            text = f"{math.hypot(dx, dy):.0f} px" + (f"   ↔ {dx:.0f}  ↕ {dy:.0f}" if dx >= 1 and dy >= 1 else "")
            self._paint_tag(p, s, (a + b) / 2, text)
        if self.tool == "picker" and self.hover_pt is not None:
            self._paint_loupe(p, s, self.hover_pt)

    def _paint_tag(self, p, s, at, text):
        p.save()
        p.resetTransform()
        f = QFont("Segoe UI")
        f.setPixelSize(12)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 16, fm.height() + 8
        x, y = at.x() * s + 12, at.y() * s + 8
        box = QRectF(min(x, self.width() - w - 4), min(y, self.height() - h - 4), w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, 235))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignCenter, text)
        p.restore()

    def _paint_loupe(self, p, s, pt):
        ix, iy = int(pt.x()), int(pt.y())
        if not self.base.rect().contains(ix, iy):
            return
        n, cell = 11, 9
        size = n * cell
        src = self.base.copy(ix - n // 2, iy - n // 2, n, n)
        p.save()
        p.resetTransform()
        cx, cy = pt.x() * s, pt.y() * s
        ox = cx + 22 if cx + 22 + size < self.width() else cx - 22 - size
        oy = cy + 22 if cy + 22 + size + 30 < self.height() else cy - 22 - size - 30
        box = QRectF(ox, oy, size, size)
        clip = QPainterPath()
        clip.addRoundedRect(box, 8, 8)
        p.setClipPath(clip)
        p.fillRect(box, QColor("black"))
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawImage(box, src)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QPen(QColor("white"), 1))
        p.drawRect(QRectF(ox + (n // 2) * cell, oy + (n // 2) * cell, cell, cell))
        col = QColor(self.base.pixel(ix, iy))
        label = f"{col.name().upper()}   {col.red()}, {col.green()}, {col.blue()}"
        f = QFont("Cascadia Mono")
        f.setStyleHint(QFont.Monospace)
        f.setPixelSize(11)
        p.setFont(f)
        info = QRectF(ox, oy + size + 4, max(size, QFontMetrics(f).horizontalAdvance(label) + 34), 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, 235))
        p.drawRoundedRect(info, 5, 5)
        p.setBrush(col)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))
        p.drawRoundedRect(QRectF(info.x() + 5, info.y() + 5, 14, 14), 3, 3)
        p.setPen(QColor("white"))
        p.drawText(info.adjusted(24, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        p.restore()

    # ---------------------------------------------------------------- shape creation
    def new_shape(self, kind, pt):
        st = self.ed.annot_style()
        color = st["color"]
        if kind == "highlight":
            color = HIGHLIGHT_COLORS.get(color.lower(), color)
        return {"kind": kind, "pts": [[pt.x(), pt.y()], [pt.x(), pt.y()]] if kind != "pen" else [[pt.x(), pt.y()]],
                "color": color, "width": st["width"], "fill": st["fill"], "shadow": st["shadow"],
                "text": "", "font": st["font"], "number": 0, "head": st["head"], "outline": st["outline"],
                "bubble": st["bubble"] if kind == "text" else False}

    def next_step(self):
        nums = [s.get("number", 0) for s in self.shapes if s["kind"] == "step"]
        return (max(nums) + 1) if nums else 1

    # ---------------------------------------------------------------- navigation helpers
    def _scrollbars(self):
        a = self.ed.area
        return a.horizontalScrollBar(), a.verticalScrollBar()

    def zoom_at(self, factor, widget_pos=None):
        """Zoom keeping the image point under the cursor fixed (or the view centre)."""
        area = self.ed.area
        vp = area.viewport()
        if widget_pos is None:
            vpos = QPointF(vp.width() / 2, vp.height() / 2)
            widget_pos = QPointF(self.mapFrom(vp, vpos.toPoint()))
        else:
            vpos = QPointF(self.mapTo(vp, widget_pos.toPoint()))
        s0 = self.scale()
        anchor = QPointF(widget_pos.x() / s0, widget_pos.y() / s0)  # framed-canvas coords
        self.set_zoom(self.zoom * factor)

        def settle():
            # the scroll area grows asynchronously; apply once its new size/ranges are in place
            QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
            area.widget().layout().activate()
            s1 = self.scale()
            hb, vb = self._scrollbars()
            hb.setValue(int(self.x() + anchor.x() * s1 - vpos.x()))
            vb.setValue(int(self.y() + anchor.y() * s1 - vpos.y()))

        settle()
        QTimer.singleShot(0, self, settle)

    def _start_pan(self, e):
        self.pan = e.globalPosition()
        self.pan_moved = 0
        self.setCursor(Qt.ClosedHandCursor)

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        self.setFocus()
        if self.text_edit:
            self.finish_text()
            return
        if e.button() in (Qt.MiddleButton, Qt.RightButton) or (e.button() == Qt.LeftButton and self.space_down):
            self._start_pan(e)
            self.pan_button = e.button()
            return
        if e.button() != Qt.LeftButton:
            return
        pt = self.to_img(e.position())
        if self.tool != "crop":
            h = self.handle_at(pt)
            if h is not None:
                self.drag = {"mode": "handle", "h": h, "orig": copy.deepcopy(self.selected())}
                return
        if self.tool == "select":
            idx = self.hit(pt)
            self.set_sel(idx)
            if idx is not None:
                self.drag = {"mode": "move", "start": pt, "orig": copy.deepcopy(self.shapes[idx]), "moved": False}
            return
        if self.sel is not None and self.hit(pt) == self.sel and self.tool not in ("step", "crop"):
            self.drag = {"mode": "move", "start": pt, "orig": copy.deepcopy(self.shapes[self.sel]), "moved": False}
            return
        idx = self.hit(pt)
        if self.tool == "picker":
            self.ed.pick_from_image(pt, rgb=bool(e.modifiers() & Qt.ShiftModifier))
            return
        if self.tool == "measure":
            self.drag = {"mode": "measure", "start": pt}
            self.measure = (pt, pt)
            self.update()
            return
        if idx is not None and self.shapes[idx]["kind"] in ("image", "stamp") and self.tool not in ("crop", "step", "text"):
            # pasted images and stamps are picked up with any tool - they're objects, not something you draw on
            self.set_sel(idx)
            self.drag = {"mode": "move", "start": pt, "orig": copy.deepcopy(self.shapes[idx]), "moved": False}
            return
        if self.tool == "text":
            if idx is not None and self.shapes[idx]["kind"] == "text":
                self.edit_text(idx)
            else:
                self.edit_text(None, pt)
            return
        if self.tool == "stamp":
            self.insert_stamp(self.ed._stamp, pt)
            return
        if self.tool == "step":
            s = self.new_shape("step", pt)
            s["pts"] = [[pt.x(), pt.y()]]
            s["number"] = self.next_step()
            self.shapes.append(s)
            self.set_sel(len(self.shapes) - 1)
            self.commit()
            return
        if self.tool == "crop" or self.grab_mode:
            self.drag = {"mode": "grab" if self.grab_mode else "crop", "start": pt}
            self.crop_rect = QRectF(pt, pt)
            return
        self.set_sel(None)
        self.temp = self.new_shape(self.tool, pt)
        self.drag = {"mode": "draw", "start": pt}

    def mouseMoveEvent(self, e):
        if self.pan is not None:
            d = e.globalPosition() - self.pan
            self.pan = e.globalPosition()
            self.pan_moved += abs(d.x()) + abs(d.y())
            hb, vb = self._scrollbars()
            hb.setValue(int(hb.value() - d.x()))
            vb.setValue(int(vb.value() - d.y()))
            return
        pt = self.to_img(e.position())
        d = self.drag
        if self.tool == "picker":
            self.hover_pt = pt
            self.update()
        if d and d["mode"] == "measure":
            end = QPointF(*self._constrain(d["start"], pt, "line", bool(e.modifiers() & Qt.ShiftModifier)))
            self.measure = (d["start"], end)
            self.update()
            return
        if not d:
            self._update_cursor(pt)
            return
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        alt = bool(e.modifiers() & Qt.AltModifier)
        if d["mode"] == "draw" and self.temp:
            if self.temp["kind"] == "pen":
                lx, ly = self.temp["pts"][-1]
                if math.hypot(pt.x() - lx, pt.y() - ly) >= 1.5 / self.scale():
                    self.temp["pts"].append([pt.x(), pt.y()])
            else:
                self.temp["pts"][1] = list(self._constrain(d["start"], pt, self.temp["kind"], shift))
        elif d["mode"] == "move":
            s = self.shapes[self.sel]
            s["pts"] = copy.deepcopy(d["orig"]["pts"])
            dx, dy = pt.x() - d["start"].x(), pt.y() - d["start"].y()
            if shift:
                dx, dy = (dx, 0) if abs(dx) > abs(dy) else (0, dy)
            render.translate(s, dx, dy)
            self.guides = []
            if not alt:  # Alt = move freely without snapping
                sx, sy = self._snap(s)
                render.translate(s, sx, sy)
            d["moved"] = True
        elif d["mode"] == "handle":
            s = self.shapes[self.sel]
            s["pts"] = copy.deepcopy(d["orig"]["pts"])
            if shift and s["kind"] in render.LINE_KINDS and d["h"] < 2:
                anchor = render.P(s["pts"][-1] if d["h"] == 0 else s["pts"][0])
                pt = QPointF(*self._constrain(anchor, pt, s["kind"], True))
            render.set_handle(s, d["h"], pt, free=shift)
            d["moved"] = True
        elif d["mode"] in ("crop", "grab"):
            b = QRectF(self.base.rect())
            self.crop_rect = QRectF(d["start"], pt).normalized().intersected(b)
        self.update()

    def _snap(self, s):
        """Snap a moving shape's edges/centre to the image and other shapes. Returns (dx, dy)."""
        tol = 6 / self.scale()
        b = render.bounds(s) if s["kind"] not in render.RECT_KINDS else render.norm_rect(s)
        W, H = self.base.width(), self.base.height()
        xs, ys = [0, W / 2, W], [0, H / 2, H]
        for i, o in enumerate(self.shapes):
            if i == self.sel:
                continue
            ob = render.norm_rect(o) if o["kind"] in render.RECT_KINDS else render.bounds(o)
            xs += [ob.left(), ob.center().x(), ob.right()]
            ys += [ob.top(), ob.center().y(), ob.bottom()]
        best = [None, None]
        for axis, mine, cands in ((0, (b.left(), b.center().x(), b.right()), xs),
                                  (1, (b.top(), b.center().y(), b.bottom()), ys)):
            for m in mine:
                for c in cands:
                    diff = c - m
                    if abs(diff) <= tol and (best[axis] is None or abs(diff) < abs(best[axis][0])):
                        best[axis] = (diff, c)
        self.guides = []
        if best[0]:
            self.guides.append(("v", best[0][1]))
        if best[1]:
            self.guides.append(("h", best[1][1]))
        return (best[0][0] if best[0] else 0), (best[1][0] if best[1] else 0)

    def _constrain(self, a, b, kind, shift):
        if not shift:
            return b.x(), b.y()
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if kind in render.LINE_KINDS:
            ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
            L = math.hypot(dx, dy)
            return a.x() + L * math.cos(ang), a.y() + L * math.sin(ang)
        m = max(abs(dx), abs(dy))
        return a.x() + math.copysign(m, dx), a.y() + math.copysign(m, dy)

    def mouseReleaseEvent(self, e):
        if self.pan is not None:
            moved = self.pan_moved
            button = getattr(self, "pan_button", None)
            self.pan = None
            self._update_cursor(self.to_img(e.position()))
            if button == Qt.RightButton and moved < 4:   # a right *click* (not a drag) opens the menu
                self.context_menu(e)
            return
        d = self.drag
        self.drag = None
        self.guides = []
        if not d:
            return
        if d["mode"] == "measure":
            a, b = self.measure or (None, None)
            if a is not None and math.hypot(b.x() - a.x(), b.y() - a.y()) > 1:
                dist = math.hypot(b.x() - a.x(), b.y() - a.y())
                QApplication.clipboard().setText(f"{dist:.0f}")
                self.ed.flash(f"{dist:.0f} px  ·  copied  ·  Esc to clear")
            return
        if d["mode"] == "grab":
            r = self.crop_rect
            self.crop_rect = None
            self.set_grab_mode(False)
            if r is not None and r.width() > 4 and r.height() > 4:
                self.copy_text_in(r)
            self.update()
            return
        if d["mode"] == "draw" and self.temp:
            s = self.temp
            self.temp = None
            if s["kind"] == "blur" and math.hypot(s["pts"][1][0] - s["pts"][0][0],
                                                  s["pts"][1][1] - s["pts"][0][1]) <= 3:
                # a click (no drag) with the pixelate tool hides the line of text under the cursor
                self.hide_text_at(render.P(s["pts"][0]), word=bool(e.modifiers() & Qt.AltModifier))
                self.update()
                return
            ok = len(s["pts"]) > 1 if s["kind"] == "pen" else (
                math.hypot(s["pts"][1][0] - s["pts"][0][0], s["pts"][1][1] - s["pts"][0][1]) > 3)
            if s["kind"] in render.RECT_KINDS:
                r = render.norm_rect(s)
                ok = r.width() > 3 and r.height() > 3
            if ok:
                self.shapes.append(s)
                self.set_sel(len(self.shapes) - 1)
                self.commit()
            self.update()
        elif d["mode"] in ("move", "handle"):
            if d.get("moved"):
                self.commit()
            self.update()
        elif d["mode"] == "crop":
            r = self.crop_rect
            self.crop_rect = None
            if r is not None and r.width() > 4 and r.height() > 4:
                self.apply_crop(r.toAlignedRect().intersected(self.base.rect()))
            self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pt = self.to_img(e.position())
        idx = self.hit(pt)
        if idx is not None and self.shapes[idx]["kind"] == "text":
            self.edit_text(idx)
        elif idx is None and not QRectF(self.base.rect()).contains(pt):
            self.ed.fit()  # double-click the empty area around the image: fit to window

    def _update_cursor(self, pt):
        if self.space_down:
            self.setCursor(Qt.OpenHandCursor)
        elif self.handle_at(pt) is not None:
            self.setCursor(Qt.SizeAllCursor)
        elif self.tool == "select":
            self.setCursor(Qt.SizeAllCursor if self.hit(pt) is not None else Qt.ArrowCursor)
        elif self.sel is not None and self.hit(pt) == self.sel and self.tool not in ("step", "crop"):
            self.setCursor(Qt.SizeAllCursor)
        elif self.tool == "text":
            self.setCursor(Qt.IBeamCursor)
        elif self.tool in ("picker", "measure"):
            self.setCursor(Qt.CrossCursor)
        else:
            idx = self.hit(pt)
            if idx is not None and self.shapes[idx]["kind"] in ("image", "stamp") and self.tool not in ("crop", "step"):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)

    def leaveEvent(self, e):
        if self.hover_pt is not None:
            self.hover_pt = None
            self.update()
        super().leaveEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            steps = e.angleDelta().y() / 120.0
            if steps:
                self.zoom_at(1.15 ** steps, e.position())
            e.accept()
        else:
            e.ignore()  # let the scroll area scroll (Shift+wheel scrolls sideways)

    def keyPressEvent(self, e):
        k = e.key()
        s = self.selected()
        if k == Qt.Key_Space and not e.isAutoRepeat():
            self.space_down = True
            self.setCursor(Qt.OpenHandCursor)
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and s:
            self.shapes.pop(self.sel)
            self.set_sel(None)
            self.commit()
        elif k == Qt.Key_Escape and (self.measure is not None or self.tool in ("picker", "measure")):
            self.measure = None
            self.ed.set_tool(self.ed._prev_tool if self.tool in ("picker", "measure") else self.tool)
            self.update()
        elif k == Qt.Key_Escape:
            if self.grab_mode:
                self.set_grab_mode(False)
            if self.drag or self.temp or self.crop_rect is not None:
                self.drag = self.temp = self.crop_rect = None
                self.update()
            else:
                self.set_sel(None)
        elif s and k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if e.modifiers() & Qt.ShiftModifier else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            render.translate(s, dx, dy)
            self.commit()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space_down = False
            self._update_cursor(self.to_img(QPointF(self.mapFromGlobal(QCursor.pos()))))
        else:
            super().keyReleaseEvent(e)

    def focusOutEvent(self, e):
        self.space_down = False
        super().focusOutEvent(e)

    # ---------------------------------------------------------------- context menu
    def context_menu(self, e):
        pt = self.to_img(e.position())
        idx = self.hit(pt)
        if idx is not None:
            self.set_sel(idx)
        m = QMenu(self)
        s = self.shapes[idx] if idx is not None else None
        if s is not None and s["kind"] in render.LINE_KINDS and len(s["pts"]) == 3:
            m.addAction("Straighten", lambda: self.set_prop(pts=[s["pts"][0], s["pts"][-1]]))
            m.addSeparator()
        if s is not None and s["kind"] == "magnify":
            zm = m.addMenu("Zoom")
            for z in (1.5, 2.0, 3.0, 4.0):
                a = zm.addAction(f"{z:g}×", lambda z=z: self.set_prop(zoom=z))
                a.setCheckable(True)
                a.setChecked(abs(s.get("zoom", 2.0) - z) < 0.01)
            m.addAction("Square lens" if not s.get("fill") else "Round lens",
                        lambda: self.set_prop(fill=not s.get("fill")))
            m.addSeparator()
        if s is not None and s["kind"] == "spotlight":
            m.addAction("Round spotlight" if not s.get("fill") else "Rectangle spotlight",
                        lambda: self.set_prop(fill=not s.get("fill")))
            m.addSeparator()
        if s is not None and s["kind"] == "text":
            cur = s.get("bubble") or False
            for label, val in (("Plain text", False), ("Text box", "box"), ("Callout bubble", True)):
                a = m.addAction(label, lambda v=val: self.set_prop(bubble=v))
                a.setCheckable(True)
                a.setChecked(cur == val)
            m.addSeparator()
        if s is not None and s["kind"] == "stamp":
            sm = m.addMenu("Change stamp")
            self._stamp_menu(sm, lambda lab: self.set_prop(text=lab))
            m.addSeparator()
        if idx is not None:
            m.addAction("Copy shape", self.copy_shape, QKeySequence.Copy)
            m.addAction("Duplicate", self.duplicate, QKeySequence("Ctrl+D"))
            m.addSeparator()
            m.addAction("Bring to front", lambda: self.reorder(1), QKeySequence("Ctrl+]"))
            m.addAction("Send to back", lambda: self.reorder(-1), QKeySequence("Ctrl+["))
            m.addSeparator()
            m.addAction("Delete", self.delete_selected, QKeySequence.Delete)
        else:
            m.addAction("Paste", lambda: self.paste(at=pt), QKeySequence.Paste)
            m.addSeparator()
            m.addAction("Add callout here", lambda: self.insert_callout(pt))
            m.addAction("Add text box here", lambda: self.insert_callout(pt, box=True))
            self._stamp_menu(m.addMenu("Add stamp here"), lambda lab: self.insert_stamp(lab, pt))
            m.addAction("Add spotlight here", lambda: self.insert_spotlight(pt))
            m.addAction("Add magnifier here", lambda: self.insert_magnifier(pt))
            m.addSeparator()
            m.addAction("Fit to window", self.ed.fit, QKeySequence("Ctrl+0"))
            m.addAction("Actual size", lambda: self.set_zoom(1.0), QKeySequence("Ctrl+1"))
        m.exec(e.globalPosition().toPoint())

    # ---------------------------------------------------------------- text-aware helpers
    def ocr_lines(self):
        """OCR of the current image, cached until the image changes. None if OCR failed."""
        from . import ocr
        key = self.base.cacheKey()
        if self._ocr_cache[0] == key:
            return self._ocr_cache[1]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            lines = ocr.recognize(self.base)
        except Exception as e:
            QMessageBox.warning(self.ed, "Glint", f"Text recognition failed.\n\n{e}")
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self._ocr_cache = (key, lines)
        return lines

    def hide_text_at(self, pt, word=False):
        lines = self.ocr_lines()
        if not lines:
            if lines is not None:
                self.ed.flash("No text there")
            return
        hit = None
        for words in lines:
            box = QRectF()
            for _, r in words:
                box = box.united(r)
            if box.adjusted(-4, -4, 4, 4).contains(pt):
                hit = box
                if word:
                    w = next((r for _, r in words if r.adjusted(-3, -4, 3, 4).contains(pt)), None)
                    hit = w
                break
        if hit is None:
            self.ed.flash("No text there · drag to pixelate an area")
            return
        pad = max(2.0, hit.height() * 0.18)
        r = hit.adjusted(-pad, -pad, pad, pad)
        s = self.new_shape("blur", r.topLeft())
        s["pts"] = [[r.left(), r.top()], [r.right(), r.bottom()]]
        self.shapes.append(s)
        self.set_sel(len(self.shapes) - 1)
        self.commit()

    def set_grab_mode(self, on):
        self.grab_mode = on
        if on:
            self.set_sel(None)
            self.setCursor(Qt.CrossCursor)
            self.ed.flash("Drag over the text you want to copy", 3000)
        else:
            self._update_cursor(self.to_img(QPointF(self.mapFromGlobal(QCursor.pos()))))

    def copy_text_in(self, area):
        from . import ocr
        lines = self.ocr_lines()
        if lines is None:
            return
        picked = []
        for words in lines:
            ws = [(w, r) for w, r in words if area.contains(r.center())]
            if ws:
                picked.append(ws)
        text = ocr.lines_to_text(picked).strip()
        if not text:
            self.ed.flash("No text in that area")
            return
        QApplication.clipboard().setText(text)
        n = len(text.splitlines())
        self.ed.flash(f"Copied {n} line{'s' if n != 1 else ''} of text")

    # ---------------------------------------------------------------- inserted objects
    def _default_box(self, at, frac=0.35, square=False):
        W, H = self.base.width(), self.base.height()
        c = at if at is not None else self.visible_center()
        w, h = max(40.0, W * frac), max(40.0, H * frac)
        if square:
            w = h = min(w, h)
        x = min(max(c.x() - w / 2, 0), max(0, W - w))
        y = min(max(c.y() - h / 2, 0), max(0, H - h))
        return x, y, w, h

    def insert_spotlight(self, at=None):
        x, y, w, h = self._default_box(at)
        s = self.new_shape("spotlight", QPointF(x, y))
        s.update(pts=[[x, y], [x + w, y + h]], fill=False, shadow=False)
        self.shapes.insert(0, s)     # behind everything, so arrows/text on top stay on top
        self.set_sel(0)
        self.commit()
        self.ed.flash("Drag the corners to fit · right-click for round")

    def insert_magnifier(self, at=None):
        x, y, w, h = self._default_box(at, 0.22, square=True)
        s = self.new_shape("magnify", QPointF(x, y))
        s.update(pts=[[x, y], [x + w, y + h]], fill=False, zoom=2.0, width=max(3, min(6, self.ed._width)))
        self.shapes.append(s)
        self.set_sel(len(self.shapes) - 1)
        self.commit()
        self.ed.flash("Move it over what you want enlarged · right-click for zoom")

    def insert_callout(self, at=None, box=False):
        self.ed.set_tool("text")
        c = at if at is not None else self.visible_center()
        self.next_bubble = "box" if box else True
        self.edit_text(None, c)

    def _stamp_menu(self, menu, pick):
        menu.setStyleSheet("QMenu::item { padding: 6px 16px 6px 12px; }")
        sym = menu.addMenu("Symbols")
        f = QFont("Segoe UI Emoji")
        f.setPointSize(12)
        sym.setFont(f)
        for lab in render.STAMP_SYMBOLS:
            sym.addAction(lab, lambda lab=lab: pick(lab))
        menu.addSeparator()
        for lab in render.STAMP_BADGES:
            menu.addAction(lab, lambda lab=lab: pick(lab))

    def insert_stamp(self, label, at=None):
        W, H = self.base.width(), self.base.height()
        h = max(28.0, min(W, H) * (0.07 if render.is_badge(label) else 0.09))
        w, h = render.stamp_size(label, h)
        c = at if at is not None else self.visible_center()
        x = min(max(c.x() - w / 2, 0), max(0, W - w))
        y = min(max(c.y() - h / 2, 0), max(0, H - h))
        s = self.new_shape("stamp", QPointF(x, y))
        color = s["color"]
        if render.is_badge(label) and color.lower() in ("#ffffff", "#1c1c1e"):
            color = "#ff3b30"
        s.update(pts=[[x, y], [x + w, y + h]], text=label, color=color, fill=False)
        self.shapes.append(s)
        self.set_sel(len(self.shapes) - 1)
        self.commit()

    def set_prop(self, **kw):
        s = self.selected()
        if s:
            s.update(kw)
            self.commit()

    # ---------------------------------------------------------------- object operations
    def delete_selected(self):
        if self.selected():
            self.shapes.pop(self.sel)
            self.set_sel(None)
            self.commit()

    def reorder(self, direction):
        s = self.selected()
        if not s:
            return
        self.shapes.pop(self.sel)
        if direction > 0:
            self.shapes.append(s)
            self.sel = len(self.shapes) - 1
        else:
            self.shapes.insert(0, s)
            self.sel = 0
        self.commit()

    def duplicate(self):
        s = self.selected()
        if not s:
            return
        c = copy.deepcopy(s)
        render.translate(c, 16, 16)
        if c["kind"] == "step":
            c["number"] = self.next_step()
        self.shapes.append(c)
        self.set_sel(len(self.shapes) - 1)
        self.commit()

    def copy_shape(self):
        s = self.selected()
        if not s:
            return False
        mime = QMimeData()
        mime.setData(SHAPES_MIME, json.dumps([s]).encode("utf-8"))
        QApplication.clipboard().setMimeData(mime)
        return True

    def paste(self, at=None):
        """Paste annotations, an image, or image files. Returns a short description or None."""
        md = QApplication.clipboard().mimeData()
        if md is None:
            return None
        if md.hasFormat(SHAPES_MIME):
            shapes = json.loads(bytes(md.data(SHAPES_MIME)).decode("utf-8"))
            for c in shapes:
                render.translate(c, 16, 16)
            self.shapes.extend(shapes)
            self.set_sel(len(self.shapes) - 1)
            self.commit()
            # keep cascading if pasted again
            QApplication.clipboard().mimeData().setData(SHAPES_MIME, json.dumps(shapes).encode("utf-8"))
            return "Pasted shape"
        img = self._image_from_mime(md)
        if img is not None:
            self.insert_image(img, at)
            return "Pasted image"
        return None

    @staticmethod
    def _image_from_mime(md):
        if md.hasImage():
            img = QImage(md.imageData())
            if not img.isNull():
                return img
        for u in md.urls() if md.hasUrls() else []:
            if u.isLocalFile():
                img = QImage(u.toLocalFile())
                if not img.isNull():
                    return img
        return None

    def visible_center(self):
        vp = self.ed.area.viewport()
        c = self.mapFrom(vp, QPoint(vp.width() // 2, vp.height() // 2))
        p = self.to_img(QPointF(c))
        return QPointF(min(max(p.x(), 0), self.base.width()), min(max(p.y(), 0), self.base.height()))

    def insert_image(self, img, at=None):
        """Add an image as a movable, resizable layer, scaled to fit comfortably inside the capture."""
        img = img.convertToFormat(QImage.Format_ARGB32)
        W, H = self.base.width(), self.base.height()
        k = min(1.0, W * 0.6 / max(1, img.width()), H * 0.6 / max(1, img.height()))
        w, h = img.width() * k, img.height() * k
        c = at if at is not None else self.visible_center()
        x = min(max(c.x() - w / 2, 0), max(0, W - w))
        y = min(max(c.y() - h / 2, 0), max(0, H - h))
        s = {"kind": "image", "pts": [[x, y], [x + w, y + h]], "img": render.encode_image(img),
             "color": "#000000", "width": 1, "fill": False, "shadow": True, "text": "", "font": 24, "number": 0}
        self.shapes.append(s)
        self.set_sel(len(self.shapes) - 1)
        self.commit()

    # drag & drop images / files onto the capture
    def dragEnterEvent(self, e):
        if self._image_from_mime(e.mimeData()) is not None:
            e.acceptProposedAction()

    def dropEvent(self, e):
        img = self._image_from_mime(e.mimeData())
        if img is not None:
            e.acceptProposedAction()
            self.insert_image(img, self.to_img(e.position()))

    # ---------------------------------------------------------------- whole-image transforms
    def transform(self, kind):
        """rotate_cw | rotate_ccw | flip_h | flip_v - image and every annotation together."""
        from PySide6.QtGui import QTransform
        W, H = self.base.width(), self.base.height()
        if kind == "rotate_cw":
            t, f = QTransform().rotate(90), (lambda x, y: (H - y, x))
        elif kind == "rotate_ccw":
            t, f = QTransform().rotate(-90), (lambda x, y: (y, W - x))
        elif kind == "flip_h":
            t, f = QTransform().scale(-1, 1), (lambda x, y: (W - x, y))
        else:
            t, f = QTransform().scale(1, -1), (lambda x, y: (x, H - y))
        self.base = self.base.transformed(t)
        for s in self.shapes:
            s["pts"] = [list(f(x, y)) for x, y in s["pts"]]
            if s["kind"] == "text":  # keep text upright: re-anchor its top-left corner
                r = render.text_rect(dict(s, pts=[[0, 0]]))
                tail = s["pts"][1:]
                x, y = s["pts"][0]
                if kind == "rotate_cw":
                    s["pts"] = [[x - r.height(), y]]
                elif kind == "rotate_ccw":
                    s["pts"] = [[x, y - r.width()]]
                elif kind == "flip_h":
                    s["pts"] = [[x - r.width(), y]]
                else:
                    s["pts"] = [[x, y - r.height()]]
                s["pts"] += tail
            if s["kind"] == "image":
                s["img"] = render.encode_image(render.shape_image(s).transformed(t))
        self.set_sel(None)
        self.update_size()
        self.commit()

    def scale_image(self, f):
        """Resize the image and every annotation together (f = 0.5 halves it)."""
        W, H = self.base.width(), self.base.height()
        nw, nh = max(1, round(W * f)), max(1, round(H * f))
        self.base = self.base.scaled(nw, nh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        for s in self.shapes:
            s["pts"] = [[x * f, y * f] for x, y in s["pts"]]
            s["width"] = max(1, round(s["width"] * f, 1))
            if "font" in s:
                s["font"] = max(6, round(s.get("font", 24) * f))
        self.measure = None
        self.set_sel(None)
        self.update_size()
        self.commit()

    def extend(self, side, amount=None):
        """Add empty space on one side (for placing another capture next to this one)."""
        W, H = self.base.width(), self.base.height()
        amount = amount or (W // 2 if side in ("left", "right") else H // 2)
        nw, nh = (W + amount, H) if side in ("left", "right") else (W, H + amount)
        bg = QColor(self.base.pixel(0, 0) if side in ("left", "top") else self.base.pixel(W - 1, H - 1))
        out = QImage(nw, nh, QImage.Format_RGB32)
        out.fill(bg)
        ox, oy = (amount, 0) if side == "left" else (0, amount) if side == "top" else (0, 0)
        p = QPainter(out)
        p.drawImage(ox, oy, self.base)
        p.end()
        self.base = out
        for s in self.shapes:
            render.translate(s, ox, oy)
        self.update_size()
        self.commit()

    def apply_crop(self, r):
        if r.isEmpty() or r == self.base.rect():
            return
        self.base = self.base.copy(r)
        for s in self.shapes:
            render.translate(s, -r.x(), -r.y())
        self.set_sel(None)
        self.update_size()
        self.commit()

    def apply_style(self, **kw):
        s = self.selected()
        if not s:
            return
        changed = False
        for k, v in kw.items():
            if k == "color" and s["kind"] == "highlight":
                v = HIGHLIGHT_COLORS.get(v.lower(), v)
            if s.get(k) != v:
                s[k] = v
                changed = True
        if changed:
            self.commit()

    def add_shapes(self, shapes):
        if shapes:
            self.shapes.extend(shapes)
            self.commit()

    # ---------------------------------------------------------------- text editing
    def edit_text(self, idx, pt=None):
        self.finish_text()
        if idx is not None:
            shape = self.shapes[idx]
            self.editing_idx = idx
            pt = render.P(shape["pts"][0])
            text, color, size = shape["text"], shape["color"], shape["font"]
        else:
            st = self.ed.annot_style()
            text, color, size = "", st["color"], st["font"]
            pt = QPointF(pt.x(), pt.y() - size * 0.6)
        self._text_origin = (pt.x(), pt.y())
        te = InlineText(self)
        f = QFont(render.text_font(size * self.scale()))
        te.setFont(f)
        outline = "#111" if render.is_light(color) else "#fff"
        te.setStyleSheet(f"QPlainTextEdit {{ background: rgba(0,0,0,0); color: {color}; border: 1.5px dashed {theme.ACCENT};"
                         f" padding: 0px; selection-background-color: #1a6fd1; }}")
        te.document().setDocumentMargin(2)
        te.setPlainText(text)
        s = self.scale()
        _, _, ox, oy = self.layout()
        te.move(int((pt.x() + ox) * s) - 4, int((pt.y() + oy) * s) - 4)
        te.fit()
        te.show()
        te.setFocus()
        cur = te.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        te.setTextCursor(cur)
        te.done.connect(self.finish_text)
        self.text_edit = te
        self.update()

    def finish_text(self):
        te = self.text_edit
        if te is None:
            return
        self.text_edit = None
        text = te.toPlainText().rstrip()
        idx = self.editing_idx
        self.editing_idx = None
        te.hide()
        te.deleteLater()
        if idx is not None:
            if not text:
                self.shapes.pop(idx)
                self.set_sel(None)
            elif text != self.shapes[idx]["text"]:
                self.shapes[idx]["text"] = text
            else:
                self.update()
                return
            self.commit()
        elif text:
            x, y = self._text_origin
            s = self.new_shape("text", QPointF(x, y))
            s["pts"] = [[x, y]]
            s["text"] = text
            if self.next_bubble:
                s["bubble"] = self.next_bubble
                if s["color"].lower() in ("#ffffff", "#1c1c1e"):
                    s["color"] = "#ffd60a"
            self.next_bubble = False
            self.shapes.append(s)
            self.set_sel(len(self.shapes) - 1)
            self.commit()
        self.update()
        self.setFocus()


class StylePopup(QFrame):
    """Compact popover: colour, stroke, text size, fill, shadow."""

    def __init__(self, ed):
        super().__init__(ed, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.ed = ed
        self.setObjectName("popup")
        self.setAttribute(Qt.WA_StyledBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        self.presets = QComboBox()
        self.presets.setToolTip("Style presets: colour, size, arrow head, fill, shadow and outline in one click")
        self.presets.activated.connect(self._preset_chosen)
        lay.addWidget(self.presets)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.swatches = {}
        for c in PALETTE:
            b = QToolButton()
            b.setIconSize(QSize(22, 22))
            b.setToolTip(c.upper())
            b.clicked.connect(lambda _=False, col=c: self.ed.set_color(col))
            row.addWidget(b)
            self.swatches[c] = b
        self.custom = QToolButton()
        self.custom.setIconSize(QSize(22, 22))
        self.custom.setToolTip("Custom colour")
        self.custom.clicked.connect(self.ed.pick_color)
        row.addWidget(self.custom)
        lay.addLayout(row)
        hexrow = QHBoxLayout()
        hexrow.setSpacing(6)
        self.eyedrop = QToolButton()
        self.eyedrop.setIcon(theme.icon("picker", 18))
        self.eyedrop.setIconSize(QSize(18, 18))
        self.eyedrop.setToolTip("Pick a colour from the image   I")
        self.eyedrop.clicked.connect(lambda: (self.hide(), self.ed.set_tool("picker")))
        self.hex = QLineEdit()
        self.hex.setPlaceholderText("#RRGGBB")
        self.hex.setMaxLength(9)
        self.hex.setFixedWidth(96)
        self.hex.setToolTip("Type an exact colour (hex), Enter to use it")
        self.hex.returnPressed.connect(self._hex_entered)
        hexrow.addWidget(self.eyedrop)
        hexrow.addWidget(self.hex)
        hexrow.addStretch(1)
        lay.addLayout(hexrow)

        def slider_row(label, lo, hi, fn):
            r = QHBoxLayout()
            l = QLabel(label)
            l.setFixedWidth(44)
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            v = QLabel()
            v.setFixedWidth(28)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda x: (v.setText(str(x)), fn(x)))
            r.addWidget(l)
            r.addWidget(s, 1)
            r.addWidget(v)
            lay.addLayout(r)
            return s, v

        self.stroke, self.stroke_v = slider_row("Stroke", 1, 24, self.ed._on_width)
        self.font, self.font_v = slider_row("Text", 10, 120, self.ed._on_font)
        heads = QHBoxLayout()
        heads.setSpacing(2)
        hl = QLabel("Arrow")
        hl.setFixedWidth(44)
        heads.addWidget(hl)
        self.heads = {}
        for h in render.ARROW_HEADS:
            b = QToolButton()
            b.setCheckable(True)
            b.setIcon(arrow_icon(h))
            b.setIconSize(QSize(28, 28))
            b.setToolTip(HEAD_TIPS[h])
            b.clicked.connect(lambda _=False, h=h: self.ed._on_head(h))
            heads.addWidget(b)
            self.heads[h] = b
        heads.addStretch(1)
        lay.addLayout(heads)
        chips = QHBoxLayout()
        chips.setSpacing(4)
        self.fill = QToolButton()
        self.fill.setText("Fill")
        self.shadow = QToolButton()
        self.shadow.setText("Shadow")
        self.bubble = QToolButton()
        self.bubble.setText("Callout")
        self.bubble.setToolTip("Text in a speech bubble - drag the tail's dot to point it")
        self.outline = QToolButton()
        self.outline.setText("Outline")
        self.outline.setToolTip("Contrasting rim so marks stand out on busy or dark screenshots")
        for b, fn in ((self.fill, self.ed._on_fill), (self.shadow, self.ed._on_shadow),
                      (self.outline, self.ed._on_outline), (self.bubble, self.ed._on_bubble)):
            b.setObjectName("chip")
            b.setCheckable(True)
            b.toggled.connect(fn)
            chips.addWidget(b)
        chips.addStretch(1)
        lay.addLayout(chips)
        self.setFixedWidth(300)

    def sync(self):
        ed = self.ed
        ed._block = True
        self.stroke.setValue(int(ed._width))
        self.stroke_v.setText(str(int(ed._width)))
        self.font.setValue(int(ed._font))
        self.font_v.setText(str(int(ed._font)))
        self.fill.setChecked(bool(ed._fill))
        self.shadow.setChecked(bool(ed._shadow))
        self.outline.setChecked(bool(ed._outline))
        self.bubble.setChecked(bool(ed._bubble))
        self.hex.setText(QColor(ed._color).name().upper())
        for h, b in self.heads.items():
            b.setChecked(h == ed._head)
        ed._block = False
        self._fill_presets()
        cur = ed._color.lower()
        for c, b in self.swatches.items():
            b.setIcon(theme.dot_icon(c, ring=(c == cur)))
        custom = cur not in self.swatches
        self.custom.setIcon(theme.dot_icon(ed._color, ring=True) if custom else theme.icon("plus", 22))

    def _hex_entered(self):
        t = self.hex.text().strip()
        if not t.startswith("#"):
            t = "#" + t
        c = QColor(t)
        if c.isValid():
            self.ed.set_color(c.name())
            self.hex.setText(c.name().upper())
        else:
            self.hex.selectAll()

    def _fill_presets(self):
        cb = self.presets
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("Presets")
        cb.model().item(0).setEnabled(False)
        cur = self.ed.annot_style()
        match = 0

        def add(pr, kind):
            nonlocal match
            cb.addItem(theme.dot_icon(pr["color"], 16), pr["name"], (kind, pr))
            if all(pr.get(k) == cur.get(k) for k in STYLE_KEYS):
                match = match or cb.count() - 1

        for pr in PRESETS:
            add(pr, "builtin")
        mine = self.ed.app.settings.style_presets
        if mine:
            cb.insertSeparator(cb.count())
            for pr in mine:
                add(pr, "user")
        cb.insertSeparator(cb.count())
        cb.addItem(theme.icon("plus", 16), "Save current as preset…", ("save", None))
        if mine:
            cb.addItem(theme.icon("close", 16), "Delete a preset…", ("delete", None))
        cb.setCurrentIndex(match)
        cb.blockSignals(False)

    def _preset_chosen(self, i):
        data = self.presets.itemData(i)
        if not data:
            return
        kind, pr = data
        if kind in ("builtin", "user"):
            self.ed.apply_preset(pr)
        elif kind == "save":
            self.hide()
            self.ed.save_preset()
        elif kind == "delete":
            self.hide()
            self.ed.delete_preset()
        if self.isVisible():
            self.sync()

    def show_under(self, w):
        self.sync()
        self.adjustSize()
        self.move(w.mapToGlobal(QPoint(0, w.height() + 6)))
        self.show()


def _bg_swatch(key, size=26):
    from PySide6.QtGui import QIcon, QLinearGradient, QPixmap
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    r = QRectF(2, 2, size - 4, size - 4)
    path = QPainterPath()
    path.addRoundedRect(r, 6, 6)
    bg = render.BACKGROUNDS.get(key)
    if bg is None:  # transparent: checkerboard
        p.setClipPath(path)
        for i in range(0, size, 5):
            for j in range(0, size, 5):
                p.fillRect(QRectF(i, j, 5, 5), QColor("#3a3a3a" if (i + j) // 5 % 2 else "#262626"))
        p.setClipping(False)
    elif bg == "blur":
        g = QLinearGradient(0, 0, size, size)
        g.setColorAt(0, QColor("#6d7a8c"))
        g.setColorAt(0.5, QColor("#a39a8c"))
        g.setColorAt(1, QColor("#3e4a5c"))
        p.fillPath(path, g)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.4))
        p.drawRoundedRect(QRectF(8, 9, 10, 8), 2, 2)
    else:
        g = QLinearGradient(0, 0, size, size)
        g.setColorAt(0, QColor(bg[0]))
        g.setColorAt(1, QColor(bg[1]))
        p.fillPath(path, g)
    p.setPen(QPen(QColor(255, 255, 255, 30), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


class BeautifyPopup(QFrame):
    """Background, padding, corners, shadow, aspect ratio for a polished share-ready image."""

    def __init__(self, ed):
        super().__init__(ed, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.ed = ed
        self.setObjectName("popup")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(330)
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.timeout.connect(self._commit)
        self._syncing = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        head = QLabel("Background")
        lay.addWidget(head)
        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(4)
        self.bg_group = QButtonGroup(self)
        self.bg_btns = {}
        names = {"none": "Transparent", "blur": "Blurred from image"}
        for key in render.BACKGROUNDS:
            b = QToolButton()
            b.setCheckable(True)
            b.setIcon(_bg_swatch(key))
            b.setIconSize(QSize(26, 26))
            b.setToolTip(names.get(key, key.capitalize()))
            b.clicked.connect(lambda _=False, k=key: self._set("bg", k))
            self.bg_group.addButton(b)
            i = len(self.bg_btns)
            grid.addWidget(b, i // 5, i % 5)
            self.bg_btns[key] = b
        lay.addLayout(grid)

        def slider(label, lo, hi, key):
            r = QHBoxLayout()
            l = QLabel(label)
            l.setFixedWidth(62)
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.valueChanged.connect(lambda v: self._set(key, v, live=True))
            r.addWidget(l)
            r.addWidget(s, 1)
            lay.addLayout(r)
            return s

        self.pad = slider("Padding", 0, 25, "padding")
        self.rad = slider("Corners", 0, 40, "radius")
        row = QHBoxLayout()
        row.setSpacing(4)
        self.aspect_group = QButtonGroup(self)
        self.aspects = {}
        for a in ("auto", "16:9", "4:3", "1:1"):
            b = QToolButton()
            b.setObjectName("chip")
            b.setText("Auto" if a == "auto" else a)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, v=a: self._set("aspect", v))
            self.aspect_group.addButton(b)
            row.addWidget(b)
            self.aspects[a] = b
        row.addStretch(1)
        self.shadow = QToolButton()
        self.shadow.setObjectName("chip")
        self.shadow.setText("Shadow")
        self.shadow.setCheckable(True)
        self.shadow.toggled.connect(lambda v: self._set("shadow", v))
        row.addWidget(self.shadow)
        lay.addLayout(row)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        remove = QPushButton("Remove")
        remove.setObjectName("ghost")
        remove.clicked.connect(self._remove)
        bottom.addWidget(remove)
        lay.addLayout(bottom)

    def sync(self):
        f = self.ed.canvas.frame or render.DEFAULT_FRAME
        self._syncing = True
        self.bg_btns.get(f.get("bg"), self.bg_btns["graphite"]).setChecked(True)
        self.pad.setValue(int(f.get("padding", 8)))
        self.rad.setValue(int(f.get("radius", 12)))
        self.aspects.get(f.get("aspect", "auto"), self.aspects["auto"]).setChecked(True)
        self.shadow.setChecked(bool(f.get("shadow", True)))
        self._syncing = False

    def _set(self, key, value, live=False):
        if self._syncing:
            return
        f = dict(self.ed.canvas.frame or render.DEFAULT_FRAME)
        f[key] = value
        self.ed.app.settings.set(last_frame=f)
        if live:
            self.ed.canvas.set_frame(f, commit=False)
            self._commit_timer.start(450)
        else:
            self.ed.canvas.set_frame(f)
        self.ed._update_status()

    def _commit(self):
        self.ed.canvas.commit()

    def _remove(self):
        self.hide()
        self.ed.canvas.set_frame(None)
        self.ed._update_status()
        QTimer.singleShot(0, self.ed.fit)

    def show_under(self, w):
        self.sync()
        self.adjustSize()
        pos = w.mapToGlobal(QPoint(w.width() - self.width(), w.height() + 6))
        self.move(pos)
        self.show()


class StampPopup(QFrame):
    """Grid of stamps under the Stamp tool button."""

    def __init__(self, ed, anchor):
        super().__init__(ed, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.ed = ed
        self.setObjectName("popup")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        grid = QGridLayout()
        grid.setSpacing(2)
        for i, lab in enumerate(render.STAMP_SYMBOLS):
            b = QToolButton()
            b.setText(lab)
            b.setStyleSheet('QToolButton { font-family: "Segoe UI Emoji"; font-size: 20px; padding: 0; }')
            b.setFixedSize(40, 40)
            b.setCheckable(True)
            b.setChecked(lab == ed._stamp)
            b.clicked.connect(lambda _=False, l=lab: self._pick(l))
            grid.addWidget(b, i // 8, i % 8)
        lay.addLayout(grid)
        cap = QLabel("Labels  ·  use your current colour")
        lay.addWidget(cap)
        rows = QGridLayout()
        rows.setSpacing(4)
        for i, lab in enumerate(render.STAMP_BADGES):
            b = QToolButton()
            b.setObjectName("chip")
            b.setText(lab)
            b.setCheckable(True)
            b.setChecked(lab == ed._stamp)
            b.clicked.connect(lambda _=False, l=lab: self._pick(l))
            rows.addWidget(b, i // 5, i % 5)
        lay.addLayout(rows)

    def _pick(self, label):
        self.close()
        self.ed.choose_stamp(label)


class CodeBar(QFrame):
    """Floating "QR code found" bar at the top of the canvas: Open / Copy without digging in menus.
    Hovering it outlines the code(s) on the image."""

    def __init__(self, ed, parent):
        super().__init__(parent)
        self.ed = ed
        self.codes = []
        self.setObjectName("codebar")
        self.setCursor(Qt.ArrowCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 7, 7, 7)
        lay.setSpacing(8)
        ic = theme.IconLabel("qr", 18)
        ic.setFixedSize(18, 18)
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.kind = QLabel()
        self.kind.setObjectName("codekind")
        self.text = QLabel()
        col.addWidget(self.kind)
        col.addWidget(self.text)
        lay.addLayout(col, 1)
        self.open_btn = QPushButton("Open")
        self.open_btn.setObjectName("primary")
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("ghost")
        self.more_btn = QPushButton()
        self.more_btn.setObjectName("ghost")
        for b in (self.open_btn, self.copy_btn, self.more_btn):
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        close = QToolButton()
        close.setIcon(theme.icon("close", 14))
        close.setAutoRaise(True)
        close.setToolTip("Dismiss")
        close.clicked.connect(ed.dismiss_codes)
        lay.addWidget(close)
        self.open_btn.clicked.connect(self._open)
        self.copy_btn.clicked.connect(self._copy)
        self.more_btn.clicked.connect(ed.read_codes)
        self.hide()

    def set_codes(self, codes):
        from . import qr
        self.codes = codes
        if not codes:
            return
        text, kind, _ = codes[0]
        self.kind.setText(kind + ("  ·  click Open to visit" if qr.is_link(text) else "  ·  detected in this image"))
        flat = " ".join(text.split())
        self.text.setText(self.fontMetrics().elidedText(flat, Qt.ElideMiddle, 340))
        self.setToolTip(text)
        self.open_btn.setVisible(qr.is_link(text))
        self.more_btn.setVisible(len(codes) > 1)
        self.more_btn.setText(f"+{len(codes) - 1} more")

    def _open(self):
        from PySide6.QtGui import QDesktopServices
        if self.codes:
            QDesktopServices.openUrl(QUrl(self.codes[0][0].strip()))

    def _copy(self):
        if self.codes:
            QApplication.clipboard().setText(self.codes[0][0])
            self.ed.flash("Copied")

    def enterEvent(self, e):
        self.ed.show_code_marks([c for _, _, c in self.codes])
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.ed.show_code_marks([])
        super().leaveEvent(e)


class EditorWindow(QMainWindow):
    def __init__(self, app, path=None, image=None, info=None, shapes=None):
        super().__init__()
        self.app = app
        self.path = Path(path) if path else None
        self.info = info or {}
        frame = None
        if self.path:
            base, shapes, info2 = storage.load_project(self.path)
            self.info = info2 or self.info
            frame = storage.read_meta(self.path).get("frame")
        else:
            base, shapes = image, list(shapes or [])
        self.setWindowIcon(theme.app_icon())
        self.setAttribute(Qt.WA_DeleteOnClose)
        st = app.settings
        self._color, self._width, self._font = st.color, int(st.width), int(st.font_size)
        self._fill, self._shadow = bool(st.fill), bool(st.shadow)
        self._head = st.arrow_head if st.arrow_head in render.ARROW_HEADS else "tapered"
        self._outline = bool(st.outline)
        self._bubble = bool(st.callout)
        self._stamp = "✅"
        self._prev_tool = "select"
        self._block = False
        self.canvas = Canvas(self, base, shapes, frame)
        self._build_ui()
        self._update_title()
        self.canvas.changed.connect(self._on_changed)
        self.canvas.selection_changed.connect(self._sync_props)
        self.canvas.zoom_changed.connect(self._on_zoom)
        self.set_tool("arrow")
        self._size_window(base)
        winapi.style_window(self.winId())

    # ---------------------------------------------------------------- UI
    def _tb(self, icon_name, tip, fn=None, checkable=False):
        b = QToolButton()
        b.setIcon(theme.icon(icon_name))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setAutoRaise(True)
        if fn:
            b.clicked.connect(fn)
        return b

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("bar")
        bar.setAttribute(Qt.WA_StyledBackground)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 7, 10, 7)
        bl.setSpacing(2)

        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons = {}
        for name, label, key in TOOLS:
            b = self._tb(name, f"{label}   {key}", lambda _=False, n=name: self.set_tool(n), checkable=True)
            self.tool_group.addButton(b)
            bl.addWidget(b)
            self.tool_buttons[name] = b
            QShortcut(QKeySequence(key), self, activated=lambda n=name: self.set_tool(n))
        bl.addSpacing(6)
        bl.addWidget(theme.vline())
        bl.addSpacing(6)
        self.style_btn = QToolButton()
        self.style_btn.setIconSize(QSize(18, 18))
        self.style_btn.setToolTip("Colour and size")
        self.style_btn.clicked.connect(lambda: self.popup.show_under(self.style_btn))
        bl.addWidget(self.style_btn)
        self.undo_btn = self._tb("undo", "Undo   Ctrl+Z", self.canvas.undo)
        self.redo_btn = self._tb("redo", "Redo   Ctrl+Y", self.canvas.redo)
        bl.addWidget(self.undo_btn)
        bl.addWidget(self.redo_btn)
        bl.addStretch(1)
        self.beautify_btn = QPushButton("Beautify")
        self.beautify_btn.setObjectName("ghost")
        self.beautify_btn.setIcon(theme.icon("sparkle", 16))
        self.beautify_btn.setIconSize(QSize(16, 16))
        self.beautify_btn.setToolTip("Background, padding, rounded corners, shadow   Ctrl+B")
        self.beautify_btn.clicked.connect(self.open_beautify)
        self.beautify_btn.setFixedHeight(30)
        bl.addWidget(self.beautify_btn, 0, Qt.AlignVCenter)
        bl.addSpacing(8)
        # privacy: "3 hidden · Unhide" pill sits right next to the shield, which is a hide/unhide toggle
        from .widgets import HiddenPill
        self.hidden_pill = HiddenPill()
        self.hidden_pill.unhide.connect(self.unhide)
        bl.addWidget(self.hidden_pill, 0, Qt.AlignVCenter)
        self.redact_btn = self._tb("redact", "", self.toggle_hidden, checkable=True)
        bl.addWidget(self.redact_btn)
        bl.addWidget(self._tb("ocr", "Copy text   Ctrl+Shift+C", self.copy_text))
        self.pin_btn = self._tb("pin", "Pin to screen   Ctrl+P", self.pin, checkable=True)
        bl.addWidget(self.pin_btn)
        more = self._tb("more", "More")
        more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(more)
        m.addAction("Save", self.save, QKeySequence.Save)
        m.addAction("Save as…", self.save_as, QKeySequence("Ctrl+Shift+S"))
        m.addAction("Show in folder", self.show_in_folder)
        m.addSeparator()
        m.addAction("Paste image…", self.paste, QKeySequence.Paste)
        ins = m.addMenu("Insert")
        ins.addAction("Callout bubble", self.canvas.insert_callout, QKeySequence("Shift+T"))
        ins.addAction("Text box", lambda: self.canvas.insert_callout(box=True), QKeySequence("Shift+B"))
        ins.addAction("Spotlight", self.canvas.insert_spotlight, QKeySequence("Shift+S"))
        ins.addAction("Magnifier", self.canvas.insert_magnifier, QKeySequence("Shift+M"))
        m.addAction("Copy text from area…", lambda: self.canvas.set_grab_mode(True), QKeySequence("Ctrl+Alt+C"))
        m.addAction("Read QR / barcodes", self.read_codes)
        tl = m.addMenu("Tools")
        tl.addAction(theme.icon("ruler", 16), "Measure distance", lambda: self.set_tool("measure"),
                     QKeySequence("M"))
        tl.addAction(theme.icon("picker", 16), "Colour picker", lambda: self.set_tool("picker"), QKeySequence("I"))
        grid = tl.addAction("Pixel grid when zoomed in")
        grid.setCheckable(True)
        grid.setChecked(True)
        grid.toggled.connect(lambda v: (setattr(self.canvas, "pixel_grid", v), self.canvas.update()))
        cp = m.addMenu("Copy as")
        cp.addAction("Data URI  (data:image/png;base64,…)", lambda: self.copy_as("datauri"))
        cp.addAction("Base64 only", lambda: self.copy_as("base64"))
        cp.addAction("Markdown image", lambda: self.copy_as("markdown"))
        cp.addAction("HTML <img>", lambda: self.copy_as("html"))
        cp.addAction("File path", lambda: self.copy_as("path"))
        img = m.addMenu("Image")
        img.addAction("Rotate right", lambda: self.canvas.transform("rotate_cw"), QKeySequence("Ctrl+R"))
        img.addAction("Rotate left", lambda: self.canvas.transform("rotate_ccw"), QKeySequence("Ctrl+Shift+R"))
        img.addAction("Flip horizontal", lambda: self.canvas.transform("flip_h"))
        img.addAction("Flip vertical", lambda: self.canvas.transform("flip_v"))
        img.addSeparator()
        img.addAction("Resize…", self.resize_image)
        ext = m.addMenu("Add space")
        for side, label in (("right", "Right"), ("bottom", "Below"), ("left", "Left"), ("top", "Above")):
            ext.addAction(label, lambda sd=side: self.canvas.extend(sd))
        m.addSeparator()
        m.addAction("New capture", self.new_capture, QKeySequence("Ctrl+N"))
        more.setMenu(m)
        bl.addWidget(more)
        bl.addSpacing(8)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("primary")
        self.copy_btn.setToolTip("Copy image   Ctrl+C")
        self.copy_btn.clicked.connect(self.copy)
        bl.addWidget(self.copy_btn)
        root.addWidget(bar)

        area = QScrollArea()
        area.setAlignment(Qt.AlignCenter)
        area.setWidgetResizable(True)
        holder = QWidget()
        holder.setObjectName("holder")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.addWidget(self.canvas, 0, Qt.AlignCenter)
        area.setWidget(holder)
        self.area = area
        root.addWidget(area, 1)
        self.setCentralWidget(central)

        # floating bits
        self.code_bar = CodeBar(self, central)
        self._codes_key = None
        self._codes_dismissed = None
        self._code_timer = QTimer(self)
        self._code_timer.setSingleShot(True)
        self._code_timer.timeout.connect(self._scan_codes)
        self._code_timer.start(250)      # after the window is up - never delays opening
        self.toast = QLabel(central)
        self.toast.setObjectName("toast")
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)
        self.zoom_btn = QPushButton("100%", central)
        self.zoom_btn.setObjectName("ghost")
        zm = QMenu(self.zoom_btn)
        zm.addAction("Fit to window", self.fit, QKeySequence("Ctrl+0"))
        zm.addAction("Actual size", lambda: self.canvas.set_zoom(1.0), QKeySequence("Ctrl+1"))
        zm.addAction("200%", lambda: self.canvas.set_zoom(2.0))
        self.zoom_btn.setMenu(zm)
        self.dim_label = QLabel(central)
        self.dim_label.setObjectName("zoom")
        self.popup = StylePopup(self)
        self.beautify = BeautifyPopup(self)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.open_beautify)

        for seq, fn in ((QKeySequence.Undo, self.canvas.undo), ("Ctrl+Y", self.canvas.redo),
                        ("Ctrl+Shift+Z", self.canvas.redo), (QKeySequence.Copy, self.copy_shortcut),
                        (QKeySequence.Paste, self.paste), ("Ctrl+D", self.canvas.duplicate),
                        ("Ctrl+]", lambda: self.canvas.reorder(1)), ("Ctrl+[", lambda: self.canvas.reorder(-1)),
                        ("Ctrl+R", lambda: self.canvas.transform("rotate_cw")),
                        ("Ctrl+Shift+R", lambda: self.canvas.transform("rotate_ccw")),
                        ("Z", self.toggle_zoom),
                        (QKeySequence.Save, self.save), ("Ctrl+Shift+S", self.save_as),
                        ("Ctrl+H", self.toggle_hidden), ("Ctrl+Shift+C", self.copy_text), ("Ctrl+P", self.pin),
                        ("Shift+T", self.canvas.insert_callout), ("Shift+S", self.canvas.insert_spotlight),
                        ("Shift+M", self.canvas.insert_magnifier),
                        ("Shift+B", lambda: self.canvas.insert_callout(box=True)),
                        ("M", lambda: self.set_tool("measure")),
                        ("Ctrl+Alt+C", lambda: self.canvas.set_grab_mode(True)),
                        ("Ctrl+N", self.new_capture), ("Ctrl+0", self.fit),
                        ("Ctrl+1", lambda: self.canvas.set_zoom(1.0)),
                        ("Ctrl+=", lambda: self.canvas.zoom_at(1.25)),
                        ("Ctrl+-", lambda: self.canvas.zoom_at(1 / 1.25))):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self._update_style_btn()
        self._update_status()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_floating()

    def _place_floating(self):
        if not hasattr(self, "area"):
            return
        g = self.area.geometry()
        self.zoom_btn.adjustSize()
        self.zoom_btn.move(g.right() - self.zoom_btn.width() - 10, g.bottom() - self.zoom_btn.height() - 8)
        self.zoom_btn.raise_()
        self.dim_label.adjustSize()
        self.dim_label.move(g.left() + 10, g.bottom() - self.dim_label.height() - 8)
        self.dim_label.raise_()
        if self.code_bar.isVisible():
            self.code_bar.adjustSize()
            w = min(self.code_bar.sizeHint().width(), g.width() - 24)
            self.code_bar.resize(w, self.code_bar.sizeHint().height())
            self.code_bar.move(g.center().x() - w // 2, g.top() + 12)
            self.code_bar.raise_()
        if self.toast.isVisible():
            self.toast.adjustSize()
            self.toast.move(g.center().x() - self.toast.width() // 2, g.bottom() - self.toast.height() - 18)
            self.toast.raise_()

    def _size_window(self, base):
        scr = self.screen().availableGeometry()
        dpr = self.devicePixelRatioF()
        iw, ih = base.width() / dpr, base.height() / dpr
        w = int(min(max(iw + 100, 860), scr.width() * 0.9))
        h = int(min(max(ih + 140, 520), scr.height() * 0.9))
        self.resize(w, h)
        self.move(scr.x() + (scr.width() - w) // 2, scr.y() + (scr.height() - h) // 2)
        QTimer.singleShot(0, self._initial_zoom)

    def _fit_zoom(self):
        vp = self.area.viewport().size()
        dpr = self.devicePixelRatioF()
        ow, oh, _, _ = self.canvas.layout()
        return max(0.05, min((vp.width() - 64) * dpr / ow, (vp.height() - 64) * dpr / oh))

    def _initial_zoom(self):
        self.canvas.set_zoom(min(1.0, self._fit_zoom()))

    def fit(self):
        self.canvas.set_zoom(self._fit_zoom())

    def _on_zoom(self, z):
        self.zoom_btn.setText(f"{round(z * 100)}%")
        self._place_floating()

    # ---------------------------------------------------------------- style
    def annot_style(self):
        return {"color": self._color, "width": self._width, "font": self._font,
                "fill": self._fill, "shadow": self._shadow, "head": self._head, "outline": self._outline,
                "bubble": self._bubble}

    def _on_head(self, h):
        self._head = h
        self.app.settings.set(arrow_head=h)
        s = self.canvas.selected()
        if s and s["kind"] == "arrow":
            self.canvas.apply_style(head=h)
        if self.popup.isVisible():
            self.popup.sync()

    def _on_outline(self, v):
        if self._block:
            return
        self._outline = v
        self.app.settings.set(outline=v)
        self.canvas.apply_style(outline=v)

    def _on_bubble(self, v):
        if self._block:
            return
        self._bubble = v
        self.app.settings.set(callout=v)
        s = self.canvas.selected()
        if s and s["kind"] == "text":
            self.canvas.apply_style(bubble=v)

    def apply_preset(self, pr):
        self._color, self._width, self._font = pr["color"], int(pr["width"]), int(pr["font"])
        self._fill, self._shadow = bool(pr["fill"]), bool(pr["shadow"])
        self._head = pr.get("head", "tapered")
        self._outline = bool(pr.get("outline"))
        self.app.settings.set(color=self._color, width=self._width, font_size=self._font, fill=self._fill,
                              shadow=self._shadow, arrow_head=self._head, outline=self._outline)
        s = self.canvas.selected()
        if s:
            kw = {k: v for k, v in self.annot_style().items()
                  if k != "bubble" and (k != "font" or s["kind"] in ("text", "step"))}
            if s["kind"] in ("blur", "image"):
                kw = {}
            self.canvas.apply_style(**kw)
        self._update_style_btn()

    def save_preset(self):
        mine = list(self.app.settings.style_presets)
        name, ok = QInputDialog.getText(self, "Save preset", "Name this style:", text=f"My style {len(mine) + 1}")
        name = name.strip()
        if not ok or not name:
            return
        pr = dict(self.annot_style(), name=name)
        mine = [m for m in mine if m["name"] != name] + [pr]
        self.app.settings.set(style_presets=mine)

    def delete_preset(self):
        mine = list(self.app.settings.style_presets)
        if not mine:
            return
        name, ok = QInputDialog.getItem(self, "Delete preset", "Preset:", [m["name"] for m in mine], 0, False)
        if ok:
            self.app.settings.set(style_presets=[m for m in mine if m["name"] != name])

    def _update_style_btn(self):
        self.style_btn.setIcon(theme.dot_icon(self._color))
        if self.popup.isVisible():
            self.popup.sync()

    def set_color(self, c):
        self._color = c
        self.app.settings.set(color=c)
        self._update_style_btn()
        self.canvas.apply_style(color=c)

    def pick_color(self):
        self.popup.hide()
        c = QColorDialog.getColor(QColor(self._color), self, "Colour")
        if c.isValid():
            self.set_color(c.name())

    def _on_width(self, v):
        if self._block:
            return
        self._width = v
        self.app.settings.set(width=v)
        self.canvas.apply_style(width=v)

    def _on_font(self, v):
        if self._block:
            return
        self._font = v
        self.app.settings.set(font_size=v)
        self.canvas.apply_style(font=v)

    def _on_fill(self, v):
        if self._block:
            return
        self._fill = v
        self.app.settings.set(fill=v)
        self.canvas.apply_style(fill=v)

    def _on_shadow(self, v):
        if self._block:
            return
        self._shadow = v
        self.app.settings.set(shadow=v)
        self.canvas.apply_style(shadow=v)

    def _sync_props(self):
        s = self.canvas.selected()
        if not s:
            return
        self._width = int(s["width"])
        self._font = int(s.get("font", self._font))
        self._fill = bool(s.get("fill"))
        self._shadow = bool(s.get("shadow"))
        self._outline = bool(s.get("outline"))
        if s["kind"] == "arrow":
            self._head = s.get("head", "tapered")
        if s["kind"] == "text":
            self._bubble = bool(s.get("bubble"))
        if s["kind"] != "highlight":
            self._color = s["color"]
        self._update_style_btn()

    def set_tool(self, name):
        self.canvas.finish_text()
        if self.canvas.tool not in ("picker", "measure"):
            self._prev_tool = self.canvas.tool
        same = self.canvas.tool == name
        self.canvas.tool = name
        if name != "measure":
            self.canvas.measure = None
        self.canvas.hover_pt = None
        if name in self.tool_buttons:
            self.tool_buttons[name].setChecked(True)
        else:      # measure: no toolbar button - clear the checked one
            self.tool_group.setExclusive(False)
            for b in self.tool_buttons.values():
                b.setChecked(False)
            self.tool_group.setExclusive(True)
            self.flash("Measure: drag between two points  ·  Shift = straight  ·  Esc to finish")
        if name == "stamp" and (same or not getattr(self, "_stamp_chosen", False)):
            QTimer.singleShot(0, self.show_stamps)
        if name == "picker":
            self.flash("Click to use a colour (and copy its hex)  ·  Shift+click copies rgb()  ·  Esc to cancel")
        self.canvas.update()
        if name == "crop":
            self.canvas.set_sel(None)
        cursor = {"text": Qt.IBeamCursor, "select": Qt.ArrowCursor}.get(name, Qt.CrossCursor)
        self.canvas.setCursor(cursor)

    def show_stamps(self):
        b = self.tool_buttons["stamp"]
        pop = StampPopup(self, b)
        pop.move(b.mapToGlobal(QPoint(0, b.height() + 6)))
        pop.show()

    def choose_stamp(self, label):
        self._stamp = label
        self._stamp_chosen = True
        self.tool_buttons["stamp"].setToolTip(f"Stamp {label}   S  -  click the image to place it")
        if self.canvas.tool != "stamp":
            self.set_tool("stamp")
        self.flash(f"Click the image to place {label}  ·  drag the corners to resize")

    def pick_from_image(self, pt, rgb=False):
        ix, iy = int(pt.x()), int(pt.y())
        if not self.canvas.base.rect().contains(ix, iy):
            return
        c = QColor(self.canvas.base.pixel(ix, iy))
        text = f"rgb({c.red()}, {c.green()}, {c.blue()})" if rgb else c.name().upper()
        QApplication.clipboard().setText(text)
        self.set_color(c.name())
        self.set_tool(getattr(self, "_prev_tool", "select") or "select")
        self.flash(f"{text}  copied  ·  now your drawing colour")

    def copy_as(self, kind):
        import base64
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        if kind in ("markdown", "html", "path"):
            if self.path is None or self.canvas.dirty:
                if not self.save():
                    return
            p = Path(self.path).resolve()
            uri = p.as_uri()
            name = (self.info.get("title") or p.stem).replace("]", "")
            text = {"markdown": f"![{name}]({uri})", "html": f'<img src="{uri}" alt="{name}">',
                    "path": str(p)}[kind]
        else:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            self.canvas.final_image().save(buf, "PNG")
            buf.close()
            b64 = base64.b64encode(bytes(ba)).decode("ascii")
            text = b64 if kind == "base64" else f"data:image/png;base64,{b64}"
        QApplication.clipboard().setText(text)
        kb = len(text) / 1024
        self.flash(f"Copied {'(' + format(kb, '.0f') + ' KB of text)' if kb > 4 else ''}".strip())

    def resize_image(self):
        b = self.canvas.base
        pct, ok = QInputDialog.getInt(self, "Resize image",
                                      f"Now {b.width()} × {b.height()} px.  New size (% of current):",
                                      50, 5, 400, 5)
        if ok and pct != 100:
            self.canvas.scale_image(pct / 100.0)
            nb = self.canvas.base
            self.flash(f"Resized to {nb.width()} × {nb.height()}")

    # ---------------------------------------------------------------- status
    def _on_changed(self):
        if hasattr(self, "_code_timer") and self.canvas.base.cacheKey() != self._codes_key:
            self._code_timer.start(400)     # image itself changed (crop, paste, rotate...): look again
        self._update_status()
        self._update_title()

    def _update_status(self):
        b = self.canvas.base
        self.dim_label.setText(f"{b.width()} × {b.height()}")
        self.undo_btn.setEnabled(self.canvas.hidx > 0)
        self.redo_btn.setEnabled(self.canvas.hidx < len(self.canvas.history) - 1)
        n = sum(1 for s in self.canvas.shapes if s.get("redact"))
        self.hidden_pill.set_count(n)
        self.hidden_pill.setVisible(n > 0)
        self.redact_btn.setChecked(n > 0)
        self.redact_btn.setToolTip("Unhide sensitive info   Ctrl+H" if n else
                                   "Hide sensitive info   Ctrl+H\nEmails, phone numbers, cards, IPs, keys")
        self.pin_btn.setChecked(self.app.is_pinned(self))
        self.beautify_btn.setProperty("active", bool(self.canvas.frame))
        self.beautify_btn.style().unpolish(self.beautify_btn)
        self.beautify_btn.style().polish(self.beautify_btn)
        self._place_floating()

    def _update_title(self):
        name = self.path.stem if self.path else "Capture"
        self.setWindowTitle(f"{name}{' •' if self.canvas.dirty else ''}")

    def flash(self, text, ms=2400):
        self.toast.setText(text)
        self.toast.show()
        self._place_floating()
        self._toast_timer.start(ms)

    # ---------------------------------------------------------------- actions
    def copy_shortcut(self):
        """Ctrl+C: copies the selected shape if there is one (like Snagit/Figma), else the whole image."""
        if self.canvas.selected() and self.canvas.copy_shape():
            self.flash("Copied shape  ·  Ctrl+V to paste  ·  the Copy button copies the image")
        else:
            self.copy()

    def paste(self):
        what = self.canvas.paste()
        self.flash(what or "Nothing to paste - copy an image or file first")

    def toggle_zoom(self):
        if abs(self.canvas.zoom - 1.0) < 0.01:
            self.fit()
        else:
            self.canvas.zoom_at(1.0 / self.canvas.zoom)

    def copy(self):
        QApplication.clipboard().setImage(self.canvas.final_image())
        self.flash("Copied")
        self.copy_btn.setText("Copied")
        QTimer.singleShot(1400, self.copy_btn, lambda: self.copy_btn.setText("Copy"))

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            storage.save_project(self.path, self.canvas.base, self.canvas.shapes, self.canvas.final_image(),
                                 self.canvas.frame)
        except Exception as e:
            QMessageBox.warning(self, "Glint", f"Could not save.\n\n{e}")
            return False
        self.canvas.dirty = False
        self._update_title()
        self.flash("Saved")
        self.app.library_changed()
        return True

    def save_as(self):
        start = str(self.path) if self.path else str(Path(self.app.settings.save_folder) / "capture.png")
        fn, _ = QFileDialog.getSaveFileName(self, "Save as", start,
                                            "PNG (*.png);;JPEG (*.jpg *.jpeg);;Bitmap (*.bmp)")
        if not fn:
            return False
        img = self.canvas.final_image()
        p = Path(fn)
        try:
            if p.suffix.lower() == ".png":
                storage.save_project(p, self.canvas.base, self.canvas.shapes, img, self.canvas.frame)
                self.path = p
                self.canvas.dirty = False
            else:
                tmp = p.with_name(p.name + ".tmp")
                fmt = "JPG" if p.suffix.lower() in (".jpg", ".jpeg") else "BMP"
                if not img.save(str(tmp), fmt, 92):
                    raise OSError("write failed")
                tmp.replace(p)
        except Exception as e:
            QMessageBox.warning(self, "Glint", f"Could not save.\n\n{e}")
            return False
        self._update_title()
        self.flash("Saved")
        self.app.library_changed()
        return True

    def show_in_folder(self):
        import subprocess
        if self.path and self.path.exists():
            subprocess.Popen(["explorer", "/select,", str(self.path)])
        else:
            subprocess.Popen(["explorer", str(self.app.settings.save_folder)])

    def pin(self):
        """Toggle: one pin per editor."""
        if self.app.is_pinned(self):
            self.app.unpin(self)
        else:
            self.app.pin_image(self.canvas.final_image(), key=self,
                               on_close=lambda: self._safe_update())
        self._update_status()

    def _safe_update(self):
        try:
            self._update_status()
        except RuntimeError:
            pass  # editor already closed

    def toggle_hidden(self):
        from . import redact
        if redact.count(self.canvas.shapes):
            self.unhide()
        else:
            self.hide_sensitive()
        self._update_status()

    def new_capture(self):
        self.app.start_capture()

    def _ocr(self):
        return self.canvas.ocr_lines()

    def _scan_codes(self):
        from . import qr
        base = self.canvas.base
        self._codes_key = base.cacheKey()
        found = qr.find(base)
        self.code_bar.set_codes(found)
        show = bool(found) and self._codes_dismissed != self._codes_key
        self.code_bar.setVisible(show)
        if show:
            self._place_floating()

    def dismiss_codes(self):
        self._codes_dismissed = self._codes_key
        self.code_bar.hide()
        self.show_code_marks([])

    def show_code_marks(self, corners_list):
        self.canvas.code_marks = [QPolygonF([QPointF(x, y) for x, y in c]) for c in corners_list if c]
        self.canvas.update()

    def read_codes(self):
        from . import qr
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            codes = qr.decode(render.render(self.canvas.base, self.canvas.shapes))
        finally:
            QApplication.restoreOverrideCursor()
        if not codes:
            self.flash("No QR codes or barcodes found")
            return
        m = QMenu(self)
        for text, kind in codes:
            label = text if len(text) <= 70 else text[:67] + "…"
            sm = m.addMenu(f"{kind}: {label}")
            sm.addAction("Copy", lambda tx=text: (QApplication.clipboard().setText(tx), self.flash("Copied")))
            if qr.is_link(text):
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                sm.addAction("Open link", lambda tx=text: QDesktopServices.openUrl(QUrl(tx.strip())))
        m.exec(QCursor.pos())

    def copy_text(self):
        from . import ocr
        lines = self._ocr()
        if lines is None:
            return
        text = ocr.lines_to_text(lines)
        if not text.strip():
            self.flash("No text found")
            return
        QApplication.clipboard().setText(text)
        dlg = QDialog(self)
        dlg.setWindowTitle("Text")
        dlg.resize(560, 380)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(10)
        info = QLabel("Copied to clipboard. Edit and copy again if needed.")
        info.setObjectName("muted")
        lay.addWidget(info)
        te = QPlainTextEdit(text)
        lay.addWidget(te)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(dlg.reject)
        again = QPushButton("Copy")
        again.setObjectName("primary")
        again.clicked.connect(lambda: (QApplication.clipboard().setText(te.toPlainText()), dlg.accept()))
        row.addWidget(close)
        row.addWidget(again)
        lay.addLayout(row)
        winapi.style_window(dlg.winId())
        dlg.exec()

    def hide_sensitive(self):
        from . import redact
        lines = self._ocr()
        if lines is None:
            return
        hits = redact.find_sensitive(lines)
        if not hits:
            self.flash("Nothing sensitive found")
            return
        self.canvas.add_shapes(redact.make_shapes(hits, self.annot_style()["width"]))
        n = len(hits)
        self.flash(f"Hid {n} item{'s' if n != 1 else ''}", 3000)

    def unhide(self):
        from . import redact
        n = redact.count(self.canvas.shapes)
        if not n:
            return
        self.canvas.shapes = redact.strip(self.canvas.shapes)
        self.canvas.set_sel(None)
        self.canvas.commit()
        self.flash(f"Unhid {n} item{'s' if n != 1 else ''}  ·  Ctrl+Z to hide again", 3500)

    def open_beautify(self):
        if not self.canvas.frame:
            last = self.app.settings.last_frame or render.DEFAULT_FRAME
            self.canvas.set_frame(dict(last))
            QTimer.singleShot(0, self.fit)
        self.beautify.show_under(self.beautify_btn)

    # ---------------------------------------------------------------- close
    def closeEvent(self, e):
        self.canvas.finish_text()
        if self.canvas.dirty:
            if self.path and self.app.settings.auto_save:
                if not self.save():
                    e.ignore()
                    return
            else:
                r = QMessageBox.question(self, "Glint", "Save changes?",
                                         QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
                if r == QMessageBox.Cancel or (r == QMessageBox.Save and not self.save()):
                    e.ignore()
                    return
        self.app.editor_closed(self)
        super().closeEvent(e)
