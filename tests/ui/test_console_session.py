"""M6 through the main window: console (SC-01), editor (SC-02), workspace (SC-03), live
parameters from the console (SC-05), data import (IO-02), and projects (IO-04).

Runs the real in-process kernel and a real sim process, headless.
"""

import textwrap

import numpy as np
import pytest
from scipy.io import savemat

from simview.ui.console.workspace import ArrayModel, preview, visible
from simview.ui.main_window import MainWindow
from tests.ui.test_scene_session import pump

CART = """
    import numpy as np
    import simview as sv

    class Cart(sv.Entity):
        state_names = ("x", "v")
        def derivative(self, t, x, u):
            return np.array([x[1], float(u[0]) if len(u) else 0.0])

    scene = sv.Scene(dt=0.01)
    scene.add_entity(Cart([0.0, 0.0], name="cart"))
    scene.params.force = 0.0

    @scene.controller()
    def push(t, state, ctx):
        return {"cart": [ctx.params.force]}
"""


@pytest.fixture
def window(qapp, settings):
    w = MainWindow(settings)
    w.show()
    yield w
    w.close_scene()
    w.close()


@pytest.fixture
def cart(tmp_path):
    path = tmp_path / "cart.py"
    path.write_text(textwrap.dedent(CART))
    return path


def run(qapp, w, code, until):
    w.console.run_code(code)
    pump(qapp, until)


def ready(w):
    return w.history is not None and w.client is not None and w.client.frame() is not None


# -- SC-01: the console ---------------------------------------------------------------------
def test_console_runs_code_with_simview_and_sim(qapp, window):
    run(
        qapp,
        window,
        "v = sv.__version__\nnames = dir(sim)",
        lambda: "v" in window.console.namespace,
    )
    import simview

    assert window.console.namespace["v"] == simview.__version__
    assert "params" in window.console.namespace["names"]
    text = window.console.text()
    assert "In [" in text and "`sim` is the running simulation" in text
    assert "Tip:" not in text
    assert repr(window.console.namespace["sim"]) == "<sim: no scene running>"


def test_console_sees_the_running_scene(qapp, window, cart):
    window.load_scene(cart)
    pump(qapp, lambda: ready(window))
    window.client.step(10)
    pump(qapp, lambda: window.client.frame().tick == 10)
    code = "s = sim.state('cart')\nt = sim.t\nents = sim.entities\nlocal = sim.scene['cart'].x0"
    run(qapp, window, code, lambda: "local" in window.console.namespace)
    ns = window.console.namespace
    assert ns["ents"] == ["cart"] and ns["t"] == pytest.approx(0.1)
    assert set(ns["s"]) == {"x", "v"}
    pump(qapp, lambda: window.history.n == 11)
    run(qapp, window, "d = sim.data()\nf = sim.data('params.force')", lambda: "f" in ns)
    assert len(ns["d"]["t"]) == 11 and len(ns["f"]) == 11
    assert "cart.py" in repr(ns["sim"])


def test_sim_output_starts_on_its_own_line(qapp, window):
    window.console.run_code("print('partial', end='')")
    pump(qapp, lambda: "partial" in window.console.text())
    window.console.write("from the sim\n")
    pump(qapp, lambda: "from the sim" in window.console.text())
    assert "partialfrom the sim" not in window.console.text()


def test_code_panels_use_the_mono_font(qapp, window):
    from simview.ui.theme import tokens

    for widget in (window.editor.editor, window.console._control):
        widget.ensurePolished()
        assert widget.font().family() == tokens.FONT_MONO


