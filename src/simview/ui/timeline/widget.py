"""The timeline bar (VP-05, §7.4): transport buttons, a scrub slider, and the time readout."""

from __future__ import annotations

from qtpy.QtCore import QSize, Qt, Signal
from qtpy.QtGui import QAction
from qtpy.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QWidget

from simview.ui.theme import icon, tokens


class Timeline(QWidget):
    seek = Signal(int)  # history row picked on the slider

    def __init__(self, actions: dict[str, QAction], parent: QWidget | None = None) -> None:
        """`actions`: "start", "back", "toggle", "forward", "live" (from the action registry)."""
        super().__init__(parent)
        self.setObjectName("Timeline")
        lay = QHBoxLayout(self)
        s = tokens.SPACING
        lay.setContentsMargins(s[2], s[0], s[2], s[0])
        lay.setSpacing(s[0])
        self.buttons: dict[str, QToolButton] = {}
        for key, ic in (
            ("start", "skip-back"),
            ("back", "step-back"),
            ("toggle", "play"),
            ("forward", "step-forward"),
            ("live", "skip-forward"),
        ):
            b = QToolButton(self)
            b.setDefaultAction(actions[key])
            b.setIcon(icon(ic, "accent" if key == "toggle" else "text.secondary"))
            b.setIconSize(QSize(tokens.ICON_SIZE_TOOLBAR, tokens.ICON_SIZE_TOOLBAR))
            b.setAutoRaise(True)
            lay.addWidget(b)
            self.buttons[key] = b
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 0)
        self.slider.setToolTip("Scrub through the recorded run")
        self.slider.valueChanged.connect(self._moved)
        lay.addWidget(self.slider, 1)
        self.readout = QLabel(self)
        self.readout.setProperty("role", "mono")
        self.readout.setMinimumWidth(tokens.TIMELINE_READOUT_WIDTH)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.readout)
        self._syncing = False
        self._playing: bool | None = None
        self.show_state(0, 0, 0.0, 0.0, live=True, playing=False)

    def _moved(self, value: int) -> None:
        if not self._syncing:
            self.seek.emit(value)

    def show_state(
        self, index: int, last: int, t: float, t_end: float, *, live: bool, playing: bool
    ) -> None:
        """Move the slider and readout to row `index` of `last + 1` rows."""
        self._syncing = True
        if self.slider.maximum() != max(last, 0):
            self.slider.setRange(0, max(last, 0))
        if self.slider.value() != index and not self.slider.isSliderDown():
            self.slider.setValue(index)
        self._syncing = False
        mark = "live" if live else "replay" if playing else "     "
        self.readout.setText(f"t = {t:.3f} s / {t_end:.3f} s  {mark:6}")
        if playing != self._playing:
            self._playing = playing
            self.buttons["toggle"].setIcon(icon("pause" if playing else "play", "accent"))
