"""RP-01 run manifests and RP-02 `simview reproduce`."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

import simview as sv
from simview.cli import main as cli
from simview.runner import manifest as mf
from simview.runner.headless import load_scene
from simview.runner.reproduce import ReproduceError, reproduce
from simview.templates import scene_path

FIXTURE = Path(__file__).resolve().parents[1] / "testing" / "fixtures" / "pid_cart.py"


@pytest.fixture
def pid_copy(tmp_path):
    """The PID cart scene in its own folder (so edits don't touch the fixture)."""
    folder = tmp_path / "proj"
    folder.mkdir()
    shutil.copy(FIXTURE, folder / "scene.py")
    return folder / "scene.py"


def test_headless_run_stores_a_manifest(pid_copy, tmp_path):
    scene = load_scene(pid_copy, params={"kp": 12.0}, seed=4)
    run = sv.run(scene, 0.5, out=tmp_path / "a.parquet")
    m = mf.read_manifest(run.path)
    assert m["format"] == mf.FORMAT and m["simview"] == sv.__version__
    assert m["packages"]["numpy"] == np.__version__ and m["packages"]["mujoco"]
    assert {"aero", "robotics", "vehicles", "perception"} <= set(m["toolboxes"])
    assert m["machine"]["cores"] and m["machine"]["os"]
    assert m["seed"] == 4 and m["params"]["kp"] == 12.0 and m["duration"] == 0.5
    assert m["files"]["scene.py"].startswith("sha256:")
    assert m["git"] is None or set(m["git"]) == {"commit", "dirty", "root"}


def test_one_byte_changes_the_scene_hash(pid_copy):
    before = mf.file_hashes(scene_file=pid_copy)["scene.py"]
    pid_copy.write_bytes(pid_copy.read_bytes() + b" ")
    assert mf.file_hashes(scene_file=pid_copy)["scene.py"] != before


def test_machine_info_can_be_left_out(pid_copy, tmp_path, monkeypatch):
    monkeypatch.setenv(mf.NO_MACHINE_ENV, "1")
    run = sv.run(load_scene(pid_copy), 0.1, out=tmp_path / "a.parquet")
    m = mf.read_manifest(run.path)
    assert "machine" not in m and m["packages"]  # versions are still there
    assert mf.build_manifest(machine_info=True)["machine"]["hostname"]


def test_cli_flag_leaves_machine_info_out(pid_copy, tmp_path, monkeypatch):
    monkeypatch.delenv(mf.NO_MACHINE_ENV, raising=False)
    out = tmp_path / "b.parquet"
    args = ["run", str(pid_copy), "--headless", "--duration", "0.1", "--out", str(out)]
    assert cli([*args, "--no-machine-info"]) == 0
    monkeypatch.delenv(mf.NO_MACHINE_ENV, raising=False)  # the CLI set it for this process
    assert "machine" not in mf.read_manifest(out)


def test_monte_carlo_runs_have_manifests(pid_copy, tmp_path):
    res = sv.sweep(
        pid_copy, 0.2, grid={"kp": [10.0, 14.0]}, workers=0, keep_logs=True, out=tmp_path / "sw"
    )
    sweep_manifest = json.loads((tmp_path / "sw" / "manifest.json").read_text(encoding="utf-8"))
    assert sweep_manifest["files"]["scene.py"] and len(sweep_manifest["plan"]) == 2
    for log in res["log"]:
        m = mf.read_manifest(log)
        assert m["seed"] is not None and m["params"]["kp"] in (10.0, 14.0)


def test_rl_eval_episodes_have_manifests(tmp_path, monkeypatch):
    from simview.rl.metrics import TRAINING_ENV, TrainingRun

    monkeypatch.delenv(TRAINING_ENV, raising=False)
    env = sv.make_env("drone_landing", record_every=1, record_dir=tmp_path / "train")
    env.reset(seed=0)
    while True:
        *_, term, trunc, _ = env.step(np.zeros(3, np.float32))
        if term or trunc:
            break
    tr = TrainingRun(tmp_path / "train")
    tr.refresh()
    m = mf.read_manifest(tr.recorded()[0]["log"])
    assert m is not None and "scene.py" in m["files"]


def test_datasets_opened_by_the_scene_are_hashed(tmp_path):
    from simview.perception.dataset import Dataset, DatasetWriter
    from tests.perception.test_dataset import make_frames

    folder = tmp_path / "ds"
    with DatasetWriter(folder) as w:
        for frame in make_frames(n_cams=1, n=2):
            w.add(frame)
    Dataset(folder)
    hashes = mf.file_hashes(scene_file=None)
    key = next(k for k in hashes if k.rstrip("/").endswith("ds"))
    assert hashes[key].startswith("sha256:")


# -- RP-02 ------------------------------------------------------------------------------------
TEMPLATES = ["av_scenario", "drone_delivery", "drone_landing", "ur5_ik", "vision_drive"]


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_reproduces_identically(template, tmp_path):
    path = scene_path(template)
    run = sv.run(load_scene(path), 0.3, out=tmp_path / f"{template}.parquet")
    result = reproduce(run.path)
    assert result.identical, result.describe()
    assert result.environment == [] and result.has_manifest


def test_reproduce_names_a_numpy_difference(pid_copy, tmp_path, capsys):
    run = sv.run(load_scene(pid_copy), 0.3, out=tmp_path / "a.parquet")
    side = run.path.with_suffix(".run.json")
    ctx = json.loads(side.read_text(encoding="utf-8"))
    ctx["manifest"]["packages"]["numpy"] = "1.26.4"
    side.write_text(json.dumps(ctx), encoding="utf-8")
    assert cli(["reproduce", str(run.path)]) == 0  # still identical...
    out = capsys.readouterr().out
    assert "identical" in out and f"numpy: 1.26.4 (run) vs {np.__version__} (now)" in out


def test_reproduce_reports_the_first_divergence_and_the_changed_file(pid_copy, tmp_path, capsys):
    run = sv.run(load_scene(pid_copy), 1.0, out=tmp_path / "a.parquet")
    src = pid_copy.read_text(encoding="utf-8")
    pid_copy.write_text(src.replace("- 0.5 * x[1]", "- 0.6 * x[1]"), encoding="utf-8")
    result = reproduce(run.path)
    assert not result.identical
    assert result.first_signal in ("cart.v", "cart.x", "err") and result.first_time > 0
    assert "file scene.py: changed since the run" in result.environment
    assert cli(["reproduce", str(run.path)]) == 1
    assert "DIVERGED" in capsys.readouterr().out


def test_reproduce_needs_the_scene(pid_copy, tmp_path, capsys):
    run = sv.run(load_scene(pid_copy), 0.1, out=tmp_path / "a.parquet")
    pid_copy.unlink()
    with pytest.raises(ReproduceError, match="not found"):
        reproduce(run.path)
    assert cli(["reproduce", str(run.path)]) == 2
    assert "cannot reproduce" in capsys.readouterr().out


def test_runs_without_a_manifest_still_reproduce(pid_copy, tmp_path):
    run = sv.run(load_scene(pid_copy), 0.2, out=tmp_path / "a.parquet")
    side = run.path.with_suffix(".run.json")
    ctx = json.loads(side.read_text(encoding="utf-8"))
    del ctx["manifest"]
    side.write_text(json.dumps(ctx), encoding="utf-8")
    result = reproduce(run.path)
    assert result.identical and not result.has_manifest
    assert "no manifest" in result.describe()
