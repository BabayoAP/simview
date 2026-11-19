"""RB-11: the Menagerie robot library (download on first use, pinned, licensed, cached)."""

import urllib.error

import numpy as np
import pytest

import simview as sv
from simview.toolboxes.robotics import library


def test_entries_are_licensed_and_pinned():
    assert len(library.MENAGERIE_COMMIT) == 40
    for name in ("panda", "ur10e", "robotiq_2f85"):
        assert library.ROBOTS[name].license
    assert set(library.available()) == set(library.ROBOTS)


def test_unknown_robot():
    with pytest.raises(KeyError, match="available"):
        library.fetch("r2d2")
    with pytest.raises(FileNotFoundError, match="library: "):
        sv.Scene().add_robot("r2d2")


def test_cache_location_follows_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMVIEW_CACHE", str(tmp_path))
    assert library.robot_dir("panda").is_relative_to(tmp_path)


def test_offline_error_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMVIEW_CACHE", str(tmp_path))

    def offline(*args, **kwargs):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(library.urllib.request, "urlopen", offline)
    with pytest.raises(library.FetchError, match="downloaded once on first use"):
        library.fetch("robotiq_2f85")
    assert not list(tmp_path.rglob("*.part"))  # no half-written files left behind


def test_referenced_files_are_parsed(tmp_path):
    xml = tmp_path / "r.xml"
    xml.write_text(
        '<mujoco><compiler meshdir="assets" texturedir="tex"/><include file="more.xml"/>'
        '<asset><mesh file="a.obj"/><texture file="t.png"/></asset></mujoco>'
    )
    assert sorted(library._referenced(xml, "x")) == ["assets/a.obj", "more.xml", "tex/t.png"]


@pytest.mark.network
def test_fetch_panda_and_load_it():
    path = library.fetch("panda")
    assert path.is_file() and (path.parent / "LICENSE").is_file()
    panda = sv.Scene().add_robot("panda")
    assert len(panda.joint_names) == 9 and len(panda.actuator_names) == 8
    assert panda.default_frame == "hand"
    assert np.isfinite(panda.fk()).all()


@pytest.mark.network
def test_cached_fetch_needs_no_network(monkeypatch):
    library.fetch("robotiq_2f85")

    def offline(*args, **kwargs):
        raise AssertionError("should not download again")

    monkeypatch.setattr(library.urllib.request, "urlopen", offline)
    library.fetch("robotiq_2f85")


@pytest.mark.network
def test_gripper_mounted_on_ur10e_keeps_tendons_and_equalities(tmp_path):
    scene = sv.Scene(dt=2e-3)
    scene.add_ground()
    arm = scene.add_robot("ur10e")
    grip = scene.add_robot("robotiq_2f85", name="grip", mount=("ur10e", "attachment_site"))
    m = scene.world.model
    assert m.ntendon >= 1 and m.neq >= 1  # the 2F-85's linkage survived composition
    assert grip.default_frame == "pinch"
    # The gripper hangs off the body that carries the arm's attachment site.
    from simview.toolboxes import robotics as rb

    assert rb.frame_tree(grip)["base_mount"] == "ur10e/wrist_3_link"
    site = arm.fk(None, "attachment_site")
    assert np.linalg.norm(grip.fk()[:3, 3] - site[:3, 3]) > 0.1  # the pinch is out past it
    grip.set_controls({"fingers_actuator": 255.0})
    run = sv.run(scene, 0.5, out=tmp_path / "g.parquet")
    assert run.ticks == 250
    assert max(abs(v) for v in grip.q) > 0.1  # the fingers closed


@pytest.mark.network
def test_panda_reaches_a_pose_with_differential_ik(tmp_path):
    from simview.toolboxes import robotics as rb

    scene = sv.Scene(dt=2e-3)
    scene.add_ground()
    panda = scene.add_robot("panda", gravity_compensation=True)
    home = np.array([0.0, -0.3, 0.0, -2.2, 0.0, 2.0, 0.8])
    panda.x0[:7] = home
    arm_joints = panda.joint_names[:7]
    panda.set_targets(dict(zip(arm_joints, home, strict=True)))
    target = panda.fk(np.concatenate([home, panda.q[7:]])).copy()
    target[:3, 3] += [0.1, 0.1, -0.1]
    ik = rb.DifferentialIK(panda, max_step=0.02)

    @scene.controller(rate=100)
    def reach(t, state, ctx):
        q = ik.step(target)
        panda.set_targets(dict(zip(arm_joints, q[:7], strict=True)))

    sv.run(scene, 3.0, out=tmp_path / "p.parquet")
    assert np.linalg.norm(panda.fk()[:3, 3] - target[:3, 3]) < 5e-3
