# Decisions

Ambiguities resolved with the simplest reading (PRD §0 rule 6). Newest last.

## M1

**D-001 — Layout persistence before projects exist.** DS-03 asks for the layout to persist
per project, but projects (`.svproj`, IO-04) arrive in M6. The main window saves its dock state
to `QSettings` under `layout/<project key>`. The key is `untitled`, `template/<id>`, or the
project folder path. M6 can move this into the `.svproj` folder without changing the window API.

**D-002 — Template cards before templates exist.** DS-08 needs the 4 template cards, but the
templates are built in M8. Clicking a card opens the main window titled with the template
name and an empty scene. The card thumbnail is a Lucide glyph until real renders exist (M10).

**D-003 — Only part of the Lucide set is used, but all of it is bundled.** All 1,540 SVGs
from `lucide-static@0.460.0` are bundled (about 1.5 MB) so later milestones don't need a
re-fetch. Icons are tinted at load time by swapping `currentColor` for a token color and
`stroke-width="2"` for the §7.3 value of 1.5.

**D-004 — Layout sizes are tokens.** §7.3 bans hard-coded sizes outside the theme, so the
default window, side-panel, timeline, bottom-row, palette, and card sizes live in `tokens.py`.

**D-005 — Text on accent and light `state.success` contrast.** White on the dark `accent`
`#0A84FF` measures 3.35:1, below AA. Resolved (approved 2026-11-18): a new `accent.fill` token
is used only for filled controls (primary buttons, selected list rows, selected menu items,
text selection), with `text.on_accent` (white) on top. Dark `accent.fill` is `#0A6FEE`: 4.64:1
for white text, and at least 3.0:1 against every dark surface, so the control edge still
reads. Light `accent.fill` equals the light `accent` (`#0071E3`, 4.70:1 with white).
`accent` itself is unchanged for focus rings, selection outlines, and the time cursor.
Separately, light `state.success` is darkened from the PRD's `#248A3D` (4.40:1 on white) to
`#1F7A35` (5.39:1 on white, 4.95:1 on `bg.app`), so it is safe as text too.

**D-006 — The content-area target in §7.2.1.** With the original §7.4 panel sizes at 1440×900,
the viewport plus plots took 55.7% of the window. Fixed chrome (menu, toolbar, status bar,
timeline) is about 18% of the window by itself, so 70% of the whole window would need side
panels near 100 px. Resolved (approved 2026-11-18): side panels default to 180/200 px, plots
take 75% of the bottom row, and the timeline dock has no title bar (it is a thin strip). The
70% target is measured against the work area between the toolbar and the status bar. That
measures 68.6% offscreen (61.7% of the full window). Getting to a strict 70% of the work area
would also need plots at 80% of the bottom row (console about 287 px wide). The timeline can't
be dragged by a title bar; it returns to place with Reset Layout.

**D-007 — Icons don't re-tint on a live theme switch.** Toggling the theme re-applies the QSS,
but existing icons keep the old theme's tint until the window is reopened. Both themes'
`text.secondary` and `accent` stay legible on either background, so this is cosmetic. It will be
fixed when the panels gain real content.

**D-008 — R5 verified.** qtconsole's `RichJupyterWidget` with an in-process kernel ran under
PySide6 via qtpy (tested in a throwaway venv on macOS, Python 3.12, PySide6 6.12). It is not a
project dependency until M6.

**D-009 — License.** MIT, the PRD Q3 default, confirmed 2026-11-18.

**D-010 — pytest-cov.** Added as a dev dependency (approved 2026-11-18) for NF-09
(≥80% line coverage of `simview/core`). CI reports coverage now; the 80% gate will be enforced
on `simview/core` once M2 creates it.

## M2

**D-011 — One `simview` command.** SE-05 asks for `simview run scene.py --headless`, so the
console script now points at `simview.cli:main`. It sends `run ...` to the headless runner and
everything else to `simview.ui.app.main` unchanged, so `simview [--theme light]` behaves as in M1.
The headless path never imports Qt.

**D-012 — Ground contact without events.** Events (`on_collision`, SE-11) are v1, so the
bouncing ball's ground is a stiff spring-damper (k = 1e4 N/m, c = 20 N·s/m) inside its
`derivative`. That gives a restitution of about 0.73 and under 4 cm of penetration at dt = 1 ms.

