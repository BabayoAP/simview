# SimView architecture

How the code is put together, for someone about to change it. The PRD (§8) says what the
architecture should be; this file says what was built. Decisions behind the details are in
`DECISIONS.md` (D-0xx).

## The big picture

SimView is two kinds of process:

- **The UI process** (PySide6 through `qtpy`): the windows, the 3D viewport, plots, the block
  editor, the IPython console. It never runs physics.
- **Sim processes**: each one loads a scene file and steps it. The app starts one per live run;
  headless runs, Monte Carlo sweeps and RL vector envs start one per trial or env, with no UI.

The same scene file and the same `Scheduler` run in every case, so a scene behaves the same
live, headless, in a sweep, and as a Gymnasium env.

```
 UI process                                         sim process (one per live run)
 ┌──────────────────────────────────────┐           ┌──────────────────────────────┐
 │ MainWindow                           │  commands │ SimServer (ipc/server.py)    │
 │  viewport · plots · timeline · docks │ ────ZMQ──►│  loads scene.py              │
 │        ▲                             │ ◄───ZMQ── │  Scheduler.step() per tick   │
 │        │ reads                       │   events  │  Logger -> Parquet           │
 │  SimClient (ipc/client.py) ◄─────────┼── shared ─┤  StateBuffer (ipc/shm.py)    │
 │  History (ui/timeline/history.py)    │   memory  │  history rows (ipc/record.py)│
 └──────────────────────────────────────┘           └──────────────────────────────┘
```

## Repository layout

```
src/simview/
  core/         Scene, Entity, Scheduler, integrators, RNG, Logger, live params, debug draw
  physics/      one shared MuJoCo world per scene; URDF/MJCF import
  sensors/      IMU, GPS, seeker, camera, lidar (ray casts through MuJoCo)
  blocks/       block diagrams: model + .svd file, library, compiler, runtime. Qt-free
  ipc/          sim process, client, shared-memory state, history rows, message protocol
  runner/       sv.run + Run handle, headless CLI, Monte Carlo sweeps
  rl/           make_env, make_vec_env, training metrics and recorded episodes
  analysis/     step_info, error stats, Bode and spectra
  investigate/  run catalog, scenarios, findings, reports, comparison, log import
  io/           CSV/.mat import, exports, .svproj projects
  toolboxes/    registry (entry points) and the built-in robotics, aero, vehicles toolboxes
  templates/    one folder per start-screen card, each with a scene.py
  ui/           everything Qt: main window, viewport, plots, timeline, block editor, console,
                start screen, sweep view, training panel, theme/
  cli.py        the `simview` command
```

Everything outside `ui/` is Qt-free. That keeps the engine importable in sim processes and on
headless CI, and lets most of it be tested without a display.

## A scene and one tick

A scene file builds a `Scene` (`core/scene.py`): entities with their own Python dynamics,
MuJoCo robots and objects in one shared world (`physics/world.py`, D-026), sensors
attached to entities, controllers registered with `@scene.controller(rate=...)`, logged
channels, and optionally a block diagram. Scripts and the GUI build scenes the same way (SC-04).

`Scheduler.step()` (`core/scheduler.py`) does one fixed-`dt` tick, always in this order:

1. Each controller that is due (its rate divides into whole ticks) gets `(t, scene, ctx)` and
   returns control inputs, which are written to the named entities. Its debug draws replace
   the ones from its previous call (D-089).
2. Every entity advances its own dynamics by `dt` with its integrator (RK4 or RK45, SE-04).
3. The MuJoCo world steps.
4. The tick count goes up, and each sensor that is due samples (ray-casting sensors get the
   updated geometry first).

Time is `tick * dt`, never a running sum, and all randomness comes from one seeded generator per
run (`core/rng.py`), so the same seed gives byte-identical logs (SE-07, NF-06).

## Logging and runs

`core/logger.py` records one row per tick, one column per signal, and writes Parquet when the run
ends. The file's schema metadata holds a `simview` JSON entry (dt, seed, duration, scene, date,
source, params). That one format is a "run" everywhere: `sv.run(...)` returns a `Run` handle
over it, the Runs panel lists a folder of them (`investigate/runs.py`), scenarios scan them, and
imported robot logs (CSV or Parquet, RI-06) are converted to the same shape.

Where runs go: `runs/` next to the scene file, the project's runs folder for a `.svproj`
project, or `$SIMVIEW_RUNS` if set.

## Sim process and UI

`SimClient` starts the sim process (`multiprocessing`, spawn start method) and talks to it in
three ways:

