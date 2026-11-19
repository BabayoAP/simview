"""One seeded random generator per run (SE-07)."""

from __future__ import annotations

import numpy as np


def make_rng(seed: int) -> np.random.Generator:
    """Return the run's generator. PCG64 is pinned so a seed means the same stream everywhere."""
    return np.random.Generator(np.random.PCG64(seed))
