"""Python Function (BD-03): any Python function as a block.

Ports come from the type-hinted signature: each parameter is an input (a parameter named
`t` gets the time instead), and the return annotation sets the outputs: `tuple[float, float]`
gives two, a NamedTuple gives one per field (named after them), anything else one.

    def thrust(z: float, vz: float) -> float: ...        # 2 inputs, 1 output

`function` is a callable (scripts) or a reference saved in the diagram file: "pkg.mod:fn",
or "file.py:fn" relative to the diagram file.
"""

from __future__ import annotations

import importlib
import inspect
import runpy
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal


def resolve(ref: str, base: Path | None) -> Callable[..., Any]:
    target, sep, attr = ref.rpartition(":")
    if not sep or not target or not attr:
        raise BlockError(f'function {ref!r} must look like "file.py:name" or "module:name"')
    if target.endswith(".py"):
        path = Path(target)
        if not path.is_absolute() and base is not None:
            path = base / path
        if not path.is_file():
            raise BlockError(f"no file {path}")
        namespace = runpy.run_path(str(path))
        fn = namespace.get(attr)
    else:
        try:
            fn = getattr(importlib.import_module(target), attr, None)
        except ImportError as exc:
            raise BlockError(f"can't import {target}: {exc}") from exc
    if not callable(fn):
        raise BlockError(f"{ref} is not a function")
    return fn


def signature_ports(fn: Callable[..., Any]) -> tuple[list[str], bool, list[str]]:
    """(input names, takes t, output names) from the signature and hints."""
    sig = inspect.signature(fn)
    inputs: list[str] = []
    takes_t = False
    for i, p in enumerate(sig.parameters.values()):
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise BlockError("*args and **kwargs can't be ports; name each input")
        if i == 0 and p.name == "t":
            takes_t = True
            continue
        inputs.append(p.name)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001 - unresolvable hints fall back to one output
        hints = {}
    ret = hints.get("return", sig.return_annotation)
    fields = getattr(ret, "_fields", None)
    if fields:
        outputs = list(fields)
    elif typing.get_origin(ret) is tuple:
        args = [a for a in typing.get_args(ret) if a is not Ellipsis]
        outputs = [f"y{i + 1}" for i in range(len(args))]
    elif ret is None or ret is type(None):
        outputs = []
    else:
        outputs = ["y"]
    return inputs, takes_t, outputs


class PythonFunction(Block):
    type = "PythonFunction"
    category = "Python"
    doc = 'Calls a Python function; ports come from its type hints. function: "file.py:name".'
    defaults = {"function": ""}

    def configure(self) -> None:
        ref = self.params["function"]
        if callable(ref):
            self.fn = ref
        elif not ref:
            raise BlockError('set function to "file.py:name" or "module:name"')
        else:
            self.fn = resolve(str(ref), self.base)
        self.inputs, self.takes_t, self.outputs = signature_ports(self.fn)
        self.n_in, self.n_out = len(self.inputs), len(self.outputs)

    def input_names(self) -> list[str]:
        return self.inputs

    def output_names(self) -> list[str]:
        return self.outputs

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        args = [v if np.ndim(v) else float(v) for v in u]
        result = self.fn(t, *args) if self.takes_t else self.fn(*args)
        if self.n_out == 0:
            return []
        values = [result] if self.n_out == 1 else list(result)
        if len(values) != self.n_out:
            raise BlockError(f"returned {len(values)} values, expected {self.n_out}")
        return [np.asarray(v, dtype=np.float64) for v in values]
