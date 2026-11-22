"""Live parameters (SC-05): `sim.params.kp = 3` takes effect on the next tick.

A scene file declares its parameters (`scene.params.kp = 2000.0`), and controllers read them
(`ctx.params.kp`). Scalar parameters are also logged every tick as `params.<name>` channels,
so a change made mid-run shows up in plots, reports, and scenarios. The set of names is fixed
once a run starts, so a typo like `sim.params.kpp = 3` is an error instead of a silent no-op.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import numpy as np

PREFIX = "params."  # logged channel name prefix

# SE-08: a Monte Carlo trial loads the scene file with some parameters replaced. Scene files
# read parameters while they build the scene (`Wind(gust_std=p.gust)`), so the trial's value
# has to win at the moment the file declares the name, not after the file has run (D-106).
_OVERRIDES: ContextVar[dict[str, Any] | None] = ContextVar("simview_param_overrides", default=None)


@contextmanager
def overrides(values: Mapping[str, Any]) -> Iterator[set[str]]:
    """Scenes created inside this block declare these parameters with these values instead of
    their own. Yields the set of names that were declared (to report unknown ones)."""
    state: dict[str, Any] = {"values": dict(values), "used": set()}
    token = _OVERRIDES.set(state)
    try:
        yield state["used"]
    finally:
        _OVERRIDES.reset(token)


Value = float | np.ndarray


def _coerce(name: str, value: Any, old: Value | None = None) -> Value:
    """A scalar stays a float, an array keeps its shape (so the log layout can't change)."""
    if isinstance(value, bool | int | float | np.integer | np.floating) or (
        isinstance(value, np.ndarray) and value.ndim == 0
    ):
        if isinstance(old, np.ndarray):
            raise TypeError(f"parameter {name!r} is an array of shape {old.shape}")
        return float(value)
    try:
        arr = np.array(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"parameter {name!r} must be a number or an array of numbers") from exc
    if old is not None and (not isinstance(old, np.ndarray) or old.shape != arr.shape):
        shape = "a number" if not isinstance(old, np.ndarray) else f"shape {old.shape}"
        raise TypeError(f"parameter {name!r} is {shape}, got shape {arr.shape}")
    return arr


class Params:
    """Named numbers and arrays, read and set as attributes."""

    def __init__(self, on_declare: Callable[[str, Value], None] | None = None) -> None:
        object.__setattr__(self, "_values", {})
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_on_declare", on_declare)
        object.__setattr__(self, "_overrides", _OVERRIDES.get())

    def set(self, name: str, value: Any) -> None:
        values: dict[str, Value] = self._values
        if name.startswith("_") or not name.isidentifier():
            raise AttributeError(f"{name!r} is not a valid parameter name")
        if name in values:
            values[name] = _coerce(name, value, values[name])
            return
        if self._frozen:
            known = ", ".join(values) or "none"
            raise AttributeError(
                f"no parameter {name!r}; declare it in the scene file (declared: {known})"
            )
        state = self._overrides
        if state is not None and name in state["values"]:
            value = state["values"][name]
            state["used"].add(name)
        values[name] = _coerce(name, value)
        if self._on_declare is not None:
            self._on_declare(name, values[name])

    def freeze(self) -> None:
        """No new names from now on (a run has started); values can still change."""
        object.__setattr__(self, "_frozen", True)

    def to_dict(self) -> dict[str, Value]:
        return {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in self._values.items()}

    def to_json(self) -> dict[str, Any]:
        """JSON-ready values (arrays as lists), for run metadata."""
        values = self._values.items()
        return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in values}

    def __getattr__(self, name: str) -> Value:
        if name.startswith("_"):  # not set up yet (copy, pickle): don't recurse on _values
            raise AttributeError(name)
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(f"no parameter {name!r}") from None

    def __setattr__(self, name: str, value: Any) -> None:
        self.set(name, value)

    def __getitem__(self, name: str) -> Value:
        return self._values[name]

    def __setitem__(self, name: str, value: Any) -> None:
        self.set(name, value)

    def __contains__(self, name: object) -> bool:
        return name in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __dir__(self) -> list[str]:
        return [*self._values, "set", "to_dict"]

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self._values.items())
        return f"Params({inner})"
