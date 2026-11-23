# SimView

Docs (large: grep or read the section you need, don't load whole files):

- `docs/PROGRESS.md`: read first; which milestone is done, approved, or next.
- `docs/PRD.md`: source of truth. Read §0 (rules) and the current milestone's row in §10, then
  only the requirement sections it names (grep the IDs, e.g. `BD-0`).
- `docs/DECISIONS.md`: resolved ambiguities, D-001 onward. Grep for a topic or D-number; read
  the tail to find the next free number.
- `docs/UX_GUIDELINES.md`: tooltip, help, and guidance rules (sourced); check UI changes
  against its checklist. `docs/USER_GUIDE.md`: the end-user guide; update it with user-facing features.

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

Windows dev box: `.venv/Scripts/…` (Python 3.13, pip, no uv); tests with
`QT_QPA_PLATFORM=offscreen SIMVIEW_OFFLINE=1 SIMVIEW_CACHE=$TEMP/svcache`; GL tests with
`QT_QPA_PLATFORM=windows SIMVIEW_GL=1 -m gl`. Use `--cov=simview` (not `simview.core` alone).

**Verify (definition of done):** lint clean + full test suite green locally (+ `-m gl` when the
viewport changed). Iterate with `pytest tests/<area>` first; full suite once before commit.

Stack: Python 3.11+ (dev on 3.12), PySide6 through `qtpy`, type hints everywhere.
Repo: public `BabayoAP/simview` (since 2026-11-20), MIT. CI (3 OSes × Python 3.11/3.12, lint, `simview/core`
coverage ≥80%) runs only on PRs to `main` or by hand (`gh workflow run CI --ref <branch>`), D-088.
