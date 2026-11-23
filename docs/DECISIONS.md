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

**D-025 — Alloy's robotics, rebuilt natively.** *Superseded by D-037: this decision identified the
wrong Alloy. The text below is kept as the record of what was decided at the time.* The owner asked (2026-11-18) for "all the
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

**D-031 — Objects.** Sizes are full lengths in metres (easier to read than MuJoCo's half sizes,
which are derived): box (x, y, z), sphere (diameter), cylinder and capsule (diameter, length). A free
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

## PRD 1.2

**D-037 — "Alloy robotics" is Alloy Robotics (usealloy.ai), not Argon's Alloy engine.** D-025 took
"all the necessary functionality of Alloy robotics" to mean the Alloy physics engine from Argon
Robotics, the first match a web search returned, and PRD 1.1 framed §5.10 and M3b around it. The
owner meant Alloy Robotics (usealloy.ai), an AI platform for investigating robot data: it ingests
logs (MCAP, ROS, Parquet, CSV, ArduPilot), answers questions about missions, scans every run for
a pattern defined once ("Scenarios"), writes mission reports with plots, links each finding to its
signals and time window, and offers an MCP server. It has no simulation. The owner's decisions
(2026-11-18):
- M3b stays, as plain "Robotics depth". Its code and requirements (RB-01..RB-12) are sound and
  unchanged; only the Alloy framing is removed from the PRD and PROGRESS. 1.1's physics-engine
  `[Future]` list (RB-20..RB-28) is removed.
- usealloy.ai's functionality becomes PRD §5.11 Run investigation (RI-01..RI-06 MVP, RI-20..RI-24
  later), applied to SimView's own runs and to imported robot logs, as milestone M5b after M5 (it
  needs the timeline and plots). Natural-language Q&A and an MCP server are `[Future]` for now.
- Lesson recorded: confirm a product's identity from its own site before building on it.

## M4

**D-038 — The sim process.** `ipc/client.py` starts the sim in a `spawn`ed process (the same on
every OS, and no forked Qt state). State goes through one shared-memory float64 buffer guarded by a
sequence counter (a seqlock: the reader retries instead of seeing a half-written frame). Commands,
events, debug draws, and tracebacks go through a ZeroMQ `PAIR` socket on 127.0.0.1 as pickled
dicts (both ends are SimView on one machine). The sim publishes state at most every 1/120 s.
Stop resets by loading the scene file again. A user-code exception (scene file or controller)
arrives as a traceback in the console and pauses the run, with the process still up; `print`
output is forwarded line by line. A killed or crashed sim is reported once with its exit code, and
Run starts a new one (NF-10).

**D-039 — Pacing and its numbers (SE-10, NF-04).** Speeds 0.1×, 0.25×, 0.5×, 1×, 2×, 5×, 10×, and
Max (no pacing). The reported RTF averages over 0.5 s of wall time. Measured on the development
machine: 2.000 s of sim time per 2.001 s of wall time at 1×; about 10× at Max for the UR5 pick
scene; state latency median 4.8 ms, p99 about 10 ms (NF-04: 20 ms). The test checks the median.

**D-040 — VP-05 is split between M4 and M5.** VP-05 is in both milestones' lists. M4 builds play,
pause, step forward, and the speeds; step back and the scrub slider need recorded history, which
is M5's timeline. Step back (`,`) is not bound yet.

**D-041 — The HUD and heads-up toolbar are drawn inside VTK.** Qt widgets laid over the native
OpenGL surface don't composite reliably across platforms, so the toolbar is VTK textured buttons
(Lucide icons rendered by Qt) on a translucent `bg.elevated` backdrop, and the HUD is a VTK text
actor in JetBrains Mono. This keeps §7.5's look. VTK buttons have no tooltips. The "view presets"
button cycles iso, front, right, top (the ViewCube and keys 1/3/7/0 pick one directly). The
"sensor visuals" toggle waits for sensors (M8). The HUD text refreshes at 10 Hz: VTK's corner
annotation re-fitted its font on every change and cost about 25 ms a frame.

**D-042 — Navigation.** SimView's style (§7.5) is the only preset for now: right- or middle-drag
orbits around the point under the cursor, Ctrl+right or Shift+middle pans, the wheel zooms toward
the cursor (keeping that point under it, in perspective and orthographic), left-click selects.
The other presets (SolidWorks, Onshape, Blender, MATLAB) need the Settings dialog and come with it.
Fly mode is a toolbar toggle: W/S, A/D, Q/E move the camera; in fly mode A strafes instead of
framing all. 2D mode (Tab) is top-down orthographic; right-drag pans there and the ViewCube is off.
The world coordinates under the cursor show as a HUD line rather than a tooltip. VTK's own key
handling never sees keys (its defaults close the window on q/e).

**D-043 — Selection and gizmos (VP-06, VP-10, DS-06).** Clicking a robot's link selects the robot.
Selection and hover are one state shared by the viewport, scene tree, and inspector; plots join in
M5. Outlines are silhouettes in a second renderer layer, so they show through other geometry. Drag
targets (`scene.add_target`) always show the translate/rotate gizmo; a selected free body gets one
too, and is placed (at rest) where it is released. Robots get no gizmo: their bases are fixed and
their joints follow IK targets. PyVista's gizmo switches the interactor to its trackball style on
release; SimView puts its own style back.

**D-044 — Testing the OpenGL viewport.** Tests that need a GL context are marked `gl` and run only
with `SIMVIEW_GL=1`. CI runs them on Linux (Mesa under `xvfb`) and macOS. GitHub's Windows runners
only offer OpenGL 1.1, below VTK's 3.2, so Windows GL runs on the development machine (GTX 1050 Ti,
all `gl` tests pass). Without GL (headless runs, broken drivers) the main window uses a stand-in
view: the sim, panels, and console still work and nothing crashes. Everything else in the viewport
(geometry, matrices, trails, draws, grid, navigation math) is OpenGL-free and tested everywhere.

