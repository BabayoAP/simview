# Progress

Milestone status against the plan in [PRD §10](PRD.md#10-mvp-definition-and-milestone-plan-12-weeks).
Decisions made along the way are in [DECISIONS.md](DECISIONS.md). Newest last.

| Milestone | Status | Branch | Requirement IDs |
|---|---|---|---|
| M1: Skeleton + design system | ✅ Approved 2026-11-18 | `main` | DS-01, DS-02, DS-03, DS-07, DS-08, DS-14 |
| M2: Core sim engine | ✅ Merged to `main` 2026-11-18 | `main` | SE-01, SE-04, SE-05, SE-06, SE-07, SC-04 (+ NF-06, NF-09) |
| M3: Physics + robots | ✅ Approved 2026-11-18 | `main` | SE-03, IO-01, TB-ROBOT (partial, D-023) |
| M3b: Robotics depth (PRD 1.1) | ✅ Approved 2026-11-18 | `main` | RB-01–RB-12, TB-ROBOT (rest) |
| M4: Viewport + IPC | ✅ Approved 2026-11-18 | `main` | SE-02, SE-10, VP-01–VP-07, VP-10, NF-04, NF-10, DS-04–DS-06 |
| M5: Timeline + plots | ✅ Approved 2026-11-19 | `main` | VP-05, DA-01–DA-04, DA-07, DS-09 |
| M5b: Run investigation (PRD 1.2) | ✅ Approved 2026-11-19 | `main` | RI-01–RI-06 |
| M6: Console + workspace | ✅ Approved 2026-11-19 | `main` | SC-01–SC-05, IO-02, IO-04 |
| M7: Block editor | ✅ Approved 2026-11-20 (CI: green except macOS GL, see Next) | `main` | BD-01–BD-08, DS-10 |
| M8: Sensors + Aero/Vehicles toolboxes | ✅ Approved 2026-11-21 | `m8-sensors-aero-vehicles` | SN-01–SN-03, VP-08, VP-09, TB-AERO, TB-VEH |
| M9: Monte Carlo + RL | ✅ Approved 2026-11-22 | `m9-monte-carlo-rl` | SE-08, SE-09, DA-05, DA-06, ML-01–ML-04 |
| M10: Polish + hero demo | In progress | `m10-polish-demo` | NF-01–NF-09, TB-01, TB-02, DS-11 |

## M1: Skeleton + design system

- Theme tokens → QSS (dark and light), bundled Inter / JetBrains Mono fonts and Lucide 0.460.0
  icons, default layout with empty docked panels, start screen with 4 template cards, command
  palette shell.
- CI: ruff (0.17.5, pinned) + pytest on Ubuntu / macOS / Windows × Python 3.11 / 3.12.
- Gate answers from the owner (2026-11-18): D-005 (`accent.fill` #0A6FEE with white text on
  filled controls, dark text on accent declined; light success #1F7A35), D-006 (side panels
  180/200 px, plots 75% of bottom row, §7.2.1 measured on the work area: 68.6%), D-009 (MIT),
  D-010 (pytest-cov added).
- R5 verified: qtconsole in-process kernel runs under PySide6 (D-008). Not a dependency until M6.
- Known cosmetic issue: icons don't re-tint on a live theme switch (D-007).

## M2: Core sim engine

- `simview/core/`: `Scene`, `Entity`, integrators (euler, rk4, rk45), seeded RNG (`sim.rng`),
  fixed-step scheduler `Sim`, Parquet logger.
- `simview/runner/`: `sv.run(...)` → `Run`, `load_scene`, headless CLI
  (`simview run scene.py --headless`). Console script is `simview.cli:main` (D-011).
- `examples/bouncing_ball.py`. 10 repeated runs give byte-identical logs.
- 102 tests, `simview/core` coverage 99%; CI enforces ≥80% on core (NF-09).
- Decisions D-011..D-016. Deferred to M4/M5: `scene.controller(rate=...)`, `ctx.draw`, live
  (non-headless) runs, the 60 Hz render clock (D-016). pandas is not a dependency.

## M3: Physics + robots

- `simview/physics/`: `urdf.py` loads URDF and MJCF (static frames kept, mesh paths resolved,
  bundled robots by name); `mujoco_world.py` adds the `Robot` entity (`scene.add_robot(...)`),
  stepped by MuJoCo with the scene's `dt` next to custom ODE entities (D-018, D-019, D-020).
- `simview/toolboxes/robotics/`: `fk`, `jacobian`, damped-least-squares `ik`, `se3` helpers;
  also `robot.fk/jacobian/ik` and `sv.robotics` (loaded lazily, so `import simview` stays
  MuJoCo-free). Bundled UR5 URDF + STL meshes, BSD-3-Clause (D-017).
- Adds `mujoco>=3.1` (listed in PRD §8).
- Done-when: the UR5 loads ✅; FK matches UR's DH reference within 1e-6 ✅ (worst 6e-10 over
  1,000 configurations, D-021); IK converges within 50 iterations for ≥95% of random reachable
  poses ✅ (98.3–99.0% measured, D-022).
