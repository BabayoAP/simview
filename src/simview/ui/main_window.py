"""Main window: the default Simulate layout from PRD §7.4 (DS-03)."""

from __future__ import annotations

import sys
from collections.abc import Callable

from qtpy.QtCore import QSettings, QSize, Qt, Signal
from qtpy.QtGui import QCloseEvent, QKeySequence, QShowEvent
from qtpy.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from simview.ui import theme
from simview.ui.actions import ActionRegistry
from simview.ui.command_palette import CommandPalette
from simview.ui.panels import EmptyState
from simview.ui.theme import icon, tokens

# (object name, title, area)
DOCKS: tuple[tuple[str, str, Qt.DockWidgetArea], ...] = (
    ("scene_tree", "Scene Tree", Qt.DockWidgetArea.LeftDockWidgetArea),
    ("signals", "Signals", Qt.DockWidgetArea.LeftDockWidgetArea),
    ("inspector", "Inspector", Qt.DockWidgetArea.RightDockWidgetArea),
    ("workspace", "Workspace", Qt.DockWidgetArea.RightDockWidgetArea),
    ("timeline", "Timeline", Qt.DockWidgetArea.BottomDockWidgetArea),
    ("plots", "Plots", Qt.DockWidgetArea.BottomDockWidgetArea),
    ("console", "Console / Editor", Qt.DockWidgetArea.BottomDockWidgetArea),
)
LAYOUT_VERSION = 1

UNTITLED = "untitled"


