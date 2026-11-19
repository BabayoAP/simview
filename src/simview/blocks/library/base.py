"""What every block implements (BD-02). Qt-free.

A block has input and output ports, parameters (JSON values), and optionally continuous
states (integrated by the diagram) and discrete states (updated once per sample).

- `feedthrough`: an output depends on the inputs at the same instant. Only feedthrough
  blocks can form algebraic loops (BD-05); a non-feedthrough block's `output` must not read
  `u` (it gets None).
- `discrete`: the outputs are computed at samples and held between them (Delay, PID,
  Derivative), so the continuous solver sees them constant over a sample period.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

Signal = np.ndarray
Inputs = Sequence[Signal]


class BlockError(ValueError):
    """A problem with one block (bad parameter, wrong input shape)."""


def as_signal(value: Any, what: str = "value") -> np.ndarray:
    try:
        arr = np.array(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise BlockError(f"{what} must be a number, a list of numbers, or a matrix") from exc
    if arr.ndim > 2:
        raise BlockError(
            f"{what} has {arr.ndim} dimensions; signals are scalars, vectors, or matrices"
        )
    return arr


class Block:
    type: ClassVar[str] = ""
    category: ClassVar[str] = ""
    doc: ClassVar[str] = ""
    defaults: ClassVar[dict[str, Any]] = {}
    feedthrough: ClassVar[bool] = True
    discrete: ClassVar[bool] = False
    ts: float = 0.0  # the diagram's sample period, set before a run starts

    def __init__(
        self, name: str, params: Mapping[str, Any] | None = None, base: Path | None = None
    ) -> None:
        self.name = name
        self.base = base  # the diagram file's folder (Python Function references)
        params = dict(params or {})
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise BlockError(f"unknown parameter(s) {', '.join(sorted(unknown))}")
        self.params: dict[str, Any] = {**self.defaults, **params}
        self.n_in = 1
        self.n_out = 1
        self.configure()

    # -- set up -----------------------------------------------------------------------------
    def configure(self) -> None:
        """Read `self.params`, set `n_in` / `n_out`; raise BlockError on bad values."""

    def bind(self, scene: Any) -> None:
        """Called once with the scene (entities by name) before a run, or a stand-in in the
        editor. Entity blocks look up their entity here."""

    def input_names(self) -> list[str]:
        return ["u"] if self.n_in == 1 else [f"u{i + 1}" for i in range(self.n_in)]

    def output_names(self) -> list[str]:
        return ["y"] if self.n_out == 1 else [f"y{i + 1}" for i in range(self.n_out)]

    # -- states -----------------------------------------------------------------------------
    def x0(self) -> np.ndarray:
        """Initial continuous state (flat)."""
        return np.zeros(0)

    def reset(self) -> None:
        """Back to the initial discrete state (a run starts)."""

    # -- behavior ---------------------------------------------------------------------------
    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        raise NotImplementedError

    def derivative(self, t: float, x: np.ndarray, u: Inputs) -> np.ndarray:
        return np.zeros(0)

    def update(self, t: float, x: np.ndarray, u: Inputs, ts: float) -> None:
        """Discrete state update after a sample's outputs (`ts` = sample period)."""
