"""Small shared widgets."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from . import theme


class HiddenPill(QFrame):
    """[shield] 3 hidden | Unhide  - one rounded pill, fixed height so it never misaligns."""
    unhide = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pill")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedHeight(30)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 3, 3, 3)
        lay.setSpacing(7)
        icon = theme.IconLabel("redact", 14)
        icon.setFixedSize(14, 14)
        self.text = QLabel()
        self.text.setObjectName("pilltext")
        div = QFrame()
        div.setObjectName("pilldiv")
        div.setFixedSize(1, 14)
        self.button = QPushButton("Unhide")
        self.button.setObjectName("pillbtn")
        self.button.setFixedHeight(22)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setToolTip("Remove the blurs and show the original")
        self.button.clicked.connect(self.unhide)
        lay.addWidget(icon, 0, Qt.AlignVCenter)
        lay.addWidget(self.text, 0, Qt.AlignVCenter)
        lay.addWidget(div, 0, Qt.AlignVCenter)
        lay.addWidget(self.button, 0, Qt.AlignVCenter)

    def set_count(self, n):
        self.text.setText(f"{n} hidden")
        self.button.show()

    def set_done(self, text):
        self.text.setText(text)
        self.button.hide()
