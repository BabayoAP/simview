"""The `sim` object in the console (SC-01, SC-05): the running scene, seen from the UI process.

The sim runs in its own process, so `sim` is a handle: it reads the latest state frame and the
recorded history, and sends commands. `sim.params.kp = 3` sends the change, which the sim
applies before its next tick. Nothing here imports Qt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from simview.core.scene import Scene
    from simview.ipc.client import SimClient
    from simview.ui.timeline.history import History


class Source(Protocol):
    """What the handle needs from the main window."""

    @property
    def client(self) -> SimClient | None: ...

    @property
    def history(self) -> History | None: ...


class NoSceneError(RuntimeError):
    pass


class ParamsHandle:
    """`sim.params`: reads the last values the sim reported, sets values in the sim."""

    def __init__(self, sim: SimHandle) -> None:
        object.__setattr__(self, "_sim", sim)

    def _values(self) -> dict[str, Any]:
        return self._sim._param_values

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        values = self._values()
        if name not in values:
            known = ", ".join(values) or "none"
            raise AttributeError(f"no parameter {name!r} (declared: {known})")
        return values[name]

    def __setattr__(self, name: str, value: Any) -> None:
        self._sim._set_param(name, value)

    __getitem__ = __getattr__
    __setitem__ = __setattr__

    def __contains__(self, name: object) -> bool:
        return name in self._values()

    def __iter__(self) -> Any:
        return iter(self._values())

    def __dir__(self) -> list[str]:  # tab completion in the console
        return list(self._values())

    def to_dict(self) -> dict[str, Any]:
        return dict(self._values())

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self._values().items())
        return f"Params({inner})"


class SimHandle:
    """The running simulation: `sim.t`, `sim.state("ur5")`, `sim.data("ball.z")`,
    `sim.params.kp = 3`, `sim.play()`, `sim.pause()`, `sim.step()`, `sim.reset()`."""

    def __init__(self, source: Source) -> None:
        self._source = source
        self._param_values: dict[str, Any] = {}
        self._scene: Scene | None = None
        self._scene_for: object = None
        self.params = ParamsHandle(self)

    # -- what the window tells the handle ---------------------------------------------------
    def loaded(self, params: dict[str, Any]) -> None:
        """A scene (re)loaded: its declared parameters and their values."""
        self._param_values = dict(params)
        self._scene = None

    def params_changed(self, values: dict[str, Any]) -> None:
        """The sim's answer to a change (the values it actually holds)."""
        self._param_values = dict(values)

    # -- internals --------------------------------------------------------------------------
    def _client(self) -> SimClient:
        client = self._source.client
        if client is None or not client.alive:
            raise NoSceneError("no scene is running; open one with File > Open Scene…")
        return client

    def _set_param(self, name: str, value: Any) -> None:
        from simview.core.params import _coerce

        if name not in self._param_values:
            known = ", ".join(self._param_values) or "none"
            raise AttributeError(
                f"no parameter {name!r}; declare it in the scene file (declared: {known})"
            )
        client = self._client()
        value = _coerce(name, value, self._param_values[name])  # same checks as the sim
        self._param_values[name] = value  # shown right away; the sim's answer confirms it
        client.set_param(name, value)

    # -- state ------------------------------------------------------------------------------
    @property
    def t(self) -> float:
        f = self._client().frame()
        return float(f.t) if f is not None else 0.0

    @property
    def tick(self) -> int:
        f = self._client().frame()
        return int(f.tick) if f is not None else 0

    @property
    def dt(self) -> float:
        desc = self._client().description
        return float(desc.dt) if desc is not None else float("nan")

    @property
    def running(self) -> bool:
        f = self._client().frame()
        return bool(f.running) if f is not None else False

    @property
    def entities(self) -> list[str]:
        desc = self._client().description
        return [e.name for e in desc.entities] if desc is not None else []

    def state(self, entity: str) -> dict[str, float]:
        """An entity's current state by name, e.g. `sim.state("ball")["z"]`."""
        client = self._client()
        f, desc = client.frame(), client.description
        info = next((e for e in desc.entities if e.name == entity), None) if desc else None
        if f is None or info is None:
            raise KeyError(f"no entity {entity!r} (entities: {', '.join(self.entities)})")
        x = f.states[entity]
        return {s: float(v) for s, v in zip(info.state_names, x, strict=True)}

    @property
    def signals(self) -> list[str]:
        h = self._source.history
        return list(h.signals) if h is not None else []

    def data(self, signal: str | None = None) -> Any:
        """The recorded history: one signal as an array, or every signal (and "t") as a dict
        of arrays. It's what the timeline and plots show, up to the latest tick."""
        h = self._source.history
        if h is None:
            raise NoSceneError("nothing recorded yet; run the simulation first")
        if signal == "t":
            return h.t.copy()
        if signal is not None:
            if signal not in h.signals:
                raise KeyError(f"no signal {signal!r}; see sim.signals")
            return h.signal(signal).copy()
        out = {"t": h.t.copy()}
        out.update({s: h.signal(s).copy() for s in h.signals})
        return out

    @property
    def scene(self) -> Scene:
        """A copy of the scene built from its file in the console, for kinematics and
        inspection (e.g. `sim.scene["ur5"].fk(q)`). It doesn't move with the simulation."""
        client = self._client()
        if self._scene is None or self._scene_for is not client.description:
            from simview.runner.headless import load_scene

            assert client.scene_path is not None
            self._scene = load_scene(client.scene_path)
            self._scene_for = client.description
        return self._scene

    # -- commands ---------------------------------------------------------------------------
    def play(self) -> None:
        self._client().play()

    def pause(self) -> None:
        self._client().pause()

    def step(self, n: int = 1) -> None:
        self._client().step(n)

    def reset(self) -> None:
        """Reload the scene file from the start (parameters go back to its values)."""
        self._client().reset()

    def __repr__(self) -> str:
        client = self._source.client
        if client is None or not client.alive or client.scene_path is None:
            return "<sim: no scene running>"
        f = client.frame()
        t, tick = (f.t, f.tick) if f is not None else (0.0, 0)
        status = "running" if f is not None and f.running else "paused"
        params = ", ".join(self._param_values) or "none"
        return (
            f"<sim: {client.scene_path.name}, t = {t:.3f} s (tick {tick}), {status}; "
            f"params: {params}>"
        )