def test_sim_errors_reach_the_console(qapp, window, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("raise ValueError('broken scene')\n")
    window.load_scene(bad)
    pump(qapp, lambda: "ValueError: broken scene" in window.console.text())


# -- SC-05: live parameters from the console (M6 done-when) ----------------------------------
def test_sim_params_change_takes_effect_on_the_next_tick(qapp, window, cart):
    window.load_scene(cart)
    pump(qapp, lambda: ready(window))
    window.client.step(5)
    pump(qapp, lambda: window.client.frame().tick == 5)
    run(
        qapp,
        window,
        "sim.params.force = 4.0\np = sim.params.force",
        lambda: "p" in window.console.namespace,
    )
    assert window.console.namespace["p"] == 4.0
    pump(qapp, lambda: window.sim_handle._param_values == {"force": 4.0})
    window.client.step(1)
    pump(qapp, lambda: window.client.frame().tick == 6)
    assert window.client.frame().states["cart"][1] == pytest.approx(4.0 * 0.01)
    pump(qapp, lambda: window.history.n == 7)
    force = window.history.signal("params.force")
    assert force[5] == 0.0 and force[6] == 4.0  # logged from the tick it took effect


def test_unknown_params_are_errors_in_the_console(qapp, window, cart):
    window.load_scene(cart)
    pump(qapp, lambda: ready(window))
    run(
        qapp,
        window,
        "sim.params.forse = 1.0",
        lambda: "declare it in the scene file" in window.console.text(),
    )


# -- SC-02: the editor ----------------------------------------------------------------------
def test_editor_highlights_and_numbers_lines(qapp, window):
    ed = window.editor.editor
    ed.setPlainText('def f(x):\n    """doc\n    more"""\n    return x + 1  # one\n')
    assert ed.line_numbers() == [1, 2, 3, 4, 5]
    assert ed.gutter_width() > 0
    qapp.processEvents()
    first = ed.document().firstBlock()
    formats = first.layout().formats()
    assert formats and any(f.format.fontWeight() > 400 for f in formats)  # `def` is bold
    third = ed.document().findBlockByNumber(2)
    assert third.previous().userState() == 1  # line 2 ends inside the docstring
    assert third.userState() == 0


def test_run_selection_and_run_file(qapp, window, tmp_path):
    panel = window.editor
    panel.editor.setPlainText("a = 1\n    b = 2\nc = 3\n")
    cursor = panel.editor.textCursor()
    doc = panel.editor.document()
    cursor.setPosition(doc.findBlockByNumber(1).position())
    panel.editor.setTextCursor(cursor)  # no selection: the current line, dedented
    assert panel.editor.selected_code() == "b = 2"
    panel.run_selection()
    pump(qapp, lambda: window.console.namespace.get("b") == 2)
    assert "a" not in window.console.namespace

    script = tmp_path / "script.py"
    script.write_text("ran = np.arange(3) * 2\nfrom_sim = repr(sim)\n")
    panel.open(script)
    panel.editor.appendPlainText("extra = 7")
    panel.run()  # saves, then %run -i: it sees sim and np, and leaves its variables
    pump(qapp, lambda: window.console.namespace.get("extra") == 7)
    assert "extra = 7" in script.read_text()
    np.testing.assert_array_equal(window.console.namespace["ran"], [0, 2, 4])
    assert window.console.namespace["from_sim"].startswith("<sim")


# -- SC-03: the workspace browser -----------------------------------------------------------
def test_workspace_lists_variables(qapp, window):
    code = "m = np.eye(3)\nscalar = 2.5\nlabel = 'hi'\n_private = 1\nimport math"
    run(qapp, window, code, lambda: "m" in window.workspace.names())
    names = window.workspace.names()
    assert {"m", "scalar", "label"} <= set(names)
    assert not {"_private", "math", "sim", "sv", "np"} & set(names)
    m = window.workspace.row("m")
    assert (m["Type"], m["Shape"]) == ("ndarray float64", "3×3")
    assert m["Value"].startswith("[[1.")
    assert window.workspace.row("scalar")["Value"] == "2.5"
    assert window.workspace_stack.currentWidget() is window.workspace


def test_double_click_opens_an_array_table(qapp, window):
    run(
        qapp,
        window,
        "grid = np.arange(12.0).reshape(3, 4)",
        lambda: "grid" in window.workspace.names(),
    )
    items = window.workspace.findItems("grid", __import__("qtpy").QtCore.Qt.MatchFlag.MatchExactly)
    window.workspace.itemDoubleClicked.emit(items[0], 0)
    viewer = window.array_viewers[-1]
    model = viewer.model
    assert (model.rowCount(), model.columnCount()) == (3, 4)
    assert model.data(model.index(2, 3)) == "11"
    viewer.close()


def test_array_model_shapes_and_previews():
    rec = np.zeros(3, dtype=[("t", float), ("x", float)])
    m = ArrayModel(rec)
    assert (
        m.columnCount() == 2
        and m.headerData(1, __import__("qtpy").QtCore.Qt.Orientation.Horizontal) == "x"
    )
    assert ArrayModel(np.float64(3.0)).rowCount() == 1
    assert ArrayModel(np.zeros((2, 3, 4))).columnCount() == 12
    assert preview(rec) == "[t, x]"
    assert len(preview("x" * 500)) <= 60
    assert visible({"a": 1, "np": np, "_b": 2}, {}) == ["a"]


# -- IO-02: importing data ------------------------------------------------------------------
def test_import_csv_and_mat_into_the_workspace(qapp, window, tmp_path):
    csv = tmp_path / "flight log.csv"
    csv.write_text("t,alt,mode\n0,1.5,hover\n0.1,1.7,climb\n")
    assert window.import_data(csv) == ["flight_log"]
    data = window.console.namespace["flight_log"]
    np.testing.assert_array_equal(data["alt"], [1.5, 1.7])
    assert list(data["mode"]) == ["hover", "climb"]
    mat = tmp_path / "gains.mat"
    savemat(mat, {"K": np.array([[1.0, 2.0]]), "name": "lqr"})
    assert set(window.import_data(mat)) == {"K", "name"}
    qapp.processEvents()
    assert {"flight_log", "K", "name"} <= set(window.workspace.names())
    assert window.import_data(tmp_path / "missing.csv") == []


# -- IO-04: projects (M6 done-when: a project round-trips save -> load) ----------------------
def test_project_round_trips_save_and_load(qapp, settings, cart, tmp_path, monkeypatch):
    monkeypatch.delenv("SIMVIEW_RUNS", raising=False)  # runs go to the project
    a = MainWindow(settings)
    a.show()
    a.load_scene(cart)
    pump(qapp, lambda: ready(a))
    a.editor.editor.setPlainText("answer = 42\n")
    project = a.new_project(tmp_path / "demo")
    assert project.path.name == "demo.svproj"
    assert project.scene == "scenes/cart.py" and project.script == "scripts/script.py"
    a.client.step(20)
    pump(qapp, lambda: a.history is not None and a.history.n == 21)
    a.stop()  # saves the run into the project's runs/
    runs = project.files("runs", "*.parquet")
    assert len(runs) == 1
    a.close_scene()
    a.close()

    b = MainWindow(settings, str(project.path))
    b.show()
    opened = b.open_project(project.path)
    assert opened.name == "demo"
    assert "demo" in b.windowTitle()
    assert b.editor.editor.toPlainText() == "answer = 42\n"
    assert b.scene_path == project.path / "scenes" / "cart.py"
    pump(qapp, lambda: ready(b))
    assert b.runs_folder() == project.runs_dir
    pump(qapp, lambda: len(b.runs.catalog.runs()) == 1 if b.runs.catalog else False)
    b.close_scene()
    b.close()


def test_save_without_a_project_saves_the_script(qapp, window, tmp_path):
    script = tmp_path / "s.py"
    script.write_text("x = 1\n")
    window.editor.open(script)
    window.editor.editor.setPlainText("x = 2\n")
    window.actions_.get("file.save").trigger()
    assert script.read_text() == "x = 2\n" and window.project is None
