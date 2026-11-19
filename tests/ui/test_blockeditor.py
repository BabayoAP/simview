"""M7 block editor (BD-01, BD-05..BD-08, DS-10): the document, the canvas, quick-add, the
parameter panel, subsystems, and the editor inside the main window."""

import json
import time
from pathlib import Path

import pytest
from qtpy.QtCore import QPointF

from simview.blocks import Diagram
from simview.ui.blockeditor import BlockEditor
from simview.ui.blockeditor.canvas import kind_of, route, snap
from simview.ui.blockeditor.document import Document, parse_value
from simview.ui.blockeditor.palette import entries, matches
from simview.ui.main_window import MainWindow
from simview.ui.theme import tokens
from simview.ui.theme.contrast import contrast_ratio

ROOT = Path(__file__).resolve().parents[2]
DRONE = ROOT / "examples" / "drone_altitude"


def pump(qapp, until, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


@pytest.fixture
def editor(qapp):
    e = BlockEditor()
    e.resize(1000, 600)
    e.show()
    yield e
    e.close()
    e.deleteLater()


def loop_diagram():
    """ref -> sum -> gain -> back into sum: an algebraic loop (sum and gain)."""
    d = Diagram("loop")
    d.add("Constant", "ref", (0, 0))
    d.add("Sum", "sum", (160, 0), signs="+-")
    d.add("Gain", "gain", (320, 0), gain=2.0)
    d.connect("ref:0", "sum:0")
    d.connect("sum:0", "gain:0")
    d.connect("gain:0", "sum:1")
    return d


# -- the document: edits, undo, files ----------------------------------------------------------
def test_edits_undo_and_redo(qapp):
    doc = Document()
    assert doc.is_blank and not doc.can_undo
    c = doc.add("Constant", (0, 0))
    g = doc.add("Gain", (160, 0))
    doc.connect((c, 0), (g, 0))
    doc.set_param(g, "gain", 3.0)
    doc.move({g: (200.0, 16.0)})
    assert doc.current.blocks[g].params == {"gain": 3.0} and doc.modified
    doc.undo()  # the move
    assert doc.current.blocks[g].pos == (160.0, 0.0)
    doc.undo()  # the parameter
    assert doc.current.blocks[g].params == {}
    doc.redo()
    assert doc.current.blocks[g].params == {"gain": 3.0}
    doc.add("Sine", (0, 80))  # a new edit drops the redo step
    assert not doc.can_redo
    for _ in range(10):
        doc.undo()
    assert doc.current.blocks == {} and not doc.modified


def test_connecting_a_used_input_replaces_its_wire(qapp):
    doc = Document()
    a, b, g = doc.add("Constant", (0, 0)), doc.add("Sine", (0, 80)), doc.add("Gain", (160, 0))
    doc.connect((a, 0), (g, 0))
    doc.connect((b, 0), (g, 0))
    assert [(w.src, w.dst) for w in doc.current.wires] == [(b, g)]


def test_save_writes_an_svd_and_clears_modified(qapp, tmp_path):
    doc = Document()
    doc.add("Constant", (0, 0))
    path = doc.save(tmp_path / "ctrl")
    assert path.name == "ctrl.svd" and not doc.modified
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == "ctrl" and data["blocks"][0]["type"] == "Constant"
    doc.open(path)
    assert list(doc.current.blocks) == ["constant1"] and doc.path == path


def test_parameter_text_parsing():
    assert parse_value("2.5") == 2.5
    assert parse_value("[1, 0]") == [1, 0]
    assert parse_value("(1, 2)") == [1, 2] or parse_value("(1, 2)") == (1, 2)
    assert parse_value('"drone"') == "drone"
    assert parse_value("drone") == "drone"  # plain text needs no quotes
    assert parse_value("+-") == "+-"
    assert parse_value("true") is True


# -- BD-05 in the editor: problems on the offending blocks ---------------------------------------
def test_algebraic_loop_outlines_every_block_in_it(qapp, editor, tmp_path):
    path = loop_diagram().save(tmp_path / "loop.svd")
    editor.open(path)
    items = editor.view.blocks
    assert items["sum"].issues and items["gain"].issues  # red outline (§7.7)
    assert not items["ref"].issues
    assert "algebraic loop" in items["sum"].error.toPlainText()  # the inline message
    assert editor.problems.text() == "2 problems"


def test_problems_clear_when_fixed_and_unconnected_inputs_show(qapp, editor):
    g = editor.add_block("Gain", (0, 0))
    assert "input u is not connected" in editor.view.blocks[g].issues[0]
    c = editor.add_block("Constant", (-160, 0))
    editor.doc.connect((c, 0), (g, 0))
    assert editor.doc.issues == [] and editor.view.blocks[g].issues == []
    assert editor.problems.text() == "No problems"


def test_entity_blocks_check_against_the_scene_entities(qapp, editor):
    s = editor.add_block("EntityState", (0, 0))
    editor.doc.set_param(s, "entity", "drone")
    assert "no entity 'drone'" in editor.doc.issues_for(s)[0]
    editor.set_entities({"drone": ("z", "vz")})
    assert editor.doc.issues_for(s) == []
    assert editor.view.blocks[s].outputs == ["z", "vz"]  # one port per state (BD-04)


# -- the canvas (BD-01, DS-10) -------------------------------------------------------------------
def test_wires_are_orthogonal():
    def axis_aligned(points):
        return all(
            a.x() == b.x() or a.y() == b.y() for a, b in zip(points, points[1:], strict=False)
        )

    fwd = route(QPointF(0, 0), QPointF(200, 64), below=100)
    assert len(fwd) == 4 and axis_aligned(fwd)
    back = route(QPointF(200, 0), QPointF(0, 40), below=120)  # a feedback wire
    assert axis_aligned(back) and max(p.y() for p in back) == 120
    assert route(QPointF(0, 10), QPointF(50, 10), below=0) == [QPointF(0, 10), QPointF(50, 10)]


def test_blocks_snap_to_the_grid(qapp, editor):
    g = editor.add_block("Gain", (0, 0))
    item = editor.view.blocks[g]
    item.setPos(QPointF(13, 21))
    assert (item.pos().x(), item.pos().y()) == (16, 24)
    assert snap(3) == 0 and snap(5) == tokens.GRID_SNAP


def test_ports_are_colored_by_signal_type(qapp, editor):
    assert (kind_of(()), kind_of((3,)), kind_of((2, 2)), kind_of(None)) == (
        "scalar",
        "vector",
        "matrix",
        None,
    )
    v = editor.add_block("Constant", (0, 0))
    editor.doc.set_param(v, "value", [1.0, 2.0, 3.0])
    m = editor.add_block("Constant", (0, 80))
    editor.doc.set_param(m, "value", [[1.0, 0.0], [0.0, 1.0]])
    assert editor.view.blocks[v].out_ports[0].kind == "vector"
    assert editor.view.blocks[m].out_ports[0].kind == "matrix"


def test_drag_between_ports_connects(qapp, editor):
    c = editor.add_block("Constant", (0, 0))
    g = editor.add_block("Gain", (160, 0))
    out, inp = editor.view.blocks[c].out_ports[0], editor.view.blocks[g].in_ports[0]
    assert not editor.view.finish_connect(out, editor.view.blocks[c].out_ports[0])
    assert editor.view.finish_connect(inp, out)  # dragged from the input end works too
    assert [(w.src, w.dst) for w in editor.doc.current.wires] == [(c, g)]
    assert len(editor.view.wire_items) == 1


def test_delete_removes_blocks_and_their_wires(qapp, editor):
    c = editor.add_block("Constant", (0, 0))
    g = editor.add_block("Gain", (160, 0))
    editor.doc.connect((c, 0), (g, 0))
    editor.view.select([g])
    editor.delete_selection()
    assert list(editor.doc.current.blocks) == [c] and editor.doc.current.wires == []
    editor.doc.undo()
    assert g in editor.doc.current.blocks and len(editor.doc.current.wires) == 1


def test_wire_hover_shows_the_live_value(qapp, editor):
    c = editor.add_block("Constant", (0, 0))
    g = editor.add_block("Gain", (160, 0))
    editor.doc.connect((c, 0), (g, 0))
    wire = editor.view.wire_items[0]
    assert "run the sim" in wire.tooltip_text()
    editor.value_lookup = lambda block, port: "4.5" if (block, port) == (c, "y") else None
    editor.redraw()
    assert editor.view.wire_items[0].tooltip_text() == f"{c}.y = 4.5"


# -- quick-add (§7.7) ----------------------------------------------------------------------------
def test_quick_add_searches_the_library_in_category_order(qapp, editor):
    types = [e[0] for e in entries()]
    assert types.index("Constant") < types.index("Gain") < types.index("Integrator")
    assert types[-1] == "Subsystem"
    assert matches("gain", ("Gain", "Math", "")) and not matches("gain", ("Sine", "Sources", ""))
    editor.quick.open_at(editor.mapToGlobal(editor.rect().center()))
    editor.quick.search.setText("transfer")
    assert editor.quick.visible_types() == ["TransferFunction"]
    editor._add_at = QPointF(48, 32)
    editor.quick._choose()
    block = editor.doc.current.blocks["transferfunction1"]
    assert block.pos == (48.0, 32.0)


# -- the parameter panel -------------------------------------------------------------------------
def test_parameter_panel_edits_and_renames(qapp, editor):
    g = editor.add_block("Gain", (0, 0))
    editor.view.select([g])
    panel = editor.params
    assert panel.block is not None and panel.block.id == g
    field = panel.fields["gain"]
    field.setText("2.5")
    field.editingFinished.emit()
    assert editor.doc.current.blocks[g].params["gain"] == 2.5
    field = editor.params.fields["gain"]
    field.setText("2.5")  # unchanged: no extra undo step
    before = editor.doc._at
    field.editingFinished.emit()
    assert editor.doc._at == before
    name = editor.params.fields["__name__"]
    name.setText("k")
    name.editingFinished.emit()
    assert "k" in editor.doc.current.blocks and editor.params.block.id == "k"


# -- subsystems (BD-07) --------------------------------------------------------------------------
def test_group_open_and_ungroup(qapp, editor, tmp_path):
    editor.open(loop_diagram().save(tmp_path / "loop.svd"))
    editor.view.select(["sum", "gain"])
    editor.group()
    sub = editor.view.selected_blocks()
    assert sub == ["subsystem1"]
    assert editor.view.blocks["subsystem1"].issues  # the loop is reported on the subsystem
    editor.doc.enter("subsystem1")
    assert set(editor.view.blocks) >= {"sum", "gain"} and editor.doc.level == ["subsystem1"]
    assert "subsystem1" in editor.crumbs.text()
    editor.doc.up()
    editor.view.select(["subsystem1"])
    editor.ungroup()
    assert set(editor.doc.current.blocks) == {"ref", "sum", "gain"}


# -- theme ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("bg", ["bg.panel", "bg.elevated"])
def test_category_and_port_colors_contrast(theme, bg):
    """DS-10: category strips and port colors are UI components (WCAG 1.4.11, 3:1)."""
    surface = tokens.COLORS[theme][bg]
    for table in (tokens.BLOCK_CATEGORY_COLORS, tokens.PORT_COLORS):
        for name, value in table[theme].items():
            assert contrast_ratio(value, surface) >= 3.0, name
    from simview.blocks.library import CATEGORIES

    assert set(CATEGORIES) < set(tokens.BLOCK_CATEGORY_COLORS[theme])


# -- in the main window (BD-04, BD-08) -----------------------------------------------------------
@pytest.fixture
def window(qapp, settings):
    w = MainWindow(settings)
    w.show()
    yield w
    w.close_scene()
    w.close()


def test_scene_opens_its_diagram_docks_scopes_and_shows_wire_values(qapp, window):
    window.load_scene(DRONE / "blocks.py")
    pump(qapp, lambda: window.history is not None and window.scope_plots)
    ed = window.block_editor
    assert (
        ed.path == (DRONE / "altitude.svd").resolve()
        or ed.path.resolve() == (DRONE / "altitude.svd").resolve()
    )
    assert ed.doc.issues == []  # entity blocks bound to the scene's drone
    (scope,) = window.scope_plots  # BD-08: the Scope block's plot, docked in the plot panel
    assert scope.title.text() == "altitude.altitude" and scope in window.plots.plots
    assert len(scope.names) == 2
    window.show_central(1)
    assert window.centralWidget().currentWidget() is ed
    window.run()
    pump(qapp, lambda: window.history.n > 50)
    window.pause()
    value = window.diagram_value("pid", "y")
    assert value is not None and float(value) == float(value)
    wire = next(w for w in ed.view.wire_items if w.src.block.block.id == "pid")
    assert wire.tooltip_text().startswith("pid.y = ")


def test_project_keeps_the_open_diagram(qapp, window, tmp_path):
    window.new_diagram()
    window.block_editor.add_block("Constant", (0, 0))
    p = window.new_project(tmp_path / "demo")
    assert p.diagram == "diagrams/diagram.svd"
    assert (p.path / "diagrams" / "diagram.svd").is_file()
    other = MainWindow(window.settings)
    try:
        other.open_project(p.path)
        assert list(other.block_editor.doc.current.blocks) == ["constant1"]
    finally:
        other.close()
