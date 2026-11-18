"""Empty-state panel content (PRD §7.8: every panel shows a one-line hint and an action)."""

from __future__ import annotations

from collections.abc import Callable

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from simview.ui.theme import icon, tokens


class EmptyState(QWidget):
    def __init__(
        self,
        icon_name: str,
        hint: str,
        button_text: str,
        on_click: Callable[[], object],
        parent: QWidget | None = None,
        compact: bool = False,
    ) -> None:
        """`compact` lays the hint out in one row, for short panels like the timeline."""
        super().__init__(parent)
        self.setObjectName("EmptyState")
        glyph = QToolButton(self)
        glyph.setIcon(icon(icon_name, size=tokens.ICON_SIZE_START))
        glyph.setIconSize(QSize(tokens.ICON_SIZE_START, tokens.ICON_SIZE_START))
        glyph.setAutoRaise(True)
        glyph.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        glyph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.hint = QLabel(hint, self)
        self.hint.setProperty("role", "secondary")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)

        self.button = QPushButton(button_text, self)
        self.button.clicked.connect(lambda _checked=False: on_click())

        layout: QBoxLayout = QHBoxLayout(self) if compact else QVBoxLayout(self)
        center = Qt.AlignmentFlag.AlignCenter
        if compact:
            pad = tokens.SPACING[1]
            layout.setContentsMargins(pad, pad, pad, pad)
            glyph.setIconSize(QSize(tokens.ICON_SIZE_TOOLBAR, tokens.ICON_SIZE_TOOLBAR))
            self.hint.setWordWrap(False)
        layout.setSpacing(tokens.SPACING[1])
        layout.addStretch(1)
        layout.addWidget(glyph, 0, center)
        if compact:
            layout.addWidget(self.hint, 0, center)
        else:  # no alignment flag: it would break the wrapped label's height-for-width
            layout.addWidget(self.hint)
        layout.addWidget(self.button, 0, center)
        layout.addStretch(1)