- Requirement IDs: SE-03 ✅ (MuJoCo bodies and custom models in one scene; MJCF and ODE pendulums
  agree within 1e-4 rad over 2 s; gravity compensation holds the arm; mixed-scene logs are
  byte-identical). IO-01 ✅ (meshes, joints, limits, inertials tested for URDF; MJCF import and
  round-trip). TB-ROBOT ◐ (FK, Jacobian, IK, SE(3) basics; see D-023).
- 138 tests (36 new), `simview/core` coverage 99%. Decisions D-017..D-024.

## M3b: Robotics depth

Added by PRD 1.1 (2026-11-18): deeper robotics on SimView's MuJoCo backend, plus the rest of
TB-ROBOT. (1.1 credited this to the wrong "Alloy"; corrected in PRD 1.2, D-037.)

- `physics/world.py`: one shared MuJoCo world per scene; ground, boxes, spheres, cylinders,
  capsules (free or static); world options (integrator, friction cone). `Robot` moved into it
  with M3's API kept (D-026, D-027, D-028, D-031).
- `Robot`: placement (`pos`, `quat`), MJCF strings, mounting on another robot's body or site,
  generated position/velocity servos, `set_targets` with clamping and ramps, `set_controls`,
  gravity compensation, adjacent-link contact exclusion (D-029, D-032).
- `scene.controller(rate=...)` from PRD §8.3, without `ctx.draw` (D-033).
- Robotics toolbox: `JointPID` (PID / impedance), `DifferentialIK`, `OperationalSpace`,
  `inverse_dynamics` / `gravity_torques` / `bias_forces` / `mass_matrix`, `trajectory`
  (cubic, quintic, trapezoidal), `frames` / `frame_tree` / `transform`, and `library`
  (Menagerie Panda, UR10e, Robotiq 2F-85, downloaded on first use, D-034).
- `examples/ur5_pick.py`: UC-3 pick-and-lift, runs headless from the CLI.
- Done-when: pick up a cube and lift it 10 cm under differential IK ✅ (UR5 + scripted gripper,
  9.9 cm, D-035); operational-space control tracks a task-space step within 1 mm ✅; inverse
  dynamics matches forward dynamics within 1e-6 ✅ (worst 5e-12); all M3 tests still pass ✅.
- Requirement IDs: RB-01 ✅ RB-02 ✅ RB-03 ✅ RB-04 ✅ RB-05 ✅ RB-06 ✅ RB-07 ✅ RB-08 ✅
  RB-09 ✅ RB-10 ✅ RB-11 ✅ RB-12 ✅; TB-ROBOT ✅ (complete with M3).
- 197 tests (59 new; network tests download about 70 MB once), `simview/core` coverage 99%.
  Decisions D-025..D-036.

## M4: Viewport + IPC

- `simview/ipc/`: the sim runs in its own process (SE-02): seqlocked shared-memory state, ZeroMQ
  commands and events, real-time pacing at 0.1×–10× or flat out (SE-10), tracebacks and `print`
  output in the console, crash reporting and restart (NF-10) (D-038, D-039).
- `simview/ui/viewport/`: PyVista viewport. `model.py` and `navigation.py` are OpenGL-free
  (geometry, matrices, grid, trails, draws, camera math); `view.py` draws them, with SimView's own
  mouse and key handling, picking, outlines on an overlay layer, ViewCube, triad, heads-up toolbar,
  HUD, scale bar, and gizmos (D-041, D-042, D-043).
- Main window: Open Scene (or `simview scene.py`), run/pause/step/stop, speed, live RTF, scene tree,
  inspector with joint sliders, console; one selection and hover shared by all (DS-06) (D-047).
- Scene API: `ctx.draw`, `scene.add_target`, `scene.add_visual`, `scene.trail`, `Entity.position()`
  (D-045). `examples/ur5_ik_drag.py` is the UC-3 drag demo.
- Done-when: the UC-3 IK drag demo works live ✅ (test: with the sim running, a target move the
  gizmo emits brings the tool within 5 mm; GL test: the gizmo reports its moves); killing the sim
  process doesn't crash the UI ✅ (test: kill, UI reports it, Run restarts).
- Requirement IDs: SE-02 ✅ SE-10 ✅ VP-01 ✅ VP-02 ✅ VP-03 ✅ VP-04 ✅ VP-05 ◐ (play, pause, step
  forward, speeds; scrubbing and step back are M5, D-040) VP-06 ✅ VP-07 ✅ VP-10 ✅ NF-04 ✅
  (median 4.8 ms) NF-10 ✅ DS-04 ✅ DS-05 ✅ (SimView preset; other presets with Settings, D-042)
  DS-06 ✅ (viewport, tree, inspector; plots in M5).
