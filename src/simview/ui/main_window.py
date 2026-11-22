"""Main window: the default Simulate layout from PRD §7.4 (DS-03)."""

from __future__ import annotations

import os
import sys
import time
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
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from simview.blocks.graph import SUFFIX as SVD
from simview.ui import theme
from simview.ui.actions import ActionRegistry
from simview.ui.blockeditor import BlockEditor
from simview.ui.command_palette import CommandPalette
from simview.ui.console.editor import EditorPanel
from simview.ui.console.handle import SimHandle
from simview.ui.console.kernel import ConsoleWidget
from simview.ui.console.workspace import ArrayViewer, WorkspaceBrowser
from simview.ui.panels import EmptyState
from simview.ui.plots.panel import PlotPanel
from simview.ui.plots.signals import SignalTree
from simview.ui.runs_panel import RunsPanel
from simview.ui.sim_panels import Inspector, NoViewport, SceneTree
from simview.ui.sweep_view import SweepView
from simview.ui.theme import icon, tokens
from simview.ui.timeline.history import History
from simview.ui.timeline.playback import Playback
from simview.ui.timeline.widget import Timeline

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
    ("runs", "Runs", Qt.DockWidgetArea.BottomDockWidgetArea),
)
LAYOUT_VERSION = 3  # 2: M5 panels, dropping layouts with the M4 viewport bug; 3: Runs (M5b)
CENTRAL_PAGES = ("3D View", "Diagram")  # BD-01: the block editor sits next to the 3D view
COMPARE_ATOL, COMPARE_RTOL = 1e-6, 1e-6  # run comparison tolerance in the app (D-059)
RUNS_ENV = "SIMVIEW_RUNS"  # overrides the run folder (default: `runs/` next to the scene file)

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
        self.project: Any = None  # simview.io.project.Project, once one is open (IO-04)
        self.console = ConsoleWidget()  # SC-01, works without a scene
        self.editor = EditorPanel()  # SC-02
        self.workspace = WorkspaceBrowser()  # SC-03
        self.block_editor = BlockEditor()  # BD-01..BD-08
        self.block_editor.value_lookup = self.diagram_value
        self.block_editor.default_dir = self._diagram_dir
        self.block_editor.status.connect(lambda m: self.statusBar().showMessage(m, 4000))
        self.block_editor.saved.connect(self._diagram_saved)
        self.scene_diagrams: dict[str, Path] = {}  # name -> .svd file, of the loaded scene
        self.scope_plots: list[Any] = []  # BD-08: the Scope blocks' plots
        self.sim_handle = SimHandle(self)  # `sim` in the console (SC-05)
        self.array_viewers: list[ArrayViewer] = []
        self.sweep_views: list[SweepView] = []
        self.signal_tree: SignalTree | None = None
        self.runs: RunsPanel | None = None
        self.opened_run: Any = None  # RunInfo shown on the timeline, or None for the live sim
        self._pending_run: Any = None  # RunInfo to replay once the scene is ready
        self._pending_finding: Any = None  # Finding to show once its run has replayed
        self.open_reports = True  # open written reports in the browser (tests turn it off)
        self.plots: PlotPanel | None = None
        self.timeline: Timeline | None = None
        self.history: History | None = None
        self.playback = Playback(_SimControls(self))  # VP-05: live or a recorded row (D-048)
        self._live_frame: Any = None
        self._live_draws: list[tuple] = []
        self._drawn: list[tuple] | None = None
        self._shown: tuple | None = None
        self._last_tick_at = 0.0
        self._plots_at = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

        self._register_actions()
        self._connect_console()
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
        reg("file.new_project", "New Project…", self.new_project_dialog, None, "File")
        reg("file.open", "Open Project…", self._open_project, QKeySequence.StandardKey.Open, "File")
        reg("file.save", "Save Project", self.save, QKeySequence.StandardKey.Save, "File")
        reg("file.import_data", "Import Data (CSV, .mat)…", self.import_data_dialog, None, "File")
        reg("file.open_sweep", "Open Sweep Results…", self.open_sweep_dialog, None, "File")
        reg("file.start", "Show Start Screen", self.show_start_screen.emit, None, "File")
        reg("file.open_scene", "Open Scene…", self._open_scene_dialog, "Ctrl+Shift+O", "File")
        reg("sim.run", "Run", self.run, None, "Simulation")
        reg("sim.pause", "Pause", self.pause, None, "Simulation")
        reg("sim.stop", "Stop and Reset", self.stop, None, "Simulation")
        reg("sim.toggle", "Run / Pause", self.toggle_run, "Space", "Simulation")
        reg("sim.step", "Step Forward One Tick", self.step, ".", "Simulation")
        reg("sim.step_back", "Step Back One Tick", self.step_back, ",", "Simulation")
        reg("timeline.start", "Go to Start of Recording", self.to_start, None, "Simulation")
        reg("timeline.live", "Go to Live (End of Recording)", self.to_live, None, "Simulation")
        reg("plots.export_data", "Export Data…", self.export_data_dialog, None, "File")
        reg("diagram.new", "New Diagram", self.new_diagram, None, "File")
        reg("diagram.open", "Open Diagram…", self.open_diagram_dialog, None, "File")
        reg("diagram.save", "Save Diagram", self.save_diagram, None, "File")
        reg("view.3d", "Show 3D View", lambda: self.show_central(0), "Ctrl+1", "View")
        reg("view.diagram", "Show Diagram", lambda: self.show_central(1), "Ctrl+2", "View")
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
            self.open_project(path)

    def toggle_theme(self) -> None:
        new = "light" if theme.current_theme() == "dark" else "dark"
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        theme.apply_theme(app, new)
        self.settings.setValue("theme", new)
        if self.sim_view is not None:
            self.sim_view.set_theme(new)
        if self.plots is not None:
            self.plots.set_theme(new)
        self.console.set_theme(new)
        self.editor.set_theme(new)
        self.block_editor.set_theme(new)
        for view in self.sweep_views:
            view.style(new)

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
        for aid in (
            "file.new",
            "file.open_scene",
            "file.new_project",
            "file.open",
            "file.save",
            "file.import_data",
            "diagram.new",
            "diagram.open",
            "file.start",
        ):
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

        self.page_buttons: list[QToolButton] = []
        for i, (label, ic) in enumerate(zip(CENTRAL_PAGES, ("box", "workflow"), strict=True)):
            b = QToolButton(tb)
            b.setText(label)
            b.setIcon(icon(ic))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setToolTip(f"{label} (Ctrl+{i + 1})")
            b.clicked.connect(lambda _c=False, k=i: self.show_central(k))
            tb.addWidget(b)
            self.page_buttons.append(b)
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
        # One central widget for the window's life: replacing QMainWindow's central widget after
        # the docks are laid out left it zero-wide (the 3D view vanished, docks took the space).
        self.central = QStackedWidget(self)
        self.central.setObjectName("CentralArea")
        self.central.addWidget(self.viewport)
        # 3D view or diagram, switched from the toolbar (a tab bar here would cost the 3D
        # view its §7.2.1 share of the window).
        self.central_pages = QStackedWidget(self)
        self.central_pages.setObjectName("CentralArea")
        self.central_pages.addWidget(self.central)
        self.central_pages.addWidget(self.block_editor)
        self.setCentralWidget(self.central_pages)

    def show_central(self, index: int) -> None:
        self.central_pages.setCurrentIndex(index)
        for i, b in enumerate(self.page_buttons):
            b.setChecked(i == index)

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
            "runs": (
                "history",
                "Open a scene to see its saved runs.",
                "Open Scene…",
                a("file.open_scene").trigger,
            ),
        }
        if name == "timeline":
            hint = "Run a simulation to scrub through time."
            return EmptyState("clock-3", hint, "Run", a("sim.run").trigger, compact=True)
        if name == "console":
            tabs = QTabWidget()
            tabs.setObjectName("ConsoleTabs")
            tabs.addTab(self.console, "Console")
            tabs.addTab(self.editor, "Editor")
            self.console_tabs = tabs
            return tabs
        if name == "workspace":
            self.workspace_stack = QStackedWidget()
            self.workspace_empty = EmptyState(
                "table",
                "Console variables appear here.",
                "Import Data…",
                a("file.import_data").trigger,
            )
            self.workspace_stack.addWidget(self.workspace_empty)
            self.workspace_stack.addWidget(self.workspace)
            return self.workspace_stack
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
        self.tabifyDockWidget(d["console"], d["runs"])
        d["console"].raise_()

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
        title = self.scene_path.name
        if self.project is not None:
            title = f"{self.project.name} — {title}"
        self.setWindowTitle(f"SimView — {title}")
        self._ensure_scene_panels()
        self.client = SimClient()
        self.client.start(self.scene_path)
        self.opened_run = None
        assert self.runs is not None
        self.runs.set_folder(self.runs_folder())
        self.playback.sim_running = False
        self.playback.reset(None)
        self.timer.start(int(1000 / tokens.VIEWPORT_FPS))
        self.statusBar().showMessage(f"Loading {self.scene_path.name}…")

    def close_scene(self) -> None:
        self.timer.stop()
        self.save_live_run()
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
        self.central.addWidget(self.sim_view)
        self.central.setCurrentWidget(self.sim_view)
        self.viewport = self.sim_view
        self.scene_tree = SceneTree()
        self.inspector = Inspector()
        a = self.actions_.get
        self.timeline = Timeline(
            {
                "start": a("timeline.start"),
                "back": a("sim.step_back"),
                "toggle": a("sim.toggle"),
                "forward": a("sim.step"),
                "live": a("timeline.live"),
            }
        )
        self.signal_tree = SignalTree()
        self.plots = PlotPanel(self._focus_dock("signals"))
        self.runs = RunsPanel()
        self.docks["runs"].setWidget(self.runs)
        self.runs.open_run.connect(self.open_run)
        self.runs.finding_clicked.connect(self.show_finding)
        self.runs.report_requested.connect(self.write_report)
        self.runs.compare_requested.connect(self.compare_runs)
        self.runs.import_requested.connect(self.import_dialog)
        self.docks["scene_tree"].setWidget(self.scene_tree)
        self.docks["inspector"].setWidget(self.inspector)
        self.docks["timeline"].setWidget(self.timeline)
        self.docks["signals"].setWidget(self.signal_tree)
        self.docks["plots"].setWidget(self.plots)
        self.timeline.seek.connect(self.seek)
        self.signal_tree.activated.connect(self.plots.plot_signals)
        self.plots.seek_time.connect(self.seek_time)
        self.plots.hover_time.connect(self._plot_hover)
        self.plots.export_data.connect(self.export_data_dialog)
        # DS-06: one selection and one hover, shown everywhere.
        tree, view = self.scene_tree, self.sim_view
        view.selected.connect(self._select)
        view.hovered.connect(tree.set_hover)
        tree.selected.connect(self._select)
        tree.hovered.connect(view.set_hover)
        self.signal_tree.selected.connect(self._select)
        self.signal_tree.hovered.connect(self._hover)
        self.plots.selected.connect(self._select)
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
        if self.signal_tree is not None and self.plots is not None:
            self.signal_tree.select(name)
            self.plots.set_selection(name)
        desc = self.client.description if self.client is not None else None
        self.inspector.show_entity(desc, name)

    def _hover(self, name: str | None) -> None:
        assert self.scene_tree is not None
        self.sim_view.set_hover(name)
        self.scene_tree.set_hover(name)

    def _tick(self) -> None:
        """Poll the sim process and redraw (VIEWPORT_FPS)."""
        from simview.ipc import protocol as proto

        client = self.client
        if client is None:
            return
        for ev in client.poll():
            kind = ev["event"]
            if kind == proto.READY:
                self._on_ready(ev["description"])
            elif kind == proto.ROWS:
                if self.history is not None:
                    self.history.append(ev["rows"])
            elif kind == proto.REPLAYED:
                self._on_replayed(ev)
            elif kind == proto.DRAWS:
                self._live_draws = ev["draws"]  # the newest set (draws can change every tick)
                if self.history is not None:
                    self.history.add_draws(ev["tick"], ev["draws"])
            elif kind == proto.PARAMS:
                self.sim_handle.params_changed(ev["values"])
            elif kind == proto.LOG:
                token = "state.error" if ev["stream"] == "stderr" else "text.primary"
                self.console.write(ev["text"], token)
            elif kind == proto.ERROR:
                self.playback.sim_stopped()
                self.console.write(ev["traceback"], "state.error")
                self._focus_dock("console")()
                self.statusBar().showMessage(
                    "The simulation raised an error; see the console.", 6000
                )
            elif kind == proto.STOPPED:
                self._on_stopped(ev.get("exitcode"))
        now = time.monotonic()
        wall_dt, self._last_tick_at = now - self._last_tick_at, now
        self.playback.advance(min(wall_dt, 0.1), float(self.speed_box.currentData()))
        frame = client.frame()
        if frame is not None:
            self._live_frame = frame
            speed = "max" if frame.speed <= 0 else f"{frame.speed:g}×"
            self.rtf_label.setText(f"RTF {frame.rtf:.2f}× ({speed})")
        self.show_time()
        if self.plots is not None and now - self._plots_at >= 1.0 / tokens.PLOT_FPS:
            self._plots_at = now
            self.plots.refresh()

    def show_time(self) -> None:
        """Show the timeline's moment (live or recorded) everywhere at once (VP-05, DA-02).
        The 3D view is updated and rendered only when that moment changed (D-061)."""
        pb, h = self.playback, self.history
        shown = pb.shown
        live = self._live_frame
        row = -1
        if h is not None and h.n:
            row = h.n - 1 if shown is None else min(shown, h.n - 1)
        if shown is None or row < 0:
            moment = None if live is None else ("live", live.tick, live.wall)
        else:
            moment = ("row", row)
        draws = self._live_draws
        if shown is not None and row >= 0:
            assert h is not None
            draws = h.draws_at(int(h.ticks[row]))
        key = (moment, h.version if h is not None else 0, id(draws))
        if moment is not None and key != self._shown:
            self._shown = key
            frame = live if shown is None or row < 0 else h.frame(row, live)  # type: ignore[union-attr]
            trails = h.trails(row, self._trail_seconds()) if h is not None and row >= 0 else None
            if draws is not self._drawn:
                self._drawn = draws
                self.sim_view.set_draws(draws)
            self.sim_view.update_frame(frame, trails)
            if self.inspector is not None:
                self.inspector.update_frame(frame)
            self.sim_view.render()
        if self.plots is not None:
            self.plots.set_cursor(pb.index if row >= 0 else None, pb.preview)
        if self.timeline is not None and h is not None and h.n:
            self.timeline.show_state(
                pb.index,
                pb.last,
                h.time_of(pb.index),
                h.time_of(pb.last),
                live=pb.live and not pb.recorded,
                playing=pb.running,
            )

    def _trail_seconds(self) -> dict[str, float]:
        desc = self.client.description if self.client is not None else None
        if desc is None:
            return {}
        return {
            e.name: desc.trails.get(e.name, (tokens.TRAIL_SECONDS, None))[0]
            for e in desc.entities
            if e.has_marker
        }

    def _on_ready(self, desc: Any) -> None:
        assert self.scene_tree is not None and self.inspector is not None
        self.sim_view.load(desc)
        self.scene_tree.load(desc)
        self.inspector.show_entity(desc, None)
        layout = self.client.row_layout
        self.history = History(layout, desc.dt) if layout is not None else None
        self.playback.reset(self.history)
        self._live_draws, self._drawn, self._shown = [], None, None
        if layout is not None:
            assert self.signal_tree is not None and self.plots is not None
            self.signal_tree.load(layout)
            self.plots.set_history(self.history)
        self._load_diagrams(desc)
        self.dt_label.setText(f"dt {desc.dt * 1e3:g} ms")
        self.sim_handle.loaded(desc.params)
        self.client.set_speed(float(self.speed_box.currentData()))
        self.statusBar().showMessage(f"{self.scene_path.name} loaded.", 3000)
        if self.playback.sim_running:
            self.client.play()  # Run was pressed while the scene loaded
        self.opened_run = None
        if self._pending_run is not None:  # a saved run waits for its scene
            run, self._pending_run = self._pending_run, None
            self.client.replay(run.path)

    # ----- block diagrams (BD-01, BD-04, BD-08) -------------------------------------
    def _load_diagrams(self, desc: Any) -> None:
        """A scene was loaded: the editor checks entity blocks against its entities, opens
        the diagram it runs (unless one is being edited), and each Scope block gets a plot."""
        ed = self.block_editor
        ed.set_entities({e.name: tuple(e.state_names) for e in desc.entities})
        self.scene_diagrams = {k: Path(v).resolve() for k, v in desc.diagrams.items() if v}
        paths = list(self.scene_diagrams.values())
        here = ed.path.resolve() if ed.path is not None else None
        if paths and here not in paths and (ed.doc.is_blank or not ed.doc.modified):
            ed.open(paths[0])
        if self.plots is not None:
            for view in self.scope_plots:
                if view in self.plots.plots:
                    self.plots.remove_plot(view)
            self.scope_plots = []
            for scope, signals in desc.scopes.items():
                if not signals or self.history is None:
                    continue
                view = self.plots.add_plot("time", list(signals))
                view.title.setText(scope)
                view.hint.setText("Scope")
                self.scope_plots.append(view)

    def _diagram_name(self) -> str | None:
        """The name the loaded scene runs the edited diagram under, if it runs it."""
        path = self.block_editor.path
        if path is None:
            return None
        path = path.resolve()
        return next((k for k, v in self.scene_diagrams.items() if v == path), None)

    def diagram_value(self, block: str, port: str) -> str | None:
        """§7.7: a wire's value at the timeline's row, for the hover tooltip."""
        name, h = self._diagram_name(), self.history
        if name is None or h is None or h.n == 0:
            return None
        base = f"{name}.{block}.{port}"
        row = self.playback.index
        if base in h.units:
            return f"{float(h.signal(base)[row]):.6g}"
        values, k = [], 0
        while f"{base}[{k}]" in h.units:
            values.append(f"{float(h.signal(f'{base}[{k}]')[row]):.6g}")
            k += 1
        return f"[{', '.join(values)}]" if values else None

    def _diagram_dir(self) -> Path | None:
        if self.project is not None:
            return self.project.folder("diagrams")
        return self.scene_path.parent if self.scene_path is not None else None

    def new_diagram(self) -> None:
        self.block_editor.new()
        self.show_central(1)

    def open_diagram_dialog(self) -> None:
        self.show_central(1)
        self.block_editor.open_dialog()

    def open_diagram(self, path: str | Path) -> None:
        self.block_editor.open(path)
        self.show_central(1)

    def save_diagram(self) -> Path | None:
        return self.block_editor.save()

    def _diagram_saved(self, path: Path) -> None:
        """Edits run once the scene reloads (D-085): reload now when the open scene runs
        this diagram and time isn't moving."""
        if self.scene_path is None or self._diagram_name() is None:
            return
        if self.running:
            self.statusBar().showMessage(
                f"Saved {path.name}. Stop the simulation to run the changes.", 5000
            )
            return
        self.load_scene(self.scene_path)

    def _on_stopped(self, code: int | None) -> None:
        """NF-10: the sim process died; the UI stays up and Run starts a new one."""
        self.playback.sim_stopped()
        if code not in (0, None):
            msg = f"The sim process exited (code {code}). Run restarts it."
            self.console.write(msg + "\n", "state.error")
            self.statusBar().showMessage(msg, 6000)

    # ----- run controls --------------------------------------------------------------
    @property
    def running(self) -> bool:
        """Time is moving: the live sim runs, or the timeline replays the recording."""
        return self.playback.running

    def _has_scene(self) -> bool:
        if self.client is None:
            self._no_scene()
            return False
        return True

    def _transport(self, action: Callable[[], None]) -> None:
        if self._has_scene():
            action()
            self.show_time()

    def run(self) -> None:
        if self._has_scene() and not self.client.alive and self.scene_path is not None:
            self.client.start(self.scene_path)  # after a crash: a fresh sim process
            self.playback.reset(None)
        self._transport(self.playback.play)

    def pause(self) -> None:
        self._transport(self.playback.pause)

    def toggle_run(self) -> None:
        if self.running:
            self.pause()
        else:
            self.run()

    def step(self) -> None:
        self._transport(self.playback.step_forward)

    def step_back(self) -> None:
        self._transport(self.playback.step_back)

    def to_start(self) -> None:
        self._transport(self.playback.to_start)

    def to_live(self) -> None:
        self._transport(self.playback.to_live)

    def seek(self, index: int) -> None:
        """Scrub to history row `index` (VP-05): viewport, plots, and timeline follow at once."""
        self._transport(lambda: self.playback.seek(index))

    def seek_time(self, t: float) -> None:
        if self.history is not None and self.history.n:
            self.seek(self.history.index_at(t))

    def _plot_hover(self, t: float | None) -> None:
        """DA-02: hovering a plot shows that moment in the viewport until the mouse leaves."""
        h = self.history
        self.playback.preview = h.index_at(t) if t is not None and h is not None and h.n else None
        if self.client is not None:
            self.show_time()

    def stop(self) -> None:
        """Stop and reset: the scene file is loaded again from the start. A live run is saved
        to the run folder first (RI-01) and scanned for the scenarios (RI-02)."""
        if self._has_scene():
            self.playback.pause()
            self.save_live_run()
            self.client.reset()

    # ----- console, editor, workspace (SC-01-SC-03, SC-05, IO-02) -------------------
    def _connect_console(self) -> None:
        self.console.push({"sim": self.sim_handle}, hidden=True)
        self.console.namespace_changed.connect(self.refresh_workspace)
        self.editor.run_code.connect(self._run_in_console)
        # Forward slashes and double quotes: %run splits its arguments like a shell would.
        self.editor.run_file.connect(
            lambda path: self._run_in_console(f'%run -i "{Path(path).as_posix()}"')
        )
        self.workspace.open_array.connect(self.open_array)

    def _run_in_console(self, code: str) -> None:
        self.console_tabs.setCurrentWidget(self.console)
        self.console.run_code(code)

    def refresh_workspace(self) -> None:
        self.workspace.refresh(self.console.namespace, self.console.hidden)
        has_vars = bool(self.workspace.values)
        self.workspace_stack.setCurrentWidget(self.workspace if has_vars else self.workspace_empty)

    def open_array(self, name: str) -> ArrayViewer:
        """SC-03: a NumPy variable in a table viewer."""
        viewer = ArrayViewer(name, self.workspace.values[name], self)
        self.array_viewers = [v for v in self.array_viewers if v.isVisible()] + [viewer]
        viewer.show()
        return viewer

    def open_sweep_dialog(self) -> None:
        start = str(self.runs_folder()) if self.runs_folder().is_dir() else ""
        kinds = "Sweep results (results.parquet);;Parquet (*.parquet)"
        path, _ = QFileDialog.getOpenFileName(self, "Open Sweep Results", start, kinds)
        if path:
            self.open_sweep(path)

    def open_sweep(self, path: Any) -> SweepView | None:
        """DA-06: a Monte Carlo sweep's results (a `SweepResults`, its `results.parquet`, or
        its folder) in a results window."""
        from simview.runner.montecarlo import SweepResults

        try:
            res = path if isinstance(path, SweepResults) else SweepResults.load(path)
        except Exception as exc:  # noqa: BLE001 - a bad file is a message, not a crash
            self.statusBar().showMessage(f"Couldn't open sweep results: {exc}", 6000)
            return None
        if not res.metrics and not res.params:
            self.statusBar().showMessage(f"{res.path.name} isn't a sweep's results file", 6000)
            return None
        view = SweepView(res, self)
        self.sweep_views = [v for v in self.sweep_views if v.isVisible()] + [view]
        view.show()
        return view

    def import_data_dialog(self) -> None:
        start = str(self.project.path) if self.project is not None else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Data", start, "Data files (*.csv *.mat);;All files (*)"
        )
        if path:
            self.import_data(path)

    def import_data(self, path: str | Path) -> list[str]:
        """IO-02: a CSV file (one record array named after the file) or a .mat file's
        variables, into the console's workspace."""
        from simview.io.data import load_data

        try:
            values = load_data(path)
        except Exception as exc:  # noqa: BLE001 - a bad file is a message, not a crash
            self.statusBar().showMessage(f"Couldn't import {Path(path).name}: {exc}", 6000)
            return []
        self.console.push(values)
        names = ", ".join(values) or "nothing"
        self.console.write(f"Imported {Path(path).name}: {names}\n", "text.secondary")
        self._focus_dock("workspace")()
        self.statusBar().showMessage(f"Imported {names} from {Path(path).name}", 4000)
        return list(values)

    # ----- projects (IO-04) ----------------------------------------------------------
    def new_project_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "New Project", "", "SimView project (*.svproj)")
        if path:
            self.new_project(path)

    def new_project(self, path: str | Path) -> Any:
        """Create a project folder and save what's open into it (scene, script)."""
        from simview.io import project as proj

        try:
            p = proj.create(path)
        except proj.ProjectError as exc:
            self.statusBar().showMessage(str(exc), 6000)
            return None
        self._set_project(p)
        self.save_project()
        return p

    def open_project(self, path: str | Path) -> Any:
        """Open a project: its scene (and its run folder), and its script in the editor."""
        from simview.io import project as proj
        from simview.ui.start_screen import add_recent_project

        try:
            p = proj.load(path)
        except proj.ProjectError as exc:
            self.statusBar().showMessage(str(exc), 6000)
            return None
        self._set_project(p)
        add_recent_project(self.settings, str(p.path))
        script = p.script_path
        if script is not None and script.is_file():
            self.editor.open(script)
        diagram = p.diagram_path
        if diagram is not None and diagram.is_file():
            self.block_editor.open(diagram)
        scene = p.scene_path
        if scene is not None and scene.is_file():
            self.load_scene(scene)
        self.statusBar().showMessage(f"Opened project {p.name}", 3000)
        return p

    def _set_project(self, p: Any) -> None:
        self.project = p
        self.setWindowTitle(f"SimView — {p.name}")
        if self.runs is not None:
            self.runs.set_folder(self.runs_folder())

    def save(self) -> None:
        """Ctrl+S: save the project. With no project open, save the editor's script if it has
        one (or unsaved text); with nothing to save, offer a new project."""
        ed = self.editor
        if self.central_pages.currentIndex() == 1 and self.project is None:
            self.save_diagram()
        elif self.project is not None:
            self.save_project()
        elif ed.path is not None or ed.editor.document().isModified():
            ed.save()
        else:
            self.new_project_dialog()

    def save_project(self) -> Path | None:
        """Write the project: the open scene and script are kept in its folders (copied in
        if they came from elsewhere), and `project.json` names them. Runs are written to
        its `runs/` when they stop (RI-01)."""
        p = self.project
        if p is None:
            return None
        ed = self.editor
        if ed.path is not None or ed.editor.toPlainText().strip():
            if ed.path is None or p.relative(ed.path) is None:
                name = ed.path.name if ed.path is not None else "script.py"
                ed.path = p.folder("scripts") / name
            ed.save_to(ed.path)
            p.script = p.relative(ed.path)
            ed.file_changed.emit(ed.path)
        diagram = self.block_editor
        if diagram.path is not None or diagram.doc.root.blocks:
            if diagram.path is None:
                diagram.save_as(p.folder("diagrams") / f"diagram{SVD}")
            elif diagram.doc.modified:
                diagram.save_as(None)
            p.diagram = p.relative(diagram.path) if diagram.path is not None else None
        if self.scene_path is not None:
            self.scene_path = p.set_scene(self.scene_path)
        manifest = p.save()
        self.statusBar().showMessage(f"Saved project {p.name}", 3000)
        return manifest

    # ----- run investigation (PRD §5.11) ---------------------------------------------
    def runs_folder(self) -> Path:
        override = os.environ.get(RUNS_ENV)
        if override:
            return Path(override)
        if self.project is not None:
            return self.project.runs_dir
        base = self.scene_path.parent if self.scene_path is not None else Path.cwd()
        return base / "runs"

    def save_live_run(self) -> Path | None:
        """Write the live recording to the run folder (not a replayed run, not an empty one)."""
        h, desc = self.history, self.client.description if self.client is not None else None
        if h is None or h.n < 2 or self.playback.recorded or desc is None:
            return None
        from simview.investigate.runs import Catalog, run_stem
        from simview.io.export import write_table
        from simview.runner.run import write_context

        catalog = Catalog(self.runs_folder())
        path = catalog.new_path(run_stem(desc.seed))
        meta = {
            "dt": desc.dt,
            "seed": desc.seed,
            "duration": h.time_of(h.n - 1) - h.time_of(0),
            "source": "app",
            "units": {k: u for k, u in h.units.items() if u},
            "params": {
                k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in desc.params.items()
            },
        }
        write_table(h.table(meta), path)
        scene_file = str(self.scene_path.resolve()) if self.scene_path is not None else None
        write_context(path, scene_file=scene_file)
        self.history = None  # saved once
        if self.runs is not None:
            self.runs.refresh(scan_runs=True)
        self.statusBar().showMessage(f"Run saved to {path}", 4000)
        return path

    def open_run(self, run: Any) -> None:
        """RI-01: show a saved or imported run. Its scene is loaded, then the sim process
        replays the log, so the viewport, timeline, and plots show it."""
        if not run.scene:
            self.statusBar().showMessage(
                f"{run.name} has no scene file to replay it with (import it with a scene).", 6000
            )
            return
        scene = Path(run.scene)
        self._pending_run = run
        same = self.scene_path is not None and self.scene_path.resolve() == scene.resolve()
        if same and self.client is not None and self.client.alive and self.history is not None:
            self.save_live_run()
            self._pending_run = None
            self.client.replay(run.path)
        else:
            self.load_scene(scene)
        self.statusBar().showMessage(f"Opening {run.name}…")

    def _on_replayed(self, ev: dict[str, Any]) -> None:
        layout = self.client.row_layout
        if layout is None:
            return
        from simview.investigate.runs import read_info

        self.history = History(layout, float(ev["dt"]))
        self.history.append(ev["rows"])
        self.playback.reset(self.history, recorded=True)
        if self.history.n > 1:
            self.playback.seek(0)
        self._live_draws, self._drawn, self._shown = [], None, None
        assert self.signal_tree is not None and self.plots is not None
        self.signal_tree.load(layout)
        self.plots.set_history(self.history)
        self.opened_run = read_info(ev["path"])
        self.setWindowTitle(f"SimView — {self.scene_path.name} — {self.opened_run.name}")
        self.statusBar().showMessage(f"{self.opened_run.name}: {self.history.n} samples.", 4000)
        if self._pending_finding is not None:
            f, self._pending_finding = self._pending_finding, None
            self.show_finding(f)
        self.show_time()

    def show_finding(self, finding: Any) -> None:
        """RI-03: move the timeline, viewport, and plots to a finding's window (opening its
        run first if another one is shown)."""
        shown = self.opened_run
        if shown is None or Path(shown.path).resolve() != Path(finding.run.path).resolve():
            self._pending_finding = finding
            self.open_run(finding.run)
            return
        h = self.history
        if h is None or not h.n:
            return
        self.playback.seek(h.index_at(finding.start))
        assert self.plots is not None
        self.plots.show_window(list(finding.signals), finding.start, finding.end, h.dt)
        self.show_time()

    def write_report(self, runs: list[Any]) -> Path | None:
        """RI-04: an HTML report of the runs, written to `<run folder>/reports/`."""
        from simview.investigate.report import write_report
        from simview.investigate.runs import RunData

        assert self.runs is not None
        data = [RunData(r) for r in runs]
        paths = {r.path for r in runs}
        results = [x for x in self.runs.results if x.run.path in paths]
        name = runs[0].name if len(runs) == 1 else f"{runs[0].name}-and-{len(runs) - 1}-more"
        out = write_report(data, results, self.runs_folder() / "reports" / f"{name}.html")
        self._show_report(out)
        return out

    def compare_runs(self, run: Any, baseline: Any) -> Any:
        """RI-05: compare two runs; divergences become findings and a report is written."""
        from simview.investigate.compare import compare
        from simview.investigate.report import write_report
        from simview.investigate.runs import RunData

        assert self.runs is not None
        a, b = RunData(run), RunData(baseline)
        c = compare(a, b, atol=COMPARE_ATOL, rtol=COMPARE_RTOL, scenarios=self.runs.scenarios)
        self.runs.show_comparison_findings(c.findings)
        results = [x for x in self.runs.results if x.run.path in (run.path, baseline.path)]
        out = write_report(
            [a, b],
            results,
            self.runs_folder() / "reports" / f"{run.name}-vs-{baseline.name}.html",
            comparison=c,
            title=f"{run.name} vs {baseline.name}",
        )
        self._show_report(out)
        return c

    def _show_report(self, path: Path) -> None:
        self.statusBar().showMessage(f"Report written to {path}", 6000)
        if self.open_reports:
            from qtpy.QtCore import QUrl
            from qtpy.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def import_dialog(self) -> None:
        """RI-06: pick a CSV or Parquet log, then map its columns onto the scene's signals."""
        from qtpy.QtWidgets import QInputDialog

        from simview.investigate.importer import read_columns

        path, _ = QFileDialog.getOpenFileName(
            self, "Import Robot Log", "", "Logs (*.csv *.parquet)"
        )
        if not path:
            return
        columns = read_columns(path)
        signals = self.history.signals if self.history is not None else ()
        time_col = next((c for c in ("t", "time", "timestamp") if c in columns), columns[0])
        guess = [f"{s} = {s}" for s in signals if s in columns]
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Map Columns",
            f"Time column: {time_col} (seconds). One `signal = column` per line;\n"
            "mapped columns drive the scene's entities when the run is replayed.",
            "\n".join(guess) or "# ur5.shoulder_pan_joint.q = joint1",
        )
        if ok:
            mapping = {}
            for line in text.splitlines():
                sig, sep, col = line.partition("=")
                if sep and not line.lstrip().startswith("#"):
                    mapping[sig.strip()] = col.strip()
            self.import_log(path, mapping, time_col)

    def import_log(self, path: str | Path, mapping: dict[str, str], time_column: str = "t") -> Any:
        from simview.investigate.importer import import_log
        from simview.investigate.runs import Catalog

        info = import_log(
            path,
            Catalog(self.runs_folder()),
            mapping=mapping,
            time_column=time_column,
            scene=self.scene_path,
        )
        if self.runs is not None:
            self.runs.refresh(scan_runs=True)
        self.statusBar().showMessage(f"Imported {info.rows} rows as {info.name}", 4000)
        return info

    def export_data_dialog(self) -> None:
        """DA-07: every logged signal of the recorded run to CSV, Parquet, or .mat."""
        if self.history is None or not self.history.n:
            self.statusBar().showMessage("Run a simulation first: there is no data yet.", 4000)
            return
        stem = self.scene_path.stem if self.scene_path is not None else "run"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Data", f"{stem}.csv", "CSV (*.csv);;Parquet (*.parquet);;MATLAB (*.mat)"
        )
        if path:
            self.export_data(path)

    def export_data(self, path: str | Path) -> Path:
        from simview.io.export import write_table

        assert self.history is not None
        meta = {"scene": str(self.scene_path)} if self.scene_path is not None else {}
        out = write_table(self.history.table(meta), path)
        self.statusBar().showMessage(f"Exported {self.history.n} rows to {out}", 4000)
        return out

    def _speed_changed(self) -> None:
        if self.client is not None:
            self.client.set_speed(float(self.speed_box.currentData()))


class _SimControls:
    """What the playback asks of the sim process (play, pause, one step)."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    def play(self) -> None:
        if self.window.client is not None:
            self.window.client.play()

    def pause(self) -> None:
        if self.window.client is not None:
            self.window.client.pause()

    def step(self, n: int = 1) -> None:
        if self.window.client is not None:
            self.window.client.step(n)
