# SimView

Build, run, and visualize simulations of robots, vehicles, drones, and dynamic systems, in Python.

> Status: M2 (core sim engine, headless runs). See [docs/PRD.md](docs/PRD.md) for the milestone plan and [docs/PROGRESS.md](docs/PROGRESS.md) for where things stand.

## Install and run

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/simview            # or: simview --theme light
```

## Headless runs

```bash
.venv/bin/simview run examples/bouncing_ball.py --headless --duration 5
```

Or from Python:

```python
import simview as sv
from simview.runner.headless import load_scene

run = sv.run(load_scene("examples/bouncing_ball.py"), duration=5.0)
run["ball.h"]  # NumPy array, one value per tick
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
