"""Start screen (DS-08): recent projects, template cards, New empty scene, Open…."""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import QSettings, QSize, Qt, Signal
from qtpy.QtGui import QMouseEvent
from qtpy.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from simview.ui.panels import EmptyState
from simview.ui.theme import icon, tokens

# (template id, title, one-line description, Lucide icon)
TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    ("av_scenario", "Autonomous Vehicle", "Bicycle-model car with lidar and camera.", "car"),
    ("drone_intercept", "Drone Interception", "Seeker, EKF, and PN guidance.", "crosshair"),
    ("ur5_ik", "Robotic Arm (UR5)", "Drag the end effector, watch IK solve.", "bot"),
    ("drone_landing", "Drone Landing (RL)", "Gymnasium env for PPO training.", "plane-landing"),
)
RECENT_KEY = "recent_projects"
RECENT_MAX = 10


def recent_projects(settings: QSettings) -> list[str]:
    value = settings.value(RECENT_KEY, [])
    if isinstance(value, str):  # QSettings returns a bare string for 1-item lists
        value = [value]
    return [str(v) for v in value or []]


def add_recent_project(settings: QSettings, path: str) -> None:
    items = [p for p in recent_projects(settings) if p != path]
    settings.setValue(RECENT_KEY, [path, *items][:RECENT_MAX])
    settings.sync()


class TemplateCard(QFrame):
    clicked = Signal(str)

    def __init__(self, template_id: str, title: str, desc: str, icon_name: str) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.template_id = template_id
        self.setFixedSize(*tokens.TEMPLATE_CARD)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)

        thumb = QToolButton(self)
        thumb.setIcon(icon(icon_name, "accent", tokens.TEMPLATE_GLYPH))
        thumb.setIconSize(QSize(tokens.TEMPLATE_GLYPH, tokens.TEMPLATE_GLYPH))
        thumb.setAutoRaise(True)
        thumb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        thumb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        name = QLabel(title)
        name.setProperty("role", "panelTitle")
        name.setWordWrap(True)
        sub = QLabel(desc)
        sub.setProperty("role", "caption")
        sub.setWordWrap(True)

        lay = QVBoxLayout(self)
        pad = tokens.SPACING[2]
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(tokens.SPACING[0])
        lay.addWidget(thumb, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        lay.addWidget(name)
        lay.addWidget(sub)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.template_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802, ANN001 (Qt API)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.template_id)
            return
        super().keyPressEvent(event)


class StartScreen(QWidget):
    template_chosen = Signal(str)
    new_scene = Signal()
    project_opened = Signal(str)

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StartScreen")
        self.setWindowTitle("SimView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.settings = settings
        self.resize(*tokens.START_WINDOW)

        title = QLabel("SimView")
        title.setProperty("role", "title")
        subtitle = QLabel("Build, run, and visualize simulations.")
        subtitle.setProperty("role", "secondary")

        # Templates
        tmpl_title = QLabel("Templates")
        tmpl_title.setProperty("role", "panelTitle")
        grid = QGridLayout()
        grid.setSpacing(tokens.SPACING[2])
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.cards: list[TemplateCard] = []
        for i, spec in enumerate(TEMPLATES):
            card = TemplateCard(*spec)
            card.clicked.connect(self.template_chosen.emit)
            grid.addWidget(card, i // 2, i % 2)
            self.cards.append(card)

        self.new_button = QPushButton("New Empty Scene")
        self.new_button.setIcon(icon("file-plus", "text.on_accent"))
        self.new_button.setProperty("primary", "true")
        self.new_button.clicked.connect(lambda _c=False: self.new_scene.emit())
        self.open_button = QPushButton("Open…")
        self.open_button.setIcon(icon("folder-open", "text.primary"))
        self.open_button.clicked.connect(lambda _c=False: self._open())
        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.SPACING[1])
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)

        left = QVBoxLayout()
        left.setSpacing(tokens.SPACING[2])
        left.addWidget(title)
        left.addWidget(subtitle)
        left.addSpacing(tokens.SPACING[3])
        left.addWidget(tmpl_title)
        left.addLayout(grid)
        left.addSpacing(tokens.SPACING[2])
        left.addLayout(buttons)
        left.addStretch(1)

        # Recent projects
        recent_title = QLabel("Recent")
        recent_title.setProperty("role", "panelTitle")
        self.recent_list = QListWidget()
        self.recent_list.itemActivated.connect(lambda it: self.project_opened.emit(it.toolTip()))
        self.recent_empty = EmptyState("folder-open", "No recent projects.", "Open…", self._open)
        self.recent_stack = QStackedWidget()
        self.recent_stack.addWidget(self.recent_empty)
        self.recent_stack.addWidget(self.recent_list)
        right = QVBoxLayout()
        right.setSpacing(tokens.SPACING[1])
        right.addWidget(recent_title)
        right.addWidget(self.recent_stack, 1)

        root = QHBoxLayout(self)
        m = tokens.SPACING[5]
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(tokens.SPACING[5])
        root.addLayout(left, 3)
        root.addLayout(right, 2)
        self.refresh_recent()

    def refresh_recent(self) -> None:
        self.recent_list.clear()
        for path in recent_projects(self.settings):
            self.recent_list.addItem(Path(path).name)
            self.recent_list.item(self.recent_list.count() - 1).setToolTip(path)
        self.recent_stack.setCurrentWidget(
            self.recent_list if self.recent_list.count() else self.recent_empty
        )

    def _open(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Project (.svproj)")
        if path:
            self.project_opened.emit(path)
