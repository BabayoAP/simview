"""Toolbox discovery and registration (TB-01, TB-02, D-119).

A toolbox is a pip-installable package that declares an entry point in the group
`simview.toolboxes` pointing at a function `register(tb: Toolbox) -> None`:

    # the toolbox's pyproject.toml
    [project.entry-points."simview.toolboxes"]
    marine = "simview_marine:register"

    # simview_marine/__init__.py
    def register(tb):
        tb.add_module("marine", "simview_marine.api")   # sv.marine
        tb.add_block(Thruster)                           # block library
        tb.add_entity("simview_marine.boat:Boat")        # entity type
        tb.add_sensor("simview_marine.sonar:Sonar")      # sensor
        tb.add_template("harbor", "Harbor", "Dock a boat.", "simview_marine/harbor/scene.py")

Entity types, sensors, and modules may be given as "module:attr" / "module" strings so
registering stays cheap (nothing heavy is imported at startup); they are imported on first
use. SimView's own toolboxes (robotics, aero, vehicles) register the same way.

Discovery runs once, at app startup and in the sim process, and also lazily the first time
something looks up a name it doesn't know (a block type, a template, `sv.<name>`). A toolbox
that fails to load is recorded in `toolboxes()` with its error and skipped; it never stops
SimView from starting.
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

GROUP = "simview.toolboxes"
log = logging.getLogger(__name__)


@dataclass
class ToolboxInfo:
    """One discovered toolbox (what a toolbox manager panel lists, TB-03)."""

    name: str
    version: str
    distribution: str  # the pip package that provides it ("simview" for built-ins)
    error: str | None = None
    blocks: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    sensors: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TemplateSpec:
    """A start-screen card: `scene` is the template's scene file (None = opens empty)."""

    id: str
    title: str
    description: str
    icon: str
    scene: Path | None
    toolbox: str


class _Lazy:
    """A class or module named by an import string, imported on first `get()`."""

    def __init__(self, target: str | object) -> None:
        self.target = target
        self._value: object | None = None if isinstance(target, str) else target

    def get(self) -> Any:  # noqa: ANN401
        if self._value is None:
            assert isinstance(self.target, str)
            mod_name, _, attr = self.target.partition(":")
            value: object = importlib.import_module(mod_name)
            for part in attr.split(".") if attr else ():
                value = getattr(value, part)
            self._value = value
        return self._value


def _short_name(target: str | object) -> str:
    if isinstance(target, str):
        return target.rpartition(":")[2].rpartition(".")[2] or target
    return getattr(target, "__name__", repr(target))


class _State:
    def __init__(self) -> None:
        self.discovered = False
        self.toolboxes: dict[str, ToolboxInfo] = {}
        self.entities: dict[str, _Lazy] = {}
        self.sensors: dict[str, _Lazy] = {}
        self.modules: dict[str, _Lazy] = {}
        self.templates: dict[str, TemplateSpec] = {}
        self.blocks: list[str] = []  # block types added by toolboxes (for reset in tests)


_state = _State()
_lock = threading.RLock()


class Toolbox:
    """The handle a toolbox's `register(tb)` function receives."""

    def __init__(self, info: ToolboxInfo, root: Path | None = None) -> None:
        self.info = info
        self.name = info.name
        self._root = root  # relative template paths resolve against the toolbox package

    def add_block(self, cls: type) -> None:
        """A block class (subclass of `simview.blocks.Block`), shown in the quick-add palette
        under its `category` (one of the §7.7 categories)."""
        from simview.blocks.library import register

        register(cls)
        _state.blocks.append(cls.type)  # type: ignore[attr-defined]
        self.info.blocks.append(cls.type)  # type: ignore[attr-defined]

    def add_entity(self, cls: str | type, name: str | None = None) -> None:
        """An entity type (subclass of `simview.Entity`), by class or "module:Class"."""
        key = name or _short_name(cls)
        _add(_state.entities, key, cls, "entity type")
        self.info.entities.append(key)

    def add_sensor(self, cls: str | type, name: str | None = None) -> None:
        """A sensor (subclass of `simview.sensors.Sensor`), by class or "module:Class". It is
        also reachable as `simview.sensors.<name>`."""
        key = name or _short_name(cls)
        _add(_state.sensors, key, cls, "sensor")
        self.info.sensors.append(key)

    def add_module(self, name: str, module: str | ModuleType) -> None:
        """A Python API module, reachable as `simview.<name>` (imported on first use)."""
        import simview

        if name in simview.__all__ and name not in _BUILTIN_MODULES:
            raise ValueError(f"`simview.{name}` is part of SimView's own API")
        _add(_state.modules, name, module, "module")
        self.info.modules.append(name)

    def add_template(
        self,
        id: str,  # noqa: A002 (reads naturally at the call site)
        title: str,
        description: str,
        scene: str | Path | None = None,
        icon: str = "box",
    ) -> None:
        """A start-screen card. `scene` is a scene.py path (relative paths resolve against
        the toolbox's package folder); `icon` is a Lucide icon name."""
        from simview.templates import FLAGSHIP

        if id in _state.templates or any(t.id == id for t in FLAGSHIP):
            raise ValueError(f"a template named {id!r} already exists")
        path: Path | None = None
        if scene is not None:
            path = Path(scene)
            if not path.is_absolute() and self._root is not None:
                path = self._root / path
        _state.templates[id] = TemplateSpec(id, title, description, icon, path, self.name)
        self.info.templates.append(id)


