"""DA-01: min/max thinning for drawing long signals (D-050)."""

import numpy as np

from simview.ui.plots.decimate import PeakCache, peak_decimate


def test_short_data_is_unchanged():
    t = np.arange(10.0)
    x, (y,) = peak_decimate(t, [t * 2], bins=100)
    assert x is t and np.array_equal(y, t * 2)


def test_peaks_survive_and_range_is_kept():
    n = 100_000
    t = np.arange(n) * 1e-3
    v = np.zeros(n)
    v[12_345] = 5.0  # a one-sample spike
    v[54_321] = -3.0
    v[777] = np.nan  # skipped, not spread
    x, (y,) = peak_decimate(t, [v], bins=500)
    assert len(x) <= 2 * 500 + 2 * (n // 500)
    assert np.nanmax(y) == 5.0 and np.nanmin(y) == -3.0
    assert x[0] == t[0] and x[-1] == t[-1]
    assert np.all(np.isfinite(y))


def test_strided_columns_need_no_copy():
    data = np.random.default_rng(1).normal(size=(5000, 4))
    t = np.arange(5000.0)
    x, ys = peak_decimate(t, [data[:, 1], data[:, 3]], bins=100)
    assert len(ys) == 2 and len(ys[0]) == len(x)
    assert ys[1].max() == data[:, 3].max()


def test_cache_matches_a_full_reduction_as_data_grows():
    rng = np.random.default_rng(0)
    full = rng.normal(size=200_000).cumsum()
    t_full = np.arange(len(full)) * 1e-3
    cache = PeakCache()
    for n in (10_000, 10_500, 40_000, 120_000, 200_000):
        x, (y,) = cache.update("run", t_full[:n], [full[:n]], bins=800)
        assert x[-1] == t_full[n - 1]
        assert y.max() == full[:n].max() and y.min() == full[:n].min()
        assert 400 <= len(x) / 2 <= 800 + cache.k  # bins of 2^m samples
        k = cache.k
        whole = (n // k) * k
        ref = full[:whole].reshape(-1, k)
        np.testing.assert_array_equal(y[: 2 * (whole // k) : 2], ref.min(1))
    done = cache.done
    cache.update("other run", t_full[:1000], [full[:1000]], bins=10)  # new key: starts over
    assert cache.done < done