**D-045 — Scene API added for the viewport.** `ctx.draw.line/arrow/point/text/frame` with
`persist=` (VP-07; recorded headless too). `scene.add_target(name, pose)` (VP-10). `Entity.position()`
places markers and trails (VP-04): states named x/y/z by default, a free body's position, a robot's
default frame. `scene.trail(entity, seconds, color)` (VP-04). `scene.add_visual(name, path, pose)`
shows an STL, OBJ, PLY, or GLB/glTF mesh without physics (VP-01; MuJoCo can't load GLB); glTF is
+Y-up, so it is turned +90° about x. World axes sit at the origin and toggle with the grid. Mesh
geoms render with subtle feature edges (shaded+edges, §7.5).

**D-046 — Frame rate.** Measured on the development machine at 1000×700 with 4× MSAA: 62 fps for
both the pick scene and the IK-drag scene (whose debug draws change every tick). Debug draws are
coalesced to the newest set per UI frame and batched into a few actors. NF-01's target scene
(20 entities and a 50k-point cloud) is checked in M10.

**D-047 — Panels and launch.** The Console tab now shows sim output and tracebacks; the IPython
console replaces it in M6. The Inspector lists every state live, and a robot's joints as sliders
that follow the simulation (UC-3). `simview scene.py` opens a scene directly. New dependencies:
`pyvista`, `pyvistaqt`, `pyzmq` (all in PRD §8.1).

## M5

**D-048 — The timeline replays a recording; it doesn't rewind the sim (VP-05).** A run can't be
restarted from a past tick: its state includes MuJoCo's warm starts and whatever controllers keep
in closures (`DifferentialIK.q_cmd`). So the UI keeps a recording of every tick (D-049), and the
timeline shows either the live sim or a recorded row. Scrubbing or stepping back (`,`) pauses the
sim and parks on a row. Play from a parked row replays the recording at the playback speed (Max
replays at 10×) and, when it runs out, the live sim carries on from where it stopped. Step forward
(`.`) moves through the recording, and at its end steps the sim one tick. Hovering a time plot
previews that moment in the viewport without moving the cursor (DA-02); clicking one seeks. Start
and live-end buttons sit beside the transport (palette: "Go to Start / Live"). The speed menu
stays in the toolbar; the timeline shows `live` or `replay` beside the time.

**D-049 — Recording.** After every tick the sim process records one float64 row: the tick, every
logged signal (the Parquet log's columns, SE-06), each entity's marker position, and every MuJoCo
body pose (`ipc/record.py`). Rows go to the UI with each state publish (at most 120 Hz) as one
array. A re-recorded tick (a body dropped by the gizmo while paused) or a reset replaces the rows
from that tick on. The UI's `History` keeps them in one growable array; past 512 MB it drops its
oldest quarter. Debug draws are recorded as the sim sends them (when they change, at most once per
publish), so a scrubbed frame shows the newest draw set sent at or before it; per-tick draws
would cost too much for controllers that draw every tick. Recording costs the UR5 drag scene a
`mj_kinematics` per tick (a few µs).

**D-050 — Plot speed (DA-01).** pyqtgraph's own downsampling still drew 10 × 9k-point antialiased
paths (about 500 ms a frame), and 1.5 px antialiased polylines are slow in Qt's raster engine.
Time plots now thin every trace to a min and a max per bin before drawing (`ui/plots/decimate.py`;
spikes survive), at most 0.75 bins per pixel, and draw segmented lines. While rows stream in, the
bins are a power of two of samples and are cached, so a redraw only reduces new rows. Zooming
or panning by hand re-thins just the visible span. Measured on the development machine for 10
signals × 100k samples at 1000×300: median 25 ms per update (about 40 FPS). The test asserts
33 ms locally; CI runners render in software and only get a regression bound (150 ms).

**D-051 — Plot kinds and behavior (DA-02..DA-04, DS-06).** Kinds: time, XY (the first signal
dropped is X; each later one is a Y series against it; same units lock the aspect ratio, so a
top view isn't skewed), scatter (XY with points), and histogram (all recorded samples; the cursor
marks the current value). Drop signals from the tree onto a plot, onto the empty panel (makes a
time plot), or double-click them. Clicking a trace selects its entity, and the selected entity's
traces are drawn bold; plots don't report hover (pyqtgraph curves have no hover signal), but the
signal tree does. A one-trace plot has no legend (its axis label names it); more get a legend in
the top right, hidden while the hover readout shows. Vector components (x/y/z, vx…, wx…) use the
X/Y/Z axis colors, others Okabe–Ito in order. Plots scroll in their panel instead of growing the
dock. Axis values are shown as logged (no SI rescaling).

**D-052 — Units for plot labels (DS-09).** `Entity.state_units` (optional class attribute, e.g.
`{"h": "m"}`) and `scene.log(name, fn, unit="")` are new optional arguments; nothing existing
changes. Free bodies and robots fill them in (m, m/s, rad, rad/s; quaternions unitless).

**D-053 — Exports (DA-07, DS-09).** Export Data writes the whole recording (every signal, `t`,
`tick`) to CSV, Parquet, or `.mat` by extension. In `.mat`, names become valid MATLAB variables
(`ur5.shoulder.q` → `ur5_shoulder_q`) and `signal_names` lists the originals. Each plot exports
itself to PNG (2× its size) or SVG, in the light theme. pyqtgraph's SVG exporter fails on Qt 6
paths, so SVG uses Qt's `QSvgGenerator`. New dependency: `pyqtgraph` (PRD §8.1).

**D-054 — Fixes to M4 found while checking M5 on screen.** (1) Opening a scene replaced the main
window's central widget, which left it zero-wide: the 3D view vanished and the side docks took
the width. The central widget is now one `QStackedWidget` (empty state, then the view), and the
layout version is bumped so layouts saved with the bug are dropped. (2) The light theme showed
black panels (Inspector, Console) when Windows is in dark mode: the Qt palette now comes from the
tokens too, and Qt no longer makes the docks native windows next to VTK's. (3) Sliders and tree
selection used the OS accent color: both are styled from the tokens now. (4) pyqtgraph creates
parentless menus per plot; plots adopt them so they are deleted with the plot (no leak), and the
test teardown deletes plain stray widgets last. (5) The shared-memory reader gave up after 100
quick retries, so a writer descheduled mid-frame (a busy 2-core CI machine) made `frame()` return
None; it now yields and waits out a write for up to 20 ms. The GL scrub test checks timing only
off CI: CI renders OpenGL in software (0.3–1.3 s a frame).

## M5b

**D-055 — Scenario expressions (RI-02).** A scenario is `condition for <n> s|ms` (no `for`: any
single sample). The condition is parsed with Python's `ast` and only a whitelist is evaluated:
numbers, signal names (`entity.state` or a channel; backticks quote any other name; `t` is
time), comparisons (chains too), arithmetic, `and`/`or`/`not`, and `abs sqrt hypot min max deg
rad`. Anything else (calls, attributes of non-signals, strings, subscripts) is refused when the
scenario is defined. A Python predicate (`Scenario(name, predicate=fn, signals=[...])`) is the
escape hatch. "Holds for d" counts each sample as one sample period long: k consecutive samples
last k·dt. A match is the window from its first to its last sample. A run that doesn't log a
needed signal is reported as "not checked: missing …", never as no match (RI-03).

**D-056 — The run catalog (RI-01).** A run is a Parquet log (SE-06) in a run folder: `runs/` next
to the scene file in the app (projects arrive in M6), `runs/` in the working directory headless,
or `SIMVIEW_RUNS`. The log's metadata gains `source` (sim, app, import), `units`, and `params`
(empty until `sim.params`, M6). The date and the scene file go in a sidecar `<run>.run.json`,
because the log itself must stay byte-identical for the same seed (NF-06, and SC-04 compares a
scene file's log with the same scene built in code). The catalog reads only Parquet footers and
sidecars; there is no separate index to go stale. The app saves the live run when it is stopped
(or the scene closed), if it has more than one sample.

**D-057 — Scanning (RI-02).** Results of expression scenarios are cached per run in
`<folder>/.scan-cache.json`, keyed by the run file's size and modification time and by the
scenario's name and text, so a scan reads only new or changed runs ("new runs are scanned when
they finish": the app scans right after saving a run; headless, `simview runs scan` or
`investigate.scan`). Predicates aren't cached. Expression scenarios are saved in
`<folder>/scenarios.json`.

**D-058 — Opening a run replays it through its scene (RI-01, RI-06).** The sim process loads the
run's scene, then for each logged row sets the entities' states (states the log lacks keep their
start values), recomputes markers and body poses, and sends the rows as history; channels come
from the log. The timeline then shows the run in "recorded" mode: Play replays it and stops at
its end, step forward stops there too, and Stop goes back to the live scene. Debug draws aren't
in logs, so a replayed run shows none. An imported log's unmapped columns aren't scene signals:
they are scanned and reported, but not in the Signals panel.

**D-059 — Findings, comparisons (RI-03, RI-05).** Findings are grouped by run in the Runs
panel. Clicking one opens its run if another is shown, moves the timeline to the window's start,
zooms every time plot to the window with context either side, and adds a time plot of its
signals if none shows them. Comparison aligns two runs on shared ticks when their sample periods
match, otherwise interpolates the baseline onto the run's times, over the time both cover. A
signal diverges where |Δ| > atol + rtol·|baseline| (the app uses 1e-6 and 1e-6; the API and CLI
default to 1e-9 and 0). Each first divergence and each scenario match found in only one run
becomes a finding; `simview runs compare` exits 1 when anything diverged.

**D-060 — Reports (RI-04).** One self-contained HTML file: inline CSS from the light-theme
tokens, plots as inline SVG drawn with matplotlib (text as outlines, so no fonts are needed),
no scripts or links. Per run: metadata, every match (scenario, window, signals), the scenarios
it couldn't check, plots of the matched scenarios' signals with the windows shaded (or the
run's channels when nothing matched), and min/max/mean/final of every signal with units. A set
of runs adds a scenario × run table; a comparison adds its table and a plot. The app writes
reports to `<run folder>/reports/` and opens them. New dependency: `matplotlib` (PRD §8.1 lists
it for exports).

**D-061 — Importing logs (RI-06).** CSV or Parquet; `mapping` renames log columns to scene
signals (`ur5.shoulder_pan_joint.q=j1`). Time comes from one column (scaled, e.g. ms → s),
shifted to start at 0; rows are sorted by time and repeated times dropped; the sample period is
the median spacing and ticks are time / period. Other numeric columns are kept under their own
names. The app's Import asks for the file, then shows a `signal = column` mapping prefilled with
columns that already match the scene's signals.

**D-062 — Faster scrubbing.** Scrubbing a run rendered the 3D view three to four times per move:
pyvista re-renders whenever an actor is added or removed (the debug draws are rebuilt), and the
UI rendered on every timer tick even when nothing had changed. Draw actors are now added and
removed without rendering, the UI renders only when the shown moment, the history, or the draws
changed, and an empty draw set is one shared object. Measured: a finding click on an open run
takes 49–62 ms with the OpenGL viewport (it was 67–124 ms).

## M6

**D-063 — M6 dependencies.** `qtconsole`, `ipykernel`, and `pygments`, all named in PRD §8.1
(console: qtconsole + ipykernel in-process; editor: QPlainTextEdit + Pygments). QScintilla is
not used, so nothing needed asking.

**D-064 — Declaring parameters (SC-05).** A scene file declares them: `scene.params.kp = 2000.0`
(numbers or arrays of numbers). Controllers read `ctx.params.kp` (or `scene.params`, the same
object as `sim.params`). The set of names is fixed when a run starts (`Sim` freezes it), so
`sim.params.kpp = 3` is an error instead of a silent no-op, and a value keeps its kind (a
number stays a float, an array keeps its shape). Scalar parameters are logged every tick as
`params.<name>` channels, so a live change shows in plots, reports, comparisons, and scenarios;
arrays are not logged. The run's metadata `params` holds the values at the start. Stop / Reset
reloads the scene file, so parameters go back to the file's values.

**D-065 — "Takes effect on the next tick."** The UI sends `{"cmd": "param"}`; the sim process
applies it between ticks (its command poll runs every loop iteration, at most one publish
period, about 8 ms, apart while running flat out), so the next tick computed uses it. The sim
answers with its current values (`"params"` event), also after rejecting a value, whose reason
goes to the console as stderr.

**D-066 — `sim` in the console (SC-01).** The sim runs in its own process (SE-02), so `sim` in
the console is a handle: `sim.t`, `sim.tick`, `sim.dt`, `sim.running`, `sim.entities`,
`sim.state(name)` (a dict by state name), `sim.signals` and `sim.data(signal=None)` (the recorded
history, what the timeline and plots show), `sim.params`, and `sim.play() / pause() / step(n)
/ reset()`. `sim.scene` builds a copy of the scene from its file inside the console, for
kinematics and inspection (UC-3: `sim.scene["ur5"].fk(q)`); it doesn't move with the sim. The
namespace also has `sv` (simview) and `np`.

**D-067 — One kernel per UI process.** IPython's shell is a process singleton, so every window
shares one in-process kernel and namespace; the newest window's `sim` is the one in it. Output
and tracebacks from the sim process (NF-10) are written above the prompt on a line of their own.
IPython also installs its namespace as `__main__`, and `%run` leaves `__file__` there, which
`multiprocessing`'s spawn would run again in a new sim process; `SimClient.start` hides
`__main__.__file__` while spawning (the sim process only needs `simview.ipc.server.serve`).

**D-068 — Editor (SC-02).** One script at a time with New / Open / Save. Run File (F5) saves the
file and runs it with `%run -i`, so it sees `sim` and its variables land in the workspace (an
untitled script runs its text as typed). Run Selection (F9) runs the selected whole lines, or
the current line when nothing is selected, dedented. Tab inserts 4 spaces. Ctrl/Cmd+S is the
window's Save: it saves the project, or with no project open, the editor's script. The editor
has no Save shortcut of its own, since two Ctrl+S shortcuts would cancel each other.

**D-069 — Workspace browser (SC-03).** It lists the console's user variables, refreshed after
every cell (typed, Run File, imports): not `_private` names, modules, functions, classes, or the
names SimView puts there (`sim`, `sv`, `np`, unless reassigned). Columns are Name, Value, Shape,
Type, with Value second because the side panel is narrow (full preview in its tooltip).
Double-clicking a NumPy array opens a table: 0-D and 1-D as one column, 2-D as is, higher
dimensions as (first axis, the rest), record arrays with one column per field, up to 1M cells.

**D-070 — The console dock has no empty state.** §7.8 asks every empty panel for a hint and an
action. The console is a live prompt with a banner, so it is never empty; the editor's hint is
its placeholder text, next to its Open button. The Workspace panel keeps an empty state (with
Import Data…) until a variable exists.

**D-071 — Importing data (IO-02).** File > Import Data reads a CSV file into one record array
named after the file (`flight_log["alt"]`; numeric columns as float64 with empty cells as NaN,
other columns as text) or a `.mat` file's variables by their own names (`scipy.io.loadmat`,
`squeeze_me=True`; MATLAB v7.3 files are HDF5 and need re-saving with `-v7`). The same functions
are `sv.io.data.load_csv`, `load_mat`, and `load_data` in scripts.

**D-072 — Projects (IO-04).** A `<name>.svproj` folder with `project.json` (format 1, name, the
open scene and script as relative paths) and `scenes/`, `diagrams/` (for M7), `scripts/`, and
`runs/`. Save Project copies the open scene and script into the folder if they came from
elsewhere (never overwriting: `name-1.py`), saves the script, and writes `project.json`; runs
are written to `runs/` when they stop (RI-01), and the Runs panel shows that folder. Files the
scene loads by relative path aren't copied. Workspace variables aren't saved (re-run the script).
Unknown `project.json` keys are kept on save; a newer format is refused. Opening a project loads
its scene and opens its script; the window layout is kept per project (DS-03, keyed by path).
New Project, Open Project, Save Project (Ctrl/Cmd+S), and Import Data are in the File menu,
the Project button, and the command palette.

**D-073 — Code colors.** New `SYNTAX` tokens per theme (keyword, string, number, comment,
function, class, builtin, decorator), each ≥ 4.5:1 on `bg.panel` and `bg.elevated` (tested).
One Pygments style built from them colors the editor and the console; the console's prompts
and errors use the existing accent, success, and error tokens. Code text uses JetBrains Mono
through a `role="code"` stylesheet rule (the app-wide `*` rule otherwise forces Inter).

**D-074 — PySide6 below 6.12 on Python 3.11.** After M6, the Ubuntu / Python 3.11 CI job passed
every test and then crashed at exit (`Fatal Python error: bool_dealloc`). Measured on CI:
PySide6 6.12.0 over-releases `True` when a signal is emitted (a five-line `Signal(object)`
script crashes Python 3.11 within 1000 emits), while 6.10.2 and 6.11.1 don't. qtconsole sends
every kernel message through such signals, so each console cell and each new window drained
`True`'s reference count until it was freed. Python 3.12 made `True` and `False` immortal, so
there the bug is harmless. `pyproject.toml` keeps `PySide6<6.12` on Python < 3.12 only; lift it
once a fixed PySide6 release is out.

## M7

**D-075 — How a diagram runs.** A diagram is a sampled system run as one of the scene's
controllers, every tick or at `rate` Hz (`scene.add_diagram("x.svd", rate=100)`). At each sample
it computes every block's outputs in topological order, writes Entity Input blocks (before the
entities move that tick), updates discrete blocks, then integrates its continuous states over
the sample period with the chosen integrator (`rk4` by default), holding discrete outputs and
entity readings (the same input hold as D-013). So a diagram and a script controller with the
same math give the same numbers: the M7 check passes with an exact match, not just within 1e-9.

**D-076 — Block semantics.** PID is discrete at the diagram's sample period Ts:
`I += e·Ts` (skipped while saturated and pushing further into the limit: anti-windup),
`D = (e - e_prev)/Ts` (0 at the first sample), `u = kp·e + ki·I + kd·D`, clipped to optional
limits. Derivative is the backward difference at samples. Sine follows Simulink (amplitude,
bias, frequency in rad/s, phase). Integrator's shape is its initial value's (a vector integrator
needs a vector initial value). Gain with a matrix multiplies; otherwise it scales elementwise.
Mux concatenates; Demux splits evenly. Entity State has one output per chosen state (all by
default, named after them); Entity Input sets the entity's whole `u` (a number or a vector).

**D-077 — Shapes and errors.** Signals are scalars, vectors, or matrices (no bus block is in the
MVP list, so no bus type). Shapes are found by evaluating the diagram once at t = 0 (a probe):
a mismatch is reported on the block where it happens. Every problem comes back at once as
`Issue(block path, message)` (unconnected input, bad parameter, missing entity, algebraic
loop, shape mismatch), so the editor can outline each offending block. An algebraic loop is a
cycle through direct-feedthrough blocks only (Tarjan SCCs); every block in it is reported.

**D-078 — Logging block signals (SE-06).** Every block output is logged as
`<diagram>.<block path>.<port>` (`[k]` per element of a vector or matrix), e.g.
`altitude.pid.y`, `altitude.ctrl/gain1.y` inside a subsystem. Outputs hold between samples.
The logger and the controller share one evaluation per sample, so the row for tick k shows the
outputs the controller used at tick k. To Workspace blocks are recorded in the run metadata;
`run.workspace()` returns each as a record array (`t`, `value`).

**D-079 — `.svd` files (BD-06).** JSON with sorted keys and 2-space indent, `format: 1`, a
`blocks` list (id, type, params, pos, and a nested `diagram` for subsystems) and a `wires`
list of `{"from": "block:port", "to": "block:port"}` with ports numbered from 0. One edited
parameter changes one line. A Python Function block saves its function as `"file.py:name"`
(relative to the diagram file) or `"module:name"`; a callable passed from a script works but
can't be saved.

**D-080 — Subsystems (BD-07).** `diagram.group(ids)` moves blocks into a Subsystem; each
distinct outside source becomes an Inport and each distinct inside source an Outport.
`ungroup` reverses it. The compiler flattens subsystems before running (inner blocks keep
their path), so grouping doesn't change results (tested bit for bit).

**D-081 — The M7 check uses vertical drone dynamics.** The PRD's check names a quadrotor, but
the 6-DOF quadrotor is part of the Aerospace toolbox (M8). `examples/drone_altitude/` uses the
quadrotor's vertical axis (m·z'' = thrust − m·g) with the same PID as a script (`script.py`) and
as a diagram (`blocks.py` + `altitude.svd`). Rerun the check with the full quadrotor in M8.

**D-082 — Where the editor lives (BD-01).** The central area holds two pages, the 3D view and
the diagram, switched by "3D View" / "Diagram" buttons in the main toolbar (Ctrl+1 / Ctrl+2,
also in the View menu and the command palette). A tab bar above the central area would cost
about 28 px of height and drop the §7.2.1 content share below its 68% floor (measured: 66%).
The editor is one diagram at a time with New / Open / Save (File menu, Project button, and its
own toolbar); a new window starts with an untitled, empty diagram whose canvas says
"Double-click to add a block." (§7.8's empty state). The parameter panel sits to the right of
the canvas, 180 to 240 px wide.

**D-083 — Editing and undo.** Every edit (add, connect, delete, move, rename, parameter,
group, ungroup) is one undo step; undo restores a JSON snapshot of the whole diagram (an
`.svd` file is a few kB). Connecting to an input that already has a wire replaces it (an input
takes one wire, BD-05). A block's `pos` is its top-left corner; positions snap to 8 px and grid
dots are drawn every 16 px. Parameters are typed as JSON or Python literals (`2.5`, `[1, 0]`);
anything else is taken as text, so `+-` and `drone` need no quotes. Ctrl+S on the Diagram page
saves the diagram (with a project open, it saves the project, which saves the diagram).

**D-084 — Checking in the editor (BD-05).** The editor re-runs `blocks.check` after every
edit, with a stand-in scene built from the sim process's description (entity names and state
names), so Entity State shows one port per state of its entity and a wrong entity name is
reported on the block. Without a scene, entity blocks report "no entity ... (entities: none)".
Problems on blocks inside a subsystem are also shown on the subsystem block. The compiler no
longer reports "input ... is not connected" on a block fed by a block that failed (the failing
block has its own message), so one bad block is outlined once, not along the whole chain.

**D-085 — When edits run, and projects.** A running scene compiled its diagram when it loaded
(SE-02: the sim is a separate process), so edits run after a reload. Saving a diagram that the
open scene runs reloads the scene right away if time isn't moving; while it runs, the status
bar says to stop it first. When a scene loads, the editor opens the scene's (first) diagram
unless it has unsaved edits to another one. A project records the open diagram as `diagram`
in `project.json` when it is inside the project; Save Project saves an untitled diagram to
`diagrams/diagram.svd`. A diagram outside the project stays where it is (the scene refers to it
by a relative path, D-072) and opens with its scene.

**D-086 — Live values and port colors (§7.7).** Hovering a wire shows its source's value at
the timeline's current row (live or scrubbed), `pid.y = 0.2101`, or `[a, b]` for a vector; a
diagram that the loaded scene doesn't run says "run the sim to see its value". Ports are
colored by the probed shape of their signal: scalar, vector, matrix (D-077: no bus). Input
ports and ports whose shape isn't known (the diagram doesn't compile) are drawn hollow; wires
take their source port's color. The category and port colors are tokens, ≥ 3:1 on the panel
surfaces in both themes (tested).

