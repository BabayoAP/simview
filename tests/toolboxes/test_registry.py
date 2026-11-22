"""TB-01 / TB-02: toolboxes are pip-installed packages found through the `simview.toolboxes`
entry point; each registers blocks, entity types, sensors, templates, and API modules.

The fake toolboxes here are real installed distributions: a package plus a `.dist-info`
folder with `entry_points.txt` on `sys.path`, the layout pip writes."""

from __future__ import annotations

import sys
import textwrap
from importlib.metadata import entry_points
from pathlib import Path

import pytest

import simview as sv
from simview.toolboxes import registry

MARINE = """
import numpy as np

import simview as sv
from simview.blocks.library import Block
from simview.sensors import Sensor


class Thruster(Block):
    type = "Thruster"
    category = "Math"
    doc = "Thrust from a throttle command."
    defaults = {"max_thrust": 10.0}

    def configure(self):
        self.k = float(self.params["max_thrust"])

    def output(self, t, x, u):
        return [self.k * u[0]]


class Boat(sv.Entity):
    pass


class Sonar(Sensor):
    fields = ("depth",)


def answer():
    return 42


def register(tb):
    tb.add_module("marine", "{pkg}")
    tb.add_block(Thruster)
    tb.add_entity(Boat)
    tb.add_sensor("{pkg}:Sonar")
    tb.add_template("harbor", "Harbor", "Dock a boat.", "harbor/scene.py", icon="ship")
"""


def install(site: Path, pkg: str, ep_name: str, source: str, version: str = "1.2.0") -> None:
    """Lay out an installed distribution `pkg` with one `simview.toolboxes` entry point."""
    (site / pkg).mkdir()
    (site / pkg / "__init__.py").write_text(textwrap.dedent(source).replace("{pkg}", pkg))
    (site / pkg / "harbor").mkdir()
    (site / pkg / "harbor" / "scene.py").write_text("import simview as sv\nscene = sv.Scene()\n")
    dist = site / f"{pkg}-{version}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {pkg}\nVersion: {version}\n")
    (dist / "entry_points.txt").write_text(f"[simview.toolboxes]\n{ep_name} = {pkg}:register\n")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A fresh registry and an extra site folder; everything is undone afterwards."""
    before = set(sys.modules)
    monkeypatch.syspath_prepend(str(tmp_path))
    registry.reset()
    yield tmp_path
    registry.reset()
    for name in set(sys.modules) - before:
        if name.startswith("svtest_"):
            del sys.modules[name]


def test_builtins_are_declared_as_entry_points_and_load_cleanly(site):
    declared = {ep.name: ep.value for ep in entry_points(group=registry.GROUP)}
    assert declared == dict(registry.BUILTINS)  # pyproject.toml matches the registry
    found = registry.toolboxes()
    assert {"robotics", "aero", "vehicles"} <= set(found)
    assert all(info.error is None for info in found.values())
    assert sv.aero.Quadrotor is registry.entity_types()["Quadrotor"]
    assert {"Robot", "Wind", "KinematicBicycle", "ScriptedNPC"} <= set(registry.entity_types())


def test_installed_toolbox_registers_every_kind(site):
    install(site, "svtest_marine", "marine", MARINE)
    info = registry.toolboxes()["marine"]
    assert (info.error, info.version, info.distribution) == (None, "1.2.0", "svtest_marine")
    assert info.blocks == ["Thruster"] and info.entities == ["Boat"]
    assert info.sensors == ["Sonar"] and info.templates == ["harbor"]
    # Python API module
    assert sv.marine.answer() == 42
    # block: in the library, the quick-add palette, and constructible by type name
    from simview.blocks.library import BLOCKS, block_class
    from simview.ui.blockeditor.palette import entries

    assert block_class("Thruster") is BLOCKS["Thruster"]
    assert ("Thruster", "Math", "Thrust from a throttle command.") in entries()
    # entity type and sensor
    assert issubclass(registry.entity_types()["Boat"], sv.Entity)
    assert sv.sensors.Sonar.fields == ("depth",)
    # template: listed after the flagship ones, scene path relative to the package
    from simview.templates import FLAGSHIP, scene_path, templates

    ids = [t.id for t in templates()]
    assert ids[: len(FLAGSHIP)] == [t.id for t in FLAGSHIP] and ids[-1] == "harbor"
    assert scene_path("harbor") == site / "svtest_marine" / "harbor" / "scene.py"


def test_unknown_block_type_triggers_discovery(site):
    install(site, "svtest_marine", "marine", MARINE)
    from simview.blocks.library import block_class

    assert not registry._state.discovered
    assert block_class("Thruster").type == "Thruster"  # a diagram that uses it just loads


def test_broken_toolboxes_are_reported_not_fatal(site):
    install(site, "svtest_raises", "raises", "def register(tb):\n    raise RuntimeError('boom')\n")
    install(site, "svtest_noimport", "noimport", "import not_a_real_module\n")
    install(site, "svtest_marine", "marine", MARINE)
    found = registry.toolboxes()
    assert found["raises"].error == "RuntimeError: boom"
    assert "ModuleNotFoundError" in (found["noimport"].error or "")
    assert found["marine"].error is None and sv.marine.answer() == 42


def test_name_clashes_are_rejected(site):
    install(site, "svtest_clash", "aero", "def register(tb):\n    pass\n")
    install(site, "svtest_shadow", "shadow", "def register(tb):\n    tb.add_module('io', 'json')\n")
    found = registry.toolboxes()
    assert "already taken" in found["aero (svtest_clash)"].error
    assert found["aero"].distribution == "simview"  # the built-in keeps the name
    assert "SimView's own API" in found["shadow"].error
    assert sv.io.__name__ == "simview.io"


def test_unknown_attribute_still_raises(site):
    with pytest.raises(AttributeError):
        sv.no_such_toolbox  # noqa: B018
    with pytest.raises(AttributeError):
        sv.sensors.NoSuchSensor  # noqa: B018


def test_start_screen_shows_toolbox_templates(site, qapp, settings):
    install(site, "svtest_marine", "marine", MARINE)
    from simview.ui.start_screen import StartScreen

    screen = StartScreen(settings)
    assert [c.template_id for c in screen.cards][-1] == "harbor"
    assert len(screen.cards) == 5
