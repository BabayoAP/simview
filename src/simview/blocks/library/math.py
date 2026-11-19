"""Math: Gain, Sum, Product, Saturation, Mux, Demux (BD-02)."""

from __future__ import annotations

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal, as_signal


def _same_shape(block: Block, u: Inputs) -> None:
    shapes = {np.shape(v) for v in u}
    if len(shapes) > 1 and len(shapes - {()}) > 1:
        listed = ", ".join(str(np.shape(v)) for v in u)
        raise BlockError(f"inputs have different shapes: {listed}")


class Gain(Block):
    type = "Gain"
    category = "Math"
    doc = "gain · u. A matrix gain multiplies (K @ u); a number or vector scales elementwise."
    defaults = {"gain": 1.0}

    def configure(self) -> None:
        self.k = as_signal(self.params["gain"], "gain")

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        if self.k.ndim == 2:
            if np.ndim(u[0]) == 0 or self.k.shape[1] != np.shape(u[0])[0]:
                raise BlockError(f"gain is {self.k.shape} but the input is {np.shape(u[0])}")
            return [self.k @ u[0]]
        return [self.k * u[0]]


class Sum(Block):
    type = "Sum"
    category = "Math"
    doc = 'Adds and subtracts its inputs; `signs` has one + or - per input, e.g. "+-".'
    defaults = {"signs": "++"}

    def configure(self) -> None:
        signs = str(self.params["signs"])
        if not signs or set(signs) - {"+", "-"}:
            raise BlockError('signs must be a string of + and -, e.g. "+-"')
        self.signs = [1.0 if s == "+" else -1.0 for s in signs]
        self.n_in = len(signs)

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        _same_shape(self, u)
        total = self.signs[0] * u[0]
        for s, v in zip(self.signs[1:], u[1:], strict=True):
            total = total + s * v
        return [np.asarray(total, dtype=np.float64)]


class Product(Block):
    type = "Product"
    category = "Math"
    doc = "Multiplies and divides its inputs elementwise; `ops` has one * or / per input."
    defaults = {"ops": "**"}

    def configure(self) -> None:
        ops = str(self.params["ops"])
        if not ops or set(ops) - {"*", "/"}:
            raise BlockError('ops must be a string of * and /, e.g. "*/"')
        self.ops = ops
        self.n_in = len(ops)

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        _same_shape(self, u)
        out = np.ones_like(np.asarray(u[0], dtype=np.float64))
        for op, v in zip(self.ops, u, strict=True):
            out = out * v if op == "*" else out / v
        return [np.asarray(out, dtype=np.float64)]


class Saturation(Block):
    type = "Saturation"
    category = "Math"
    doc = "Clips the input to [lower, upper]."
    defaults = {"lower": -1.0, "upper": 1.0}

    def configure(self) -> None:
        self.lo = as_signal(self.params["lower"], "lower")
        self.hi = as_signal(self.params["upper"], "upper")
        if np.any(self.lo > self.hi):
            raise BlockError("lower must not exceed upper")

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        return [np.clip(u[0], self.lo, self.hi)]


class Mux(Block):
    type = "Mux"
    category = "Math"
    doc = "Joins its inputs into one vector."
    defaults = {"inputs": 2}

    def configure(self) -> None:
        self.n_in = int(self.params["inputs"])
        if self.n_in < 1:
            raise BlockError("inputs must be at least 1")

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        return [np.concatenate([np.ravel(v) for v in u]).astype(np.float64)]


class Demux(Block):
    type = "Demux"
    category = "Math"
    doc = "Splits a vector into `outputs` equal parts (a scalar each when they divide evenly)."
    defaults = {"outputs": 2}

    def configure(self) -> None:
        self.n_out = int(self.params["outputs"])
        if self.n_out < 1:
            raise BlockError("outputs must be at least 1")

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        v = np.ravel(u[0])
        if len(v) % self.n_out:
            raise BlockError(f"a vector of {len(v)} doesn't split into {self.n_out} equal parts")
        parts = np.split(v, self.n_out)
        return [p[0] if len(p) == 1 else p for p in parts]
