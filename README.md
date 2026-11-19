# SimView

Build, run, and visualize simulations of robots, vehicles, drones, and dynamic systems, in Python.

> Status: M5b (run investigation: run catalog, scenarios, findings, reports, comparison, log import). See [docs/PRD.md](docs/PRD.md) for the milestone plan and [docs/PROGRESS.md](docs/PROGRESS.md) for where things stand.

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

## Open a scene in the app

```bash
.venv/bin/simview examples/ur5_ik_drag.py   # press Space to run, drag the blue target
```

The simulation runs in its own process, so a crash in scene code shows a traceback in the
console instead of taking the window down. Viewport: right-drag orbits around the point under
the cursor, Ctrl+right-drag pans, the wheel zooms toward the cursor, click selects, `F`/`A` frame
the selection or everything, `1` `3` `7` `0` pick front/right/top/iso, and `Tab` toggles 2D.

Every tick is recorded. The timeline scrubs it: `,` and `.` step back and forward one tick, and
Play from an earlier point replays the run, then carries on live. Drag signals from the Signals
panel onto the Plots panel (time, XY, scatter, histogram); hovering a time plot shows that moment
in the 3D view. Export Data writes every signal to CSV, Parquet, or MATLAB `.mat`; each plot
exports to PNG or SVG in the light theme.

## Investigate runs

Every run is a Parquet log in a run folder (`runs/`; the app saves a run when you press Stop).
Define a pattern once and scan every run for it; each match names its run, signals, and time
window, and clicking it in the app's Runs panel jumps the timeline there.

```bash
.venv/bin/simview runs scan -s "lifted: cube.z > 0.08 for 0.5 s" --save   # every run
.venv/bin/simview runs report <run> -o report.html                         # HTML debrief
.venv/bin/simview runs compare <run> <baseline> --atol 1e-6                # first divergence
.venv/bin/simview runs import robot.csv --time t --map ur5.shoulder_pan_joint.q=j1
```

## Robots

```bash
.venv/bin/simview run examples/ur5_pick.py --headless --duration 5.5   # UR5 picks up a cube
```

```python
import simview as sv
from simview.toolboxes import robotics as rb

scene = sv.Scene(dt=2e-3)
scene.add_ground()
arm = scene.add_robot("ur5", servos="position", gravity_compensation=True)
panda = scene.add_robot("panda", pos=(1.0, 0, 0))  # MuJoCo Menagerie, downloaded on first use
scene.add_box("cube", (0.04, 0.04, 0.04), (0.45, 0.15, 0.02), mass=0.1)
```

Library robots (Franka Panda, UR10e, Robotiq 2F-85) are downloaded once from MuJoCo Menagerie
into `~/.cache/simview` (or `$SIMVIEW_CACHE`), each with its license. Set `SIMVIEW_OFFLINE=1` to
skip the tests that download them.

## Third-party assets

- Library robots (downloaded, not bundled): Panda Apache-2.0, UR10e BSD-3-Clause, Robotiq
  2F-85 BSD-2-Clause, from MuJoCo Menagerie at a pinned commit.
- UR5 robot description and meshes: BSD-3-Clause, from Universal Robots'
  `Universal_Robots_ROS2_Description` (`src/simview/toolboxes/robotics/assets/ur5/`).
- Inter and JetBrains Mono fonts: SIL Open Font License (`src/simview/ui/assets/fonts/`).
- Lucide icons v0.460.0: ISC license (`src/simview/ui/assets/icons/lucide/LICENSE`).

## License

MIT, see `LICENSE`.
