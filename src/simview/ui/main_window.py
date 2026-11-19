"""Main window: the default Simulate layout from PRD §7.4 (DS-03)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qtpy.QtCore import QSettings, QSize, Qt, QTimer, Signal
from qtpy.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShowEvent
from qtpy.QtWidgets import (
    QApplication,
    QComboBox,
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
from simview.ui.sim_panels import Console, Inspector, NoViewport, SceneTree
from simview.ui.theme import icon, tokens

# SE-10 playback speeds; 0 = as fast as possible.
SPEEDS = (
    ("0.1×", 0.1),
    ("0.25×", 0.25),
    ("0.5×", 0.5),
    ("1×", 1.0),
    ("2×", 2.0),
    ("5×", 5.0),
    ("10×", 10.0),
    ("Max", 0.0),
)

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
        self.client: Any = None  # SimClient, once a scene is opened
        self.scene_path: Path | None = None
        self.sim_view: Any = None  # Viewport, or NoViewport without OpenGL
        self.scene_tree: SceneTree | None = None
        self.inspector: Inspector | None = None
        self.console: Console | None = None
        self.running = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

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
        reg("file.open_scene", "Open Scene…", self._open_scene_dialog, "Ctrl+Shift+O", "File")
        reg("sim.run", "Run", self.run, None, "Simulation")
        reg("sim.pause", "Pause", self.pause, None, "Simulation")
        reg("sim.stop", "Stop and Reset", self.stop, None, "Simulation")
        reg("sim.toggle", "Run / Pause", self.toggle_run, "Space", "Simulation")
        reg("sim.step", "Step Forward One Tick", self.step, ".", "Simulation")
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
        if self.sim_view is not None:
            self.sim_view.set_theme(new)

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
        for aid in ("file.new", "file.open_scene", "file.open", "file.start"):
            menu.addAction(self.actions_.get(aid))
        project.setMenu(menu)
        tb.addWidget(project)
        tb.addSeparator()

        for aid, ic, token in (
            ("sim.run", "play", "accent"),
            ("sim.pause", "pause", "text.secondary"),
            ("sim.step", "step-forward", "text.secondary"),
            ("sim.stop", "square", "text.secondary"),
        ):
            action = self.actions_.get(aid)
            action.setIcon(icon(ic, token))
            tb.addAction(action)
        self.speed_box = QComboBox(tb)
        self.speed_box.setToolTip("Playback speed (× real time)")
        for label, value in SPEEDS:
            self.speed_box.addItem(label, value)
        self.speed_box.setCurrentIndex(3)  # 1× (real time)
        self.speed_box.currentIndexChanged.connect(self._speed_changed)
        tb.addWidget(self.speed_box)
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
        self.close_scene()
        super().closeEvent(event)

    # ----- the loaded scene (SE-02, SE-10, VP-06, DS-06, NF-10) ----------------------
    def _open_scene_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Scene", "", "Scene files (*.py)")
        if path:
            self.load_scene(path)

    def load_scene(self, path: str | Path) -> None:
        """Start a sim process for a scene file and show it."""
        from simview.ipc.client import SimClient

        self.close_scene()
        self.scene_path = Path(path)
        self.setWindowTitle(f"SimView — {self.scene_path.name}")
        self._ensure_scene_panels()
        self.client = SimClient()
        self.client.start(self.scene_path)
        self.running = False
        self.timer.start(int(1000 / tokens.VIEWPORT_FPS))
        self.statusBar().showMessage(f"Loading {self.scene_path.name}…")

    def close_scene(self) -> None:
        self.timer.stop()
        if self.client is not None:
            self.client.stop()
            self.client = None

    def _make_viewport(self) -> Any:
        if QGuiApplication.platformName() in ("offscreen", "minimal"):
            return NoViewport("no OpenGL display (headless)")
        try:
            from simview.ui.viewport.view import Viewport

            return Viewport(theme.current_theme())
        except Exception as exc:  # noqa: BLE001 - a missing GL driver must not stop the app
            return NoViewport(f"{type(exc).__name__}: {exc}")

    def _ensure_scene_panels(self) -> None:
        if self.sim_view is not None:
            return
        self.sim_view = self._make_viewport()
        self.sim_view.setObjectName("CentralArea")
        self.setCentralWidget(self.sim_view)
        self.viewport = self.sim_view
        self.scene_tree = SceneTree()
        self.inspector = Inspector()
        self.console = Console()
        self.docks["scene_tree"].setWidget(self.scene_tree)
        self.docks["inspector"].setWidget(self.inspector)
        tabs = self.docks["console"].widget()
        if isinstance(tabs, QTabWidget):
            tabs.removeTab(0)
            tabs.insertTab(0, self.console, "Console")
            tabs.setCurrentIndex(0)
        # DS-06: one selection and one hover, shown everywhere.
        tree, view = self.scene_tree, self.sim_view
        view.selected.connect(self._select)
        view.hovered.connect(tree.set_hover)
        tree.selected.connect(self._select)
        tree.hovered.connect(view.set_hover)
        view.target_moved.connect(self._target_moved)
        view.body_moved.connect(self._body_moved)

    def _target_moved(self, name: str, pose: Any) -> None:
        if self.client is not None:
            self.client.set_target(name, pose)

    def _body_moved(self, name: str, pos: Any, quat: Any) -> None:
        if self.client is not None:
            self.client.set_body_pose(name, pos, quat)

    def _select(self, name: str | None) -> None:
        assert self.scene_tree is not None and self.inspector is not None
        self.sim_view.select(name)
        self.scene_tree.select(name)
        desc = self.client.description if self.client is not None else None
        self.inspector.show_entity(desc, name)

    def _tick(self) -> None:
        """Poll the sim process and redraw (VIEWPORT_FPS)."""
        from simview.ipc import protocol as proto

        client = self.client
        if client is None:
            return
        draws = None
        for ev in client.poll():
            kind = ev["event"]
            if kind == proto.READY:
                self._on_ready(ev["description"])
            elif kind == proto.DRAWS:
                draws = ev["draws"]  # only the newest set is drawn (draws can change every tick)
            elif kind == proto.LOG:
                assert self.console is not None
                token = "state.error" if ev["stream"] == "stderr" else "text.primary"
                self.console.write(ev["text"], token)
            elif kind == proto.ERROR:
                assert self.console is not None
                self.running = False
                self.console.write(ev["traceback"], "state.error")
                self._focus_dock("console")()
                self.statusBar().showMessage(
                    "The simulation raised an error; see the console.", 6000
                )
            elif kind == proto.STOPPED:
                self._on_stopped(ev.get("exitcode"))
        if draws is not None:
            self.sim_view.set_draws(draws)
        frame = client.frame()
        if frame is not None:
            self.sim_view.update_frame(frame)
            if self.inspector is not None:
                self.inspector.update_frame(frame)
            speed = "max" if frame.speed <= 0 else f"{frame.speed:g}×"
            self.rtf_label.setText(f"RTF {frame.rtf:.2f}× ({speed})")
        self.sim_view.render()

    def _on_ready(self, desc: Any) -> None:
        assert self.scene_tree is not None and self.inspector is not None
        self.sim_view.load(desc)
        self.scene_tree.load(desc)
        self.inspector.show_entity(desc, None)
        self.dt_label.setText(f"dt {desc.dt * 1e3:g} ms")
        self.client.set_speed(float(self.speed_box.currentData()))
        self.statusBar().showMessage(f"{self.scene_path.name} loaded.", 3000)
        if self.running:
            self.client.play()

    def _on_stopped(self, code: int | None) -> None:
        """NF-10: the sim process died; the UI stays up and Run starts a new one."""
        assert self.console is not None
        self.running = False
        if code not in (0, None):
            msg = f"The sim process exited (code {code}). Run restarts it."
            self.console.write(msg + "\n", "state.error")
            self.statusBar().showMessage(msg, 6000)

    # ----- run controls --------------------------------------------------------------
    def run(self) -> None:
        if self.client is None:
            self._no_scene()
            return
        if not self.client.alive and self.scene_path is not None:
            self.client.start(self.scene_path)  # after a crash: a fresh sim process
        self.running = True
        self.client.play()

    def pause(self) -> None:
        if self.client is None:
            self._no_scene()
            return
        self.running = False
        self.client.pause()

    def toggle_run(self) -> None:
        if self.running:
            self.pause()
        else:
            self.run()

    def step(self) -> None:
        if self.client is None:
            self._no_scene()
            return
        self.running = False
        self.client.step()

    def stop(self) -> None:
        """Stop and reset: the scene file is loaded again from the start."""
        if self.client is None:
            self._no_scene()
            return
        self.running = False
        self.client.reset()

    def _speed_changed(self) -> None:
        if self.client is not None:
            self.client.set_speed(float(self.speed_box.currentData()))
