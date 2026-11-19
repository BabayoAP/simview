"""BD-06 (JSON files) and BD-07 (subsystems)."""

import json

import numpy as np
import pytest

import simview as sv
from simview.blocks import Diagram, compile_diagram


def loop():
    d = Diagram("loop")
    d.add("Step", "ref", (0, 0), time=0.0)
    d.add("Sum", "err", (100, 0), signs="+-")
    d.add("Gain", "k", (200, 0), gain=5.0)
    d.add("Integrator", "plant", (300, 0))
    d.connect("ref:0", "err:0")
    d.connect("err:0", "k:0")
    d.connect("k:0", "plant:0")
    d.connect("plant:0", "err:1")
    return d


def test_svd_is_readable_sorted_json_and_round_trips(tmp_path):
    d = loop()
    path = d.save(tmp_path / "loop")
    assert path.suffix == ".svd"
    text = path.read_text()
    data = json.loads(text)
    assert data["format"] == 1 and data["name"] == "loop"
    assert {"from": "plant:0", "to": "err:1"} in data["wires"]
    assert text == json.dumps(data, indent=2, sort_keys=True) + "\n"  # stable for git diffs
    again = Diagram.load(path)
    assert again.dumps() == text
    d.blocks["k"].params["gain"] = 6.0
    diff = [a for a, b in zip(d.dumps().splitlines(), text.splitlines(), strict=True) if a != b]
    assert len(diff) == 1 and "6.0" in diff[0]  # one edit, one changed line


def test_editing_rules():
    d = loop()
    with pytest.raises(ValueError, match="already has a wire"):
        d.connect("ref:0", "err:1")
    with pytest.raises(ValueError, match="already exists"):
        d.add("Gain", "k")
    assert d.add("Gain").id == "gain1"
    d.rename("k", "kp")
    assert any(w.src == "kp" for w in d.wires)
    d.remove("kp")
    assert all("kp" not in (w.src, w.dst) for w in d.wires)


def test_group_into_a_subsystem_keeps_behavior(tmp_path):
    flat = loop()
    grouped = loop()
    sub = grouped.group(["err", "k"], "ctrl")
    assert set(grouped.blocks) == {"ref", "plant", "ctrl"}
    assert sub.ports() == (["in1", "in2"], ["out1"])
    assert {b.type for b in sub.diagram.blocks.values()} >= {"Inport", "Outport", "Sum", "Gain"}
    path = grouped.save(tmp_path / "g.svd")
    grouped = Diagram.load(path)  # nested diagrams survive the file
    results = []
    for d, out in ((flat, "f"), (grouped, "g")):
        scene = sv.Scene(dt=1e-3)
        scene.add_diagram(d)
        results.append(sv.run(scene, 1.0, out=tmp_path / f"{out}.parquet"))
    np.testing.assert_array_equal(results[0]["loop.plant.y"], results[1]["loop.plant.y"])
    assert "loop.ctrl/k.y" in results[1].columns  # inner blocks log under their path
    # and back
    grouped.ungroup("ctrl")
    assert set(grouped.blocks) == set(flat.blocks)
    c = compile_diagram(grouped)
    assert len(c.nodes) == 4


def test_nested_subsystems_compile():
    d = loop()
    d.group(["err", "k"], "ctrl")
    d.group(["ctrl"], "outer")
    c = compile_diagram(d)
    assert {n.path for n in c.nodes} == {"ref", "plant", "outer/ctrl/err", "outer/ctrl/k"}
