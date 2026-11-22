"""DA-05: analysis functions against closed-form answers."""

import numpy as np
import pytest
from scipy import signal

import simview as sv

A = sv.analysis


def second_order(zeta=0.5, wn=2.0, t_end=15.0, n=30001):
    t = np.linspace(0.0, t_end, n)
    _, y = signal.step(([wn**2], [1.0, 2 * zeta * wn, wn**2]), T=t)
    return t, y


def test_step_info_matches_second_order_formulas():
    zeta, wn = 0.5, 2.0
    t, y = second_order(zeta, wn)
    info = A.step_info(y, t, final=1.0)
    wd = wn * np.sqrt(1 - zeta**2)
    assert info["overshoot"] == pytest.approx(
        100 * np.exp(-np.pi * zeta / np.sqrt(1 - zeta**2)), rel=1e-3
    )
    assert info["peak_time"] == pytest.approx(np.pi / wd, abs=1e-3)
    assert info["peak"] == pytest.approx(1 + info["overshoot"] / 100, rel=1e-6)
    # rise and settling: check against the definitions on the analytic response
    ya = 1 - np.exp(-zeta * wn * t) * (
        np.cos(wd * t) + zeta / np.sqrt(1 - zeta**2) * np.sin(wd * t)
    )
    rise = t[np.argmax(ya >= 0.9)] - t[np.argmax(ya >= 0.1)]
    assert info["rise_time"] == pytest.approx(rise, abs=2e-3)
    out = np.nonzero(np.abs(ya - 1) > 0.02)[0]
    assert info["settling_time"] == pytest.approx(t[out[-1] + 1], abs=2e-3)
    assert info["final"] == 1.0


def test_step_info_first_order_downward_and_edge_cases():
    t = np.linspace(0, 10, 10001)
    y = 5.0 - 3.0 * (1 - np.exp(-t))  # falls from 5 to 2, tau = 1 s
    info = A.step_info(y, t, final=2.0)
    assert info["overshoot"] == 0.0
    assert info["rise_time"] == pytest.approx(np.log(9), abs=2e-3)  # 10-90% of a first order
    assert info["settling_time"] == pytest.approx(np.log(50), abs=2e-3)
    still = A.step_info(np.r_[0.0, np.ones(9) * 0.5], np.arange(10.0), final=1.0)
    assert np.isnan(still["rise_time"]) and np.isnan(still["settling_time"])
    with pytest.raises(ValueError):
        A.step_info([1, 1, 1], [0, 1, 2])
    with pytest.raises(ValueError):
        A.step_info([0, 1], [1, 0])


def test_bode_first_order():
    w, mag, phase = A.bode(([1.0], [1.0, 1.0]), w=[0.01, 1.0, 100.0])
    np.testing.assert_allclose(w, [0.01, 1.0, 100.0])
    assert mag[1] == pytest.approx(-10 * np.log10(2), abs=1e-9)
    assert phase[1] == pytest.approx(-45.0, abs=1e-9)
    assert mag[0] == pytest.approx(0.0, abs=1e-3) and mag[2] == pytest.approx(-40.0, abs=1e-3)
    # state-space and lti forms give the same answer
    _, mag_ss, _ = A.bode(([[-1.0]], [[1.0]], [[1.0]], [[0.0]]), w=[1.0])
    assert mag_ss[0] == pytest.approx(mag[1])
    w_auto, _, _ = A.bode(signal.lti([1.0], [1.0, 1.0]), n=50)
    assert len(w_auto) == 50
    with pytest.raises(TypeError):
        A.bode("not a system")


def test_fft_finds_sinusoid_amplitudes():
    fs = 1000.0
    t = np.arange(2000) / fs
    y = 0.5 + 2.0 * np.sin(2 * np.pi * 50 * t) + 0.3 * np.cos(2 * np.pi * 120 * t)
    f, amp = A.fft(y, t)
    assert amp[0] == pytest.approx(0.5, abs=1e-9)
    assert amp[np.argmin(np.abs(f - 50))] == pytest.approx(2.0, abs=1e-9)
    assert amp[np.argmin(np.abs(f - 120))] == pytest.approx(0.3, abs=1e-9)
    f2, amp2 = A.fft(y, fs=fs)
    np.testing.assert_allclose(f2, f) and np.testing.assert_allclose(amp2, amp)
    with pytest.raises(ValueError):
        A.fft(y, np.r_[t[:-1], t[-1] + 0.1])  # uneven
    with pytest.raises(ValueError):
        A.fft(y)


def test_psd_integrates_to_variance():
    rng = np.random.default_rng(0)
    y = rng.normal(0.0, 2.0, 200_000)
    f, p = A.psd(y, fs=100.0, nperseg=1024)
    assert np.trapezoid(p, f) == pytest.approx(4.0, rel=0.03)
    assert f[-1] == pytest.approx(50.0)


def test_rmse():
    assert A.rmse([1, 2, 3], [1, 2, 3]) == 0.0
    assert A.rmse([3, -3]) == 3.0
    assert A.rmse([1, 1], [0, 2]) == 1.0
    with pytest.raises(ValueError):
        A.rmse([])