**D-013 — RK45 is adaptive inside each tick.** SE-01 fixes the tick, so `rk45` runs SciPy's
`solve_ivp(method="RK45")` across each `dt` with `rtol=1e-8`, `atol=1e-10`, and the input `u`
held constant over the tick. Euler and RK4 take one step per tick.

**D-014 — Scene files.** A `scene.py` defines a module-level `scene = simview.Scene(...)`;
`load_scene` runs it with `runpy`. The CLI's `--duration` defaults to 10 s, `--seed` overrides
the scene's seed, and the default log path is `runs/<YYYYmmdd-HHMMSS>-seed<seed>.parquet` in the
working directory (with a numeric suffix if taken). The GUI will build the same `Scene` object.

**D-015 — Log layout.** One row per tick, including tick 0: `t`, `tick`, then
`<entity>.<state>` for every entity state, then tagged channels from `scene.log(name, fn)`,
where `fn(sim)` returns a float. `t` is `tick * dt` (no summed drift). Run settings go in the
Parquet schema metadata under `simview` as sorted-key JSON, with no timestamps, so
same seed + same scene gives byte-identical files. Block signals join the log in M5.

**D-016 — Left for later milestones.** `scene.controller(rate=...)` and `ctx.draw` from the
§8.3 sketch, live (non-headless) runs, and the 60 Hz render clock in SE-01 need the viewport
or blocks, so they arrive in M4/M5. `run(..., headless=False)` raises `NotImplementedError` until
then. `Run.to_pandas()` works if pandas is installed; pandas is not a dependency (not in §8),
and `run["column"]` returns a NumPy array.

## M3

