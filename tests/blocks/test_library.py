"""BD-02: each block in the core library, through small diagrams."""

import numpy as np
import pytest
from scipy.signal import lti, step

import simview as sv
from simview.blocks import Diagram, compile_diagram
from simview.blocks.library import BLOCKS, CATEGORIES, BlockError, block_class


def run(diagram, duration=1.0, dt=1e-3, rate=None, entities=(), tmp=None, **kw):
    scene = sv.Scene(dt=dt)
    for e in entities:
        scene.add_entity(e)
    scene.add_diagram(diagram, rate=rate, **kw)
    return sv.run(scene, duration=duration, out=tmp)


def chain(*specs, wires=None):
    d = Diagram("d")
    for bid, typ, params in specs:
        d.add(typ, bid, **params)
    for a, b in wires or []:
        d.connect(a, b)
    return d


def test_library_is_the_prd_list():
    expected = {
        "Constant", "Step", "Sine", "Gain", "Sum", "Product", "Integrator", "Derivative",
        "TransferFunction", "StateSpace", "PID", "Saturation", "Delay", "Mux", "Demux",
        "Scope", "ToWorkspace", "EntityState", "EntityInput", "PythonFunction",
        "Inport", "Outport",
    }  # fmt: skip
    assert set(BLOCKS) == expected
    assert {c.category for c in BLOCKS.values()} <= set(CATEGORIES)
    with pytest.raises(BlockError, match="unknown block type"):
        block_class("Nope")
    with pytest.raises(BlockError, match="unknown parameter"):
        block_class("Gain")("g", {"gian": 2})


def test_sources_math_and_signal_logging(tmp_path):
    d = chain(
        ("c", "Constant", {"value": [1.0, 2.0]}),
        ("st", "Step", {"time": 0.5, "before": 0.0, "after": 3.0}),
        ("s", "Sine", {"amplitude": 2.0, "frequency": 3.0, "bias": 1.0}),
        ("g", "Gain", {"gain": 2.0}),
        ("m", "Gain", {"gain": [[1.0, 1.0]]}),
        ("sum", "Sum", {"signs": "+-"}),
        ("p", "Product", {"ops": "*/"}),
        ("sat", "Saturation", {"lower": -1.0, "upper": 1.0}),
        ("mux", "Mux", {"inputs": 2}),
        ("dmx", "Demux", {"outputs": 3}),
        ("sc", "Scope", {"inputs": 1}),
        wires=[("c:0", "g:0"), ("c:0", "m:0"), ("st:0", "sum:0"), ("s:0", "sum:1"),
               ("st:0", "p:0"), ("s:0", "p:1"), ("s:0", "sat:0"), ("m:0", "mux:0"),
               ("g:0", "mux:1"), ("mux:0", "dmx:0"), ("sum:0", "sc:0")],
    )  # fmt: skip
    r = run(d, duration=1.0, tmp=tmp_path / "r.parquet")
    t = r["t"]
    sine = 2.0 * np.sin(3.0 * t) + 1.0
    step_ = np.where(t >= 0.5 - 1e-12, 3.0, 0.0)
    assert r["d.g.y[1]"][0] == 4.0 and r["d.m.y[0]"][0] == 3.0
    np.testing.assert_allclose(r["d.s.y"], sine, atol=1e-12)
    np.testing.assert_allclose(r["d.sum.y"], step_ - sine, atol=1e-12)
    np.testing.assert_allclose(r["d.p.y"], step_ / sine, atol=1e-12)
    np.testing.assert_allclose(r["d.sat.y"], np.clip(sine, -1, 1), atol=1e-12)
    assert [r[f"d.mux.y[{k}]"][0] for k in range(3)] == [3.0, 2.0, 4.0]
    assert r["d.dmx.y2"][0] == 2.0


def test_integrator_and_transfer_function_match_analytic(tmp_path):
    d = chain(
        ("one", "Constant", {"value": 1.0}),
        ("cos", "Sine", {"phase": np.pi / 2}),
        ("i", "Integrator", {"initial": 0.5}),
        ("tf", "TransferFunction", {"num": [1.0], "den": [1.0, 2.0, 1.0]}),
        wires=[("cos:0", "i:0"), ("one:0", "tf:0")],
    )
    r = run(d, duration=3.0, dt=1e-3, tmp=tmp_path / "r.parquet")
    np.testing.assert_allclose(r["d.i.y"], 0.5 + np.sin(r["t"]), atol=1e-9)
    _, y = step(lti([1.0], [1.0, 2.0, 1.0]), T=r["t"])
    np.testing.assert_allclose(r["d.tf.y"], y, atol=1e-6)