**D-087 — Canvas interaction and Scope plots (BD-01, BD-07, BD-08).** Left-drag on the canvas
selects with a rubber band; middle-drag or Alt + drag pans; the wheel zooms around the mouse
(25% to 400%); Ctrl+0 fits the diagram. Drag from any port to a port of the other direction to
connect. Delete / Backspace removes the selection, Ctrl+G groups the selected blocks into a
subsystem, Ctrl+Shift+G ungroups one, Ctrl+A selects all. Double-click a subsystem to open it;
breadcrumbs ("altitude › ctrl") and the Up button go back. Each Scope block gets a time plot in
the plot panel when its scene loads, titled `<diagram>.<scope>` with all its inputs; reloading
the scene replaces those plots (plots the user added are kept).

## Process

**D-088 — CI runs by hand or on PRs to main.** Every push ran 9 jobs, about 99 billed minutes
(GitHub bills macOS at 10× and Windows at 2× on private repos), and November's 43 runs used up
the account's Actions minutes. CI now triggers on `workflow_dispatch` and on pull requests to
`main` (docs-only changes skipped). Branch work is verified locally; the 3-OS run happens once
per milestone, before the owner merges.

## M8: Sensors and draws

**D-089 — A controller's draws last until it runs again.** Before M8 every non-persistent draw
lasted one tick, so a 10 Hz controller on a 1 kHz scene showed its draws for 1 tick in 100.
Draws made inside a controller now belong to it and are replaced the next time it runs; draws
made outside a controller still last one tick; `persist=True` and `clear()` are unchanged.

**D-090 — Solids for custom-model entities.** `scene.attach_shape(entity, shape, size, ...)`
adds a MuJoCo mocap body that follows the entity's `pose()` each tick, so lidar and cameras see
it and the viewport draws (and selects) it. It is kinematic: it pushes free objects, nothing
pushes it.

**D-091 — Sensor timing and noise.** A sensor samples once at the start of a run, then at the
end of every tick that is a multiple of its period, so a controller at tick k reads the state at
tick k, and it holds its reading in between. Its rate must divide 1/dt. Each sensor has its own
noise generator, seeded from the scene seed and its full name, so adding a sensor doesn't
change the others' noise. The IMU differentiates the entity's velocity and orientation over its
sample period (any entity works); its first sample reads -g and zero rate.

**D-092 — Seeker angles.** Range, bearing and elevation to the target are in the world frame at
the sensor (a stabilized seeker): bearing atan2(dy, dx), elevation atan2(dz, horizontal
distance), with white noise per channel.

**D-093 — The camera is ray cast, not rendered.** One MuJoCo ray per pixel on the CPU (geom
color shaded by incidence angle, sky color on a miss) instead of an OpenGL render, so it works
headless and gives the same image on every machine. Default 160x120 at 10 Hz.

## M8: Vehicles toolbox

**D-094 — Paths and roads (TB-VEH).** A path is a 2-D polyline (`sv.vehicles.Path`) with arc
length, `point_at` / `heading_at` (clamped to the ends) and `nearest`, whose `cross_track` is
positive left of the path. Road and lane primitives are data, not MuJoCo geometry: a `Road` is
a centerline with N lanes of equal width, lane 0 the rightmost (drive on the right); lanes and
edges are mitred offsets of the centerline. `road.draw(ctx.draw)` draws edges and dashed
dividers as persistent debug lines (call it once, at t = 0). Lidar doesn't see the road
surface; NPCs get solids with `scene.attach_shape` (D-090) when sensors should see them.

