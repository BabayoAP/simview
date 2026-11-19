"""IO-04: the .svproj folder (no Qt)."""

import json

import pytest

from simview.io import project as proj


def test_create_save_load_round_trip(tmp_path):
    scene = tmp_path / "scene.py"
    scene.write_text("scene = None\n")
    p = proj.create(tmp_path / "robot")
    assert p.path.name == "robot.svproj" and p.name == "robot"
    assert all((p.path / f).is_dir() for f in proj.FOLDERS)
    copied = p.set_scene(scene)
    assert copied == p.path / "scenes" / "scene.py" and copied.read_text() == "scene = None\n"
    script = p.folder("scripts") / "a.py"
    script.write_text("x = 1\n")
    assert p.set_script(script) == script.resolve()  # already inside: not copied
    p.save()
    again = proj.load(p.path)
    assert (again.name, again.scene, again.script) == ("robot", "scenes/scene.py", "scripts/a.py")
    assert again.scene_path.read_text() == "scene = None\n"
    assert proj.is_project(p.path) and not proj.is_project(tmp_path)


def test_copies_never_overwrite_and_unknown_keys_survive(tmp_path):
    p = proj.create(tmp_path / "x.svproj")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "s.py").write_text("1")
    (tmp_path / "b" / "s.py").write_text("2")
    first = p.add_file(tmp_path / "a" / "s.py", "scenes")
    second = p.add_file(tmp_path / "b" / "s.py", "scenes")
    assert first.name == "s.py" and second.name == "s-1.py" and first.read_text() == "1"
    manifest = p.path / proj.MANIFEST
    data = json.loads(manifest.read_text())
    data["layout"] = "simulate"
    manifest.write_text(json.dumps(data))
    loaded = proj.load(p.path)
    loaded.save()
    assert json.loads(manifest.read_text())["layout"] == "simulate"


def test_bad_projects(tmp_path):
    with pytest.raises(proj.ProjectError, match="isn't a SimView project"):
        proj.load(tmp_path)
    p = proj.create(tmp_path / "n")
    with pytest.raises(proj.ProjectError, match="isn't empty"):
        proj.create(p.path)
    (p.path / proj.MANIFEST).write_text("{")
    with pytest.raises(proj.ProjectError, match="JSON"):
        proj.load(p.path)
    (p.path / proj.MANIFEST).write_text('{"format": 99}')
    with pytest.raises(proj.ProjectError, match="newer"):
        proj.load(p.path)
    assert p.relative(tmp_path / "elsewhere") is None
