# Progress

Milestone status against the plan in [PRD §10](PRD.md#10-mvp-definition-and-milestone-plan-12-weeks).
Decisions made along the way are in [DECISIONS.md](DECISIONS.md). Newest last.

| Milestone | Status | Branch | Requirement IDs |
|---|---|---|---|
| M1: Skeleton + design system | ✅ Approved 2026-11-18 | `main` | DS-01, DS-02, DS-03, DS-07, DS-08, DS-14 |
| M2: Core sim engine | ✅ Merged to `main` 2026-11-18 | `main` | SE-01, SE-04, SE-05, SE-06, SE-07, SC-04 (+ NF-06, NF-09) |
| M3: Physics + robots | ✅ Approved 2026-11-18 | `main` | SE-03, IO-01, TB-ROBOT (partial, D-023) |
| M3b: Robotics depth (PRD 1.1) | ✅ Approved 2026-11-18 | `main` | RB-01–RB-12, TB-ROBOT (rest) |
| M4: Viewport + IPC | Built, CI green, **awaiting approval** | `m4-viewport-ipc` | SE-02, SE-10, VP-01–VP-07, VP-10, NF-04, NF-10, DS-04–DS-06 |
| M5: Timeline + plots | Not started | | VP-05, DA-01–DA-04, DA-07, DS-09 |
| M5b: Run investigation (PRD 1.2) | Not started | | RI-01–RI-06 |
| M6–M10 | Not started | | see PRD §10 |

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

## Next

1. Owner reviews M4 (try `simview examples/ur5_ik_drag.py`, press Space, drag the blue target).
2. Start **M5: Timeline + plots** (VP-05, DA-01–DA-04, DA-07, DS-09), then **M5b: Run
   investigation** (RI-01–RI-06).
