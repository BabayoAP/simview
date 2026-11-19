"""Entities (BD-04): read an entity's state, or write its control input, in the scene."""

from __future__ import annotations

from typing import Any

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal


def _entity(scene: Any, name: str) -> Any:
    try:
        return scene[name]
    except KeyError:
        known = ", ".join(scene.entities) or "none"
        raise BlockError(f"no entity {name!r} in the scene (entities: {known})") from None


class EntityState(Block):
    type = "EntityState"
    category = "Entities"
    doc = "One output per chosen state of an entity (`states`: names, or empty for all)."
    defaults = {"entity": "", "states": []}
    feedthrough = False  # reads the entity, not its inputs

    def configure(self) -> None:
        self.n_in = 0
        self.states: list[str] = [str(s) for s in self.params["states"] or []]
        self.n_out = max(1, len(self.states))
        self.entity: Any = None
        self.index: list[int] = []

    def bind(self, scene: Any) -> None:
        name = str(self.params["entity"])
        if not name:
            raise BlockError("choose an entity")
        self.entity = _entity(scene, name)
        names = list(self.entity.state_names)
        if not self.states:
            self.states = names
            self.n_out = len(names)
        missing = [s for s in self.states if s not in names]
        if missing:
            raise BlockError(f"{name} has no state {missing[0]!r} (states: {', '.join(names)})")
        self.index = [names.index(s) for s in self.states]

    def output_names(self) -> list[str]:
        return self.states or ["y"]

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        if self.entity is None:
            raise BlockError("not bound to a scene")
        xs = self.entity.x
        return [np.asarray(xs[i], dtype=np.float64) for i in self.index]


class EntityInput(Block):
    type = "EntityInput"
    category = "Entities"
    doc = "Sets an entity's control input `u` (a number or a vector) at every sample."
    defaults = {"entity": ""}

    def configure(self) -> None:
        self.n_out = 0
        self.entity: Any = None

    def bind(self, scene: Any) -> None:
        name = str(self.params["entity"])
        if not name:
            raise BlockError("choose an entity")
        self.entity = _entity(scene, name)

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return []

    def write(self, u: Inputs) -> None:
        self.entity.u = np.atleast_1d(np.asarray(u[0], dtype=np.float64)).copy()
