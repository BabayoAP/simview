# SimView

Build, run, and visualize simulations of robots, vehicles, drones, and dynamic systems, in Python.

> Status: M1 (skeleton + design system). See the PRD for the milestone plan.

## Install and run

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/simview            # or: simview --theme light
```

## Develop

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

## Third-party assets

- Inter and JetBrains Mono fonts: SIL Open Font License (`src/simview/ui/assets/fonts/`).
- Lucide icons v0.460.0: ISC license (`src/simview/ui/assets/icons/lucide/LICENSE`).

## License

MIT, see `LICENSE`.
