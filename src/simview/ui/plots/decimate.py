"""Thinning long signals for drawing: a min and a max per bin (DA-01, D-050). Qt-free.

Peaks survive (unlike plain striding), so a one-sample spike still shows. A live time plot
redraws at PLOT_FPS while rows stream in; `PeakCache` keeps the bins it already reduced, so each
redraw only reduces the newest rows.
"""

from __future__ import annotations

import math

import numpy as np


def _reduce(t: np.ndarray, ys: list[np.ndarray], k: int) -> tuple[np.ndarray, list[np.ndarray]]:
    """Whole bins of k samples -> (bin start, bin end) times and (min, max) values."""
    b = len(t) // k
    tb = t[: b * k].reshape(b, k)
    x = np.empty(2 * b)
    x[0::2] = tb[:, 0]
    x[1::2] = tb[:, -1]
    out = []
    for v in ys:
        block = v[: b * k].reshape(b, k)
        y = np.empty(2 * b)
        y[0::2] = np.fmin.reduce(block, axis=1)  # fmin/fmax skip NaN
        y[1::2] = np.fmax.reduce(block, axis=1)
        out.append(y)
    return x, out


def peak_decimate(
    t: np.ndarray, ys: list[np.ndarray], bins: int
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Thin times `t` and same-length series `ys` to a min and a max per bin (about `bins`).
    The series may be strided views (history columns); short data comes back as it is."""
    n = len(t)
    bins = max(1, bins)
    if n <= 2 * bins:
        return t, ys
    k = n // bins
    m = (n // k) * k
    x, out = _reduce(t, ys, k)
    return np.concatenate([x, t[m:]]), [
        np.concatenate([y, v[m:]]) for y, v in zip(out, ys, strict=True)
    ]


class PeakCache:
    """Incremental `peak_decimate` for data that only grows at the end.

    Bins hold a power-of-two number of samples, chosen so there are between `bins / 2` and
    `bins` of them; the bin size only changes when the data doubles, and then the cache starts
    over. `key` identifies the data (anything that changes when old rows are replaced)."""

    def __init__(self) -> None:
        self.key: object = None
        self.k = 0
        self.done = 0  # samples already reduced into bins
        self.x = np.zeros(0)
        self.ys: list[np.ndarray] = []

    def update(
        self, key: object, t: np.ndarray, ys: list[np.ndarray], bins: int
    ) -> tuple[np.ndarray, list[np.ndarray]]:
        n = len(t)
        bins = max(1, bins)
        if n <= 2 * bins:
            self.key = None
            return t, ys
        k = 1 << max(0, math.ceil(math.log2(n / bins)))
        if (key, k) != (self.key, self.k) or self.done > n:
            self.key, self.k, self.done = key, k, 0
            self.x, self.ys = np.zeros(0), [np.zeros(0) for _ in ys]
        full = (n // k) * k
        if full > self.done:
            x, new = _reduce(t[self.done : full], [v[self.done : full] for v in ys], k)
            self.x = np.concatenate([self.x, x])
            self.ys = [np.concatenate([a, b]) for a, b in zip(self.ys, new, strict=True)]
            self.done = full
        return np.concatenate([self.x, t[full:]]), [
            np.concatenate([y, v[full:]]) for y, v in zip(self.ys, ys, strict=True)
        ]