- Measured: 62 fps at 1000×700 with 4× MSAA on a GTX 1050 Ti (D-046).
- 250 tests (53 new), 11 of them `gl` tests that need a display (D-044); `simview/core`
  coverage 90%. CI adds a GL job on Linux and macOS.

### Manual checks (visual, §0 rule 5)

Checked from rendered screenshots on the development machine: robot meshes with feature edges,
fading grid, per-body frames, triad, ViewCube, heads-up toolbar (icons in `text.secondary`,
active toggles in `accent`), HUD in the lower right, accent selection outline visible through the
arm, target gizmo arrows and rings, 2D top view with the scale bar and the ViewCube hidden.
Screenshots caught and fixed: the camera re-framing to the whole grid, the HUD over the ViewCube,
a gizmo too small to see, toolbar icons dimmed by their own backdrop, the HUD over the scale bar,
and the ViewCube still drawn in 2D. Debug draws are covered by the GL tests, not by eye.

Not checked by me (needs a person at the mouse): how dragging the gizmo, orbiting, and zooming
feel; the ViewCube's click-to-view animation; the light theme in the viewport; high-DPI scaling;
how debug-draw lines look on macOS (its OpenGL draws wide lines another way; the GL tests
check the batched geometry, not the pixels).

## M5: Timeline + plots

- Recording (D-049): the sim process records every tick (signals, markers, body poses) and
  streams the rows to the UI with each state frame; `ui/timeline/history.py` holds them.
- Timeline (D-048): scrub slider, step back `,` / forward `.`, start and live-end buttons, and
  Play from a past row replays the recording at the playback speed, then hands over to the live
  sim. The readout shows `t = … s / … s` and `live` or `replay`.
- Signals panel: every logged channel grouped by entity, with units (D-052); drag (one signal or a
  whole entity) onto the Plots panel, or double-click.
- Plots (`ui/plots/`, pyqtgraph): time, XY, scatter, and histogram plots (D-051); the synced time
  cursor; hover crosshair readout of every trace; hovering previews that time in the viewport,
  clicking seeks; trace click selects the entity (DS-06); min/max thinning for speed (D-050).
- Exports (D-053): Export Data (all signals) to CSV, Parquet, `.mat`; each plot to PNG or SVG in
  the light theme.
- M4 fixes found while checking on screen (D-054): the 3D view vanished from the main window once
  a scene was opened; black panels in the light theme; OS accent colors on sliders and tree
  selection; a pyqtgraph menu leak.
- Done-when: scrubbing moves the viewport and plot cursor together within 100 ms ✅ (test, no-GL
  view: every scrub < 100 ms with the viewport frame, plot cursor, and readout checked; GL test:
  the real viewport re-posed and rendered, median < 100 ms; measured 54–73 ms at 1440×900 with
  the UR5 and a plot).
- Requirement IDs: VP-05 ✅ (scrubbing and step back added to M4's transport) DA-01 ✅ (10 × 100k
  samples: median 25 ms per update, about 40 FPS) DA-02 ✅ DA-03 ✅ DA-04 ✅ DA-07 ✅ DS-09 ✅
  (units on axes, light grid, legend top right, mono tick labels, 1.5 px data, 1 px accent cursor,
  light-theme exports) DS-06 ✅ (plots and the signal tree now join the shared selection).
- 294 tests (44 new; 13 of them `gl`); `simview/core` coverage 91%. New dependency: `pyqtgraph`.

### Manual checks (visual, §0 rule 5)

Checked from screen captures of the main window at 1440×900 in both themes, with the UR5 drag
scene recorded and scrubbed: the 3D view in the central area, timeline (accent slider, readout),
signal tree with units, time plots with legend, accent cursor, and hover readout, and a PNG export
in the light theme. The captures found and fixed: the missing 3D view (D-054), black light-theme
panels, OS-colored sliders and selection, values rescaled by SI prefixes (0.15 m shown as 150),
legends clipping short plots, legend text invisible in light exports, truncated signal names (now
elided in the middle so `.q`/`.v` stay visible), and a plot's x label cut off at the default
panel height.

Not checked by me (needs a person at the mouse): dragging signals from the tree onto plots (the
tests drive the drop handler, not a real drag), how scrubbing and replay feel, zooming and panning
a plot by hand, and the XY, scatter, and histogram plots by eye (tested, not screenshotted).

## M5b: Run investigation