**D-095 — Kinematic bicycle.** Reference point is the rear axle; states x, y, yaw, v; input
`u = [accel, steer]`, clipped to `max_accel` / `max_steer` (35° default), speed held within
[`min_speed`, `max_speed`] (0 to 40 m/s, so no reversing by default). Wheelbase 2.7 m default.

**D-096 — Path trackers.** Pure pursuit uses lookahead `gain * v + min_lookahead` (0.5 s,
3 m) with the goal searched forward from the nearest point; Stanley uses the front-axle
cross-track error with a softening speed (1 m/s). Both are plain callables
`ctrl(x, y, yaw, v) -> steer`, so they work in script controllers and are easy to wrap as
blocks later; `speed_control` is a clipped P-controller on speed.

**D-097 — Scripted NPCs.** `ScriptedNPC` follows a path at a speed given as a constant, a
(t, v) schedule (linear between points) or a function of t; it has no dynamics and doesn't
react to other agents (the PRD's "scripted"). Arc length advances by the trapezoid rule, exact
for piecewise-linear schedules. At the path's end it stops, or starts over with `loop=True`.

## M8: Templates

**D-098 — A template is a scene file that a start-screen card opens.** Each template lives in
`src/simview/templates/<id>/scene.py` (PRD §8) and is self-contained: UC-1's planner is a
controller inside the scene file rather than a separate `planner.py`, so Save Project, which
copies the open scene into the project, takes everything along. Opening a card loads that
scene; cards without a scene yet (UC-2 until the Aerospace toolbox lands, UC-3, UC-4) still
open an empty window. The UC-1 planner keeps its lane with pure pursuit and its distance with
a gap taken from lidar returns inside the lane (6 m standoff + 1.5 s headway, 12 m/s cruise).

**D-099 — UC-2 is a drone delivery fleet (PRD 1.3).** The owner replaced the drone
interception use case with a delivery fleet on 2026-11-20 and kept it as the hero demo. The
Aerospace toolbox (TB-AERO) keeps the 6-DOF quadrotor, EKF and UKF, and flight metrics; it adds
attitude/position flight control, route following, and a wind and gust model, and drops the
interceptor and guidance laws. The template id is `drone_delivery`. The seeker sensor (SN-01)
stays as a general range/bearing sensor.

## M8: Aerospace toolbox (TB-AERO, PRD 1.3)

**D-100 — Quadrotor model.** A rigid body with collective thrust along body z and body
torques: `u = [thrust, tau_x, tau_y, tau_z]`, clipped to [0, `max_thrust`] (2.5 m g by default)
and +-`max_torque`. States are position, world velocity, quaternion (w, x, y, z, body to world,
renormalized each tick), and body rate, so `position()`, `velocity()`, `rotation()` and sensors
work unchanged. Rotor speeds and motor lag aren't modelled. Drag is linear in the air-relative
velocity, `drag * (v - wind)`, which is how a `Wind` entity acts on it.

**D-101 — Attitude controller.** An acceleration command becomes the thrust vector
m (a + g); its direction is the desired body z (tilt limited, 35° default, and never below
10% of hover lift), and yaw is set by keeping body y perpendicular to the yaw heading (the
geometric SO(3) construction). A PD law on the SO(3) error with per-axis gains J wn^2 and
2 zeta wn J (wn 25 rad/s, zeta 0.9) gives the torques. `PositionController` is a PD on
position and velocity errors plus a feed-forward acceleration, limited to `max_accel`.

**D-102 — Wind.** A `Wind` entity is uniform in space: mean plus a first-order Gauss-Markov
gust per axis, stepped with the exact discrete update so the gust variance doesn't depend on
dt. Its velocity is logged as `wind.wx/wy/wz`. Its noise comes from its own generator seeded
from the scene seed and its name, like sensors (D-091).

**D-103 — Route follower.** A carrot moves along the current leg at the route speed, ramping
up and down at `accel` (2 m/s^2), so it stops at each waypoint, and slowing to a stop as the
drone falls `max_lag` behind; its acceleration is fed forward, so the drone doesn't overshoot
the corners. A waypoint counts as reached inside `arrive_radius`; arrival times are recorded
(delivery time is read from them), and `dwell` hovers there (a drop-off). It steers by whatever
state it is given, true or estimated.

**D-104 — EKF and UKF.** One interface: `predict(dt, u)` then `update(z)`, with models as
plain functions and `Q`/`R` as matrices or functions of dt. The EKF takes Jacobians or uses
central differences, and updates P in Joseph form. The UKF uses scaled sigma points (alpha
0.5, beta 2, kappa 0). Both keep the last innovation and its NIS. A `residual` function lets
angle measurements wrap.

**D-105 — Navigation filter.** `NavFilter` estimates position and velocity (6 states) from an
IMU and GPS, loosely coupled: the IMU's specific force, rotated to the world by the drone's
attitude, plus gravity, is the prediction input, and each GPS fix is a position update. The
attitude is taken as known (an attitude reference), so the models are linear and the EKF and
UKF agree; IMU biases aren't estimated. Process noise is the discrete white-noise acceleration
model with the accelerometer noise. In the loop (25 s of gusty flight) the position error stays
inside 3 sigma over 97% of the time and the mean NEES is consistent with 3 degrees of freedom.

**D-106 — How a sweep sets parameters (SE-08).** Scene files read their parameters while they
build the scene (`Wind(gust_std=p.gust)`), so setting `scene.params` after loading would change
nothing that was already built. `load_scene(path, params={...}, seed=...)` runs the file with
overrides: when the file declares a parameter that has an override, the override's value is
used instead. Naming a parameter the file doesn't declare is an error. A later assignment in the
file to the same name still wins (the override applies at declaration only).

**D-107 — Sweep metrics are declared in the scene file.** `scene.metric(name, fn)` with
`fn(run) -> float`. Trials run in spawned processes that load the scene file themselves, so the
metric functions never have to be pickled (lambdas can't be). `sweep(metrics=...)` can also name
logged columns (the last value is taken) or pass a dict of picklable callables. A trial that
raises is a row with `status = "error"` and the message; the sweep carries on.

**D-108 — Sweep plan, seeds, and files.** `params` maps names to constants or distributions
(`Uniform`, `Normal` with optional clipping, `Choice`); `grid` maps names to value lists and
every combination runs `trials` times. All samples are drawn up front from `seed`, and trial i
runs with scene seed `seed + i`, so a sweep repeats exactly whatever the worker count. Results
go to `runs/sweep-<time>/results.parquet` (params, metrics, status, wall time, sweep metadata in
the schema); trial logs are dropped unless `keep_logs=True` (a 60 s UC-2 log is about 70 MB).
`workers=0` runs in-process (debugging). Callers need an `if __name__ == "__main__":` guard.

**D-109 — Analysis definitions (DA-05).** `step_info` follows MATLAB's `stepinfo`: 10-90% rise
time (interpolated), overshoot in percent of the change, settling time as the last entry into a
2% band; `initial`/`final` default to the first/last samples, and levels never reached give NaN.
`bode` takes `(num, den)`, `(A, B, C, D)`, or a `scipy.signal.lti` and returns unwrapped phase
in degrees. `fft` is the one-sided amplitude spectrum scaled so a sinusoid of amplitude A peaks
at A; `psd` is Welch's method in units²/Hz. Both need evenly spaced samples. `rmse(a)` alone is
the RMS of an error signal. They live in `simview/analysis/` (PRD §8.4) and load lazily as
`sv.analysis`.

**D-110 — `Run[column]` reads one column.** It used to read the whole Parquet file for every
column; sweep metrics read several columns of large logs, so it now reads only the one asked
for (same result; unknown names still raise `KeyError`).

**D-111 — Where sweep results open (DA-06).** In their own non-modal window (like the array
viewer), from File → Open Sweep Results… (also the command palette) or `window.open_sweep(...)`
with a `SweepResults`, its `results.parquet`, or its folder. A central page or dock would sit
empty for every scene that isn't swept. The window has the trials table (sortable, numbers
sort numerically, failed trials in `state.error` with the error as tooltip) and, beside it, a
histogram of the chosen metric over the finished trials and a scatter of that metric against a
chosen parameter (or the trial number); selecting a row marks its trial in both, clicking a
point selects its row. Sweeps run from scripts or the console; the in-process console waits
for the sweep to finish (the UI is busy meanwhile), so long sweeps belong in a script.

**D-112 — Scenes as Gymnasium envs (ML-01).** `sv.make_env(scene, obs_fn, reward_fn, done_fn,
**task)` takes a `Scene`, a function that builds one, a scene file, or a template id. A scene file
can declare its own task with `scene.rl_task(...)` (same keys; arguments to `make_env` override
it), so `sv.make_env("drone_landing")` works as in UC-4. Each `reset()` builds a fresh `Sim` with
a scene seed drawn from the env's RNG (so `reset(seed=s)` repeats exactly), then calls
`reset_fn(sim, rng)` to randomize the start. The policy acts at `rate` Hz (default: every tick;
it must divide the tick rate); one env step runs that many ticks and stops early on the tick
`done_fn` turns true. `max_time` truncates. `success_fn` goes to `info["is_success"]` at the end
of an episode, which SB3 reports as `success_rate`. The observation space is inferred (unbounded
float32) when not given.

**D-113 — How a policy drives the scene: `ctx.action`.** The env applies the action twice over:
`act_fn(sim, action)` may return controller-style outputs `{entity: u}` that are applied
directly, and the action itself is exposed to every scene controller as `ctx.action` (None when
no policy is attached). Scenes with an inner loop (the quadrotor's attitude controller at
100 Hz under a 25 Hz policy) read `ctx.action`, and the same scene file runs without a policy:
the drone-landing controller falls back to a PD lander, so the start-screen card still works.

**D-114 — Parallel envs (SE-09, ML-02).** `sv.make_vec_env(scene, n_envs, seed=, subprocess=True)`
returns SB3's own `SubprocVecEnv` (spawned processes) or `DummyVecEnv`, each env wrapped in SB3's
`Monitor`; env i is seeded `seed + i`. It builds the env list itself (not SB3's `make_vec_env`)
so each env knows its index for recording. A `Scene` object can't be sent to other processes,
so it is refused there; pass the file, a template id, or a builder function. Without the `rl`
extra the scene and template still load; `make_env` then raises an ImportError naming the extra.

**D-115 — RL extra and CI.** `pip install simview[rl]` = Gymnasium >= 1.0 and
Stable-Baselines3 >= 2.3 (PRD §8, which pulls in PyTorch). CI installs CPU-only PyTorch from the
PyTorch index first, so Linux runners don't download the CUDA wheels. RL tests use
`pytest.importorskip`, so a dev install without the extra skips them. TensorBoard is not a
dependency: SimView reads event files with its own small protobuf reader (scalars only, simple
and tensor values; CRCs are not checked).

**D-116 — Training metrics and episode replay (ML-03, ML-04).** A training run writes to a
folder `runs/train-<time>/` (`sv.rl.training_dir()`; env worker processes inherit it through
`SIMVIEW_TRAINING`): `metrics.jsonl` from `sv.log_metric(name, step, value)` and from
`model.set_logger(sv.rl.sb3_logger())` (all of PPO's scalars), `episodes-<env>.jsonl` with each
finished episode's return, length, success, and (every `record_every`th episode per env) the
path of its full tick log under `episodes/`, written as a normal run log with its scene file,
so the app replays it like any saved run. TensorBoard event files anywhere in the folder are read
too. The Training panel is a new bottom dock, tabbed with Runs (layout version 4), present
without a scene; it follows the newest `train-*` folder in the run folder (or one opened by
hand), rereads the files once a second, plots the checked metrics against the step, and draws
recorded episodes as large points on the episode-return curve: clicking one replays it. The
episode step is the env's own step count times the number of envs (close to SB3's global step).
Also fixed on the way (RI-01, from M5b): the last row of a saved run showed the scene's start
state, because the timeline's last row means "live"; a saved run has no live state, so its last
row is drawn.

**D-117 — How the NF targets are measured (M10).** `benchmarks/nf_bench.py` runs each check in
a fresh child process. NF-02: `examples/ur5_pick.py` (the UC-3 arm with its IK controller and
logged channel) with `dt` set to 1 ms, 10 s headless. NF-03: the UC-2 template, 30 s headless.
RTF is simulated time over the wall time of the tick loop (`Run.rtf`), not counting scene
loading or the Parquet write. NF-05: "usable" means the window is shown and the Qt event loop
is running (the first zero-delay timer fires), timed from the process's creation, so the
interpreter start and every import count; both the start screen and an empty main window are
measured, best of 3 after one warm-up launch. NF-06: 10 UC-2 runs of 5 s, SHA-256 of each
Parquet file. NF-07: peak resident memory of a UC-2 run with its full log; `--full` runs the
10 minutes, the quick mode extrapolates a 60 s run linearly (the log array is preallocated, so
it grows linearly with the duration). The reference hardware is the GTX 1660 / M1 class named
in NF-01; the Windows dev box (i7-10700K, GTX 1050 Ti, Python 3.13) is slower on single-threaded Python, so
its numbers are a lower bound and the Mac's are the ones the targets are judged on.

**D-118 — Performance changes (M10, NF-02, NF-03).** No public API changes. (1) A MuJoCo world
with no degrees of freedom (only static shapes and the mocap mirrors of custom entities, as in
UC-1 and UC-2) skips `mj_step`; mocap poses are loaded when something reads them
(`World.kinematics()`, now also called by the viewport and recorder before they read body poses).
(2) `Quadrotor` integrates RK4 on Python floats when its integrator is `rk4` and `derivative`
isn't overridden, reading the input and the wind once per tick (they are constant across the
stages); results are bit-identical to the generic integrator. (3) The attitude controller,
`quat_matrix`, and `se3.rot_log` use scalar closed forms (SciPy kept for rotations near pi);
results match within 1e-13. (4) Cached lookups: state indices by name, a robot's frame and
actuator ids (per compiled model), the nav filter's F and Q (per dt), each world member's qpos
and qvel slots as slices. (5) `fk` skips MuJoCo's centre-of-mass pass (only Jacobians and
dynamics need it). (6) SciPy's integrator is imported on first RK45 use (about 1 s of startup).