class MainWindow(QMainWindow):
    show_start_screen = Signal()

    def __init__(
        self,
        settings: QSettings,
        project_key: str = UNTITLED,
        title: str = "Untitled",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.project_key = project_key
        self.setWindowTitle(f"SimView — {title}")
        self.setDockNestingEnabled(True)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.BottomDockWidgetArea)

        self.actions_ = ActionRegistry(self)
        self.palette_ = CommandPalette(self.actions_, self)
        self.docks: dict[str, QDockWidget] = {}

        self._register_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_docks()
        self.resize(QSize(*tokens.WINDOW_DEFAULT))
        self._apply_default_sizes()
        self.restore_layout()

    # ----- actions -------------------------------------------------------------------
    def _register_actions(self) -> None:
        reg = self.actions_.register
        reg("palette.open", "Command Palette…", self.palette_.open, "Ctrl+K", "View")
        reg("file.new", "New Empty Scene", self._new_scene, QKeySequence.StandardKey.New, "File")
        reg("file.open", "Open Project…", self._open_project, QKeySequence.StandardKey.Open, "File")
        reg("file.start", "Show Start Screen", self.show_start_screen.emit, None, "File")
        reg("sim.run", "Run", self._no_scene, None, "Simulation")
        reg("sim.pause", "Pause", self._no_scene, None, "Simulation")
        reg("sim.stop", "Stop", self._no_scene, None, "Simulation")
        reg("view.theme", "Toggle Light/Dark Theme", self.toggle_theme, None, "View")
        reg("view.reset_layout", "Reset Layout", self.reset_layout, None, "View")
        for name, title, _ in DOCKS:
            reg(f"view.focus.{name}", f"Show {title}", self._focus_dock(name), None, "Panels")

    def _focus_dock(self, name: str) -> Callable[[], None]:
        def go() -> None:
            dock = self.docks[name]
            dock.show()
            dock.raise_()
            dock.setFocus()

        return go

    def _no_scene(self) -> None:
        self.statusBar().showMessage("No scene loaded. Open a template to run a simulation.", 4000)

    def _new_scene(self) -> None:
        self.setWindowTitle("SimView — Untitled")
        self.statusBar().showMessage("New empty scene.", 3000)

    def _open_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Project (.svproj)")
        if path:
            self.statusBar().showMessage(f"Opened {path}", 3000)

    def toggle_theme(self) -> None:
        new = "light" if theme.current_theme() == "dark" else "dark"
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        theme.apply_theme(app, new)
        self.settings.setValue("theme", new)

    # ----- chrome --------------------------------------------------------------------
    def _build_menu(self) -> None:
        bar = self.menuBar()
        bar.setNativeMenuBar(sys.platform == "darwin")
        by_cat: dict[str, QMenu] = {}
        for cat in ("File", "Simulation", "View", "Panels"):
            by_cat[cat] = bar.addMenu(cat if cat != "Panels" else "Window")
        for action in self.actions_.all():
            by_cat[str(action.data())].addAction(action)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Toolbar", self)
        tb.setObjectName("toolbar")
        tb.setMovable(False)
        size = tokens.ICON_SIZE_TOOLBAR
        tb.setIconSize(QSize(size, size))

        project = QToolButton(tb)
        project.setText("Project")
        project.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(project)
        for aid in ("file.new", "file.open", "file.start"):
            menu.addAction(self.actions_.get(aid))
        project.setMenu(menu)
        tb.addWidget(project)
        tb.addSeparator()

        for aid, ic, token in (
            ("sim.run", "play", "accent"),
            ("sim.pause", "pause", "text.secondary"),
            ("sim.stop", "square", "text.secondary"),
        ):
            action = self.actions_.get(aid)
            action.setIcon(icon(ic, token))
            tb.addAction(action)
        tb.addSeparator()

        self.dt_label = QLabel("dt 1 ms", tb)
        self.rtf_label = QLabel("RTF 1.0×", tb)
        for lbl in (self.dt_label, self.rtf_label):
            lbl.setProperty("role", "mono")
            lbl.setContentsMargins(tokens.SPACING[1], 0, tokens.SPACING[1], 0)
            tb.addWidget(lbl)

        spacer = QWidget(tb)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        search = QToolButton(tb)
        key = "⌘K" if sys.platform == "darwin" else "Ctrl+K"
        search.setText(f"{key}  Search…")
        search.setIcon(icon("search"))
        search.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        search.clicked.connect(lambda _c=False: self.palette_.open())
        tb.addWidget(search)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.statusBar()

    def _build_central(self) -> None:
        self.viewport = EmptyState(
            "box", "No scene loaded.", "Open Template…", self.show_start_screen.emit
        )
        self.viewport.setObjectName("CentralArea")
        self.setCentralWidget(self.viewport)

    def _dock_content(self, name: str) -> QWidget:
        a = self.actions_.get
        content: dict[str, tuple[str, str, str, Callable[[], object]]] = {
            "scene_tree": (
                "box",
                "No entities yet.",
                "Open Template…",
                self.show_start_screen.emit,
            ),
            "signals": (
                "activity",
                "Run a simulation to see logged signals.",
                "Run",
                a("sim.run").trigger,
            ),
            "inspector": (
                "sliders-horizontal",
                "Select an entity to see its properties.",
                "Show Scene Tree",
                a("view.focus.scene_tree").trigger,
            ),
            "workspace": (
                "table",
                "Console variables appear here.",
                "Show Console",
                a("view.focus.console").trigger,
            ),
            "timeline": (
                "clock-3",
                "Run a simulation to scrub through time.",
                "Run",
                a("sim.run").trigger,
            ),
            "plots": (
                "chart-line",
                "Drag a signal here to plot it.",
                "Show Signals",
                a("view.focus.signals").trigger,
            ),
        }
        if name == "timeline":
            hint = "Run a simulation to scrub through time."
            return EmptyState("clock-3", hint, "Run", a("sim.run").trigger, compact=True)
        if name == "console":
            tabs = QTabWidget()
            tabs.addTab(
                EmptyState(
                    "terminal",
                    "The console isn't connected yet.",
                    "Command Palette…",
                    self.palette_.open,
                ),
                "Console",
            )
            tabs.addTab(
                EmptyState(
                    "file-plus",
                    "Open a script to edit it.",
                    "Open Project…",
                    a("file.open").trigger,
                ),
                "Editor",
            )
            return tabs
        return EmptyState(*content[name])

    def _build_docks(self) -> None:
        features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        for name, title, _area in DOCKS:
            dock = QDockWidget(title, self)
            dock.setObjectName(name)
            dock.setFeatures(features)
            dock.setWidget(self._dock_content(name))
            self.docks[name] = dock
        # The timeline is a thin transport strip, so it has no title bar (D-006): this keeps
        # the viewport and plots near the §7.2.1 content target.
        self.docks["timeline"].setTitleBarWidget(QWidget())
        self._place_docks()

    def _place_docks(self) -> None:
        d = self.docks
        for name, _title, area in DOCKS:
            d[name].setFloating(False)
            d[name].show()
            self.addDockWidget(area, d[name])
        self.splitDockWidget(d["scene_tree"], d["signals"], Qt.Orientation.Vertical)
        self.splitDockWidget(d["inspector"], d["workspace"], Qt.Orientation.Vertical)
        self.splitDockWidget(d["timeline"], d["plots"], Qt.Orientation.Vertical)
        self.splitDockWidget(d["plots"], d["console"], Qt.Orientation.Horizontal)

    def _apply_default_sizes(self) -> None:
        d = self.docks
        self.resizeDocks(
            [d["scene_tree"], d["inspector"]],
            list(tokens.SIDE_PANEL_WIDTH),
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks(
            [d["timeline"], d["plots"]],
            [tokens.TIMELINE_HEIGHT, tokens.BOTTOM_ROW_HEIGHT],
            Qt.Orientation.Vertical,
        )
        w = self.width()
        self.resizeDocks(
            [d["plots"], d["console"]],
            [int(w * tokens.PLOTS_SHARE), int(w * (1 - tokens.PLOTS_SHARE))],
            Qt.Orientation.Horizontal,
        )

    # ----- layout persistence (per project) ------------------------------------------
    def _layout_key(self) -> str:
        return f"layout/{self.project_key}"

    def save_layout(self) -> None:
        self.settings.setValue(f"{self._layout_key()}/state", self.saveState(LAYOUT_VERSION))
        self.settings.setValue(f"{self._layout_key()}/geometry", self.saveGeometry())
        self.settings.sync()

    def restore_layout(self) -> bool:
        state = self.settings.value(f"{self._layout_key()}/state")
        geometry = self.settings.value(f"{self._layout_key()}/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        return state is not None and self.restoreState(state, LAYOUT_VERSION)

    def reset_layout(self) -> None:
        self._place_docks()
        self._apply_default_sizes()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self.viewport.button.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        self.save_layout()
        super().closeEvent(event)
