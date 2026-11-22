"""Step-response metrics (DA-05)."""

from __future__ import annotations

from typing import Any

import numpy as np


def _arrays(y: Any, t: Any) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y, dtype=np.float64).ravel()
    t = np.asarray(t, dtype=np.float64).ravel()
    if y.shape != t.shape or y.size < 2:
        raise ValueError(f"y and t need the same length >= 2, got {y.size} and {t.size}")
    if np.any(np.diff(t) <= 0):
        raise ValueError("t must be strictly increasing")
    return y, t


def step_info(
    y: Any,
    t: Any,
    *,
    final: float | None = None,
    initial: float | None = None,
    settle: float = 0.02,
    rise: tuple[float, float] = (0.1, 0.9),
) -> dict[str, float]:
    """Rise time, overshoot, and settling time of a step response, as MATLAB's `stepinfo`.

    `initial` / `final` default to the first / last sample. Rise time goes from `rise[0]` to
    `rise[1]` of the change; overshoot is the peak past `final` in percent of the change;
    settling time is when `y` last enters (and then stays inside) `settle` of the change
    around `final`. Times are measured from `t[0]`; a level never reached gives NaN."""
    y, t = _arrays(y, t)
    y0 = float(y[0]) if initial is None else float(initial)
    yf = float(y[-1]) if final is None else float(final)
    change = yf - y0
    if change == 0:
        raise ValueError("the response doesn't change (initial == final)")
    s = (y - y0) / change  # normalized: 0 at the start, 1 at the final value
    t0 = float(t[0])

    def first_cross(level: float) -> float:
        idx = np.nonzero(s >= level)[0]
        if idx.size == 0:
            return np.nan
        i = int(idx[0])
        if i == 0:
            return float(t[0])
        # linear interpolation between the samples around the crossing
        f = (level - s[i - 1]) / (s[i] - s[i - 1])
        return float(t[i - 1] + f * (t[i] - t[i - 1]))

    rise_time = first_cross(rise[1]) - first_cross(rise[0])
    peak_i = int(np.argmax(s))
    overshoot = max(0.0, float(s[peak_i] - 1.0) * 100.0)
    outside = np.nonzero(np.abs(s - 1.0) > settle)[0]
    if outside.size == 0:
        settling = 0.0
    elif outside[-1] == s.size - 1:
        settling = np.nan  # still outside the band at the end
    else:
        settling = float(t[outside[-1] + 1]) - t0
    return {
        "rise_time": float(rise_time),
        "overshoot": overshoot,
        "settling_time": settling,
        "peak": float(y[peak_i]),
        "peak_time": float(t[peak_i]) - t0,
        "final": yf,
    }