- **Commands and events** over ZeroMQ: small dicts (run, pause, step, set a parameter, move a
  target; stopped, error with traceback, printed output). A user-code exception pauses the run
  and is shown in the console; the process stays up. If the process dies, `poll()` reports it
  and the UI keeps going (NF-10).
- **Live state** through one shared-memory float64 array (`ipc/shm.py`): entity states, marker
  positions and MuJoCo body poses. A seqlock (odd sequence number while writing) means the UI
  retries rather than reading half a frame.
- **History rows** (`ipc/record.py`): one float64 row per tick with every logged signal and every
  pose. The UI appends them to a `History` (`ui/timeline/history.py`), so the timeline can scrub
  and step back, and the plots can redraw, without asking the sim again. Scrubbing moves the
  viewport and the plot cursor together (VP-05, DA-01).

The scene description (what to draw: meshes, shapes, colors) is plain data built once in the sim
process, so the viewport draws MuJoCo scenes without importing MuJoCo.

## The UI

`ui/app.py` shows the start screen, then a `MainWindow` (`ui/main_window.py`) laid out as PRD
§7.4: Scene Tree and Signals on the left, Inspector and Workspace on the right, the timeline and
Plots along the bottom, Console / Editor, Runs and Training tabbed beside the plots. The centre
is a `QStackedWidget` of pages (3D view, Diagram) rather than swapped widgets (D-054).

- **Viewport** (`ui/viewport/`): PyVista/VTK in Qt. Trails, selection, gizmos, debug draws,
  point clouds, covariance ellipsoids, ViewCube.
- **Plots** (`ui/plots/`): pyqtgraph with SimView's own min/max decimation, because thick
  anti-aliased lines are slow there.
- **Block editor** (`ui/blockeditor/`): a custom `QGraphicsScene` over the Qt-free model in
  `blocks/`. `blocks/compiler.py` orders the blocks, finds algebraic loops, and flattens
  subsystems; `blocks/runtime.py` runs the result inside the scene's tick.
- **Console** (`ui/console/`): an in-process IPython kernel (qtconsole + ipykernel) with `sim`
  and `sv` in its namespace, a Pygments-highlighted editor, and a workspace browser.
- **Theme** (`ui/theme/`): tokens (`tokens.py`) compiled into a Qt stylesheet (`qss.py`) and a
  palette. **No style value lives outside `ui/theme/`**; a test fails on any hex color elsewhere
  (DS-01). Icons are Lucide SVGs tinted per theme; fonts are bundled Inter and JetBrains Mono.

## Batch: headless, sweeps, RL

- `simview run scene.py --headless` and `sv.run(...)` step a scene in this process with no UI.
- `sv.sweep(...)` (`runner/montecarlo.py`) draws every parameter sample up front from the seed,
  runs each trial in a worker process with seed `seed + trial`, and collects metrics into a
  `results.parquet` table that the sweep view opens. Results don't depend on the worker count.
- `sv.make_env` wraps a scene as a Gymnasium env; `sv.make_vec_env` runs N of them in worker
  processes as a Stable-Baselines3 `VecEnv`. Metrics and recorded episodes go to a training
  folder that the Training panel follows and replays (ML-03, ML-04).

Because workers are spawned, scripts that start them need `if __name__ == "__main__":`, and
workers are given a scene file, template id or builder function, never a `Scene` object.

## Toolboxes

A toolbox is a pip package with an entry point in the `simview.toolboxes` group pointing at a
`register(tb)` function, which adds `sv.<module>` names, blocks, entity types, sensors and
templates (`toolboxes/registry.py`, D-119). The built-in robotics, aero and vehicles toolboxes
register through the same entry point (`toolboxes/builtin.py`). Names are imported lazily, and a
toolbox that fails to load is reported and skipped. After changing entry points in
`pyproject.toml`, reinstall with `pip install -e . --no-deps`.

## Tests

- `pytest` runs everything; set `QT_QPA_PLATFORM=offscreen` for UI tests without a window and
  `SIMVIEW_OFFLINE=1` to skip Menagerie downloads.
- `-m gl` (with `SIMVIEW_GL=1` and a real display) runs the viewport tests that need OpenGL.
- Performance tests assert numbers from the dev machine and use a looser bound when `CI` is set,
  since CI renders in software. `benchmarks/nf_bench.py` measures the NF targets.
- CI runs lint and tests on Windows, macOS and Linux, on pull requests to `main` or by hand
  (D-088).
