"""`simview runs …`: run investigation from the command line (PRD §5.11, headless).

    simview runs list [--filter TEXT]
    simview runs scan [-s "NAME: EXPRESSION"]... [--save]
    simview runs report RUN [RUN...] [-o report.html]
    simview runs compare RUN BASELINE [--atol 1e-6] [--rtol 0] [-o compare.html]
    simview runs import LOG.csv --map ur5.shoulder_pan_joint.q=j1 ... [--time t] [--scene F]

Runs are named by file (with or without .parquet) in the folder given by --folder (default
`runs`). Scenarios come from `-s` and the folder's `scenarios.json`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from simview.investigate.compare import compare
from simview.investigate.importer import import_log
from simview.investigate.report import write_report
from simview.investigate.runs import DEFAULT_FOLDER, Catalog
from simview.investigate.scenario import Scenario, load_scenarios, save_scenarios, scan


def _scenario(text: str) -> Scenario:
    name, sep, expr = text.partition(":")
    if not sep:
        return Scenario(text.strip(), text.strip())
    return Scenario(name.strip(), expr.strip())


def _scenarios(catalog: Catalog, given: list[str] | None) -> list[Scenario]:
    out = {s.name: s for s in load_scenarios(catalog.folder)}
    for s in map(_scenario, given or []):
        out[s.name] = s
    return list(out.values())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simview runs", description="Investigate runs (RI-01..06).")
    p.add_argument("--folder", default=DEFAULT_FOLDER, help="run folder (default: runs)")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="list runs, newest first")
    ls.add_argument("--filter", default="", help="text to match in name, scene, source, date")
    sc = sub.add_parser("scan", help="scan every run for the scenarios")
    sc.add_argument("-s", "--scenario", action="append", help='"name: condition for 0.1 s"')
    sc.add_argument("--save", action="store_true", help="add -s scenarios to scenarios.json")
    rp = sub.add_parser("report", help="write an HTML report")
    rp.add_argument("runs", nargs="+")
    rp.add_argument("-s", "--scenario", action="append")
    rp.add_argument("-o", "--out", type=Path, default=Path("report.html"))
    cp = sub.add_parser("compare", help="compare a run with a baseline")
    cp.add_argument("run")
    cp.add_argument("baseline")
    cp.add_argument("--atol", type=float, default=1e-9)
    cp.add_argument("--rtol", type=float, default=0.0)
    cp.add_argument("-s", "--scenario", action="append")
    cp.add_argument("-o", "--out", type=Path, help="also write an HTML report")
    im = sub.add_parser("import", help="import a CSV or Parquet log as a run")
    im.add_argument("log", type=Path)
    im.add_argument("--map", action="append", default=[], help="signal=column (repeatable)")
    im.add_argument("--time", default="t", help="time column (default: t)")
    im.add_argument("--time-scale", type=float, default=1.0, help="e.g. 0.001 for ms")
    im.add_argument("--scene", type=Path, help="scene file to replay it with")
    im.add_argument("--name", help="run name (default: date and log name)")
    args = p.parse_args(argv)
    catalog = Catalog(args.folder)

    if args.cmd == "list":
        for r in catalog.filter(args.filter):
            scene = Path(r.scene).name if r.scene else "—"
            print(
                f"{r.name:40} {r.source:7} {scene:24} seed {r.seed!s:5} "
                f"{r.duration:8.3f} s  {r.date}"
            )
        return 0
    if args.cmd == "scan":
        scenarios = _scenarios(catalog, args.scenario)
        if not scenarios:
            p.error("no scenarios: pass -s 'name: condition' or add scenarios.json")
        if args.save:
            save_scenarios(catalog.folder, scenarios)
        found = 0
        for res in scan(catalog, scenarios):
            if res.missing:
                print(
                    f"{res.run.name}: {res.scenario.name}: not checked, missing "
                    f"{', '.join(res.missing)}"
                )
            for f in res.findings:
                print(f.describe())
                found += 1
        print(f"{found} match{'es' if found != 1 else ''}")
        return 0
    if args.cmd == "report":
        runs = [catalog.open(r) for r in args.runs]
        scenarios = _scenarios(catalog, args.scenario)
        results = scan(catalog, scenarios, [r.info for r in runs])
        print(write_report(runs, results, args.out))
        return 0
    if args.cmd == "compare":
        run, base = catalog.open(args.run), catalog.open(args.baseline)
        scenarios = _scenarios(catalog, args.scenario)
        c = compare(run, base, atol=args.atol, rtol=args.rtol, scenarios=scenarios)
        for d in c.signals:
            first = (
                "within tolerance"
                if d.first_divergence is None
                else (f"diverges at {d.first_divergence:.3f} s")
            )
            print(f"{d.signal:40} max |Δ| {d.max_abs:10.4g}  {first}")
        for f in c.findings:
            if not f.signals:
                print(f.describe())
        if args.out:
            results = scan(catalog, scenarios, [run.info, base.info])
            print(write_report([run, base], results, args.out, comparison=c))
        return 1 if c.diverged else 0
    if args.cmd == "import":
        mapping = {}
        for m in args.map:
            sig, sep, col = m.partition("=")
            if not sep:
                p.error(f"--map takes signal=column, not {m!r}")
            mapping[sig] = col
        info = import_log(
            args.log,
            catalog,
            mapping=mapping,
            time_column=args.time,
            time_scale=args.time_scale,
            scene=args.scene,
            name=args.name,
        )
        print(f"{info.path} ({info.rows} rows, {info.duration:.3f} s)")
        return 0
    return 2
