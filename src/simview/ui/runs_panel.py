"""The Runs panel (PRD §5.11): the run catalog, scenarios, and traceable findings.

Runs (RI-01) are listed newest first with a filter; double-click opens one (it replays in the
viewport, timeline, and plots). Scenarios (RI-02) are "name: condition for 0.1 s" lines saved
with the run folder; Scan runs them over every run (only new or changed runs are read). Each
finding (RI-03) names its run, signals, and window; clicking it moves the timeline, viewport,
and plots there. Report (RI-04), Compare (RI-05), and Import (RI-06) act on the selection.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from qtpy.QtCore import QSize, Qt, Signal
from qtpy.QtGui import QBrush, QColor
from qtpy.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simview.investigate.runs import Catalog, RunInfo
from simview.investigate.scenario import (
    Finding,
    ScanResult,
    Scenario,
    ScenarioError,
    load_scenarios,
    save_scenarios,
    scan,
)
from simview.ui import theme
from simview.ui.theme import icon, tokens

DATA = Qt.ItemDataRole.UserRole
RUN_COLUMNS = ("Run", "Scene", "Source", "Seed", "Duration", "Date", "Matches")


def _button(parent: QWidget, ic: str, tip: str, text: str = "") -> QToolButton:
    b = QToolButton(parent)
    b.setIcon(icon(ic))
    b.setIconSize(QSize(tokens.ICON_SIZE_TOOLBAR, tokens.ICON_SIZE_TOOLBAR))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return b


class RunsPanel(QWidget):
    open_run = Signal(object)  # RunInfo
    finding_clicked = Signal(object)  # Finding
    report_requested = Signal(list)  # [RunInfo]
    compare_requested = Signal(object, object)  # run, baseline
    import_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog: Catalog | None = None
        self.scenarios: list[Scenario] = []
        self.results: list[ScanResult] = []
        self.extra_findings: list[Finding] = []  # from a comparison
        lay = QVBoxLayout(self)
        s = tokens.SPACING
        lay.setContentsMargins(s[1], s[0], s[1], s[0])
        lay.setSpacing(s[0])

        bar = QHBoxLayout()
        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Filter runs (name, scene, seed, date)")
        self.filter.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.filter, 1)
        self.buttons = {
            "refresh": _button(self, "refresh-cw", "Re-read the run folder and scan new runs"),
            "import": _button(self, "file-input", "Import a CSV or Parquet log as a run"),
            "report": _button(self, "file-text", "HTML report of the selected runs", "Report"),
            "compare": _button(
                self, "git-compare", "Compare the first selected run with the second", "Compare"
            ),
        }
        self.buttons["refresh"].clicked.connect(lambda _c=False: self.refresh(scan_runs=True))
        self.buttons["import"].clicked.connect(lambda _c=False: self.import_requested.emit())
        self.buttons["report"].clicked.connect(lambda _c=False: self._report())
        self.buttons["compare"].clicked.connect(lambda _c=False: self._compare())
        for b in self.buttons.values():
            bar.addWidget(b)
        lay.addLayout(bar)

        split = QSplitter(Qt.Orientation.Vertical, self)
        self.table = QTreeWidget(split)
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(list(RUN_COLUMNS))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemDoubleClicked.connect(
            lambda item, _c: self.open_run.emit(item.data(0, DATA))
        )

        box = QWidget(split)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(s[0])
        row = QHBoxLayout()
        self.scenario_edit = QLineEdit(box)
        self.scenario_edit.setPlaceholderText(
            "Add a scenario:  fast elbow: ur5.elbow_joint.v > 2 for 0.05 s"
        )
        self.scenario_edit.returnPressed.connect(self._add_scenario)
        add = _button(box, "plus", "Add the scenario")
        add.clicked.connect(lambda _c=False: self._add_scenario())
        remove = _button(box, "minus", "Remove the selected scenario")
        remove.clicked.connect(lambda _c=False: self._remove_scenario())
        scan_b = _button(box, "scan-search", "Scan every run for every scenario", "Scan")
        scan_b.clicked.connect(lambda _c=False: self.refresh(scan_runs=True))
        self.buttons["scan"] = scan_b
        for w in (self.scenario_edit, add, remove, scan_b):
            row.addWidget(w, 1 if w is self.scenario_edit else 0)
        v.addLayout(row)
        self.message = QLabel(box)
        self.message.setProperty("role", "secondary")
        v.addWidget(self.message)
        self.scenario_list = QTreeWidget(box)
        self.scenario_list.setRootIsDecorated(False)
        self.scenario_list.setHeaderLabels(["Scenario", "Condition", "Matches"])
        self.scenario_list.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.scenario_list, 1)
        self.findings = QTreeWidget(box)
        self.findings.setHeaderLabels(["Finding", "Window [s]", "Signals"])
        self.findings.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.findings.itemClicked.connect(self._finding_clicked)
        v.addWidget(self.findings, 2)
        lay.addWidget(split, 1)
        # Lists shrink and scroll rather than push the bottom row up (the 3D view keeps its share).
        for tree in (self.table, self.scenario_list, self.findings):
            tree.setMinimumHeight(tokens.RUNS_LIST_MIN_HEIGHT)
        split.setChildrenCollapsible(False)

    # -- catalog ---------------------------------------------------------------------------
    def set_folder(self, folder: str | Path) -> None:
        self.catalog = Catalog(folder)
        try:
            self.scenarios = load_scenarios(folder)
        except (ValueError, ScenarioError, KeyError) as exc:
            self.scenarios = []
            self.message.setText(f"scenarios.json can't be read: {exc}")
        self.refresh(scan_runs=True)

    def refresh(self, scan_runs: bool = False) -> None:
        """List the runs (filtered); with `scan_runs`, scan them (cached: new runs only)."""
        if self.catalog is None:
            return
        runs = self.catalog.filter(self.filter.text())
        if scan_runs:
            self.results = scan(self.catalog, self.scenarios) if self.scenarios else []
        counts: dict[Path, int] = {}
        for r in self.results:
            counts[r.run.path] = counts.get(r.run.path, 0) + len(r.matches)
        selected = {i.data(0, DATA).path for i in self.table.selectedItems()}
        self.table.clear()
        for info in runs:
            scene = Path(info.scene).name if info.scene else "—"
            seed = "—" if info.seed is None else str(info.seed)
            cells = [
                info.name,
                scene,
                info.source,
                seed,
                f"{info.duration:.3f} s",
                info.date.replace("T", " "),
                str(counts.get(info.path, 0)),
            ]
            item = QTreeWidgetItem(self.table, cells)
            item.setData(0, DATA, info)
            item.setToolTip(0, str(info.path))
            if info.path in selected:
                item.setSelected(True)
        self._show_scenarios()
        self._show_findings()

    def runs(self) -> list[RunInfo]:
        return [
            self.table.topLevelItem(i).data(0, DATA) for i in range(self.table.topLevelItemCount())
        ]

    def selected_runs(self) -> list[RunInfo]:
        return [i.data(0, DATA) for i in self.table.selectedItems()]

    # -- scenarios ---------------------------------------------------------------------------
    def add_scenario(self, text: str) -> Scenario:
        """'name: condition for 0.1 s' (no name: the condition names it). Saved with the
        run folder; raises ScenarioError if the condition isn't valid."""
        name, sep, expr = text.partition(":")
        name, expr = (name.strip(), expr.strip()) if sep else (text.strip(), text.strip())
        sc = Scenario(name, expr)
        self.scenarios = [s for s in self.scenarios if s.name != name] + [sc]
        self._save()
        self.refresh(scan_runs=True)
        return sc

    def _add_scenario(self) -> None:
        text = self.scenario_edit.text().strip()
        if not text:
            return
        try:
            self.add_scenario(text)
        except ScenarioError as exc:
            self.message.setText(str(exc))
            return
        self.scenario_edit.clear()
        self.message.setText("")

    def _remove_scenario(self) -> None:
        items = self.scenario_list.selectedItems()
        if not items:
            return
        name = items[0].text(0)
        self.scenarios = [s for s in self.scenarios if s.name != name]
        self._save()
        self.results = [r for r in self.results if r.scenario.name != name]
        self.refresh()

    def _save(self) -> None:
        if self.catalog is not None:
            save_scenarios(self.catalog.folder, self.scenarios)

    def _show_scenarios(self) -> None:
        self.scenario_list.clear()
        for sc in self.scenarios:
            n = sum(len(r.matches) for r in self.results if r.scenario is sc)
            QTreeWidgetItem(self.scenario_list, [sc.name, sc.expression or "", str(n)])

    # -- findings (RI-03) --------------------------------------------------------------------
    def _show_findings(self) -> None:
        self.findings.clear()
        warn = QBrush(QColor(tokens.color(theme.current_theme(), "state.warning")))
        shown = {i.path for i in self.runs()}
        groups: dict[Path, QTreeWidgetItem] = {}

        def group(info: RunInfo) -> QTreeWidgetItem:
            if info.path not in groups:
                g = QTreeWidgetItem(self.findings, [info.name, "", ""])
                g.setData(0, DATA, None)
                groups[info.path] = g
            return groups[info.path]

        for f in self.extra_findings:
            self._finding_item(group(f.run), f)
        for r in self.results:
            if r.run.path not in shown:
                continue
            if r.missing:
                item = QTreeWidgetItem(
                    group(r.run),
                    [f"{r.scenario.name}: not checked", "", "needs " + ", ".join(r.missing)],
                )
                item.setForeground(0, warn)
                item.setForeground(2, warn)
                item.setData(0, DATA, None)
            for f in r.findings:
                self._finding_item(group(r.run), f)
        self.findings.expandAll()

    def _finding_item(self, parent: QTreeWidgetItem, f: Finding) -> QTreeWidgetItem:
        span = f"{f.start:.3f}" if f.end == f.start else f"{f.start:.3f} to {f.end:.3f}"
        title = f.title + (f"  ({f.detail})" if f.detail else "")
        item = QTreeWidgetItem(parent, [title, span, ", ".join(f.signals)])
        item.setData(0, DATA, f)
        item.setToolTip(0, f.describe())
        return item

    def all_findings(self) -> list[Finding]:
        out = []
        for i in range(self.findings.topLevelItemCount()):
            g = self.findings.topLevelItem(i)
            for k in range(g.childCount()):
                f = g.child(k).data(0, DATA)
                if f is not None:
                    out.append(f)
        return out

    def _finding_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        f = item.data(0, DATA)
        if f is not None:
            self.finding_clicked.emit(f)

    def show_comparison_findings(self, findings: Sequence[Finding]) -> None:
        self.extra_findings = list(findings)
        self._show_findings()

    # -- report and compare -------------------------------------------------------------------
    def _report(self) -> None:
        runs = self.selected_runs() or self.runs()[:1]
        if runs:
            self.report_requested.emit(runs)
        else:
            self.message.setText("No runs yet: run a simulation and stop it, or import a log.")

    def _compare(self) -> None:
        runs = self.selected_runs()
        if len(runs) != 2:
            self.message.setText("Select two runs: the run, then its baseline.")
            return
        self.compare_requested.emit(runs[0], runs[1])
