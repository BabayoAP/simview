# Progress

Milestone status against the plan in [PRD §10](PRD.md#10-mvp-definition-and-milestone-plan-12-weeks).
Decisions made along the way are in [DECISIONS.md](DECISIONS.md). Newest last.

| Milestone | Status | Branch | Requirement IDs |
|---|---|---|---|
| M1: Skeleton + design system | ✅ Approved 2026-11-18 | `main` | DS-01, DS-02, DS-03, DS-07, DS-08, DS-14 |
| M2: Core sim engine | ✅ Merged to `main` 2026-11-18 | `main` | SE-01, SE-04, SE-05, SE-06, SE-07, SC-04 (+ NF-06, NF-09) |
| M3: Physics + robots | Built, CI green, **awaiting approval** | `m3-physics-robots` | SE-03, IO-01, TB-ROBOT (partial, D-023) |
| M4–M10 | Not started | | see PRD §10 |

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

## Next

1. Owner reviews M3. Gate question: should the rest of TB-ROBOT (trajectory generation, inverse
   dynamics via MuJoCo, transform-tree utilities) be built now, or with UC-3 in M4/M8? (D-023)
2. Start **M4: Viewport + IPC** (SE-02, SE-10, VP-01–VP-07, VP-10, NF-04, NF-10, DS-04–DS-06).
