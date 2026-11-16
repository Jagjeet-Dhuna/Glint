"""Accessibility helpers, installed once on the QApplication.

- Names: icon-only buttons (editor tools, swatches, the collapsed sidebar) get their screen-reader name from
  their tooltip ("Arrow   A" -> name "Arrow", description "Arrow   A").
- Focus ring: when focus moves by keyboard (Tab / Shift+Tab / a shortcut) the focused control gets an accent
  outline. Mouse clicks don't show it, so the app looks the same for mouse users.
"""
from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QComboBox, QLineEdit,
                               QPlainTextEdit, QTextEdit, QWidget)

from . import theme

NAMED = (QAbstractButton, QComboBox, QAbstractSlider, QLineEdit)
OWN_FOCUS_STYLE = (QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QAbstractItemView)  # styled via :focus in QSS
KEYBOARD_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)


def short_name(tip):
    """'Stamp - click to place   S' -> 'Stamp'."""
    first = tip.strip().splitlines()[0] if tip.strip() else ""
    return first.split("   ")[0].split(" - ")[0].strip()


def name_from_tooltip(w):
    if not isinstance(w, NAMED) or isinstance(w.parent(), QLineEdit):
        return
    auto = w.property("a11y_auto_name")
    if w.accessibleName() and not auto:
        return                                   # set on purpose somewhere else
    if isinstance(w, QAbstractButton) and w.text().strip():
        if auto:                                 # e.g. sidebar expanded again: back to the visible text
            w.setAccessibleName("")
            w.setAccessibleDescription("")
            w.setProperty("a11y_auto_name", False)
        return                                   # Qt already reads the visible text
    tip = w.toolTip()
    if not tip:
        return
    w.setAccessibleName(short_name(tip))
    if tip.strip() != short_name(tip):
        w.setAccessibleDescription(" ".join(tip.split()))
    w.setProperty("a11y_auto_name", True)


class FocusRing(QWidget):
    """Accent outline drawn over the window around the keyboard-focused control."""

    def __init__(self, window):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.target = None
        self.hide()

    def follow(self, w):
        self.target = w
        self.place()

    def place(self):
        w = self.target
        if w is None or not w.isVisible() or w.window() is not self.parent():
            self.hide()
            return
        top_left = w.mapTo(self.parent(), w.rect().topLeft())
        r = QRect(top_left, w.size()).adjusted(-3, -3, 3, 3)
        self.setGeometry(r)
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.accent_stroke()), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)


def ring_for(window, create=True):
    ring = window.findChild(FocusRing, options=Qt.FindDirectChildrenOnly)
    if ring is None and create:
        ring = FocusRing(window)
    return ring


def _wants_ring(w):
    return not isinstance(w, OWN_FOCUS_STYLE) and not w.property("own_focus_style") and w.window() is not w


class _Filter(QObject):
    def __init__(self):
        super().__init__()
        self.focused = None

    def eventFilter(self, obj, e):
        t = e.type()
        if not isinstance(obj, QWidget):
            return False
        if t in (QEvent.Polish, QEvent.ToolTipChange):
            name_from_tooltip(obj)
        elif t == QEvent.FocusIn:
            ring = ring_for(obj.window(), create=_wants_ring(obj))
            if ring is not None:
                if e.reason() in KEYBOARD_REASONS and _wants_ring(obj):
                    self.focused = obj
                    ring.follow(obj)
                else:
                    self.focused = None
                    ring.hide()
        elif t == QEvent.FocusOut and obj is self.focused:
            ring = ring_for(obj.window(), create=False)
            if ring is not None and e.reason() not in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
                ring.hide()
                self.focused = None
        elif t in (QEvent.MouseButtonPress, QEvent.Wheel) and self.focused is not None:
            ring = ring_for(self.focused.window(), create=False)
            if ring is not None:
                ring.hide()
            self.focused = None
        elif t in (QEvent.Move, QEvent.Resize, QEvent.Hide) and self.focused is not None:
            if obj is self.focused or obj.isAncestorOf(self.focused):
                ring = ring_for(self.focused.window(), create=False)
                if ring is not None:
                    ring.place()
        return False


_installed = None


def install(app):
    global _installed
    if _installed is None:
        _installed = _Filter()
        app.installEventFilter(_installed)
    return _installed