**D-017 — The bundled UR5.** There is no license-clean plain UR5 URDF to copy: MuJoCo Menagerie
only has the UR5e (a different robot), and Universal Robots ships xacro. `toolboxes/robotics/
assets/ur5/ur5.urdf` is Universal Robots' `ur_macro.xacro` expanded by hand with the UR5 values
from `Universal_Robots_ROS2_Description` @ `0eb1a861` (BSD-3-Clause, `LICENSE` copied alongside,
provenance in that folder's `README.md`). The 7 upstream collision STLs (about 250 KB) are
bundled unmodified and used for visuals too, because MuJoCo can't load the upstream `.dae`
visual meshes. Left out: `ros2_control` tags, `ft_frame`, safety-controller limits.

**D-018 — How MuJoCo entities fit the M2 API.** `Entity` gains two methods, `validate()` (the
shape check `Sim` used to do inline) and `advance(t, dt)` (integrate `derivative`, as before).
`Sim` now calls these. MuJoCo robots override both; custom models behave exactly as in M2. No
existing signature changed; this is additive, so it was not treated as a public-API change.

**D-019 — Robot state and input.** A `Robot` is one entity whose `x` is `[qpos, qvel]`, logged as
`<robot>.<joint>.q` / `.v` (multi-DOF joints: `.q0..`, `.v0..`). `x` is the source of truth: each
tick it is copied into `MjData`, MuJoCo takes one `mj_step` with the scene's `dt`, and the result
is copied back, so code that edits `x` (IK, a slider) takes effect on the next tick. `u` drives
the actuators (`ctrl`) if the model has any, otherwise it is applied as joint forces
(`qfrc_applied`): a URDF has no actuators, so `u` is joint torques. `integrator` doesn't apply.

**D-020 — URDF import details.** Static links (`tool0`, `flange`, `base`) are kept as bodies
(`fusestatic="false"`) so they work as kinematic frames. `<visual>` elements are dropped; MuJoCo
simulates the collision geoms and the viewport (M4) will draw them. Mesh paths resolve relative to
the URDF, and `package://<pkg>/<rel>` resolves to `<rel>` relative to the URDF (no ROS package
lookup). Mesh formats MuJoCo can't read (anything but STL/OBJ/MSH) fail with a clear error instead
of being converted. MJCF files load unchanged, so MuJoCo's rules apply, including angles in
degrees unless the file sets `<compiler angle="radian"/>`. Bundled robots resolve by bare name:
`scene.add_robot("ur5.urdf")` or `"ur5"` (an existing file path wins).

**D-021 — The FK reference.** "FK matches a reference within 1e-6" uses Universal Robots'
published UR5 DH parameters, which share nothing with the URDF or MuJoCo code path. The DH chain
gives `base`→`tool0`; `base` is `base_link` rotated π about z. Measured worst error over 1,000
random configurations: 6e-10. The Jacobian is MuJoCo's geometric Jacobian of the frame origin,
rows `[linear; angular]` in the world frame, checked against finite differences.

**D-022 — What the IK target means, and how IK meets it.** "Random reachable poses" are the FK of
joint vectors drawn uniformly from [-π, π]^6, solved from one fixed seed configuration, with
tolerances of 1e-6 m and 1e-6 rad. Plain damped least squares reached only about 80%: most
failures were local minima, some were joints stopped at a limit, and the rest were targets near
singularities. The solver therefore (a) scales damping with the error, (b) wraps joints whose
range covers [-π, π] instead of clipping them, and (c) restarts from a seeded random configuration
when 3 updates fail to cut the error by 20%. Every update and every restart counts toward the 50.
Measured: 98.3–99.0% on three fresh sets of 1,000 targets, median 9 iterations, about 4 ms per
solve. The test uses 300 targets and requires ≥95%. Results are deterministic (`seed=0` default).

**D-023 — TB-ROBOT is partly built in M3.** The §10 deliverable for M3 is "FK/Jacobian/IK in the
Robotics toolbox", so M3 builds FK, the Jacobian, DLS IK, and the SE(3) basics they need
(`make`, `inv`, `rot_log`, `error`). The rest of the §9 Robotics row (trajectory generation,
inverse dynamics, transform-tree utilities) is not built yet; see the M3 gate question in
PROGRESS.md. `robot.fk(q)`, `robot.jacobian(q)`, and `robot.ik(T)` exist as methods for UC-3.

**D-024 — Math names in lint.** Robotics code uses `T`, `R`, `J` for transforms, rotations, and
Jacobians. `pyproject.toml` turns off ruff's N803/N806 naming rules for
`src/simview/toolboxes/robotics/` and for tests, instead of scattering `noqa` comments.

## M3b

**D-025 — Alloy's robotics, rebuilt natively.** The owner asked (2026-11-18) for "all the
necessary functionality of Alloy robotics", the Alloy physics engine from Argon Robotics
(`github.com/argonrobotics-ai/alloy`, Apache-2.0). Alloy runs only on Linux and Apple-silicon
macOS and pins `mujoco==3.17.0`, so it is not a dependency. Its rigid-body robotics is rebuilt on
SimView's own MuJoCo backend instead, and works on all three OSes. The owner chose the "necessary"
set: shared world and objects, joint driving, controllers, grippers and a robot library. Everything
else is listed as `[Future]` in PRD §5.10 (RB-20..RB-28). No Alloy code was copied; its API names
and units were followed where they fit (full sizes in metres, `set_targets`, ramps). PRD → 1.1,
new milestone M3b, which also finishes TB-ROBOT (trajectories, inverse dynamics, transform tree).

**D-026 — One world per scene, and what changed for M3's `Robot`.** A scene has one `World`
(`physics/world.py`), made on first use, that compiles every robot and object into one MuJoCo
model with `MjSpec.attach` (robot names prefixed `<robot>/`). It recompiles whenever an item is
added; scenes are small. Each member entity owns a slice of the state through index arrays
(`qidx`, `vidx`, `act_ids`), and the scheduler steps the world once per tick after controllers
and ODE entities. M3's public `Robot` API is kept: the same constructor argument, state names,
`q`, `qd`, `set_q`, `u`, `fk`/`jacobian`/`ik`, and `robot.model` (now the world's model). A robot
made on its own gets a private world and moves into the scene's world when added. Frame names that
contain `/` are full world names, so an arm's kinematics can use a mounted tool's frame
(`"grip/pinch"`).

**D-027 — World options belong to the world.** Once attached, a robot file's own `<option>` no
longer applies (MuJoCo warns: "keeping parent value"). The world's integrator defaults to
`implicitfast`, MuJoCo's recommendation for servo-driven robots; M3 robots used their file's
option (Euler for the UR5). `scene.physics().integrator` / `.gravity` change it; the MJCF-vs-ODE
pendulum test now selects RK4 explicitly.

**D-028 — Friction cone for grasping.** `World.cone` / `.impratio` are exposed, with MuJoCo's
defaults (pyramidal, 1). Grasping scenes set `"elliptic"` and `10`, as Menagerie grippers ask for
and MuJoCo recommends, so a squeezed object doesn't creep out of the fingers.

**D-029 — Adjacent links never collide.** Building M3b's controllers found the UR5's shoulder in
permanent contact with its base, a bug present since M3. MuJoCo skips parent-child contacts except
when the parent is welded to the world, and URDF's `base_link_inertia` is. Every robot now
excludes contacts between each body and its parent (the URDF/ROS convention). Non-adjacent
self-contacts (a folded arm) are physical and stay.

**D-030 — Differential IK integrates from its last command.** Stepping from the measured joints
made a servo-driven arm creep: a servo always lags its target, so each new target was only a small
step ahead. `DifferentialIK` keeps `q_cmd`, starts from the measured q on its first call or after
`reset()`, and takes each step from the previous command, as position-controlled arms do.

**D-031 — Objects.** Sizes are full lengths in metres (Alloy's convention; MuJoCo's half sizes are
derived): box (x, y, z), sphere (diameter), cylinder and capsule (diameter, length). A free
object needs `mass=` and is an entity with 13 logged states (`x y z qw qx qy qz vx vy vz wx wy
wz`). `static=True` makes fixed geometry that is not an entity. One ground plane per scene.

**D-032 — Servos and targets.** `servos="position"` / `"velocity"` adds a servo to each hinge or
slide joint that has no actuator (defaults kp = 1000, kv = 100; one value or a dict by joint), with
`ctrlrange` set to the joint range. MJCF actuators are used as they are. `set_targets` checks the
servo kind, clamps position targets to the joint range with a warning, and with `ramp=` moves the
target linearly from its current value. `set_controls` is raw (no clamp, no warning). Unnamed
joints and actuators are named `joint<k>` / `actuator<k>`. `gravity_compensation=True` uses
MuJoCo's body `gravcomp`, an ideal stand-in for an arm's own gravity compensation.

**D-033 — `scene.controller` arrives in M3b, without `ctx.draw`.** RB-07 needs per-tick control,
so the §8.3 controller API moves forward from M4/M5 (D-016). `fn(t, state, ctx)`: `state` is the
scene (entities by name), `ctx` has `dt` (the controller's period), `tick`, and `rng`. Due
controllers run at the start of a tick, before ODE entities and the world step. A returned dict
`{entity: u}` sets inputs; returning None is fine. The rate must divide 1/dt. `ctx.draw` comes with
the viewport in M4.

**D-034 — The robot library downloads on first use.** Menagerie robots are tens of MB each (Panda
34 MB, UR10e 33 MB), too big to bundle. `library.fetch` downloads only the files a robot's MJCF
references, plus its LICENSE and README, from `raw.githubusercontent.com` at commit `370c4396`,
with the standard library's `urllib` (no new dependency), into `$SIMVIEW_CACHE` (default
`~/.cache/simview`). An offline first use raises `FetchError` saying how to fix it. Licenses:
Panda Apache-2.0, UR10e BSD-3-Clause, Robotiq 2F-85 BSD-2-Clause. Tests that download are marked
`network` (skipped with `SIMVIEW_OFFLINE=1`); CI caches the folder.

**D-035 — The pick done-when uses the UR5 and a scripted gripper.** PRD §10 allows "a Panda (or a
scripted gripper)". The test and `examples/ur5_pick.py` use the bundled UR5 with a two-finger MJCF
gripper mounted on `tool0`, so they run offline: the cube lifts 9.9 cm (10 cm commanded; about
2 mm slip in the grip), with a quintic lift because a step target jerks the cube out. The Panda is
covered by network tests (loads, 8 actuators, reaches a pose within 5 mm under differential IK);
a Panda pick is not tested yet.

**D-036 — Controller gains and MuJoCo versions.** Fixed joint gains high enough for the UR5's
shoulder make its light wrist (about 1e-4 kg·m²) unstable under 1 ms torque control. The joint
controller tests scale gains by inertia (kp = ω²·M_ii, kd = 2ω·M_ii); `OperationalSpace` scales
by the mass matrix itself. `mujoco>=3.3` (for `MjSpec.attach`); `mj_fullM` changed signature in
MuJoCo 4 and both forms are handled. Development used MuJoCo 4.0.1; CI installs the latest release.
