"""Run comparison (RI-05): a run against a baseline.

Signals are compared where both runs have samples: on shared ticks when the runs have the same
sample period, otherwise with the baseline interpolated onto the run's times. A signal diverges
where |run - baseline| > atol + rtol·|baseline|; the first such time is a traceable finding.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from simview.investigate.runs import RunData
from simview.investigate.scenario import Finding, Scenario, Window


@dataclass(frozen=True)
class SignalDiff:
    signal: str
    max_abs: float
    rms: float
    first_divergence: float | None  # s, in the run's time; None if within tolerance


@dataclass
class Comparison:
    run: RunData
    baseline: RunData
    atol: float
    rtol: float
    signals: list[SignalDiff] = field(default_factory=list)
    only_in_run: list[str] = field(default_factory=list)
    only_in_baseline: list[str] = field(default_factory=list)
    # scenario name -> windows found in only one of the runs
    only_run_matches: dict[str, list[Window]] = field(default_factory=dict)
    only_baseline_matches: dict[str, list[Window]] = field(default_factory=dict)
    overlap: tuple[float, float] = (0.0, 0.0)

    @property
    def diverged(self) -> list[SignalDiff]:
        return [d for d in self.signals if d.first_divergence is not None]

    @property
    def findings(self) -> list[Finding]:
        """Each divergence and each one-sided scenario match, traceable to its run (RI-03)."""
        out = [
            Finding(
                self.run.info,
                f"diverges from {self.baseline.info.name}",
                (d.signal,),
                d.first_divergence,
                d.first_divergence,
                f"max |Δ| {d.max_abs:.4g}",
            )
            for d in self.diverged
            if d.first_divergence is not None
        ]
        for name, ws in self.only_run_matches.items():
            out += [
                Finding(self.run.info, f"{name} (not in baseline)", (), w.start, w.end) for w in ws
            ]
        for name, ws in self.only_baseline_matches.items():
            out += [
                Finding(self.baseline.info, f"{name} (only in baseline)", (), w.start, w.end)
                for w in ws
            ]
        return out


def _aligned(run: RunData, base: RunData) -> tuple[np.ndarray, np.ndarray]:
    """(the run's times, their indices) where both runs have data."""
    t0, t1 = max(run.t[0], base.t[0]), min(run.t[-1], base.t[-1])
    keep = np.flatnonzero((run.t >= t0 - 1e-12) & (run.t <= t1 + 1e-12))
    return run.t[keep], keep


def _overlaps(w: Window, others: Sequence[Window]) -> bool:
    return any(o.start <= w.end and w.start <= o.end for o in others)


def compare(
    run: RunData,
    baseline: RunData,
    *,
    atol: float = 1e-9,
    rtol: float = 0.0,
    scenarios: Sequence[Scenario] = (),
) -> Comparison:
    out = Comparison(run, baseline, atol, rtol)
    common = [s for s in run.signals if s in baseline.signals]
    out.only_in_run = [s for s in run.signals if s not in baseline.signals]
    out.only_in_baseline = [s for s in baseline.signals if s not in run.signals]
    if len(run.t) and len(baseline.t):
        t, keep = _aligned(run, baseline)
        if len(t):
            out.overlap = (float(t[0]), float(t[-1]))
        same_grid = (
            len(t)
            and abs(run.dt - baseline.dt) < 1e-12
            and np.allclose(np.interp(t, baseline.t, baseline.t), t, atol=1e-9)
        )
        for s in common:
            a = run[s][keep]
            if same_grid:
                idx = np.clip(np.searchsorted(baseline.t, t - 1e-12), 0, len(baseline.t) - 1)
                b = baseline[s][idx]
            else:
                b = np.interp(t, baseline.t, baseline[s])
            diff = np.abs(a - b)
            if not len(diff):
                continue
            # NaN on one side only (e.g. a sensor with no reading yet) is a divergence too;
            # NaN on both sides is not (D-143)
            bad = np.flatnonzero((diff > atol + rtol * np.abs(b)) | (np.isnan(a) != np.isnan(b)))
            finite = diff[~np.isnan(diff)]
            out.signals.append(
                SignalDiff(
                    s,
                    float(finite.max()) if len(finite) else 0.0,
                    float(np.sqrt(np.mean(finite**2))) if len(finite) else 0.0,
                    float(t[bad[0]]) if len(bad) else None,
                )
            )
    for sc in scenarios:
        a, b = sc.scan(run), sc.scan(baseline)
        if a.missing or b.missing:
            continue
        only_a = [w for w in a.matches if not _overlaps(w, b.matches)]
        only_b = [w for w in b.matches if not _overlaps(w, a.matches)]
        if only_a:
            out.only_run_matches[sc.name] = only_a
        if only_b:
            out.only_baseline_matches[sc.name] = only_b
    return out
