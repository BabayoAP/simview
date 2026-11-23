"""Error statistics (DA-05)."""

from __future__ import annotations

from typing import Any

import numpy as np


def rmse(a: Any, b: Any = None) -> float:
    """Root-mean-square error between `a` and `b`, or the RMS of `a` alone (an error signal)."""
    a = np.asarray(a, dtype=np.float64)
    err = a if b is None else a - np.asarray(b, dtype=np.float64)
    if err.size == 0:
        raise ValueError("rmse of an empty signal")
    return float(np.sqrt(np.mean(np.square(err))))
