"""The block library (BD-02): one module per family, registered by type name.

Toolboxes add blocks with `register` (TB-02).
"""

from __future__ import annotations

from simview.blocks.library.base import Block, BlockError
from simview.blocks.library.continuous import Derivative, Integrator, StateSpace, TransferFunction
from simview.blocks.library.control import PID
from simview.blocks.library.discrete import Delay
from simview.blocks.library.entities import EntityInput, EntityState
from simview.blocks.library.math import Demux, Gain, Mux, Product, Saturation, Sum
from simview.blocks.library.python import PythonFunction
from simview.blocks.library.sinks import Scope, ToWorkspace
from simview.blocks.library.sources import Constant, Sine, Step
from simview.blocks.library.subsystem import Inport, Outport

# §7.7 category order (the quick-add palette lists blocks in it).
CATEGORIES = ("Sources", "Math", "Continuous", "Discrete", "Control", "Sinks", "Entities", "Python")
SUBSYSTEM = "Subsystem"  # a block holding its own diagram (BD-07), not a library class

BLOCKS: dict[str, type[Block]] = {}


def register(cls: type[Block]) -> type[Block]:
    if not cls.type or cls.category not in CATEGORIES:
        raise ValueError(f"{cls.__name__}: set `type` and a `category` from {CATEGORIES}")
    if cls.type in BLOCKS or cls.type == SUBSYSTEM:
        raise ValueError(f"a block type named {cls.type!r} already exists")
    BLOCKS[cls.type] = cls
    return cls


for _cls in (
    Constant, Step, Sine,
    Gain, Sum, Product, Saturation, Mux, Demux,
    Integrator, Derivative, TransferFunction, StateSpace,
    Delay,
    PID,
    Scope, ToWorkspace,
    EntityState, EntityInput,
    PythonFunction,
    Inport, Outport,
):  # fmt: skip
    register(_cls)


def block_class(type_name: str) -> type[Block]:
    if type_name not in BLOCKS:
        from simview.toolboxes.registry import discover

        discover()  # an installed toolbox may provide it (TB-02)
    try:
        return BLOCKS[type_name]
    except KeyError:
        raise BlockError(f"unknown block type {type_name!r}") from None


__all__ = ["BLOCKS", "CATEGORIES", "SUBSYSTEM", "Block", "BlockError", "block_class", "register"]