**D-119 — Toolboxes (TB-01, TB-02).** A toolbox declares an entry point in the group
`simview.toolboxes` whose value is a function `register(tb)`; `tb` (`simview.toolboxes.registry.
Toolbox`) has `add_block(cls)`, `add_entity(cls)`, `add_sensor(cls)`, `add_template(id, title,
description, scene, icon)` and `add_module(name, module)`. Entities, sensors and modules may be
"module:attr" strings, imported on first use, so discovery stays cheap at startup (NF-05).
SimView's robotics, aero and vehicles toolboxes register the same way (`simview.toolboxes.
builtin`, declared in pyproject.toml as §8's layout says) but are also loaded directly, so a
source checkout works without a reinstall. Discovery runs once at app startup and in the sim
process, and lazily on the first unknown block type, template, or `sv.<name>`. What each kind
plugs into: blocks go in the block library under one of the §7.7 categories (so the theme's
category colors stay complete); modules become `simview.<name>` (SimView's own names can't be
shadowed); sensors are also `simview.sensors.<Name>`; templates become start-screen cards after
the 4 flagship ones (scene paths relative to the toolbox's package; unknown icons fall back to
`box`); entity types are listed by `registry.entity_types()` (what TB-03's v1 manager panel will
show). A toolbox that fails to import or register, or takes a name already used, is recorded in
`registry.toolboxes()` with its error and skipped; SimView still starts. Test toolboxes are real
installed distributions (`.dist-info` with `entry_points.txt` on `sys.path`).

**D-120 — Keyboard shortcuts (DS-11).** §7.8's Ctrl/Cmd+1–4 switch workspace presets, which are
DS-12 (v1); until then Ctrl+1 / Ctrl+2 switch the 3D view and the diagram (D-082). Undo/redo
cover the block editor; the inspector is read-only and the viewport has no persistent scene edits
yet, so there is nothing else to undo. The editor's standard shortcuts now bind every platform
key (`setShortcuts`): before, Redo only got its first binding, which is Ctrl+Y on Windows, so
§7.8's Ctrl+Shift+Z did nothing there.

**D-121 — Vision world model (PRD 1.4, owner request 2026-11-22).** The owner asked for camera-based
3D perception "similar to what Tesla has done", built on input/output streams. Read as: surround
cameras → depth → a fused 3D occupancy grid and BEV map that controllers drive from (Tesla's
occupancy-network idea, done geometrically rather than learned, since the simulator gives depth and
poses; the learned version is VW-30). Streams run inside the scheduler tick so runs stay
deterministic (§8.5). Owner's choices: the milestone is **M11, after M10** is finished; MVP inputs
are **simulated cameras and recorded image/depth datasets only**, with no new dependency; webcam
and video files (VW-20, would need opencv) and depth from plain RGB (VW-21) are v1. The existing
SN-02 camera already measures metric depth, so VW-01 reuses it rather than waiting for SN-04.

**D-122 — Camera rigs and frame conventions (VW-01, M11 part A).** `sv.perception.CameraRig(cameras,
rate=10, *, name="rig", pos, rpy, maxlen=64)` is a `Sensor` (attach with `ego.attach(rig)`, read as
`ego.sensors.rig`); it holds SN-02 `Camera`s whose `pos`/`rpy` are in the rig's frame, samples them
all at the rig's rate (each camera's own rate is ignored) and publishes one `Stream` per camera,
named `<entity>.<camera>` (`rig.streams`, in camera order). Presets: `CameraRig.surround(n=8, *,
width=160, height=120, rate=10, mount_height=1.4, max_range=60, name="rig")` = front_main (60°),
front_narrow (35°), front_wide (120°) 1 m ahead; left_front/right_front (±75°, 90°), left_rear/
right_rear (±135°, 90°), rear (180°, 90°), all 1.4 m up, no pitch; other n give an even ring.
`CameraRig.drone(n=6, ...)` = front/left/back/right at 90° plus down and up (other n: an n-1 ring
plus down). Conventions for every perception consumer: world frame, metres, Z up. A frame's `pose`
is world-from-camera of the **OpenCV optical frame** (x right, y down, z forward;
`SENSOR_FROM_OPTICAL` converts from SimView's sensor frame, x forward, y left, z up). `K` uses the
OpenCV pixel convention (pixel (u, v)'s centre at (u, v), so cx = W/2 - 0.5); `camera_K(cam)`
computes it (the SN-02 `Camera.intrinsics` property, cx = W/2, is unchanged). Depth is **float32
z-depth** along the optical axis (the camera's range times the ray's cosine); inf, nan or 0 = none.
`rig.camera_pose(name)` and `rig.intrinsics(name)` give a camera's pose and K.

**D-123 — Streams (VW-02).** `Stream(name, maxlen=64)`: `push(item, t) -> seq`, `latest()`,
`seq`, `t`, `items(after)`, `reader()`. A `Reader` (one per consumer) has `since_last()` (every
item since its last read), `latest()` (newest; skipped items count), `dropped`, `pending`. Items
are anything: camera streams carry `Frame(t, seq, source, K, pose, rgb, depth=None, ego=None)`
(`ego` = the vehicle's 4x4 world pose); pipeline outputs carry their stage's result. Grid streams
carry the **same live `OccupancyGrid` object** every step (use `grid.copy()` to keep a snapshot).
Wiring (additive only): `scene.add_pipeline(p)` (rate checked like controllers, unique names),
`scene.pipelines`, `sim.streams` (every rig and pipeline stream, built when the `Sim` starts),
`ctx.streams` in controllers. Order inside a tick: controllers, integration, sensors sample (rigs
publish frames), then the pipelines due at that tick; also once at start after the first sample.
So a controller at tick k sees the grid fused from frames up to tick k, and nothing is lost.

**D-124 — Pipelines (VW-04).** `Pipeline(stages, *, rate=None, inputs=None, name="perception",
maxlen=64)`; `inputs` is a rig, a stream name, a `Stream`, or a list (None = every stream in the
run except its own). A step runs only if new input arrived; stage 0 gets the list of new items
ordered by input stream then sequence number; each later stage gets the previous output; None
stops the chain. Each stage publishes `<name>.<output>`, where `output` is the stage's `output`
attribute (`cloud`, `occupancy`, `bev`, `record`) or the callable's `__name__`; a stage's
`reset()` is called when a run starts. `pipeline["occupancy"]` / `pipeline.outputs` give the
streams, `pipeline.latest()` their newest items. Offline, `pipeline.run(dataset_or_frames,
speed=None)` resets the stages and groups frames into the steps a run would have used (step k =
frames with ceil(t·rate) = k; rate None = one step per distinct t; ties in dataset camera order),
returning `{stream name: last item}`. A run exported with `Record` and replayed this way gives a
byte-identical grid (tested).

**D-125 — Back-projection (VW-05).** `BackProject(max_range=40, *, min_range=0, stride=2,
ego_box=None) -> PointCloud(t, points (N,3) float64, colors (N,3) uint8, origins (C,3),
origin_index (N,), ego)`. Range is the Euclidean distance from the camera. Strided pixels start at
(0, 0). In a sim the ray caster already skips the rig's own body (SN-02); `ego_box=((xmin, ymin,
zmin), (xmax, ymax, zmax))` in the vehicle frame also masks the vehicle in recorded data (needs
frames with `ego`). Pixels with no depth are dropped (they don't clear free space).

**D-126 — Occupancy grid (VW-06).** `OccupancyGrid(res=0.2, extent=60, *, height=(0, 4),
center=(0, 0), rolling=False, floor=0.1, l_occ=0.85, l_free=-0.4, clamp=(-2, 3.5), decay=0)`.
`extent` is the horizontal size (a number = square, or (x, y)); `height` the z range. Arrays:
`logodds` (float32, (nx, ny, nz); [i, j, k] is the voxel with lower corner origin + (i, j, k)·res)
and `seen` (bool). Per update each voxel changes at most once (OctoMap-style; a hit wins over a
pass-through); free space is traced by sampling every ray at `res` spacing, all rays at once in
NumPy (float32 voxel coordinates). Occupied = log-odds > 0, free < 0, unknown = 0. `floor`: hits
below it are ground; they clear space but never occupy, so the ground doesn't block planners
(None turns it off). `decay` scales values toward 0 each update and snaps |L| < 0.01 to 0.
`rolling` re-centres on the cloud's ego pose (else the mean camera origin) in whole voxels,
keeping the overlap. Queries: `occupied(points)`, `is_free(a, b)` (unknown counts as free),
`nearest_obstacle(pos, within=inf) -> float` (to voxel centres; a 2-element pos measures
horizontally over all heights), `closest_occupied(pos, within)`, `occupied_centers()`,
`occupancy`, `probability`, `bounds`, `copy()`, plus `t`, `version` (update count) and `ego`.
Benchmark (Windows dev box, i7-10700K): one 8-camera 160×120 rig frame casts in ~30 ms,
back-projects (stride 2, ~18k points) in ~3 ms and fuses into a 60 m × 60 m × 4 m grid at 0.2 m in
~50 ms; a box scene with that rig at 10 Hz runs headless at ~1.08× real time. R8 levers: `stride`
(3 roughly halves fusion), rig size and rate.

**D-127 — BEV map (VW-07).** `BevMap(z_band=(0.2, 2.5)) -> Bev(t, occupied (nx,ny) bool, known
(nx,ny) bool, height (nx,ny) float32 = top of the highest occupied voxel in the band or nan, image
(ny, nx, 3) uint8, origin (x, y), res, ego)`; `bev.pixel(x, y) -> (row, col)`. Arrays index like
the grid ([i, j] = x, y); the image is the map seen from above, +x right, +y up (row 0 = largest
y). Image values are data, not UI styling: unknown 128, free 255, occupied 96 (low) to 0 (tall),
gray in all three channels; a UI may recolor from the arrays.

**D-128 — Dataset format and PNG I/O (VW-03).** Folder: `cameras.json` + `<camera>/rgb/NNNNNN.png`
(8-bit RGB) + `<camera>/depth/NNNNNN.npy` (float z-depth, metres) or `.png` (16-bit gray,
millimetres, 0 = none). `cameras.json` = `{"format": "simview-dataset", "version": 1, "cameras":
[{"name", "width", "height", "K" (3x3), "frames": [{"t", "seq"?, "pose" (4x4 world-from-optical),
"rgb", "depth"?, "ego"? (4x4)}]}]}`, paths relative to the folder; K and pose follow D-122.
Required fields, matrix shapes, rigid poses, non-decreasing times and file existence are checked
on open (`DatasetError`, a `ValueError` naming the camera, frame and field); image sizes when a
frame is read. `Dataset(path)`: `cameras`, `frames()` (time order, ties in camera order),
`replay(speed=None)` (1.0 = recorded rate, 2.0 = twice as fast, None = as fast as possible; also
pushes into `dataset.streams[camera]`), `len`, `duration`. Writing: `DatasetWriter(path,
depth="npy"|"png16")` with `add(frame)`, `flush()`, `close()`; `write_dataset(path, frames)`; and
the pipeline stage `Record(path, depth="npy")`, which exports a run's camera streams (images
written as they arrive, cameras.json rewritten each step, so the folder is valid if the run
stops). The camera name is the frame's source (e.g. `ego.front_main`). `npy` is the default
because it keeps float32 depth exactly (byte-identical replay); `png16` is compact but rounds to
1 mm. PNG I/O is a small NumPy + zlib codec (`simview.perception.png`: writes unfiltered RGB8 /
Gray16; reads 8/16-bit gray, gray+alpha, RGB and RGBA with all five filters, no interlacing), so
there is no imaging dependency (D-121; Pillow is only a transitive dependency and isn't used).

**D-129 — Accuracy against ground truth (VW-10).** `evaluate(grid, scene, *, z_band=None,
radius=None, pos=None, exclude=(), observed_only=True) -> Accuracy(iou, precision, recall,
nearest_error, nearest_true, nearest_perceived, tp, fp, fn)`; `truth_grid(grid, scene, exclude)`
gives the true voxels. Truth = voxels whose volume overlaps a MuJoCo geom (tested at the voxel
centre against the shape grown by half a voxel, strictly, so a voxel that only touches a face
doesn't count): boxes, spheres, capsules, cylinders, ellipsoids; meshes and other types by their
bounding box; planes and height fields are ground and skipped; `exclude` drops entities' bodies
(and their children), e.g. the ego proxy. Scores count only voxels the grid has observed (cameras
can't see inside or behind solids), within `z_band` and within `radius` m (horizontal) of `pos`
(default: the grid's ego position). Nearest distances are from `pos` to the nearest true /
occupied voxel centre in the band. On the 4-box test scene a still 8-camera 160×120 surround rig
reaches IoU 0.89 within 20 m at 0.2 m voxels (M11 target ≥ 0.7). Logging the metrics as run
signals is left to the VW-09 logging work.

**D-130 — `sv.perception` registration.** Perception is core (`src/simview/perception/`, PRD
§8.4) but is reached as `sv.perception` through the built-in toolbox `perception`
(`simview.toolboxes.builtin:perception`, in `registry.BUILTINS` and the pyproject entry points),
which also registers `CameraRig` as a toolbox sensor (`sv.sensors.CameraRig`). `"perception"` is
in `simview.__all__`, like the other built-in toolbox modules.

**D-131 — Logging and replay of perceived worlds (VW-09, M11 part B).** A `Pipeline` with an
`OccupancyGrid` stage logs with the run, configured by new keyword arguments (defaults keep
part A's behaviour otherwise): `entity=None, signals=True, iou_radius=None, snapshot_every=0.5,
camera_every=None`. **Signals** (added to `scene.channels` by `scene.add_pipeline`, so they are
ordinary Parquet columns that plots and RI scenarios read): `<entity>.perception.min_obstacle_dist`
(m, horizontal distance from the grid's ego position, i.e. the vehicle origin, to the nearest
occupied voxel centre over all heights; **NaN** while nothing is occupied, so plots break the line
and scenario comparisons are false), `<entity>.perception.occupied_voxels`, and with `iou_radius`
`<entity>.perception.iou` = `evaluate(grid, scene, z_band=(0.2, 2.5), radius=iou_radius,
exclude=[entity])` (recomputed at most every 0.5 s because it reads every geom; it scores, the
planner never sees it). `entity` defaults to the input rig's entity, else the pipeline name.
Values are cached per grid update. **Snapshots** (every `snapshot_every` s of sim time, at the
first pipeline step at or after each due time, so t = 0, 0.5, 1.0 ... at 10 Hz) are kept in memory
and written once when `sv.run` ends to `<run>.perception/<pipeline>.parquet` beside the log (a
folder, so `Catalog`'s `*.parquet` glob doesn't list it as a run): one row per snapshot with `t`,
`version`, `res`, `origin` (3), `shape` (3), `voxels` (list<uint16>, the occupied (i, j, k)
flattened), `bev_origin`, `bev_res`, `bev_shape` (ny, nx) and `bev` (the gray BEV image bytes;
D-127 colours are gray, so one channel is stored). **Camera frames** (every `camera_every` s,
default off) go to `<pipeline>.cameras.parquet`: `t`, `camera`, `width`, `height`, `rgb` bytes
(no depth). Parquet because the run log already relies on `pq.write_table` being byte-identical
for identical data (NF-06, tested on both files); npz was rejected because zip entries carry
timestamps. **Reader** (for the UI's timeline scrubbing): `sv.perception.load_snapshots(run,
pipeline=None) -> Snapshots` (`run` = log path or `Run`; None = the only/first pipeline);
`Snapshots.times`, `len`, `[i]`, `index_at(t)`, `at(t) -> Snapshot | None` (newest at or before
t), `cameras`, `camera_at(camera, t) -> CameraFrame | None`; `Snapshot(t, version, res, origin,
shape, indices (N,3), bev (ny,nx,3) uint8 | None, bev_origin, bev_res)` with `.centers` and
`.occupancy()`; `snapshot_pipelines(run)`, `perception_dir(run)`. Sweeps delete the folder with a
trial's log unless logs are kept. Live GUI sessions don't write side files yet (the UI part
decides when a session's run is saved); `PerceptionLog.write(path)` / `runlog.write_snapshots`
are the hooks for that.

**D-132 — `Record` writes its index at the end (VW-03 perf fix).** Part A's `Record` rewrote
cameras.json every step (quadratic in run length). Now images are still written as frames arrive,
but cameras.json is written when the run ends (`Sim.close()`, new, called by `sv.run`; it calls
each pipeline's new `close()`, which calls stages' `close()`), every `flush_every` steps
(`Record(path, depth, *, flush_every=100)`, None = only at the end), and by a `weakref.finalize`
when the stage is reset or collected, so a dropped live session still leaves a valid folder. A
dataset read while a run is still going may lag up to `flush_every` steps. Replay stays
byte-identical (tested through `Sim.close()` and through `sv.run`).

**D-133 — `vision_drive` template and the M11 checks (VW-11).** Registered as a fifth start-screen
card by the built-in `perception` toolbox (`add_template`, icon "eye"); the 4 flagship cards are
unchanged. Scene: the UC-1 road (110 m straight, 60 m-radius quarter arc, 60 m straight, 2
lanes), the UC-1 kinematic bicycle with `CameraRig.surround(8, 160x120, 10 Hz)` and no lidar,
pipeline `ego` = `BackProject(max_range=30, stride=3)` → `OccupancyGrid(0.2 m, 60 m rolling,
height 0-3 m)` → `BevMap()`, with `iou_radius=20`. Obstacles: 4 parked cars on the right
shoulder, a pedestrian-sized box (0.6 x 0.6 x 1.7 m) in the ego lane, a stalled `ScriptedNPC`
(speed 0) in the ego lane, and, in every 4th layout, a barrier across the left lane next to it so
the car must stop. All obstacles are static (simplest reading of "static and slow"; a moving
object would leave a trail in a grid without decay). **Seeding:** the obstacle layout must exist
before the MuJoCo world compiles, but `load_scene(seed=)` sets the seed after the file runs, so
the jitter is driven by a scene parameter `layout` (0 = nominal, others jitter positions with
`default_rng(layout)`; `layout % 4 == 3` adds the barrier); the 20-run test sweeps `layout` 0-19
(seeds 0-19 too). **Planner** (10 Hz): reads only `ctx.streams["ego.occupancy"]` plus the ego's
own state and the lane map (map data, not obstacle geometry); occupied voxels between 0.3 and
2.2 m are put in lane-0 coordinates, corridors 1.4 m either side of each lane centre are checked;
it changes to the left lane when its lane is blocked within 28 m and the left lane is clear
further, returns when its lane is clear from 7 m behind to 20 m ahead, and sets speed from the
gap ahead (standoff 4 m, headway 1.2 s, 3 m/s² braking). **Checks:** (a) 20 of 20 layouts: no
overlap between the ego footprint and any box geom's true footprint at any tick (separating
axes, in the test only); the 15 open layouts pass the stalled car and end back in lane, the 5
blocked ones stop; (b) IoU: each run's time-averaged `ego.perception.iou` ≥ 0.7 (observed:
about 0.85; single early samples, with the car still and few views, are lower, ~0.45-0.65);
(c) replay: D-132; (d) RTF on the dev box (i7-10700K): 1.25x median for a 14 s run
(`benchmarks/vision_bench.py`). With part A's stride 2 and 35 m range it ran at 0.82x, so stride
3 and a 30 m back-projection range (obstacles are still seen ≥ 30 m ahead, enough to change lanes
at 10 m/s) are the trade-off: about half the rays, a slightly sparser grid. The 20-run sweep
(parallel processes, ~75 s) is marked `slow` (new marker; runs by default, `-m "not slow"` skips
it).

**D-134 — Perception views and replay in the app (VW-08, VW-09 UI half, M11 part C).**
**IPC (§8.5):** `simview.ipc.perception`. In the sim process `PerceptionOut` runs on every state
publish (≤ 120 Hz wall): each pipeline's newest occupied voxel centres (float32 (N, 3)) and BEV
image (gray (ny, nx) uint8; metadata t, origin, res, ego (x, y, yaw)), and each `CameraRig`
camera's newest image (decimated by an integer stride to ≤ 320 px wide), are copied into that
stream's own `FrameSlot` (new in `ipc/shm.py`: a seqlocked shared-memory block, header + 8 float64
metadata + bytes; a frame that outgrows its slot gets a new slot 1.5× its size). One ZMQ event
`{"event": "frames", "frames": [(stream, kind, shm name, seq), ...]}` names what changed. The UI's
`PerceptionIn` (on `SimClient.perception`) only notes the events and reads each slot once per UI
frame, so a slow UI skips to the newest frame. The pipelines' logged rows (D-131 snapshots and
camera frames) go to the UI as `{"event": "snapshots", "pipeline", "snapshots", "frames"}` as they
are logged: that is the live session's scrubbable history (cheap: 2 Hz by default). Pickled ZMQ
was kept for these rows because they are small and must all arrive (a slot would drop them).
`Description` gains `cameras` (camera stream names) and `pipelines` (name → ego entity).
**Snapshot format:** D-131's table gains a nullable `ego` column (x, y, yaw of the grid's ego
pose) for the BEV marker; `Snapshot.ego` defaults to None, so older logs still load.
`runlog.write_rows` / `snapshot_table` / `camera_table` are shared by `PerceptionLog.write` and
the app. **Viewport:** voxels are one `vtkGlyph3DMapper` (GPU-instanced cube of 0.92 × res per
centre, "rgb" point colors from height over 0-3 m on viridis, `tokens.VIRIDIS`, 9 stops linearly
interpolated); `set_voxels(centers, res)` swaps the mapper's input in place. Perceived vs true
geometry is a view mode `both` / `perceived` (voxels; scene geoms, edges and visuals hidden;
grid, markers and trails stay) / `true`, in the View menu and the command palette (three actions
plus "Cycle Perceived / True Geometry"), not a heads-up toolbar button (the toolbar's buttons
are two-state; a third state there was the less simple reading). **Panels:** new docks
`cameras` ("Cameras": thumbnail grid, click to enlarge, click again or Back to return) and `bev`
("BEV Map": the image scaled to fit, nearest-neighbour, ego as an `accent` arrow), tabbed after
Training in the bottom-right group; `LAYOUT_VERSION` 5. Empty states: "This scene has no camera
rig." / "This scene has no perception pipeline." with "Open Template…" (the start screen has the
vision_drive card). Only the scene's first pipeline is shown (simplest reading; one pipeline per
scene in every template). **Replay:** at the live end the views show the newest live frames;
anywhere else on the timeline they show the snapshot at or before that time, from the in-memory
history (live session) or `load_snapshots(run)` (an opened saved run). Cameras follow the
timeline only from logged camera frames: with `camera_every` off (the default, also in
vision_drive) the thumbnails show "No camera frame logged at this time" when scrubbing.
`save_live_run` writes the session's rows with `write_rows` to `<run>.perception/`, so a
reopened run shows the same snapshots. **Pending a real display:** `tests/ui/test_viewport_gl.py`
`test_voxels_render_and_toggle_perceived_vs_true` and `test_50k_voxels_render_at_30_fps` (the
VW-08 ≥ 30 FPS @ 50k criterion) are written but were not run (the dev box's screen was locked;
run `QT_QPA_PLATFORM=windows SIMVIEW_GL=1 pytest -m gl tests/ui/test_viewport_gl.py`), plus a
manual look at the vision_drive template: voxel colors, the BEV arrow's heading, thumbnail
grid, light theme.

**D-135 — M11 audit: edge-case behaviour (VW-02..VW-09).** Decisions taken while fixing bugs
found in the M11 review. **Default pipeline inputs:** `Pipeline(inputs=None)` reads only the
sensors' (camera rig) streams, not other pipelines' outputs (D-124 said "every stream except
its own", which fed a second pipeline the first one's grids and crashed `BackProject`; the
docstring already said "every camera stream"). **Readers after a reset:** `Stream.reset()` bumps
`stream.epoch`; a `Reader` that sees a new epoch starts again from the first item (before, a
reader kept its old cursor and missed every item of a replayed dataset). **Occupancy input:**
points or camera origins that aren't finite are dropped before fusion (inf cast to a huge ray
length on ARM); a rolling grid with no ego pose and no camera origins doesn't move; grids of
2^31 voxels or more use int64 flat indices in ray tracing. **Snapshots:** voxel indices are
uint16 (D-131), so a pipeline that logs snapshots refuses, when it is built, an
`OccupancyGrid` with more than 65535 voxels along an axis (`snapshot_every=None` lifts it).
**Closing runs:** `Sim.close()` is idempotent and now also runs when `sv.run` fails, when the
sim process reloads a scene or its loop crashes (which also unlinks the shared memory), at each
RL episode reset and `env.close()`, and at the end of an offline `Pipeline.run()`. **Datasets:**
`cameras.json` with another `format`, or a `version` other than 1, is refused; `seq` must be an
integer and `t`/`width`/`height` not booleans; damaged PNG/NPY files and non-numeric depth
arrays are `DatasetError`s naming the file; `DatasetWriter.add` refuses a frame whose size
differs from the camera's earlier frames, whose depth isn't the image's size, or whose time is
not finite or goes back, so the writer can't produce a folder `Dataset` rejects. **Truth for
meshes:** the search window around a mesh's bounding box uses the box's own radius (the geom's
`rbound` is about its origin, not the box centre). **UI:** a damaged perception side file no
longer stops a saved run from opening; the status bar says the snapshots weren't loaded.

**D-136 — Security review: trust boundaries and hardening.** Scene files, editor scripts,
toolboxes, projects (they load a scene), and block diagrams with Python Function blocks (the
editor runs or imports the function a block names to read its ports) are code and run with the
user's permissions by design; `SECURITY.md` says so. Data is never executed. **IPC:** the
UI's ZeroMQ PAIR socket stays on 127.0.0.1 at a random port; messages are still pickled (numpy
arrays, dataclasses), but every message is signed with HMAC-SHA256 under a 32-byte random key
made per sim process and passed to it through `multiprocessing` (not its command line), and a
message without a valid signature is dropped before it is unpickled (`protocol.send/recv`
replace `send_pyobj/recv_pyobj`). Another local process can still take the port first and
stop the session starting (denial of service only). **Shared memory:** `FrameSlot.read()`
returns None for a header whose size, dtype code, rank, or shape doesn't fit the slot; a segment
smaller than the header is refused. **Paths:** `cameras.json` frame files and a project's
`scene`/`script`/`diagram` must be relative paths that resolve inside their folder (absolute
paths and `..` escapes are refused, as `DatasetError`/`ProjectError`); `DatasetWriter` camera
names can't contain `:`; a Menagerie MJCF that references a file outside the robot's folder
is refused. **Replaying a run** loads the scene file its metadata names: the app asks first
unless that scene is the open one, inside the open project, or inside the SimView package
(templates). **Scenarios:** numeric constants evaluate as float64, so `9**9**9**9` can't hang on
Python big integers. Already safe, kept: `np.load(allow_pickle=False)`, no `eval`/`exec`/YAML/
`shell=True`, the in-process IPython kernel (no sockets), HTML reports escape every name.

**D-137 — Owner's answers to QUESTIONS_FOR_TOMORROW.md and PRD 1.5 approval (2026-11-22).**
The owner approved PRD 1.5 and took the recommended default for all 15 questions:
(1) §5.13–§5.17 approved as written, all kept out of MVP. (2) M12 after M11 builds ST-01–ST-03 and
RP-01–RP-02 (they reuse RI and the sweep runner and make the hero demo checkable as a suite); added
to §10. (3) Scenarios in Python and TOML (stdlib `tomllib`, no YAML). (4) Remote policies (PE-04,
pyzmq) stay in v1. (5) NG5–NG7 kept; ROS 2 / PX4 bridges stay in BACKLOG.md. (6) VW-20 uses an
optional `simview[video]` extra (`opencv-python-headless`), added to §8, not a core dependency.
(7) The owner reruns the M10 benchmark on the Mac reference machine; results go in PROGRESS.md.
(8) The pending visual checks are done on the current branch (M10 part 3). (9) RP-01 manifests
record the git commit and machine info by default, with a flag to leave machine info out.
(10) M10 parts 3–5 are finished before the M11 review. (11) The owner merges M8 (PR #2), then M9;
the M10/M11 branches are then rebased or merged onto the new `main`. (12) PRD changes keep being
proposed as drafts with nothing built until approved. (13) Git history is not rewritten; commits in
this repo now use the GitHub noreply address (repo-local `user.email`). (14) Opening a `.svd` runs
its Python Function blocks' files; kept, documented in SECURITY.md. (15) IPC keeps signed pickle;
revisit only if a network mode (VW-33) arrives.

**D-138 — NF-01 measurement (M10).** NF-01's scene is built in `tests/ui/test_viewport_gl.py`
(`test_nf01_...`): 20 quadrotors with box shapes and trails, a 50k-point cloud, 1280×720 with 4×
MSAA, the entities moving every frame. On the dev box (GTX 1050 Ti, below the GTX 1660 / M1
reference) a frame takes ~20 ms (~48 fps): ~14 ms VTK render, ~5 ms rebuilding the 20 trail
polylines through PyVista, ~2 ms the rest; the 50k cloud costs nothing measurable. A raw-VTK
polyline builder only saved ~0.05 ms per trail, so it was dropped. The test asserts a 30 fps
floor (a regression guard) and prints the number; the 60 fps target is checked on reference
hardware. Gap and next step (needs owner approval, it reshapes the viewport's trail actors):
merge all trails into one actor with per-point colors.

**D-139 — The hero demo's block diagram (M10).** PRD §10 asks for the UC-2 loop as a block
diagram. The Drone Delivery template flies d0 by `d0_loop.svd` (Python Function blocks from
`delivery_loop.py`: IMU + GPS → EKF → route follower → an Entity Input block on the quadrotor);
d1 and d2 stay on the script controller, so both ways are shown. `USE_DIAGRAM = False` flies d0
from the script too; a test checks the two give the same flight (1e-9). Each block loads its own
copy of `delivery_loop.py`, so the drone is passed through the module `scene.py` imports (each
copy reads it at load time, so several scenes in one process keep their own drone). With no
drone (the app's Diagram tab) the functions return zeros of the right shapes, so the editor's
check is clean. The demo video is `docs/media/hero_demo.mp4`, recorded by
`tools/record_hero_demo.py` from inside the app (widget grabs plus the VTK render, never the
desktop) with ffmpeg as an external tool, not a dependency.

**D-140 — NF-01 trail merge (M10, approved 2026-11-22).** The owner approved D-138's proposed fix
with M10. All trails are now one polyline mesh drawn by one actor (`Viewport.trail_actor`), built
each frame by `model.merged_trails` from every trail's points with a per-point uint8 "rgb" array
(a trail's `scene.trail(color=...)`, else the Okabe-Ito palette by order, cached per name and
reset when the theme reloads the scene). The per-entity `trail_actors` dict is gone (it was only
used inside the viewport and by tests). NF-01's scene on the dev box (GTX 1050 Ti): median frame
~20 ms -> ~10.4 ms (~96 fps), so the 60 fps target is met even below the reference GPU.

**D-141 — Run manifests and `simview reproduce` (M12, RP-01, RP-02).** The manifest lives in the
run's context sidecar `<run>.run.json` under `manifest`, not in the Parquet footer, so a seeded
run still writes a byte-identical log (NF-06). `write_context` builds it, and every path that
saves a run already calls it after writing the log (headless `sv.run`, the app's Stop, RL episode
recordings, sweep trials), so all of them get one; seed, params and duration are read back from
the log's own metadata, so the manifest can't disagree with it. A sweep also writes
`manifest.json` (plus its trial plan) beside `results.parquet`. Versions come from package
metadata (no imports): SimView, Python, numpy, mujoco, scipy, pyarrow; toolboxes from the
registry. "Hashes of scene files" = the scene file and the source-like files beside it
(`.py .svd .toml .json .xml .urdf .mjcf .yaml .yml .csv`, not recursive, so a scene in a big
folder stays cheap; files over 64 MB are listed as skipped), plus each diagram's `.svd` and
every dataset folder opened in the process (`perception.dataset.opened_datasets()`, recorded
once a folder validates; one hash over all its files). Machine info (OS, CPU, cores, hostname) is
on by default (D-137 Q9) and left out with `SIMVIEW_NO_MACHINE_INFO=1`, which `--no-machine-info`
on `simview run` / `simview test` sets (spawned workers inherit it). Git: `git -C <scene folder>`
commit, dirty flag (`status --porcelain`) and root, or null without git or a repo.
`simview reproduce <run>` loads the run's scene file with its seed and start params, runs it
headless for its duration into a temp folder, and compares with RI-05's `compare` at atol 0
(`--atol/--rtol` to loosen): identical means the same sample times, the same signal set and no
diverging signal. Otherwise it names the earliest-diverging signal (ties by name) and its time.
It always lists environment differences (versions, toolboxes, OS/CPU/hostname, git commit,
changed / missing / new files). Exit codes: 0 identical, 1 diverged, 2 cannot reproduce
(imported log, scene file gone, scene fails to load). Runs made before RP-01 still reproduce,
reported as having no manifest. All 5 templates reproduce identically on the dev box (test).

**D-142 — Scenario test criteria (M12, ST-01).** Criteria are strings with a verb in front of an
RI-02 pattern (the PRD's `must_not: ...` / `must: ... within 120 s` syntax): `must_not: P` fails
if P occurs anywhere; `must: P within T s` fails unless P occurs with its match starting by T;
`must: P` with no deadline fails unless P occurs at all. So `must` means "exists" and `must_not`
"never"; "always P" is written `must_not: not (P)`. `within` with `must_not` is rejected. A
missing signal fails the criterion with "missing signals: ..." (never a silent pass, like
RI-02). Evidence (RI-03): a `must_not` failure carries its match windows; a `must` failure
carries the searched span [start, T]. In TOML a criterion is a string or `{ name, must |
must_not }`. Initial conditions are scene parameters (scene files read `scene.params` while
building, D-106), so there is no separate initial-state syntax. Parameters: number, number list
(array param), `{ uniform = [lo, hi] }`, `{ normal = [mean, std], lo, hi }`, `{ choice = [...] }`;
grid values: a list or `{ linspace = [lo, hi, n] }`. A Python suite file defines
`suite = sv.TestSuite(...)`; relative scene paths are relative to the suite file. Each scenario
runs through `sv.sweep` with `keep_logs=True` (logs, results table and the sweep manifest in
`<out>/<scenario>/`), so samples run in parallel and repeat exactly whatever the worker count.
The package is `simview.testing` (`sv.TestScenario`, `sv.TestSuite`).

**D-143 — RI-05 comparison counts one-sided NaN as a divergence (M12).** Found while building
RP-02: `compare` tested `|a - b| > tol`, which is False for NaN, so a signal that was NaN in one
run and a number in the other (e.g. a sensor with no reading yet) compared as equal, and all-NaN
signals raised NumPy warnings. Now NaN on exactly one side is a divergence, NaN on both sides is
not, and max/RMS are taken over the finite differences (0 when there are none).

**D-144 — Baselines and the regression gate (M12, ST-03).** A baseline is JSON: per case
(`scenario#index`) its status, seed, params, verdict per criterion, and metrics (the scenario's
`metrics`, default every metric the scene declares). Compared with a later run: a criterion
passing before and failing now is a new failure; the reverse is newly passing; a case erroring
now but not before is a new error; a metric drifts when |now − base| > atol + rtol·|base|
(RI-05's tolerance rule) with rtol = the scenario's `tolerance` (default 0.1, per metric with a
table) and atol 1e-9. Drift in either direction is a regression (SimView doesn't know which way
is better; an intended change is accepted by saving a new baseline). Exit codes: without
`--baseline`, 1 on any failed or erroring case (ST-02); with it, 1 only on regressions, so a
failure already in the baseline is reported but doesn't block (that is the point of a baseline).
New and missing cases are listed, not regressions.

**D-145 — The hero demo's checks as a suite, and what it found (M12).**
`templates/drone_delivery/checks.toml`: 8 samples over the hero demo's ranges (GPS noise
0.4–1.6 m, gusts 0.5–3 m/s), 30 s each. Criteria: each drone delivers within 28 s (they take
~22.6 s), each drone's EKF error stays inside its per-axis 3σ bound (no stretch outside longer
than 1 s), and no drone strays more than 5 m from its route. It runs in ~15 s on 16 workers.
First run: 7 of 8 pass; sample 2 (GPS noise 1.38 m, gust 2.78 m/s) has d2's error outside its 3σ
bound for 1.2 s (14.9–16.1 s), i.e. the EKF is overconfident in strong gusts (its process noise
doesn't cover them). The suite is left strict and the EKF untouched: retuning the template's
filter changes the hero demo and is the owner's call (PROGRESS, Next). The pytest runs the first
2 samples, which are mild and pass.

Update (2026-11-22, owner asked to retune the EKF): the tuning sweep (16 seeded samples over the
same ranges) shows the filter is consistent, not overconfident: with the original settings
~0.8% of samples are outside 3σ on some axis (theory for 3 axes: 1 − 0.997³ ≈ 0.8%) and the RMS
of error/σ is ~0.92. Because the filter averages GPS over seconds, its error is slow, so an
excursion past 3σ lasts ~1–2 s; a "never outside 3σ for more than 1 s" check therefore fails
now and then even for a perfectly tuned filter. Tried and reverted: a gust term in the process
noise (no effect on the other failures) and a 0.8 m/s² process-noise floor (hero suite 8/8 but
1/32 still fails at GPS 1.6 m + gust 2.95 m/s, and route deviation rose to 0.78 m, failing the
template's 0.6 m test). A first hypothesis (an IMU lag) was wrong: sensors sample at the end of
the tick (D-091), so the IMU's mean acceleration covers exactly the interval the filter predicts.
Proposed instead (awaiting the owner): keep the EKF and change the suite's check to one a
consistent filter passes, e.g. outside 4σ for 1 s, or a fraction-of-time limit.
Resolved by D-146.

**D-146 — The hero suite checks the EKF at 4σ for 1 s, not 3σ (M12 follow-up).**
Owner's pick (2026-11-22) of the two options in D-145: keep the EKF as it is and change the
check. Each drone's criterion is now `must_not: |err| outside 4σ on any axis for 1 s`; the
logged bound is 3σ, so the expression is `abs(err) * 3 > bound * 4` (no new signal, no change to
the criteria language). A consistent filter is outside 4σ on some axis ~0.02% of the time, so a
1 s stretch there means a real divergence or an overconfident filter, not chance. Chosen over a
fraction-of-time limit because it needs no new criterion type and still names the failing
window as evidence. Check: the shipped suite (8 samples, seed 0, incl. the old failing sample 2)
passes 8/8 and a 32-sample run over the same ranges (seed 7) passes 32/32.

**D-147 — Tooltips, Help menu, and the UX guidelines (owner request, between milestones).**
Owner asked (2026-11-22) for ease-of-use work (tooltips, guides) that follows published
guidelines, written up as a doc. `docs/UX_GUIDELINES.md` collects the rules from Apple's HIG,
Microsoft's tooltip guidance, the GNOME HIG, NN/g and WCAG 2.2 SC 1.4.13, narrowed to SimView
and subordinate to PRD §7. Built on branch `ux-help` (not a milestone, so no §10 row):
(1) `ActionRegistry.register` sets every action's tooltip to "Name (shortcut)" in the
platform's spelling and a status tip (optional `tip`); the block editor's hand-written
"(Ctrl+G)" tooltips, wrong on macOS, now use the same helper; Run and Pause show Space.
(2) The 3D view's heads-up toolbar (VTK-drawn, so no Qt tooltips) shows a tooltip on hover,
with on/off for toggles. (3) A Help menu: Keyboard Shortcuts (Ctrl+/, non-modal, filterable,
built from the live actions plus `help.EXTRA_KEYS` for viewport keys) and SimView User Guide
(the platform's HelpContents key, F1 / Cmd+?), which opens `docs/USER_GUIDE.md` on GitHub (the
docs aren't installed with the package). Simplest reading of "guides": a task-based user guide
and on-demand help, no guided tour (NN/g: tours are mostly skipped). No new dependency.
Check: `tests/ui/test_help.py` (every action's tooltip has its native shortcut, every
icon-only button has a tooltip with a scene open, Help menu and shortcuts window) and
`test_viewport_gl.py::test_toolbar_tooltips`.
