"""Run reports (RI-04): a debrief of one run or a set of runs as one self-contained HTML file.

Each run gets its metadata, every scenario match (run, signals, time window: RI-03), the signals
it doesn't log, plots of the signals involved with the matched windows shaded, and summary
statistics of every signal. A comparison (RI-05) can be added. Plots are inline SVG drawn with
matplotlib in the light theme (§7.6, DS-09), so the file needs nothing else to open.
"""

from __future__ import annotations

import html
import io
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import numpy as np

from simview.investigate.compare import Comparison
from simview.investigate.runs import RunData
from simview.investigate.scenario import ScanResult, Scenario
from simview.ui.theme import tokens  # plain data (loads Qt's modules, needs no display)

FONT_DIR = Path(__file__).resolve().parents[1] / "ui" / "assets" / "fonts"
MAX_SIGNALS_PER_PLOT = 6
DEFAULT_PLOTS = 4  # signals plotted for a run with no matches: its channels, else its first states
FIG_SIZE = (7.5, 2.4)  # inches


def _color(token: str) -> str:
    return tokens.color("light", token)


def _setup_matplotlib() -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager

    for f in FONT_DIR.glob("*.ttf"):
        font_manager.fontManager.addfont(str(f))
    c = _color
    matplotlib.rcParams.update(
        {
            "font.family": tokens.FONT_UI,
            "font.size": tokens.FONT_SIZE["secondary"] * 0.75,  # px -> pt
            "axes.edgecolor": c("border.subtle"),
            "axes.labelcolor": c("text.secondary"),
            "axes.grid": True,
            "grid.color": c("border.subtle"),
            "grid.alpha": tokens.PLOT_GRID_ALPHA * 2,
            "xtick.color": c("text.secondary"),
            "ytick.color": c("text.secondary"),
            "lines.linewidth": tokens.PLOT_LINE_WIDTH * 0.75,
            "legend.loc": "upper right",
            "legend.frameon": False,
            "svg.fonttype": "path",  # text as outlines: the file needs no fonts installed
            "axes.prop_cycle": matplotlib.cycler(color=list(tokens.OKABE_ITO)),
        }
    )


