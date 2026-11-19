"""SE-05 headless runs, SE-06 Parquet logging, SE-07/NF-06 determinism, SC-04 scene files."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from simview import Scene, run
from simview.cli import main as cli_main
from simview.runner.headless import load_scene

ROOT = Path(__file__).resolve().parents[2]
BALL = ROOT / "examples" / "bouncing_ball.py"


def ball_scene(seed=42):
    scene = load_scene(BALL)
    scene.seed = seed
    return scene


def test_log_has_every_state_and_channel_each_tick(tmp_path):
    result = run(ball_scene(), 2.0, out=tmp_path / "ball.parquet")
    table = pq.read_table(result.path)
    assert table.schema.names == ["t", "tick", "ball.h", "ball.v", "h_measured"]
    assert table.num_rows == 2001  # tick 0 plus 2000 steps
    assert result["tick"].tolist() == list(range(2001))
    assert result["t"][-1] == pytest.approx(2.0)
    meta = json.loads(table.schema.metadata[b"simview"])
    assert meta == {
        "dt": 0.001,
        "duration": 2.0,
        "seed": 42,
        "version": "0.1.0",
        "source": "sim",  # RI-01 catalog fields (M5b); the date and scene are in the sidecar
        "params": {},
        "to_workspace": {},
        "units": {},
    }


def test_bouncing_ball_physics(tmp_path):
    result = run(ball_scene(), 5.0, out=tmp_path / "ball.parquet")
    t, h = result["t"], result["ball.h"]
    # Free fall before first contact matches h0 - g t^2 / 2.
    before = t < 0.45
    assert np.allclose(h[before], 1.0 - 9.81 * t[before] ** 2 / 2, atol=1e-10)
    # Each bounce peaks lower; restitution from the damping ratio is about 0.73 (e^2 ~ 0.54).
    peaks = [h[i] for i in range(1, len(h) - 1) if h[i - 1] < h[i] >= h[i + 1] and h[i] > 0.01]
    assert len(peaks) >= 4
    ratios = np.array(peaks[1:4]) / np.array(peaks[0:3])
    assert np.all((ratios > 0.45) & (ratios < 0.65))
    assert h.min() > -0.05  # stiff ground: penetration stays small


def test_ten_runs_byte_identical(tmp_path):
    # NF-06: same seed + same scene -> byte-identical Parquet, 10 times.
    blobs = {
        run(ball_scene(), 2.0, out=tmp_path / f"r{i}.parquet").path.read_bytes() for i in range(10)
    }
    assert len(blobs) == 1


def test_different_seed_changes_rng_channel_only(tmp_path):
    a = run(ball_scene(42), 1.0, out=tmp_path / "a.parquet")
    b = run(ball_scene(43), 1.0, out=tmp_path / "b.parquet")
    assert np.array_equal(a["ball.h"], b["ball.h"])
    assert not np.array_equal(a["h_measured"], b["h_measured"])


def test_script_and_api_build_the_same_scene(tmp_path):
    # SC-04: the scene file and the same scene built in code give identical logs.
    namespace = {}
    exec(compile(BALL.read_text(), str(BALL), "exec"), namespace)
    scene = Scene(dt=1e-3, seed=42)
    scene.add_entity(namespace["BouncingBall"](name="ball"))
    scene.log("h_measured", lambda sim: sim.scene["ball"]["h"] + sim.rng.normal(0.0, 0.01))
    a = run(scene, 1.0, out=tmp_path / "api.parquet")
    b = run(load_scene(BALL), 1.0, out=tmp_path / "file.parquet")
    assert a.path.read_bytes() == b.path.read_bytes()


def test_load_scene_requires_scene_variable(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n")
    with pytest.raises(TypeError, match="scene"):
        load_scene(bad)


def test_live_run_not_available_yet():
    with pytest.raises(NotImplementedError):
        run(ball_scene(), 0.1, headless=False)


def test_default_log_path_is_unique(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = run(ball_scene(), 0.01)
    b = run(ball_scene(), 0.01)
    assert a.path != b.path and a.path.parent == b.path.parent == Path("runs")
    assert a.rtf > 0


def test_cli_run_headless(tmp_path, capsys):
    out = tmp_path / "cli.parquet"
    code = cli_main(
        ["run", str(BALL), "--headless", "--duration", "1", "--seed", "7", "--out", str(out)]
    )
    assert code == 0
    assert "1000 ticks" in capsys.readouterr().out
    meta = json.loads(pq.read_schema(out).metadata[b"simview"])
    assert meta["seed"] == 7 and meta["duration"] == 1.0


def test_cli_requires_headless_for_now(capsys):
    with pytest.raises(SystemExit):
        cli_main(["run", str(BALL)])
    assert "--headless" in capsys.readouterr().err


def test_cli_subprocess_without_qt(tmp_path):
    # The headless CLI runs as a real process and never imports Qt.
    out = tmp_path / "p.parquet"
    args = ["run", str(BALL), "--headless", "--duration", "0.5", "--out", str(out)]
    code = (
        "import sys; from simview.cli import main; "
        f"r = main({args!r}); "
        "assert 'PySide6' not in sys.modules; sys.exit(r)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert pq.read_table(out).num_rows == 501


def test_ur5_pick_example_lifts_the_cube(tmp_path):
    """examples/ur5_pick.py (UC-3, M3b) still picks the cube up when run as a scene file."""
    scene = load_scene(ROOT / "examples" / "ur5_pick.py")
    result = run(scene, 5.5, out=tmp_path / "pick.parquet")
    z = result["cube.z"]
    assert z[-1] - z[0] >= 0.095
