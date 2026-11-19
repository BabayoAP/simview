# Progress

Milestone status against the plan in [PRD §10](PRD.md#10-mvp-definition-and-milestone-plan-12-weeks).
Decisions made along the way are in [DECISIONS.md](DECISIONS.md). Newest last.

| Milestone | Status | Branch | Requirement IDs |
|---|---|---|---|
| M1: Skeleton + design system | ✅ Approved 2026-11-18 | `main` | DS-01, DS-02, DS-03, DS-07, DS-08, DS-14 |
| M2: Core sim engine | Built, CI green, **awaiting approval** | `m2-core-engine` (not merged) | SE-01, SE-04, SE-05, SE-06, SE-07, SC-04 (+ NF-06, NF-09) |
| M3: Physics + robots | Not started | | SE-03, IO-01, TB-ROBOT |
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

## Next

1. Owner approves M2 and chooses how to merge `m2-core-engine` into `main` (PR or fast-forward).
2. Start **M3: Physics + robots** (SE-03, IO-01, TB-ROBOT):
   - MuJoCo world, URDF/MJCF import, FK / Jacobian / IK in the Robotics toolbox.
   - Done when the UR5 loads, FK matches a reference within 1e-6, and IK converges within
     50 iterations for 95% of random reachable poses.
   - Adds `mujoco` (listed in PRD §8). Files per PRD §8.4: `physics/mujoco_world.py`,
     `physics/urdf.py`, `toolboxes/robotics/`.
   - A UR5 model asset is needed: check its license before bundling, ask if unclear.
   - MuJoCo entities must fit the M2 `Entity` / `Sim` API. Ask before changing any M2 public API.