def test_state_space_feedthrough_delay_and_derivative(tmp_path):
    d = chain(
        ("ramp", "Sine", {"amplitude": 1.0, "frequency": 1.0}),
        ("ss", "StateSpace", {"A": [[0.0]], "B": [[1.0]], "C": [[0.0]], "D": [[2.0]]}),
        ("z", "Delay", {"samples": 2, "initial": -1.0}),
        ("dv", "Derivative", {}),
        wires=[("ramp:0", "ss:0"), ("ramp:0", "z:0"), ("ramp:0", "dv:0")],
    )
    r = run(d, duration=0.1, dt=1e-2, tmp=tmp_path / "r.parquet")
    s = np.sin(r["t"])
    np.testing.assert_allclose(r["d.ss.y"], 2 * s, atol=1e-12)  # D u
    assert list(r["d.z.y"][:2]) == [-1.0, -1.0]
    np.testing.assert_allclose(r["d.z.y"][2:], s[:-2], atol=1e-12)
    assert r["d.dv.y"][0] == 0.0
    np.testing.assert_allclose(r["d.dv.y"][1:], np.diff(s) / 1e-2, atol=1e-12)


def test_pid_anti_windup_and_rate(tmp_path):
    d = chain(
        ("e", "Constant", {"value": 1.0}),
        ("pid", "PID", {"kp": 1.0, "ki": 10.0, "upper": 2.0}),
        wires=[("e:0", "pid:0")],
    )
    r = run(d, duration=1.0, dt=1e-3, rate=100, tmp=tmp_path / "r.parquet")
    y = r["d.pid.y"]
    assert y.max() == 2.0  # saturated
    assert y[0] == pytest.approx(1.0 + 10.0 * 0.01)  # first sample integrates e * Ts
    assert np.all(y[1:10] == y[0])  # held between 100 Hz samples (dt = 1 ms)


def test_entity_blocks_read_and_write(tmp_path):
    class Cart(sv.Entity):
        state_names = ("x", "v")

        def derivative(self, t, x, u):
            return np.array([x[1], float(u[0]) if len(u) else 0.0])

    d = chain(
        ("read", "EntityState", {"entity": "cart"}),
        ("k", "Gain", {"gain": -4.0}),
        ("write", "EntityInput", {"entity": "cart"}),
        wires=[("read:0", "k:0"), ("k:0", "write:0")],
    )
    r = run(d, duration=2.0, entities=[Cart([1.0, 0.0], name="cart")], tmp=tmp_path / "r.parquet")
    assert "d.read.v" in r.columns  # one output per state, named after it
    np.testing.assert_allclose(r["cart.x"], np.cos(2.0 * r["t"]), atol=5e-3)  # input held per tick


def test_python_function_block_ports_from_hints(tmp_path):
    from typing import NamedTuple

    class Polar(NamedTuple):
        r: float
        angle: float

    def polar(x: float, y: float) -> Polar:
        return Polar(float(np.hypot(x, y)), float(np.arctan2(y, x)))

    def clock(t: float, gain: float) -> float:
        return gain * t

    d = chain(
        ("x", "Constant", {"value": 3.0}),
        ("y", "Constant", {"value": 4.0}),
        ("f", "PythonFunction", {"function": polar}),
        ("c", "PythonFunction", {"function": clock}),
        wires=[("x:0", "f:0"), ("y:0", "f:1"), ("x:0", "c:0")],
    )
    impl = block_class("PythonFunction")("f", {"function": polar})
    assert impl.input_names() == ["x", "y"] and impl.output_names() == ["r", "angle"]
    r = run(d, duration=0.01, tmp=tmp_path / "r.parquet")
    assert r["d.f.r"][0] == 5.0
    np.testing.assert_allclose(r["d.c.y"], 3.0 * r["t"])


def test_python_function_from_a_file_next_to_the_diagram(tmp_path):
    (tmp_path / "fns.py").write_text("def double(u: float) -> float:\n    return 2 * u\n")
    d = chain(
        ("c", "Constant", {"value": 2.5}),
        ("f", "PythonFunction", {"function": "fns.py:double"}),
        wires=[("c:0", "f:0")],
    )
    path = d.save(tmp_path / "d.svd")
    compiled = compile_diagram(Diagram.load(path))
    outs = compiled.outputs(0.0, compiled.x0)
    assert float(outs[compiled.index("f")][0]) == 5.0