def _label(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def plot_svg(
    run: RunData,
    signals: Sequence[str],
    windows: Sequence[tuple[float, float]] = (),
    units: dict[str, str] | None = None,
) -> str:
    """Signals against time as an inline <svg>, matched windows shaded in `accent`."""
    import matplotlib.pyplot as plt

    _setup_matplotlib()
    units = units or {}
    fig, ax = plt.subplots(figsize=FIG_SIZE, layout="constrained")
    for s in signals[:MAX_SIGNALS_PER_PLOT]:
        ax.plot(run.t, run[s], label=s)
    for a, b in windows:
        if b - a < run.dt:  # a point in time: a line, not an invisible band
            ax.axvline(a, color=_color("accent"), linewidth=tokens.PLOT_REF_WIDTH * 0.75)
        else:
            ax.axvspan(a, b, color=_color("accent"), alpha=0.15, linewidth=0)
    ax.set_xlabel("Time [s]")
    shown = list(signals[:MAX_SIGNALS_PER_PLOT])
    plot_units = {units.get(s, "") for s in shown}
    if len(shown) == 1:
        ax.set_ylabel(_label(shown[0], units.get(shown[0], "")))
    else:
        ax.set_ylabel(_label("Value", plot_units.pop() if len(plot_units) == 1 else ""))
        ax.legend(fontsize="small", ncols=min(3, len(shown)))
    ax.margins(x=0)
    buf = io.StringIO()
    fig.savefig(buf, format="svg")
    plt.close(fig)
    svg = buf.getvalue()
    return svg[svg.index("<svg") :]  # drop the XML prolog: it's inline


def _stats_rows(run: RunData, units: dict[str, str]) -> str:
    rows = []
    for s in run.signals:
        v = run[s]
        finite = v[np.isfinite(v)]
        if not len(finite):
            cells = ["—"] * 4
        else:
            cells = [f"{x:.6g}" for x in (finite.min(), finite.max(), finite.mean(), v[-1])]
        rows.append(
            f"<tr><td>{html.escape(s)}</td><td>{html.escape(units.get(s, ''))}</td>"
            + "".join(f"<td class=num>{c}</td>" for c in cells)
            + "</tr>"
        )
    return "".join(rows)


def _units(run: RunData) -> dict[str, str]:
    import json

    import pyarrow.parquet as pq

    raw = (pq.read_schema(run.info.path).metadata or {}).get(b"simview")
    return dict(json.loads(raw).get("units", {})) if raw else {}


def _run_section(run: RunData, results: Sequence[ScanResult]) -> str:
    info = run.info
    units = _units(run)
    esc = html.escape
    meta = [
        ("Scene", info.scene or "—"),
        ("Source", info.source),
        ("Seed", "—" if info.seed is None else str(info.seed)),
        ("Date", info.date),
        ("Duration", f"{info.duration:.3f} s"),
        ("Samples", f"{info.rows} at {run.dt * 1e3:g} ms"),
    ]
    out = [f"<section><h2>{esc(info.name)}</h2><dl>"]
    out += [f"<dt>{k}</dt><dd>{esc(v)}</dd>" for k, v in meta]
    out.append("</dl>")
    findings = [f for r in results for f in r.findings]
    out.append("<h3>Scenario matches</h3>")
    if findings:
        out.append(
            "<table><tr><th>Scenario</th><th>Start [s]</th><th>End [s]</th>"
            "<th>Duration [s]</th><th>Signals</th></tr>"
        )
        for f in findings:
            out.append(
                f"<tr><td>{esc(f.title)}</td><td class=num>{f.start:.3f}</td>"
                f"<td class=num>{f.end:.3f}</td><td class=num>{f.end - f.start:.3f}</td>"
                f"<td>{esc(', '.join(f.signals))}</td></tr>"
            )
        out.append("</table>")
    else:
        out.append("<p class=muted>No scenario matched in this run.</p>")
    for r in results:
        if r.missing:
            out.append(
                f"<p class=warn>{esc(r.scenario.name)}: not checked, this run doesn't log "
                f"{esc(', '.join(r.missing))}.</p>"
            )
    out.append("<h3>Plots</h3>")
    plotted = False
    for r in results:
        if r.matches and not r.missing:
            sigs = [s for s in r.scenario.signals if s in run]
            if sigs:
                out.append(
                    f"<figure>{plot_svg(run, sigs, [(w.start, w.end) for w in r.matches], units)}"
                )
                out.append(
                    f"<figcaption>{esc(r.scenario.name)}: {esc(', '.join(sigs))}, "
                    "matched windows shaded.</figcaption></figure>"
                )
                plotted = True
    if not plotted and run.signals:
        channels = [s for s in run.signals if "." not in s]
        sigs = (channels or list(run.signals))[:DEFAULT_PLOTS]
        out.append(f"<figure>{plot_svg(run, sigs, units=units)}")
        out.append(f"<figcaption>{esc(', '.join(sigs))}.</figcaption></figure>")
    out.append(
        "<h3>Signals</h3><table><tr><th>Signal</th><th>Unit</th><th>Min</th><th>Max</th>"
        f"<th>Mean</th><th>Final</th></tr>{_stats_rows(run, units)}</table></section>"
    )
    return "".join(out)


def _comparison_section(c: Comparison) -> str:
    esc = html.escape
    out = [
        f"<section><h2>{esc(c.run.info.name)} vs {esc(c.baseline.info.name)}</h2>",
        f"<p>Compared over {c.overlap[0]:.3f}–{c.overlap[1]:.3f} s with tolerance "
        f"{c.atol:g} + {c.rtol:g}·|baseline|.</p>",
        "<table><tr><th>Signal</th><th>Max |Δ|</th><th>RMS Δ</th>"
        "<th>First divergence [s]</th></tr>",
    ]
    for d in sorted(c.signals, key=lambda d: (d.first_divergence is None, d.first_divergence or 0)):
        first = "—" if d.first_divergence is None else f"{d.first_divergence:.3f}"
        out.append(
            f"<tr><td>{esc(d.signal)}</td><td class=num>{d.max_abs:.4g}</td>"
            f"<td class=num>{d.rms:.4g}</td><td class=num>{first}</td></tr>"
        )
    out.append("</table>")
    for label, names in (
        ("Only in the run", c.only_in_run),
        ("Only in the baseline", c.only_in_baseline),
    ):
        if names:
            out.append(f"<p>{label}: {esc(', '.join(names))}</p>")
    for label, matches in (
        (f"Matches only in {c.run.info.name}", c.only_run_matches),
        (f"Matches only in {c.baseline.info.name}", c.only_baseline_matches),
    ):
        for name, ws in matches.items():
            spans = ", ".join(f"{w.start:.3f}–{w.end:.3f} s" for w in ws)
            out.append(f"<p>{esc(label)}: {esc(name)} at {spans}</p>")
    diverged = [d.signal for d in c.diverged][:MAX_SIGNALS_PER_PLOT]
    if diverged:
        firsts = [
            (d.first_divergence, d.first_divergence) for d in c.diverged[:MAX_SIGNALS_PER_PLOT]
        ]
        out.append(
            f"<figure>{plot_svg(c.run, diverged, firsts)}<figcaption>Diverging signals "
            f"in {esc(c.run.info.name)}; lines mark the first divergence.</figcaption></figure>"
        )
    out.append("</section>")
    return "".join(out)


def _css() -> str:
    c = _color
    return f"""
body {{ font-family: {tokens.FONT_UI}, system-ui, sans-serif; color: {c("text.primary")};
  background: {c("bg.app")}; margin: 0 auto; max-width: 960px; padding: {tokens.SPACING[5]}px;
  font-size: {tokens.FONT_SIZE["body"]}px; }}
h1 {{ font-size: {tokens.FONT_SIZE["title"]}px; font-weight: 600; }}
h2 {{ font-size: {tokens.FONT_SIZE["panel_title"]}px; font-weight: 600; margin-top: 0; }}
h3 {{ font-size: {tokens.FONT_SIZE["body"]}px; font-weight: 600; color: {c("text.secondary")}; }}
section {{ background: {c("bg.panel")}; border-radius: {tokens.RADIUS_FLOATING}px;
  padding: {tokens.SPACING[3]}px {tokens.SPACING[4]}px; margin: {tokens.SPACING[3]}px 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: {tokens.FONT_SIZE["secondary"]}px; }}
th, td {{ text-align: left; padding: {tokens.SPACING[0]}px {tokens.SPACING[1]}px;
  border-bottom: 1px solid {c("border.subtle")}; }}
th {{ color: {c("text.secondary")}; font-weight: 600; }}
td.num {{ font-family: "{tokens.FONT_MONO}", ui-monospace, monospace; text-align: right;
  font-variant-numeric: tabular-nums; }}
dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 2px {tokens.SPACING[3]}px; }}
dt {{ color: {c("text.secondary")}; }} dd {{ margin: 0; }}
figure {{ margin: {tokens.SPACING[2]}px 0; }} figure svg {{ width: 100%; height: auto; }}
figcaption, .muted {{ color: {c("text.secondary")}; font-size: {tokens.FONT_SIZE["secondary"]}px; }}
.warn {{ color: {c("state.warning")}; }}
"""


def write_report(
    runs: Sequence[RunData],
    results: Sequence[ScanResult],
    path: str | Path,
    *,
    comparison: Comparison | None = None,
    title: str = "Run report",
) -> Path:
    """One HTML file for `runs`, with their scan `results` (and a comparison, if given)."""
    path = Path(path)
    esc = html.escape
    by_run = {r.info.path: [x for x in results if x.run.path == r.info.path] for r in runs}
    scenarios: list[Scenario] = list({id(x.scenario): x.scenario for x in results}.values())
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width, initial-scale=1'>",
        f"<title>{esc(title)}</title><style>{_css()}</style></head><body>",
        f"<h1>{esc(title)}</h1>",
        f"<p class=muted>SimView, {datetime.now().isoformat(timespec='seconds')}. "
        f"{len(runs)} run{'s' if len(runs) != 1 else ''}, {len(scenarios)} scenario"
        f"{'s' if len(scenarios) != 1 else ''}.</p>",
    ]
    if scenarios:
        parts.append("<section><h2>Scenarios</h2><table><tr><th>Scenario</th><th>Condition</th>")
        parts += [f"<th>{esc(r.info.name)}</th>" for r in runs]
        parts.append("</tr>")
        for sc in scenarios:
            cond = sc.expression or "Python predicate"
            parts.append(f"<tr><td>{esc(sc.name)}</td><td>{esc(cond)}</td>")
            for r in runs:
                hit = next((x for x in by_run[r.info.path] if x.scenario is sc), None)
                cell = (
                    "—"
                    if hit is None
                    else (
                        "missing " + ", ".join(hit.missing)
                        if hit.missing
                        else str(len(hit.matches))
                    )
                )
                parts.append(f"<td class=num>{esc(cell)}</td>")
            parts.append("</tr>")
        parts.append("</table></section>")
    if comparison is not None:
        parts.append(_comparison_section(comparison))
    parts += [_run_section(r, by_run[r.info.path]) for r in runs]
    parts.append("</body></html>\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path
