"""The `simview` command: the app by default, `simview run ...` for scripted runs,
`simview runs ...` to investigate them (PRD §5.11), `simview test suite.toml` for scenario
tests (§5.13) and `simview reproduce <run>` to re-run one from its manifest (§5.17)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["run"]:
        from simview.runner.headless import main as run_main

        return run_main(args[1:])
    if args[:1] == ["reproduce"]:
        from simview.runner.reproduce import main as reproduce_main

        return reproduce_main(args[1:])
    if args[:1] == ["test"]:
        from simview.testing.cli import main as test_main

        return test_main(args[1:])
    if args[:1] == ["runs"]:
        from simview.investigate.cli import main as runs_main

        return runs_main(args[1:])
    from simview.ui.app import main as app_main

    return app_main(args)
