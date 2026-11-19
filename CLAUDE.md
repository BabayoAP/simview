# SimView

Read these before doing anything:

1. [`docs/PRD.md`](docs/PRD.md): the source of truth. §0 holds the working rules.
2. [`docs/PROGRESS.md`](docs/PROGRESS.md): which milestone is done, approved, or next.
3. [`docs/DECISIONS.md`](docs/DECISIONS.md): ambiguities already resolved (D-001 onward).

## Working rules (PRD §0, short form)

- Build only `[MVP]` requirements, one milestone at a time, in the §10 order.
- At the end of a milestone: run the tests, map what was built to requirement IDs
  (e.g. `VP-01 ✅`), update `docs/PROGRESS.md`, then **stop and wait for approval**.
- Ask first before: adding a dependency not in §8, changing the §8 architecture, breaking the §7
  design standards, deleting files, or changing a public API from an earlier milestone.
- Ambiguity: pick the simplest reading, record it as the next `D-0xx` in `docs/DECISIONS.md`.
- Every requirement gets a pytest test, or a documented manual check if purely visual.
- No hard-coded style values outside `ui/theme/` (tokens only).
- Work on a branch per milestone (`mN-<name>`), not directly on `main`.

## Commands

```bash
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"   # setup
.venv/bin/simview [--theme light]                           # GUI
.venv/bin/simview run examples/bouncing_ball.py --headless   # headless run
QT_QPA_PLATFORM=offscreen .venv/bin/pytest                   # tests (SIMVIEW_OFFLINE=1 skips downloads)
SIMVIEW_GL=1 .venv/bin/pytest -m gl                           # OpenGL viewport tests (needs a display)
.venv/bin/ruff check . && .venv/bin/ruff format --check .    # lint (ruff 0.17.5, pinned in CI)
```

Stack: Python 3.11+ (dev on 3.12), PySide6 through `qtpy`, type hints everywhere.
Repo: private `BabayoAP/simview`, MIT. CI runs 3 OSes × Python 3.11/3.12 plus lint, and gates
`simview/core` coverage at ≥80%.
