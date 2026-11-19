"""The `simview` command: the app by default, `simview run ...` for scripted runs."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["run"]:
        from simview.runner.headless import main as run_main

        return run_main(args[1:])
    from simview.ui.app import main as app_main

    return app_main(args)