- `simview/investigate/` (headless, Qt-free except the report's color tokens): the run catalog
  (`runs.py`), scenarios and scanning with a cache (`scenario.py`), comparison (`compare.py`),
  HTML reports (`report.py`), log import (`importer.py`), and `simview runs list|scan|report|
  compare|import` (`cli.py`).
- Runs carry their source, units, and parameters in the log, and their date and scene file in a
  `<run>.run.json` sidecar, so same-seed logs stay byte-identical (D-056).
- App: a Runs panel (tabbed with the console) lists the run folder's runs with a filter; Stop
  saves the live run and scans it; scenarios are typed as `name: condition for 0.1 s`; findings
  are grouped by run and clicking one opens the run (replayed through its scene, D-058) and moves
  the timeline, viewport, and plots to its window; Report, Compare, and Import act on the
  selection.
- Scrubbing renders once per move now (D-062).
- Done-when:
  - A scenario defined once finds every injected event across 20 runs with no misses and no false
    matches ✅ (test: 20 seeded runs, 1–3 events each, plus 0.04 s near misses and long
    sub-threshold stretches that must not match; windows checked to 1e-9 s).
  - A report for the UC-3 pick run exports with its plots ✅ (test: `ur5_pick.py` run 5.5 s,
    scenarios "cube lifted" and "fingers closed" plotted as inline SVG, a missing-signal note,
    statistics with units, no scripts or external links).
  - Clicking a finding moves the timeline to it within 100 ms ✅ (test, no-GL view; measured
    49–62 ms with the OpenGL viewport at 1440×900).
  - An imported CSV log replays in the viewport ✅ (test: a CSV of UR5 joint angles, mapped onto
    the robot; the viewport's frame has the logged joints, the FK tool position, and body poses).
- Requirement IDs: RI-01 ✅ RI-02 ✅ RI-03 ✅ RI-04 ✅ RI-05 ✅ RI-06 ✅.
- 325 tests (31 new, 13 of them `gl`); `simview/investigate` coverage 97%, `simview/core` 91%.
  New dependency: `matplotlib` (PRD §8.1).

### Manual checks (visual, §0 rule 5)

Checked: the Runs panel in the light theme (two app runs, two scenarios, grouped findings), and a
run report rendered by a browser (scenario table, the matched window shaded on the plot, the
signal table with units). Not checked by me: the panel in the dark theme and inside the full
window (the screen was locked by then, so window captures came back blank; the panel was
captured on its own), the Import mapping dialog by hand, and a comparison report by eye (tested).

## M6: Console + workspace

- `simview/core/params.py`: live parameters. A scene declares `scene.params.kp = 2000.0`;
  controllers read `ctx.params.kp`; scalars are logged as `params.<name>` (D-064, D-065).
  New `"param"` command and `"params"` event between the UI and the sim process.
- `simview/ui/console/`: the IPython console on an in-process kernel with `sim`, `sv`, and `np`
  (`kernel.py`, `handle.py`, D-066, D-067), the editor (`editor.py`, D-068), and the workspace
  browser with an array table viewer (`workspace.py`, D-069). Sim output and tracebacks now go
  to the IPython console (the M4 text console is gone).
- `simview/io/data.py` (CSV, .mat, D-071) and `simview/io/project.py` (`.svproj`, D-072);
  File menu: New Project, Open Project, Save Project, Import Data.
- Fixed along the way: a new sim process re-ran the last `%run` script (D-067).
- `examples/ur5_ik_drag.py` declares `max_step` (the IK step size) as a live parameter.
- Done-when:
  - `sim.params` changes take effect on the next tick ✅ (tests: in the core, across the
    process, and typed in the console: `sim.params.force = 4.0` while paused, one step, the
    cart's velocity is exactly 4.0 · dt and the `params.force` column changes on that tick).
  - A project round-trips save → load ✅ (test: scene + script + a run saved into a new
    project, a new window opens it: same scene from `scenes/`, same script text, the run in
    the Runs panel).
- Requirement IDs: SC-01 ✅ SC-02 ✅ SC-03 ✅ SC-04 ✅ (from M2; the console's `sim.scene`
  and the app build the same `Scene` from the file) SC-05 ✅ IO-02 ✅ IO-04 ✅.
- New dependencies: `qtconsole`, `ipykernel`, `pygments` (all in PRD §8.1, D-063). PySide6 is
  kept below 6.12 on Python 3.11, where 6.12.0 crashes the interpreter (D-074).
- 348 tests (36 new); `simview/core` coverage stays above 90%.

### Manual checks (visual, §0 rule 5)

Checked from offscreen renders in both themes: the console (banner, prompts in the accent
color, a sim traceback in the error color on its own line, JetBrains Mono), the editor (line
numbers, highlighting, toolbar), and the workspace (Name / Value / Shape / Type). Not checked:
the array table viewer and the Import / New Project file dialogs by eye (both tested), and the
console on a real display alongside the 3D view.

## M7: Block editor

Engine (Qt-free, `simview/blocks/`, built on the Mac):
- `graph.py`: the diagram model, editing (add, connect, remove, rename), `group` / `ungroup`
  into subsystems, and `.svd` JSON files (D-079, D-080).
- `library/`: the BD-02 blocks in one file per family, plus Python Function (BD-03), Entity
  State / Entity Input (BD-04), and Inport / Outport; `register` for toolbox blocks (D-076).
- `compiler.py`: flattening, topological order, algebraic-loop detection, and per-block
  problems with shape probing (BD-05, D-077). A block fed by a failed block no longer also
  reports "not connected" (D-084).
- `runtime.py` + `scene.add_diagram(...)`: diagrams run as sampled systems in the scene and
  every block output is logged (D-075, D-078). The sim process describes each diagram's file
  and its Scopes' signals to the UI.

Editor (`simview/ui/blockeditor/`):
- `document.py`: the edited diagram, the shown subsystem level, undo / redo as JSON snapshots,
  and a re-check after every edit against a stand-in for the scene's entities (D-083, D-084).
- `canvas.py`: the §7.7 canvas: dot grid with 8 px snap, rounded blocks with a semibold title
  and a category strip, ports colored by signal type, orthogonal wires with rounded corners,
  live values on wire hover, red outlines with the message under the block, pan / zoom / fit,
  drag-to-connect, rubber-band selection (D-086, D-087).
- `palette.py`: quick-add on double-click, searching the library in §7.7 category order.
- `params.py`: name and parameters of the selected block, its problems, one undo step per edit.
- `editor.py`: toolbar (New, Open, Save, Undo, Redo, Group, Ungroup, Up, Fit), breadcrumbs,
  problem count, shortcuts.
- In the window: "3D View" / "Diagram" pages switched from the toolbar (D-082); the scene's
  diagram opens when it loads; each Scope block's plot is docked in the plot panel (BD-08);
  saving a diagram the scene runs reloads it (D-085); projects keep the open diagram.
- New tokens: category and port colors (≥ 3:1 in both themes, tested) and the canvas sizes.
  New QSS: error labels, mono line edits, the checked state of toolbar buttons.

- Done-when ✅: `examples/drone_altitude/` runs the same PID as a script and as a diagram; the
  flights match within 1e-9 (exactly; `tests/blocks/test_pid_match.py`). Vertical drone
  dynamics stand in for the M8 quadrotor (D-081). In the app, `blocks.py` opens the diagram,
  docks the `altitude.altitude` Scope (target and altitude), and hovering the PID's output wire
  shows its value at the timeline cursor (`tests/ui/test_blockeditor.py`).
- Requirement IDs: BD-01 ✅ BD-02 ✅ BD-03 ✅ BD-04 ✅ BD-05 ✅ BD-06 ✅ BD-07 ✅ BD-08 ✅
  DS-10 ✅ (tests for the canvas, problems, quick-add, parameters, subsystems, contrast; the
  look is a manual check below).
- 383 tests (22 new in `tests/ui/test_blockeditor.py`, 17 in `tests/blocks/` from part 1),
  lint clean with ruff 0.17.5, run locally on Windows (Python 3.13); `core` + `blocks` +
  `ui/blockeditor` coverage 88%. Under coverage, the M5 plot redraw timing test misses its
  33.3 ms bound by 0.4 ms on this machine (it passes without coverage; unrelated to M7).
  CI hasn't run on the M7 commits yet: GitHub refused to start the jobs (account billing /
  spending limit). Re-run CI once that's sorted.
- No new dependencies.

### Manual checks (visual, §0 rule 5)

Checked from offscreen renders of the whole window in both themes, with the drone scene
loaded and run for 3 s: the canvas (dot grid, category strips, semibold titles, port colors,
rounded orthogonal wires, the selected PID's accent outline), the parameter panel, the docked
Scope plot, and the toolbar's page switch. Problems (missing entity, unconnected inputs) show
as red outlines with the message under each block. Not checked by eye: dragging, the
quick-add popup, and the wire-hover tooltip on a real display (all three are tested).

## M8: Sensors + Aero/Vehicles toolboxes

- Part 1 (`3193fd1`): sensors in `simview/sensors/` (IMU, GPS, seeker, camera, lidar) mounted
  with `entity.attach(...)` and logged as `<entity>.<sensor>.<field>`; `scene.attach_shape`
  gives custom entities a MuJoCo solid (D-090); `ctx.draw.points` / `ellipsoid` (VP-08, VP-09);
  a controller's draws last until it runs again (D-089). D-089..D-093. **No sensor tests yet.**
- Part 2 (`9334f83`): Vehicles toolbox `sv.vehicles` (TB-VEH): kinematic bicycle, paths and
  roads with lanes, pure pursuit, Stanley, speed control, scripted NPCs (D-094..D-097);
  15 tests in `tests/toolboxes/vehicles/`.
- Part 3 (`2681d86`): UC-1 Autonomous Vehicle template (`src/simview/templates/av_scenario/`),
  loaded by its start-screen card (D-098). A 30 s run: about 27x real time headless, lane kept
  within 8 cm through the bend, 8.7 m closest gap behind the braking NPC, settles at 18 m /
  8 m/s; 5 tests (`tests/templates/`, `tests/ui/test_scene_session.py`).
- Part 4: sensor tests and the viewport side of VP-08 / VP-09. `tests/sensors/` (22 tests):
  IMU at rest and under acceleration + yaw rate, bias/noise statistics, sample-and-hold and
  `updated()`, seeded per-sensor noise (D-091), GPS mount offset and noise, seeker geometry
  and `rbe` round trip, lidar ranges to a wall and the ground (own solid excluded), max range,
  noise, camera color/depth/sky/intrinsics/determinism, logged `<entity>.<sensor>.<field>`
  channels, cloud and ellipsoid draw data. The viewport didn't draw `cloud` or `ellipsoid`
  draws at all: it now does (one points actor per cloud; translucent shells batched by color,
  `tokens.ELLIPSOID_OPACITY` 0.25). GL tests: a cloud keeps its points and an ellipsoid's
  shell spans its semi-axes; a 200k-point cloud replaced and drawn each frame has a median
  frame time under 33 ms (VP-08) on the Mac. Checked by eye: a 32-beam scan and a 2-sigma
  ellipsoid in the dark theme.
- Gizmo fix (`fix/gizmo-drag`, PR #1, cherry-picked here): dragging targets didn't work
  because SimView's interactor style lacked PyVista's `_parent` link.
- 425 tests pass (Mac, Python 3.12, offline: 20 skipped), plus all 16 GL tests with
  `QT_QPA_PLATFORM=cocoa SIMVIEW_GL=1` (they do run from a Claude terminal with cocoa); lint
  clean.
- Rescope (`7bddf22`, PRD 1.3, D-099): UC-2 is now a drone delivery fleet, still the hero demo.
- Part 5: Aerospace toolbox `sv.aero` (TB-AERO): `Quadrotor`, `AttitudeController`,
  `PositionController`, `Wind`, `Route` and `RouteFollower`, `EKF`, `UKF`, `NavFilter`, `nees`
  (D-100..D-105); 18 tests in `tests/toolboxes/aero/`: free fall and hover, spin-up, clipping,
  drag in wind, commanded acceleration and tilt limit, position step, gust statistics and
  correlation, seeded repeatability, route order / dwell / deviation, EKF equals the linear KF,
  UKF equals the EKF on a linear model, both converge on range-only fixes, and the GPS + IMU
  filter flying a gusty route by its own estimate stays 3-sigma consistent (EKF and UKF).
  443 tests pass, lint clean.
- Part 6: UC-2 Drone Delivery template (`src/simview/templates/drone_delivery/`), opened by its
  start-screen card. Three quadrotors (IMU 200 Hz, GPS 10 Hz, EKF `NavFilter`, `RouteFollower`)
  fly depot -> drop-off (3 s hover at 3 m) -> depot at 15 m through gusty wind, steering by the
  estimate. Params `gps_noise`, `imu_noise`, `gust`, `cruise_speed`, `cruise_alt` are the M9
  sweep knobs. Logged: per-drone error and +-3 sigma bounds per axis, error norm, route
  deviation, delivery time; wind speed. Draws: routes, 3-sigma ellipsoids, the wind arrow.
  A 60 s run: all three deliver at 20.6-22.6 s and land back on their pads; RMS error
  0.20-0.22 m (GPS noise 0.8 m), inside 3 sigma 99.7-100% of the time, route deviation under
  0.45 m in gusts up to 7.9 m/s. 7 tests (`tests/templates/test_drone_delivery.py`, the card
  in `tests/ui/test_scene_session.py`). Checked by eye in the dark theme.
- Performance: the quadrotor dynamics and route distance were rewritten for speed and the
  template logs controller-rate values, taking UC-2 from 1.9x to 6.5x real time headless at
  dt = 1 ms. NF-03 asks for 10x: the rest is the Python RK4 loop and the per-tick logger, left
  for the M10 performance pass.
- 450 tests pass (Mac, Python 3.12, offline: 20 skipped), 16 GL tests pass, lint clean.
- Not in M8 (per the PRD milestone table): the 50-trial Monte Carlo and its histogram (SE-08,
  DA-06: M9) and the UC-2 hero demo with a block-diagram version of the loop (M10).
- D-081 rerun: `tests/toolboxes/aero/test_pid_quadrotor.py` flies the M7 altitude PID
  (`examples/drone_altitude/altitude.svd`) on the 6-DOF `sv.aero.Quadrotor` (thrust only), as a
  diagram and as a script: x, y, z, vz and qw match within 1e-9, it climbs to 2 m and holds,
  and the body stays level over its start point. The M7 example itself keeps its 1-D model.
- Verified on Windows (Python 3.13, GTX 1050 Ti): 451 tests pass (offline: 20 skipped), all
  16 GL tests pass with `QT_QPA_PLATFORM=windows SIMVIEW_GL=1` (incl. the 200k-point cloud at
  30 FPS), lint and format clean.
- Done-when: the UC-1 and UC-2 templates run end to end ✅ (headless in
  `tests/templates/`, and from their start-screen cards in `tests/ui/test_scene_session.py`).
- Requirement IDs: SN-01 ✅ (IMU, GPS, seeker: `tests/sensors/`) SN-02 ✅ (pinhole camera:
  color, depth, intrinsics, rate, determinism) SN-03 ✅ (MuJoCo ray lidar: beams, FOV, range,
  noise) VP-08 ✅ (cloud draws; 200k points under 33 ms per frame, GL test) VP-09 ✅ (ellipsoid
  from covariance and sigma; GL test) TB-AERO ✅ (`tests/toolboxes/aero/`, UC-2 template)
  TB-VEH ✅ (`tests/toolboxes/vehicles/`, UC-1 template).
- Not met yet: NF-03's 10x real time for UC-2 (6.5x now), left for the M10 performance pass
  (see above).

### Manual checks (visual, §0 rule 5)

Dark theme on the Mac (parts 4 and 6). Light theme on Windows: both templates opened from
their cards and run live in the app (UC-2 for 15 s, UC-1 for 10 s), whole window captured from
the screen. UC-2: routes, depots and pads, the wind arrow, and the ground shadow read clearly on
the light background. UC-1: road edges, dashed lane line, the ego's path, NPC boxes, and the
lidar cloud (blue rings) are visible. At the default camera distance the quadrotors and their
3-sigma ellipsoids (about 0.2 m) can't be made out (not checked zoomed in). The viewport's
FPS readout showed 21-22 with the sim running live on this machine, for both templates
(VP-08's 30 FPS GL test measures rendering alone and passes).

## M9: Monte Carlo + RL (approved 2026-11-22)

Plan: (1) analysis functions + sweep runner, (2) results view, (3) `make_env` + VecEnv +
drone-landing env, (4) training panel + click-to-replay, then the PPO done-when.

- Part 1: `sv.sweep(scene_file, duration, params=..., grid=..., trials=..., workers=...)` runs
  trials in spawned processes and returns `SweepResults` (one Parquet table: trial, seed,
  params, metrics, status, error, wall time). Distributions `sv.Uniform`, `sv.Normal`,
  `sv.Choice`. Scene files declare metrics with `scene.metric(name, fn)`; `load_scene(path,
  params=, seed=)` overrides parameters at declaration (D-106..D-108). UC-2 declares
  `delivery_time`, `delivered`, `rms_error`, `max_deviation`. `sv.analysis`: `step_info`,
  `bode`, `fft`, `psd`, `rmse` on SciPy (DA-05, D-109). `Run[column]` reads one column (D-110).
  Also fixed CI: the VP-08 GL frame bound is loose under software rendering (on the M8 branch).
- 50-trial UC-2 Monte Carlo (gust ~ U(0.5, 3) m/s, GPS noise ~ U(0.3, 1.5) m, 60 s each,
  16 workers on the Windows box): finishes in 272 s, 0 failures, all 3 drones deliver in every
  trial (22.4-23.0 s), RMS estimation error 0.10-0.43 m (correlation with GPS noise 0.96), max
  route deviation 0.27-1.02 m. One UC-2 run alone is 1.65x real time on this machine (6.5x on
  the Mac).
- Part 2: results view (DA-06, D-111): `ui/sweep_view.py`, opened from File → Open Sweep
  Results… or `window.open_sweep(...)`. Trials table (sortable, failures in red with the error),
  histogram of any metric, scatter of the metric against any parameter, selection linked both
  ways. 5 tests in `tests/ui/test_sweep_view.py`. Checked by eye in both themes on the 50-trial
  UC-2 sweep (RMS error vs GPS noise: a clean rising line).
- 471 tests pass after part 2 (Windows, offline: 20 skipped); part 1 added 15 in `tests/runner/test_montecarlo.py`
  (incl. a 50-trial parallel sweep) and `tests/analysis/` (closed-form checks). Lint clean.
- Part 3: `sv.make_env` (D-112, D-113) and `sv.make_vec_env` (D-114) in `simview/rl/`, the
  `rl` extra and CPU-only PyTorch in CI (D-115). Drone Landing template (UC-4): quadrotor with its
  attitude loop at 100 Hz, policy at 25 Hz commanding acceleration, random start in a 8 x 8 x 4 m
  box, potential-based shaping, +100 for a soft landing on the pad. Without a policy a PD lander
  flies it (18/20 soft landings from random starts). One env: about 840 env steps/s.
- Part 4: training folder, `sv.log_metric`, `sv.rl.sb3_logger()`, episode recording
  (`record_every=N`), TensorBoard reader, Training panel with click-to-replay (D-116). Fixed the
  end of a replayed run showing the start state.
- **Done-when (PPO):** PPO (SB3 defaults except n_steps 256, batch 1024) with 12 subprocess envs,
  400k steps: 159 s of training on the Windows box, recording every 40th episode per env.
  Evaluated deterministically on 100 new random starts: **100/100 soft landings**, about 5 s per
  episode. Training-time success (stochastic policy) reached 88% over the last 100 episodes.
  In the app, the Training panel showed the run's curves and 72 recorded episodes; clicking one
  replayed it in the viewport with its trail (checked by eye, both themes).
- Tests: `tests/rl/test_env.py` (env checker on a custom scene and the template, seeding, step
  timing, ctx.action, termination on the exact tick, success info, argument errors, headless
  baseline, subprocess and in-process vec envs, a short PPO run, recording + replayable logs),
  `tests/rl/test_metrics.py` (event-file reader with a partial record, log tailing, SB3 logger),
  `tests/ui/test_training_panel.py` (panel follows runs, plots, picks up new episodes and newer
  runs, restyles; click replays). 486 tests pass (Windows, offline; 20 skipped). Lint clean.

### M9 requirement mapping

| ID | Status | Where / test |
|---|---|---|
| SE-08 | ✅ | `runner/montecarlo.py`; `tests/runner/test_montecarlo.py` (50-trial parallel sweep) |
| SE-09 | ✅ | `rl/vec_env.py`; `test_vec_env_in_subprocesses_is_an_sb3_vec_env` |
| DA-05 | ✅ | `analysis/`; `tests/analysis/test_analysis.py` |
| DA-06 | ✅ | `ui/sweep_view.py`; `tests/ui/test_sweep_view.py` + manual check, both themes |
| ML-01 | ✅ | `rl/env.py`; `test_custom_scene_env_passes_env_checker`, `test_template_env_passes_env_checker` |
| ML-02 | ✅ | `rl/vec_env.py`; `test_in_process_vec_env_and_a_short_ppo_run` |
| ML-03 | ✅ | `rl/metrics.py`, `ui/training_panel.py`; `tests/rl/test_metrics.py`, `tests/ui/test_training_panel.py` |
| ML-04 | ✅ | `record_every`; `test_recorded_episodes_replay_as_runs`, `test_clicking_a_recorded_episode_replays_it` + manual check |


## M10: Polish + hero demo (in progress)

Plan: (1) performance pass against NF-01–NF-07 with a rerunnable benchmark, (2) TB-01/TB-02
and DS-11 checks, (3) design QA of every panel in both themes, (4) README with GIFs and
`docs/ARCHITECTURE.md`, (5) the hero demo recording.

- Part 1 (performance): `benchmarks/nf_bench.py` measures NF-02, NF-03, NF-05, NF-06, NF-07
  (how, D-117). Changes (D-118): static MuJoCo worlds skip `mj_step`; a float RK4 fast path
  for `Quadrotor` (bit-identical); scalar attitude controller, `quat_matrix`, `rot_log`;
  cached name lookups and state slots; lazy SciPy import. Windows box (i7-10700K, Python
  3.13), before -> after:

  | Target | Required | Before | After |
  |---|---|---|---|
  | NF-02 UC-3 arm RTF, dt 1 ms | >= 20x | 6.0x | 9.5x |
  | NF-03 UC-2 RTF, dt 1 ms | >= 10x | 1.6x | 3.8x |
  | NF-05 cold start | <= 4 s | | start screen 2.0 s, main window 2.6 s ✅ |
  | NF-06 determinism | 1 log | | 10 runs, 1 distinct log ✅ |
  | NF-07 10 min UC-2 memory | <= 2 GB | | peak 1055 MB ✅ |

  This machine ran UC-2 at 1.65x where the Mac ran 6.5x (M8), so the Mac (reference
  hardware) should now clear NF-03; **rerun `python benchmarks/nf_bench.py` on the Mac** to
  confirm. NF-02's floor here: MuJoCo's step alone is 45x, SimView's tick without user code
  about 26x; the rest is the example's 100 Hz IK controller and the end-effector FK it logs
  every tick.
- 486 tests pass (offline: 20 skipped), 16 GL tests pass, lint clean. The DA-01 plot timing test
  (`test_ten_signals_of_100k_samples_redraw_at_30_fps`, median ~25 ms vs 33 ms) failed once
  under full-suite load and passed on rerun.

## Next

1. M9 approved 2026-11-22. M10 (polish + hero demo) in progress on `m10-polish-demo`.
   M8's PR into `main` is open (the owner merges); M9's PR follows it.
2. macOS GL CI: the repo is public since 2026-11-20, so Actions runs again. The first run on
   `main` (M7) is green except `gl (macos-latest)`, which crashes (exit 133) in
   `test_scrubbing_redraws_the_real_viewport_within_100_ms`, the only GL test that opens the
   whole main window; reproducible on re-run. It passed on M6 with the same dependency
   versions, so suspect M7's main-window changes. Not bisected yet (can't be run from a
   Claude terminal: try it locally, or bisect on a debug branch). Update: all GL tests,
   including this one, pass locally on the Mac with `QT_QPA_PLATFORM=cocoa SIMVIEW_GL=1`.
