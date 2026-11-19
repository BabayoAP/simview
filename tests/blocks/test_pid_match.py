"""M7 done-when: a PID block diagram controlling a drone's altitude matches the same
controller written as a script within 1e-9."""

from pathlib import Path

import numpy as np

import simview as sv
from simview.runner.headless import load_scene

EX = Path(__file__).resolve().parents[2] / "examples" / "drone_altitude"


def test_diagram_matches_the_script_within_1e_9(tmp_path):
    script = sv.run(load_scene(EX / "script.py"), duration=5.0, out=tmp_path / "s.parquet")
    blocks = sv.run(load_scene(EX / "blocks.py"), duration=5.0, out=tmp_path / "b.parquet")
    for col in ("drone.z", "drone.vz"):
        assert np.max(np.abs(script[col] - blocks[col])) <= 1e-9
    z = blocks["drone.z"]
    assert abs(z[-1] - 2.0) < 0.1 and z.max() > 1.5  # it climbs to the target
    # Every block output is logged (SE-06), and To Workspace reads back (BD-02).
    thrust = blocks["altitude.thrust.y"]
    assert len(thrust) == len(z) and thrust[0] > 0
    ws = blocks.workspace()
    np.testing.assert_array_equal(ws["thrust"]["value"], thrust)
    np.testing.assert_array_equal(ws["thrust"]["t"], blocks["t"])
