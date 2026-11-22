"""Frequency-domain analysis (DA-05): Bode plots of linear systems, and spectra of signals."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal


def _system(sys: Any) -> signal.lti:
    if isinstance(sys, signal.lti):
        return sys
    if isinstance(sys, tuple | list) and len(sys) in (2, 4):
        return signal.lti(*sys)
    raise TypeError("sys must be a scipy.signal.lti, (num, den), or (A, B, C, D)")


def bode(sys: Any, w: Any = None, *, n: int = 200) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Magnitude (dB) and phase (degrees, unwrapped) of a continuous-time SISO system at the
    angular frequencies `w` (rad/s; default `n` log-spaced points chosen by SciPy).
    `sys`: `(num, den)`, `(A, B, C, D)`, or a `scipy.signal.lti`. Returns `(w, mag_db, phase)`."""
    w_out, mag, phase = _system(sys).bode(w=w, n=n)
    return np.asarray(w_out), np.asarray(mag), np.asarray(phase)


def _fs(t: Any, fs: float | None, n: int) -> float:
    if fs is not None:
        if fs <= 0:
            raise ValueError("fs must be positive")
        return float(fs)
    if t is None:
        raise ValueError("give the sample times t or the sample rate fs")
    t = np.asarray(t, dtype=np.float64).ravel()
    if t.size != n:
        raise ValueError(f"y and t need the same length, got {n} and {t.size}")
    dt = np.diff(t)
    if np.any(dt <= 0) or not np.allclose(dt, dt.mean(), rtol=1e-6, atol=1e-12):
        raise ValueError("t must be evenly spaced (resample first)")
    return 1.0 / float(dt.mean())


def fft(y: Any, t: Any = None, *, fs: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """One-sided amplitude spectrum of a real signal: `(freq_hz, amplitude)`, scaled so a
    sinusoid of amplitude A shows a peak of A at its frequency (the mean shows at 0 Hz)."""
    y = np.asarray(y, dtype=np.float64).ravel()
    rate = _fs(t, fs, y.size)
    spec = np.fft.rfft(y)
    amp = np.abs(spec) / y.size
    amp[1:] *= 2.0
    if y.size % 2 == 0:
        amp[-1] /= 2.0  # the Nyquist bin has no mirror image
    return np.fft.rfftfreq(y.size, d=1.0 / rate), amp


def psd(
    y: Any, t: Any = None, *, fs: float | None = None, nperseg: int | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Power spectral density by Welch's method: `(freq_hz, psd)` in units^2/Hz, so its
    integral over frequency is the signal's variance."""
    y = np.asarray(y, dtype=np.float64).ravel()
    rate = _fs(t, fs, y.size)
    f, p = signal.welch(y, fs=rate, nperseg=min(nperseg or 256, y.size))
    return f, p