def _add(table: dict[str, _Lazy], key: str, target: str | object, what: str) -> None:
    if key in table:
        raise ValueError(f"a {what} named {key!r} is already registered")
    table[key] = _Lazy(target)


# SimView's own toolboxes: (name, "module:register"). Also declared as entry points in
# pyproject.toml; these are loaded directly so a source checkout works without a reinstall.
BUILTINS: tuple[tuple[str, str], ...] = (
    ("robotics", "simview.toolboxes.builtin:robotics"),
    ("aero", "simview.toolboxes.builtin:aero"),
    ("vehicles", "simview.toolboxes.builtin:vehicles"),
)
_BUILTIN_MODULES = {name for name, _ in BUILTINS}


def _entry_points() -> list[Any]:
    from importlib.metadata import entry_points

    return list(entry_points(group=GROUP))


def _load(name: str, version: str, dist: str, value: str, fn: Callable[[Toolbox], None]) -> None:
    info = ToolboxInfo(name, version, dist)
    root = None
    mod = importlib.import_module(value.partition(":")[0]) if ":" in value else None
    if mod is not None and getattr(mod, "__file__", None):
        root = Path(mod.__file__).resolve().parent  # type: ignore[arg-type]
    _state.toolboxes[name] = info
    try:
        fn(Toolbox(info, root))
    except Exception as exc:  # a broken toolbox must not stop SimView (D-119)
        info.error = f"{type(exc).__name__}: {exc}"
        log.warning("toolbox %r failed to register: %s", name, info.error)


def discover() -> dict[str, ToolboxInfo]:
    """Find and register every toolbox (once). Returns them by name."""
    with _lock:
        if _state.discovered:
            return _state.toolboxes
        _state.discovered = True
        import simview

        for name, value in BUILTINS:
            fn = _Lazy(value).get()
            _load(name, simview.__version__, "simview", value, fn)
        try:
            eps = _entry_points()
        except Exception as exc:  # broken package metadata
            log.warning("could not read %s entry points: %s", GROUP, exc)
            eps = []
        builtin_values = dict(BUILTINS)
        for ep in eps:
            if builtin_values.get(ep.name) == ep.value:
                continue  # SimView's own entry point, already loaded above
            dist = getattr(ep, "dist", None)
            dist_name = dist.metadata["Name"] if dist is not None else "?"
            version = dist.version if dist is not None else "?"
            if ep.name in _state.toolboxes:
                _state.toolboxes[f"{ep.name} ({dist_name})"] = ToolboxInfo(
                    ep.name, version, dist_name, error=f"name {ep.name!r} is already taken"
                )
                continue
            try:
                fn = ep.load()
            except Exception as exc:
                info = ToolboxInfo(ep.name, version, dist_name, f"{type(exc).__name__}: {exc}")
                _state.toolboxes[ep.name] = info
                log.warning("toolbox %r failed to import: %s", ep.name, info.error)
                continue
            _load(ep.name, version, dist_name, ep.value, fn)
        return _state.toolboxes


def toolboxes() -> dict[str, ToolboxInfo]:
    return dict(discover())


def module(name: str) -> ModuleType:
    """The module a toolbox registered as `simview.<name>`; KeyError if none."""
    discover()
    return _state.modules[name].get()


def entity_types() -> dict[str, type]:
    discover()
    return {k: v.get() for k, v in _state.entities.items()}


def sensor_types() -> dict[str, type]:
    discover()
    return {k: v.get() for k, v in _state.sensors.items()}


def sensor_type(name: str) -> type:
    discover()
    return _state.sensors[name].get()


def templates() -> list[TemplateSpec]:
    """Templates added by toolboxes (the flagship ones are in `simview.templates`)."""
    discover()
    return list(_state.templates.values())


def reset() -> None:
    """Forget everything discovered (tests). Removes toolbox blocks from the library."""
    global _state
    from simview.blocks.library import BLOCKS

    with _lock:
        for type_name in _state.blocks:
            BLOCKS.pop(type_name, None)
        _state = _State()
