# SimView — Product Requirements Document

**Version:** 1.0 · **Status:** Ready to build · **Owner:** Harrison

---

## 0. Instructions for Claude Code (read first)

This PRD is the source of truth for building SimView. Follow these rules for the whole project:

1. **Build only the MVP**, meaning the requirements tagged `[MVP]`, in the milestone order in §10. Do NOT implement `[v1]` or `[Future]` items unless I ask.
2. **Work one milestone at a time.** At the end of each milestone:
   - run the test suite,
   - give a summary of what was built and how it maps to requirement IDs (e.g. `VP-01 ✅`),
   - **stop and wait for my approval** before starting the next milestone.
3. **Stop and ask before you:** add any dependency not listed in §8, change the architecture in §8, break the design standards in §7, delete files, or change public APIs from an earlier milestone.
4. **No over-engineering.** Do not add abstractions, config systems, or features this PRD doesn't ask for.
5. **Every requirement must have a test** (pytest), or a documented manual check if it's purely visual.
6. If a requirement is ambiguous, pick the simplest interpretation, record the choice in `docs/DECISIONS.md`, and continue.
7. Use Python 3.11+, type hints everywhere, `ruff` for linting and formatting, and `pytest` for tests.

---

## 1. Overview and problem statement

SimView is a desktop application for **building, running, and visualizing simulations** of robots, vehicles, drones, and dynamic systems in 2D and 3D. It is a Python-native alternative to the MATLAB + Simulink workflow:

- **Python + NumPy/SciPy** handle the math and scripting.
- **SimView provides** what's missing around them:
  - a real-time 3D viewport,
  - a deterministic simulation engine,
  - a block-diagram system editor,
  - a synced analysis and plotting workspace,
  - a plugin system for "toolboxes".

**Why existing tools fall short:**

| Tool | Gap |
|---|---|
| MATLAB / Simulink | Expensive licenses, closed ecosystem, and toolboxes sold separately. Its 3D visualization is weak and slow next to modern game-style renderers. It also doesn't fit naturally into the Python ML stack (PyTorch, Gymnasium). |
| Gazebo / Isaac Sim | Powerful, but heavy to set up (ROS, or NVIDIA GPUs plus Omniverse). They're aimed at full robot stacks, not quick modeling, analysis, or teaching. |
| Jupyter + matplotlib | Good for analysis, but there's no real-time 3D, no time-synced playback, and no block-diagram modeling. |
| Foxglove / RViz | Visualization only. They can't author or simulate dynamics. |

**SimView's thesis:** one app where you can write a model in Python or wire it as blocks, simulate it deterministically, watch it in 3D, and analyze the results in synced plots without leaving the window.

---

## 2. Goals and non-goals

### Goals
- **G1.** Simulate rigid-body and point-mass systems (robot arms, ground vehicles, multirotors, missiles/interceptors) with a real-time 3D viewport.
- **G2.** Offer a MATLAB-like interactive environment: editor, console, workspace browser, and plots.
- **G3.** Offer a Simulink-like block-diagram editor that compiles to the same simulation engine.
- **G4.** Make simulations deterministic and reproducible: same seed plus same model gives bit-identical logs.
- **G5.** Support RL training workflows through a Gymnasium-compatible environment API.
- **G6.** Be extensible through toolboxes, which are pip-installable Python packages.

### Non-goals
- **NG1.** No new scripting language. Python only.
- **NG2.** No line-for-line MATLAB syntax compatibility. Import of `.mat` *data* only.
- **NG3.** No photorealistic rendering, ray tracing, or game-engine-grade graphics.
- **NG4.** No FEM, CFD, or soft-body physics.
- **NG5.** No cloud, multi-user collaboration, or accounts.
- **NG6.** No real-time hardware-in-the-loop or code generation to embedded targets (C/C++ codegen), at least for MVP and v1.
- **NG7.** No ROS runtime dependency. ROS bags can be imported as data only.

---

## 3. User personas

| Persona | Background | Needs from SimView |
|---|---|---|
| **Robotics engineer (Maya)** | Builds manipulators and mobile robots. Knows Python and ROS. | Load a URDF, check FK/IK, see transform trees, and test controllers without starting a full ROS stack. |
| **Controls / GNC engineer (Dev)** | MATLAB/Simulink veteran working on drones and guidance. | Block-diagram modeling, step and Bode analysis, and a 3D engagement view, without a MATLAB license. |
| **ML / RL researcher (Lena)** | PyTorch user who trains policies. | Gymnasium envs with fast parallel rollouts, plus a viewport that replays any training episode next to the reward curves. |
| **Student (Sam)** | Taking dynamics or controls courses. | Free tool, quick feedback, and a visual "see the math move" experience. |

---

## 4. Flagship use cases

### UC-1: Autonomous vehicle systems
**Story:** As Maya, I want to simulate a car with lidar and camera driving a scenario, so I can test a planner before running it on hardware.

**Workflow:**
1. Open `File → New from Template → Autonomous Vehicle`.
2. The template loads a road scene, an ego vehicle using the kinematic bicycle model, and three scripted NPC vehicles.
3. Attach a simulated lidar (32 beams, 10 Hz) and a pinhole camera to the ego vehicle.
4. Write `planner.py`, a pure-pursuit path follower that reads `sensors.lidar`.
5. Press Run. The viewport shows the point cloud, planned path, and vehicle trails. The plot panel shows speed, steering, and cross-track error.
6. Scrub the timeline to a near-collision and inspect the workspace variables at that tick.

**Features used:** VP-01–VP-08, SE-01–SE-06, SN-01–SN-03, DA-01–DA-04, PL-01.

### UC-2: Drone tracking and interception
**Story:** As Dev, I want to simulate an interceptor drone tracking and intercepting a maneuvering target drone using noisy sensor data, so I can tune guidance and filter parameters.

**Workflow:**
1. Load template `Drone Interception`. It contains a target quadrotor flying an evasive waypoint path and an interceptor quadrotor.
2. The interceptor's seeker gives noisy range, bearing, and elevation at 20 Hz.
3. An Extended Kalman Filter (EKF) block estimates target position and velocity.
4. A Proportional Navigation guidance block commands acceleration: $a_c = N \, V_c \, \dot{\lambda}$.
5. Run. The viewport shows both trajectories, the estimate's covariance ellipsoid, and the line of sight.
6. Plots show miss distance, estimation error versus $\pm 3\sigma$ bounds, and commanded versus achieved acceleration.
7. Parameter sweep: run 50 Monte Carlo trials over $N \in \{3,4,5\}$ and sensor noise levels, then view a miss-distance histogram.

**Features used:** VP-01–VP-09, SE-01–SE-08, BD-01–BD-08, DA-01–DA-06, TB-AERO.

### UC-3: Robotic transformations
**Story:** As Sam, I want to load a 6-DOF arm, drag its end effector in 3D, and watch the IK solution and joint angles update live.

**Workflow:**
1. Import `ur5.urdf`.
2. The viewport renders the links, and the transform tree panel lists every frame.
3. Toggle "show frames" to see the RGB axes on every link.
4. Drag the end-effector gizmo. Damped-least-squares IK solves in real time, and the joint sliders follow.
5. In the console, run `T = robot.fk(q)` to print the 4×4 homogeneous transform. `robot.jacobian(q)` returns the 6×6 Jacobian.
6. Script a joint-space trajectory and plot joint positions, velocities, and torques. Torques come from inverse dynamics via MuJoCo.

**Features used:** VP-01–VP-07, VP-10, SE-01–SE-04, IO-01, TB-ROBOT.

### UC-4: Autonomous training (RL)
**Story:** As Lena, I want to train a policy that lands a drone, then replay any episode in 3D with the reward curve beside it.

**Workflow:**
1. Wrap any SimView scene as a Gymnasium env: `env = simview.make_env("drone_landing")`.
2. Train with Stable-Baselines3 PPO from the console or a script, using N parallel headless envs.
3. The Training panel streams episode reward, episode length, and loss curves live.
4. Click any point on the reward curve. The viewport loads and replays that episode.
5. Compare the policy at checkpoints 10k, 100k, and 500k side by side as ghost overlays.

**Features used:** SE-01, SE-05, SE-09, ML-01–ML-04, VP-01–VP-06.

### UC-5: ML viewports
**Story:** As Lena, I want to see what my perception network "sees" overlaid on the 3D scene.

**Workflow:**
1. Register a PyTorch model as a scene observer: `scene.attach_model(model, input="ego.camera")`.
2. A side viewport shows the camera feed with predicted bounding boxes and a toggle for activation heatmaps.
3. The 3D viewport projects detections into world space as colored boxes.
4. A panel shows the policy's action distribution per tick, as bars over the discrete actions or a Gaussian for continuous ones.

**Features used:** ML-05–ML-07, VP-11, SN-02.

---

## 5. Functional requirements

Tag meanings:
- `[MVP]` — required for the 12-week build.
- `[v1]` — next release.
- `[Future]` — later.

### 5.1 Viewport (VP)

| ID | Requirement | Tag |
|---|---|---|
| VP-01 | Render a 3D scene with meshes (STL, OBJ, GLB), primitives (box, sphere, cylinder, capsule), a ground grid, and world axes. | MVP |
| VP-02 | Orbit, pan, and zoom with the mouse, plus fly mode (WASD). Preset views: top, front, side, iso. Toggle between perspective and orthographic. | MVP |
| VP-03 | Toggle 2D mode: top-down orthographic view with the camera rotation locked. | MVP |
| VP-04 | Draw trajectory trails per entity, with configurable length (seconds) and color. | MVP |
| VP-05 | Timeline bar with play, pause, step forward and back one tick, a scrub slider, and playback speeds 0.1×–10×. Scrubbing updates the viewport within 100 ms. | MVP |
| VP-06 | Select an entity by clicking it. Its properties (pose, velocity, custom state) show in the Inspector panel. | MVP |
| VP-07 | Debug draw API callable from user code: `draw.line`, `draw.arrow`, `draw.point`, `draw.text`, `draw.frame`. Draws persist for one tick unless `persist=True`. | MVP |
| VP-08 | Render point clouds of up to 200k points at ≥30 FPS. | MVP |
| VP-09 | Render covariance ellipsoids from a 3×3 covariance matrix and a sigma level. | MVP |
| VP-10 | Translate and rotate gizmo on selected entities and IK targets. | MVP |
| VP-11 | Multiple viewports in a split layout (up to 4). Each can follow a different camera or entity. | v1 |
| VP-12 | Ghost overlays: render a second recorded run semi-transparently on top of the current one. | v1 |
| VP-13 | Export a viewport recording to MP4 at a set resolution and FPS. | v1 |
| VP-14 | Shadows, skybox, and PBR materials. | Future |

### 5.2 Simulation engine (SE)

| ID | Requirement | Tag |
|---|---|---|
| SE-01 | Fixed-timestep loop with `dt` configurable from 0.1 ms to 100 ms. Default is 1 ms for physics and 60 Hz for rendering, decoupled from each other. | MVP |
| SE-02 | Run the simulation in a separate process from the UI. A UI freeze must never stall the sim, and a sim crash must never crash the UI. | MVP |
| SE-03 | Rigid-body physics through MuJoCo. Entities can be MuJoCo bodies, or custom Python dynamics models implementing `derivative(t, x, u) -> dx`. | MVP |
| SE-04 | ODE integrators for custom models: Euler, RK4, and adaptive RK45 (via SciPy). Selectable per model. | MVP |
| SE-05 | Headless mode with no rendering, available through both the CLI (`simview run scene.py --headless`) and the Python API. | MVP |
| SE-06 | Log every entity's state, every block's signals, and any user-tagged variable each tick. Logs are stored in a columnar format (Parquet) per run. | MVP |
| SE-07 | Determinism: one seeded RNG per run, exposed as `sim.rng` (NumPy Generator). Same seed + same scene → identical logs (byte-identical Parquet). | MVP |
| SE-08 | Monte Carlo and parameter-sweep runner: define a parameter grid or distributions, run N trials in parallel processes, and aggregate the results into a single table. | MVP |
| SE-09 | Vectorized parallel environments (N headless sims) for RL. | MVP |
| SE-10 | Real-time mode with wall-clock pacing at 1.0× real-time factor (RTF), and faster-than-real-time mode with no pacing. | MVP |
| SE-11 | Event system: `on_collision`, `on_condition(fn)`, and `stop_when(fn)`. | v1 |
| SE-12 | Variable-step solvers for stiff systems (BDF, Radau). | v1 |
| SE-13 | Co-simulation via the FMI 2.0 standard (import FMUs). | Future |

### 5.3 Block-diagram editor (BD)

| ID | Requirement | Tag |
|---|---|---|
| BD-01 | Canvas with blocks, typed ports, and wires, supporting drag, connect, delete, pan, and zoom. | MVP |
| BD-02 | Core block library: Constant, Step, Sine, Gain, Sum, Product, Integrator, Derivative, Transfer Function, State-Space, PID, Saturation, Delay, Mux/Demux, Scope, To Workspace. | MVP |
| BD-03 | Python Function block: wrap any Python function as a block. Ports are inferred from the type-hinted signature. | MVP |
| BD-04 | Entity blocks: read an entity's state or write its control inputs in the 3D scene. | MVP |
| BD-05 | Compile the diagram to an execution graph in topological order. Algebraic loops are detected and reported with the offending blocks highlighted. | MVP |
| BD-06 | Diagrams save as human-readable JSON (`.svd`), suitable for diffing in git. | MVP |
| BD-07 | Subsystems: group selected blocks into one collapsible block. | MVP |
| BD-08 | Scope blocks dock their plot into the plot panel, time-synced with the viewport timeline. | MVP |
| BD-09 | Multi-rate blocks with a per-block sample time. | v1 |
| BD-10 | Export a diagram to a standalone Python script. | v1 |
| BD-11 | Linearize a diagram around an operating point to get state-space (A, B, C, D) matrices. | v1 |

### 5.4 Scripting, console, and workspace (SC)

| ID | Requirement | Tag |
|---|---|---|
| SC-01 | Embedded IPython console using a Jupyter kernel. It has full access to the `simview` API and the running scene. | MVP |
| SC-02 | Code editor with Python syntax highlighting, line numbers, run file, and run selection. | MVP |
| SC-03 | Workspace browser listing console variables with name, type, shape, and a value preview. Double-click a NumPy array to open it in a table viewer. | MVP |
| SC-04 | A scene can be defined entirely in a Python file (`scene.py`). The GUI and script workflows produce the same scene object. | MVP |
| SC-05 | Live parameter tweaking: `sim.params.x = 3` takes effect on the next tick without restarting. | MVP |
| SC-06 | Autocomplete and inline docs in the editor through Jedi. | v1 |
| SC-07 | Debugger with breakpoints inside the sim step (debugpy). | Future |

### 5.5 Data analysis and plotting (DA)

| ID | Requirement | Tag |
|---|---|---|
| DA-01 | Plot panel with real-time line plots of logged signals, updating at ≥30 FPS with 10 signals × 100k samples. | MVP |
| DA-02 | A timeline cursor in plots is synced to the viewport. Hovering a plot moves the viewport to that time, and scrubbing the viewport moves the plot cursor. | MVP |
| DA-03 | Drag a signal from the signal tree (all logged channels) onto a plot. | MVP |
| DA-04 | 2D XY plots (e.g. trajectory top view), plus scatter and histogram plots. | MVP |
| DA-05 | Analysis functions in the API: `step_info` (rise time, overshoot, settling time), `bode`, `fft`, `psd`, and `rmse`. They are built on SciPy. | MVP |
| DA-06 | Monte Carlo results view: table of trials plus a histogram and scatter of any output metric versus parameters. | MVP |
| DA-07 | Export plots to PNG/SVG and data to CSV, Parquet, or `.mat`. | MVP |
| DA-08 | Load logs from any past run and compare runs on the same plot. | v1 |
| DA-09 | Root-locus and Nyquist plots. | v1 |

### 5.6 Sensors (SN)

| ID | Requirement | Tag |
|---|---|---|
| SN-01 | Sensor models: IMU (accelerometer + gyroscope with bias and white noise), GPS (position noise and update rate), range/bearing seeker. | MVP |
| SN-02 | Pinhole camera that renders an offscreen RGB image at a configurable resolution and rate. | MVP |
| SN-03 | Ray-cast lidar with configurable beams, vertical field of view, range, rate, and noise. Uses the MuJoCo ray API. | MVP |
| SN-04 | Depth camera and semantic-segmentation camera. | v1 |
| SN-05 | Radar model with RCS and clutter. | Future |

### 5.7 ML and RL integration (ML)

| ID | Requirement | Tag |
|---|---|---|
| ML-01 | `simview.make_env(scene, obs_fn, reward_fn, done_fn)` returns a Gymnasium-compliant `Env` that passes `gymnasium.utils.env_checker`. | MVP |
| ML-02 | Vectorized env wrapper compatible with Stable-Baselines3 `VecEnv`. | MVP |
| ML-03 | Training panel streams scalar metrics through a simple `simview.log_metric(name, step, value)` API, and also reads TensorBoard event files. | MVP |
| ML-04 | Click a point on a training curve to replay that episode in the viewport. This requires episodes to be logged at a configurable interval. | MVP |
| ML-05 | `scene.attach_model(model, input=...)` runs PyTorch inference per tick and exposes the outputs to the overlay and draw APIs. | v1 |
| ML-06 | Camera overlay panel showing bounding boxes, class labels, and activation heatmaps. | v1 |
| ML-07 | Action-distribution panel for the current policy output. | v1 |

### 5.8 Toolbox / plugin system (TB)

| ID | Requirement | Tag |
|---|---|---|
| TB-01 | A toolbox is a pip-installable package that declares the entry point `simview.toolboxes`. SimView discovers toolboxes at startup. | MVP |
| TB-02 | A toolbox can register blocks, entity types, sensors, scene templates, and Python API modules. | MVP |
| TB-03 | Toolbox manager panel listing installed toolboxes with version and an enable/disable toggle. | v1 |

### 5.9 Import / export (IO)

| ID | Requirement | Tag |
|---|---|---|
| IO-01 | Import URDF and MJCF robot descriptions, including meshes, joints, limits, and inertials. | MVP |
| IO-02 | Import CSV and `.mat` data (via `scipy.io`) into the workspace. | MVP |
| IO-03 | Import ROS1/ROS2 bags (via the `rosbags` library) as time-series data and as playback in the viewport. | v1 |
| IO-04 | Save and load a whole project (`.svproj` folder): scenes, diagrams, scripts, and run logs. | MVP |

---

## 6. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NF-01 | Viewport frame rate with a 20-entity scene and 50k-point cloud on a mid-range GPU (GTX 1660 / M1 integrated) | ≥ 60 FPS |
| NF-02 | Real-time factor (RTF) headless, for the 6-DOF arm (UC-3) at dt = 1 ms | ≥ 20× |
| NF-03 | RTF headless, for drone interception (UC-2) at dt = 1 ms | ≥ 10× |
| NF-04 | Sim → UI state-transfer latency | ≤ 20 ms |
| NF-05 | Cold start to usable window | ≤ 4 s |
| NF-06 | Determinism (SE-07) | Byte-identical logs across 10 repeated runs on the same machine |
| NF-07 | Memory for a 10-minute UC-2 run with full logging | ≤ 2 GB |
| NF-08 | Supported operating systems | Windows 10/11, macOS 13+ (Apple Silicon), Ubuntu 22.04+ |
| NF-09 | Test coverage of `simview/core` | ≥ 80% line coverage |
| NF-10 | Crash isolation | A user-code exception in the sim process shows a traceback in the console. The UI stays responsive. |

---

## 7. Design standards

SimView should feel like a professional engineering tool. It should be as calm and polished as an Apple app, as familiar to engineers as MATLAB, and as fluid in 3D as Onshape or SolidWorks. Design is a requirement, not polish: every UI milestone is reviewed against this section.

### 7.1 Inspiration and what we take from each

| Source | What we adopt | What we avoid |
|---|---|---|
| **Apple Human Interface Guidelines** | Clarity, deference to content, and restraint: the UI chrome recedes and the viewport and data lead. Generous spacing, crisp typography, a single accent color, subtle motion, and consistent icon weight. | Consumer-style oversized controls and hidden functionality. |
| **MATLAB** | The mental model engineers already know: docked Editor, Command Window (console), Workspace, and Figures. Variables are inspectable everywhere. Plots carry units and grids by default. | The dense, dated ribbon and the modal figure windows. |
| **Onshape** | Minimal chrome. A feature tree on the left with properties on the right. Contextual toolbars near the selection. Fast, browser-smooth 3D navigation. A clean neutral palette. | — |
| **SolidWorks** | The ViewCube and triad, a heads-up view toolbar over the viewport, the property-manager pattern for editing the selected object, and strong selection and hover feedback. | Toolbar overload and nested modal dialogs. |
| **Foxglove / Isaac Sim / Blender / Figma** | Foxglove: panel layouts and the timeline scrubber. Isaac Sim: the scene outliner. Blender: keyboard-first workflows and workspace presets. Figma: the `Cmd/Ctrl+K` command palette. | Blender's steep and unusual default controls. |

### 7.2 Design principles

1. **Content first.** The viewport and plots take ≥70% of the default window area. Chrome uses neutral grays, and color is reserved for data, selection, and state.
2. **Familiar layout, modern finish.** Use MATLAB's panel vocabulary with Onshape's visual cleanliness.
3. **Direct manipulation.** Edit things where they are: drag gizmos in 3D, scrub the timeline, edit values inline in the inspector. Avoid modal dialogs.
4. **Everything is synced.** Selection, time cursor, and hover are shared across the viewport, plots, block editor, and inspector.
5. **Keyboard-first, mouse-complete.** Every action is in the command palette, and the frequent ones have shortcuts.
6. **No surprises.** Destructive actions can be undone. Long operations show progress and can be cancelled.

### 7.3 Visual system (design tokens)

All visual values are defined once in `src/simview/ui/theme/tokens.py` and compiled into a Qt stylesheet (QSS). **No hard-coded colors, sizes, or fonts anywhere else in the UI code.**

**Typography** (bundled fonts, both SIL Open Font License):
- UI font: **Inter**. Code, console, and numeric readouts: **JetBrains Mono** with tabular figures.
- Type scale in px: 11 (caption), 12 (secondary), 13 (body, the default), 15 (panel titles), 20 (section and start-screen titles). Weights: 400 regular and 600 semibold only.

**Spacing and shape:**
- 4 px base grid. Allowed spacing: 4, 8, 12, 16, 24, 32.
- Corner radius: 6 px for controls, 10 px for floating panels, popovers, and the command palette.
- Control height: 28 px standard, 24 px compact (toolbars).
- Hairline 1 px dividers instead of heavy borders. No drop shadows except on floating elements (popovers, palette, HUD).

**Color.** Dark theme is the default, light theme is supported. Every color is a semantic token:

| Token | Dark | Light | Use |
|---|---|---|---|
| `bg.app` | `#1C1C1E` | `#F5F5F7` | Window background |
| `bg.panel` | `#242426` | `#FFFFFF` | Panels |
| `bg.elevated` | `#2C2C2E` | `#FFFFFF` | Popovers, palette, HUD |
| `border.subtle` | `#3A3A3C` | `#D2D2D7` | Dividers |
| `text.primary` | `#F5F5F7` | `#1D1D1F` | Body text |
| `text.secondary` | `#A1A1A6` | `#6E6E73` | Labels, captions |
| `accent` | `#0A84FF` | `#0071E3` | Primary actions, focus ring, selection |
| `state.success` / `warning` / `error` | `#30D158` / `#FFD60A` / `#FF453A` | `#248A3D` / `#B25000` / `#D70015` | Status only, never decorative |

**Fixed engineering conventions** (do not change):
- Axes: **X = red, Y = green, Z = blue** everywhere (triad, gizmos, frames, plots of vector components).
- Coordinates are right-handed, with Z up by default. A Y-up toggle is offered for imported assets.
- Data and entity colors use the colorblind-safe **Okabe–Ito palette**, assigned in a fixed order: `#0072B2, #E69F00, #009E73, #CC79A7, #56B4E9, #D55E00, #F0E442`.
- Sequential heatmaps use viridis. Diverging maps (errors) use a blue–white–red map centered on zero.

**Icons:** the **Lucide** icon set (ISC license) as SVG, 16 px in toolbars and 20 px on the start screen, 1.5 px stroke, tinted with the `text.secondary` and `accent` tokens. One icon set only. No emoji in the UI.

**Motion:**
- Duration is 150 ms for hover and toggles, 250 ms for panels and camera transitions. Easing is ease-out.
- Camera transitions (ViewCube clicks, "frame selected") animate. Simulation playback never interpolates fake data.
- Respect the OS "reduce motion" setting: when it's on, motion becomes instant.

### 7.4 Window layout

Default workspace (MATLAB layout, Onshape finish):

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ ▸ Toolbar: Project ▾ │ ▶ Run  ⏸  ⏹  │ dt 1ms │ RTF 1.0× │      ⌘K Search…    │
├──────────────┬──────────────────────────────────────────────┬─────────────────┤
│ Scene Tree   │                                   ┌───────┐  │ Inspector       │
│ (entities,   │           3D VIEWPORT             │ View  │  │ (properties of  │
│  sensors,    │                                   │ Cube  │  │  selection,     │
│  frames)     │                                   └───────┘  │  inline edit)   │
│              │   [heads-up view toolbar, top center]        │                 │
│ Signals      │   ┌triad┐                FPS 60 · RTF 12.4×  ├─────────────────┤
│ (log tree)   │   └─────┘                                    │ Workspace       │
├──────────────┴──────────────────────────────────────────────┴─────────────────┤
│ Timeline  ◀◀ ◀ ▶ ▶▶  ━━━━━━━━━━━━●━━━━━━━━━━━━━━━  t = 4.213 s / 20.000 s  1×   │
├──────────────────────────────────────┬────────────────────────────────────────┤
│ Plots (synced cursor)                │ Console / Editor (tabs)                │
└──────────────────────────────────────┴────────────────────────────────────────┘
```

**Workspace presets:** switch layouts from the toolbar or with `Ctrl+1–4`. Layouts persist per project.

| Preset | Emphasis |
|---|---|
| **Simulate** | The default layout above. |
| **Model** | Block editor is the main area, with the viewport as a small preview. |
| **Analyze** | Plots fill the main area, with the viewport as a picture-in-picture. |
| **Train** | Training curves next to the episode-replay viewport. |

### 7.5 Viewport standards

- **Navigation is Onshape/SolidWorks style by default.** Right-drag (or middle-drag) rotates around the point under the cursor. `Shift`+middle-drag or `Ctrl`+right-drag pans. Scroll zooms toward the cursor, not the screen center.
- **Navigation presets** are selectable in Settings: SimView (default), SolidWorks, Onshape, Blender, MATLAB.
- **ViewCube** (top right): click a face, edge, or corner to animate to that view. It also has home and perspective/orthographic toggles.
- **Triad** in the bottom-left corner shows world orientation.
- **Heads-up toolbar** (top center, translucent `bg.elevated`): frame-all, frame-selected, view presets, display mode (shaded, shaded+edges, wireframe), and toggles for grid, frames, trails, and sensor visuals.
- **Rendering quality:**
  - 4× MSAA anti-aliasing.
  - Soft vertical gradient background (from `bg.app` to slightly lighter).
  - Infinite ground grid with major/minor lines that fades with distance.
  - Subtle edge outlines on meshes (shaded+edges is the default for CAD imports).
- **Selection feedback:**
  - Hover shows a 1 px `accent` outline at 50% opacity.
  - Selection shows a 2 px `accent` outline plus a highlight in the scene tree.
  - The outline must stay visible through other geometry.
- **HUD** (bottom right, monospace): FPS, RTF, sim time, and the selected entity's live pose. It can be toggled.
- **Measurement and readouts:** a scale bar in orthographic and 2D modes. A hover tooltip shows world coordinates in meters to 3 decimal places.
- **Units:** SI everywhere and always labeled (m, m/s, rad, N·m). The display can be switched to degrees for angles. Internal values stay in radians.

### 7.6 Plot standards

- MATLAB-grade defaults:
  - axis labels with units (`Altitude [m]`),
  - light grid,
  - legend outside the data area or in the top right,
  - tabular-number tick labels.
- The synced time cursor is a 1 px vertical line in `accent`. Hovering shows a crosshair with values for all traces in a compact tooltip.
- Line widths are 1.5 px for data, 1 px for reference lines, and dashed for limits and $\pm3\sigma$ bounds.
- Exports (PNG/SVG) use the light theme by default, so they are ready for reports and papers.

### 7.7 Block editor standards

- A dot-grid canvas with snap to 8 px.
- Blocks are rounded rectangles (radius 6) with a semibold title and a category color strip on the left edge. Categories: Sources, Math, Continuous, Discrete, Control, Sinks, Entities, Python.
- Ports are circles color-coded by signal type (scalar, vector, matrix, bus). Wires are orthogonal with rounded corners. Hovering a wire shows its live value during simulation.
- Errors (algebraic loops, type mismatches) show a red outline on the offending blocks and an inline message. There are no pop-up error dialogs.
- Quick-add: double-click the canvas to open a block search palette, like Simulink's quick insert.

### 7.8 Interaction and keyboard

| Action | Shortcut |
|---|---|
| Command palette | `Ctrl/Cmd+K` |
| Run / pause | `Space` (outside text fields) |
| Step forward / back one tick | `.` / `,` |
| Frame selected / frame all | `F` / `A` |
| View presets (front, right, top, iso) | `1` / `3` / `7` / `0` |
| Toggle 2D mode | `Tab` |
| Undo / redo | `Ctrl/Cmd+Z` / `Ctrl/Cmd+Shift+Z` |
| Switch workspace preset | `Ctrl/Cmd+1–4` |

- Shortcuts follow platform conventions: `Cmd` on macOS, `Ctrl` elsewhere. Native menu bar on macOS.
- Undo and redo cover scene edits, inspector edits, and block editor edits.
- **Start screen** (similar to Apple's template chooser):
  - recent projects,
  - the 4 flagship templates as cards with thumbnails,
  - "New empty scene", and "Open…".
- **Empty states:** every panel shows a one-line hint and an action button when empty. No blank panels.

### 7.9 Accessibility and quality bar

- Text contrast is ≥ 4.5:1 (WCAG AA) in both themes. Never encode meaning with color alone: pair it with an icon, label, or line style.
- UI scaling from 100% to 200%, and crisp on high-DPI and Retina displays, which means SVG icons and no bitmap UI assets.
- Every control can be reached by keyboard and has a visible focus ring (2 px `accent`).
- No UI-thread block over 100 ms. Show a progress indicator for anything over 500 ms.

### 7.10 Design requirements

| ID | Requirement | Tag |
|---|---|---|
| DS-01 | Token-based theme (`tokens.py` → QSS) with dark and light themes. No hard-coded style values outside the theme module. A lint test fails on hex colors in `ui/` outside `theme/`. | MVP |
| DS-02 | Bundled Inter and JetBrains Mono fonts, and the Lucide icon set. | MVP |
| DS-03 | Default window layout per §7.4, with all panels dockable and the layout persisted per project. | MVP |
| DS-04 | ViewCube, triad, heads-up toolbar, and HUD per §7.5. | MVP |
| DS-05 | Onshape/SolidWorks-style navigation with zoom-to-cursor and orbit-around-cursor. | MVP |
| DS-06 | Hover and selection outlines, synced across viewport, scene tree, inspector, and plots. | MVP |
| DS-07 | Command palette listing every registered action, with fuzzy search. | MVP |
| DS-08 | Start screen with recent projects and template cards. | MVP |
| DS-09 | Plot styling per §7.6, including light-theme exports. | MVP |
| DS-10 | Block editor styling per §7.7. | MVP |
| DS-11 | Keyboard shortcuts per §7.8. | MVP |
| DS-12 | Workspace presets (Simulate, Model, Analyze, Train). | v1 |
| DS-13 | Navigation presets for SolidWorks, Blender, and MATLAB. | v1 |
| DS-14 | Accessibility bar per §7.9, verified with an automated contrast check over the tokens. | MVP |
| DS-15 | Reduce-motion support and animated camera transitions. | v1 |

---

## 8. Technical architecture

### 8.1 Stack

| Layer | Choice | Why | Rejected alternative |
|---|---|---|---|
| Language | Python 3.11+ | Matches the NumPy/SciPy/PyTorch ecosystem, which is the core positioning. | C++ core: much slower to build solo. |
| UI framework | PySide6 (Qt 6) | Mature docking and panels, and native on all 3 OSes. LGPL license. | Electron/Tauri: would need a JS↔Python bridge for everything. |
| 3D rendering | PyVista + pyvistaqt (VTK) | Mature, fast point clouds and meshes, embeds in Qt, good picking and widget support. | pygfx/wgpu: modern but a younger API that changes more. |
| Plotting | pyqtgraph | Real-time plotting at 30+ FPS with 100k+ samples. Native to Qt. | matplotlib: too slow for live plots (it's still used for exports). |
| Physics | MuJoCo (official `mujoco` Python bindings) | Fast, accurate contacts, a ray-cast API for lidar, MJCF/URDF support, Apache-2.0 license. | PyBullet: slower to update and less accurate. |
| Math | NumPy, SciPy | Standard. Integrators, signal processing, linear algebra. | — |
| Console | qtconsole + ipykernel (in-process kernel inside the UI process; it talks to the sim through the API client) | Gives a real IPython experience with no extra work. | A custom REPL widget: worse UX. |
| Code editor | QScintilla (PyQt6-QScintilla) or a QPlainTextEdit + Pygments highlighter | Lightweight. **Ask me before adding QScintilla**, because of Qt binding compatibility. | Monaco in QWebEngine: heavy. |
| Block editor | Custom `QGraphicsScene` | Full control, and no dependency risk from an abandoned node-editor library. | NodeGraphQt: smaller community. |
| Sim ↔ UI IPC | `multiprocessing` + `multiprocessing.shared_memory` for state buffers, and ZeroMQ (`pyzmq`) for commands and events | Shared memory gives near-zero-copy state transfer. ZMQ is reliable for the control plane. | gRPC: unnecessary overhead locally. |
| Logging storage | Apache Arrow / Parquet (`pyarrow`) | Columnar, fast, compact, readable from pandas and polars. | HDF5: harder for concurrent access. |
| RL | Gymnasium, Stable-Baselines3 (optional extra: `pip install simview[rl]`) | Standard RL interfaces. | RLlib: heavy. |
| ML | PyTorch (optional extra) | Most common in research. | — |
| Design assets | Inter + JetBrains Mono (OFL), Lucide icons (ISC), bundled in `src/simview/ui/assets/`. Theming via `qtpy` + a generated QSS. | Permissive licenses, cross-platform consistency, a modern look. | Platform-native fonts and icons: inconsistent across operating systems. |
| Packaging | `pyproject.toml` (hatchling); later PyInstaller for standalone builds | Simple. | conda-only. |

### 8.2 Component diagram

```
┌─────────────────────────────── UI Process (PySide6) ───────────────────────────────┐
│                                                                                    │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │ Viewport   │ │ Plot Panel │ │ Block      │ │ Editor +   │ │ Inspector /      │  │
│  │ (PyVista)  │ │(pyqtgraph) │ │ Editor     │ │ IPython    │ │ Workspace /      │  │
│  │            │ │            │ │(QGraphics) │ │ Console    │ │ Signal Tree      │  │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └────────┬─────────┘  │
│        └──────────────┴──────┬───────┴──────────────┴─────────────────┘            │
│                       ┌──────┴───────┐        ┌─────────────────┐                  │
│                       │ Timeline /   │◄──────►│ Run Log Reader  │◄── Parquet files │
│                       │ Playback Ctl │        │ (pyarrow)       │                  │
│                       └──────┬───────┘        └─────────────────┘                  │
│                       ┌──────┴───────┐                                             │
│                       │ SimClient    │                                             │
│                       └──┬────────┬──┘                                             │
└──────────────────────────┼────────┼────────────────────────────────────────────────┘
             ZMQ (cmds/events)   Shared memory (state ring buffer)
┌──────────────────────────┼────────┼──────── Sim Process(es) ───────────────────────┐
│                       ┌──┴────────┴──┐                                             │
│                       │ SimServer    │                                             │
│                       └──────┬───────┘                                             │
│   ┌──────────────┬───────────┼──────────────┬──────────────┬──────────────────┐    │
│   │ Scheduler    │ MuJoCo    │ Custom ODE   │ Block Graph  │ Sensors          │    │
│   │ (fixed dt,   │ World     │ Models       │ Executor     │ (IMU/GPS/lidar/  │    │
│   │  seeded RNG) │           │ (RK4/RK45)   │              │  camera/seeker)  │    │
│   └──────────────┴───────────┴──────────────┴──────────────┴──────────────────┘    │
│                       ┌──────────────┐  ┌───────────────────────────┐              │
│                       │ Logger →     │  │ Toolboxes (entry points)  │              │
│                       │ Parquet      │  │ robotics/controls/aero/rl │              │
│                       └──────────────┘  └───────────────────────────┘              │
└────────────────────────────────────────────────────────────────────────────────────┘
   Headless / Monte Carlo / VecEnv: N sim processes, no UI, same SimServer code.
```

### 8.3 Core abstractions (public API sketch)

```python
import simview as sv

scene = sv.Scene(dt=1e-3, seed=42)

arm = scene.add_robot("ur5.urdf")                       # MuJoCo-backed entity
drone = scene.add_entity(sv.aero.Quadrotor(mass=1.2))   # custom ODE model entity
seeker = drone.attach(sv.sensors.Seeker(rate=20, noise_std=[1.0, 0.01, 0.01]))

@scene.controller(rate=100)                             # runs at 100 Hz
def guidance(t, state, ctx):
    ctx.draw.arrow(state.pos, state.pos + state.vel, color="cyan")
    return {"thrust_cmd": ...}

scene.log("miss_distance", lambda s: ...)               # custom logged channel

run = sv.run(scene, duration=20.0, headless=False)      # returns a Run handle
df = run.to_pandas()                                    # all logged signals
sv.analysis.step_info(df["altitude"], t=df["t"])
```

### 8.4 Repository layout

```
simview/
  pyproject.toml
  README.md
  docs/  DECISIONS.md  ARCHITECTURE.md
  src/simview/
    core/        scene.py entity.py scheduler.py integrators.py rng.py logger.py
    physics/     mujoco_world.py urdf.py
    blocks/      graph.py compiler.py library/ (one file per block family)
    sensors/     imu.py gps.py seeker.py lidar.py camera.py
    ipc/         server.py client.py shm.py protocol.py
    runner/      run.py headless.py montecarlo.py
    rl/          env.py vec_env.py metrics.py
    analysis/    step.py freq.py stats.py
    io/          mat.py csv.py project.py
    ui/          app.py main_window.py viewport/ plots/ blockeditor/ console/ inspector/ timeline/
    toolboxes/   robotics/ controls/ aero/ rl/   (built-ins, registered via entry points)
    templates/   av_scenario/ drone_intercept/ ur5_ik/ drone_landing/
  tests/         mirrors src/simview/
  examples/      one script per flagship use case
```

---

## 9. Toolbox roadmap

| Toolbox | Contents | Tag |
|---|---|---|
| **Robotics** | URDF loading helpers, FK, geometric Jacobian, damped-least-squares IK, trajectory generation (cubic/quintic, trapezoidal velocity), inverse dynamics through MuJoCo, transform tree utilities, and SE(3) helpers (`sv.robotics.se3`). | MVP |
| **Controls** | PID with anti-windup, transfer function / state-space blocks, `step_info`, `bode`, LQR (`scipy.linalg.solve_continuous_are`), and discretization (`c2d`). | MVP |
| **Aerospace / Guidance** | 6-DOF quadrotor model, point-mass interceptor, Proportional Navigation and Augmented PN, seeker model, EKF and UKF blocks, and engagement metrics (miss distance, time-to-go). | MVP |
| **Vehicles** | Kinematic bicycle model, pure pursuit, Stanley controller, road/lane scene primitives, scripted NPC agents. | MVP |
| **RL** | `make_env`, VecEnv, metric logging, episode replay, and the drone-landing and arm-reach example envs. | MVP |
| **Signal Processing** | FFT, PSD (Welch), FIR/IIR filter design blocks, spectrogram plot. | v1 |
| **Perception** | Camera intrinsics and extrinsics, projection utilities, detection overlays, and point-cloud clustering. | v1 |

---

## 10. MVP definition and milestone plan (12 weeks)

**MVP cut:** every requirement tagged `[MVP]` above.

**Hero demo (the portfolio centerpiece): UC-2, Drone Interception.** A single screen shows:
- the 3D engagement with trails, line of sight, and the EKF covariance ellipsoid,
- the block diagram of the guidance loop (Seeker → EKF → PN → Quadrotor),
- live plots of miss distance and estimation error against $\pm3\sigma$,
- a 50-trial Monte Carlo histogram.

It also needs a 60–90 s screen recording for the README.

This demo is the strongest portfolio choice because it exercises every major subsystem (physics, sensors, estimation, guidance, block editor, plotting, Monte Carlo) in one visual.

### Milestones

Stop for review after each one.

| Wk | Milestone | Deliverables | Requirement IDs | Done when |
|---|---|---|---|---|
| 1 | **M1: Skeleton + design system** | Repo, `pyproject`, CI (ruff + pytest on 3 OSes via GitHub Actions), theme tokens → QSS, bundled fonts and icons, the default layout with empty docked panels, a start screen, and a command palette shell. | DS-01–DS-03, DS-07, DS-08, DS-14 | `simview` launches into the start screen with the dark and light themes. The hex-color lint and contrast tests pass. CI is green. |
| 2–3 | **M2: Core sim engine** | Scene, entities, fixed-step scheduler, RK4/RK45, seeded RNG, Parquet logger, headless runner. | SE-01, SE-04, SE-05, SE-06, SE-07, SC-04 | A bouncing-ball ODE runs headless. 10 repeated runs give byte-identical logs. |
| 3–4 | **M3: Physics + robots** | MuJoCo world, URDF/MJCF import, FK/Jacobian/IK in the Robotics toolbox. | SE-03, IO-01, TB-ROBOT | The UR5 loads, and FK matches a reference within 1e-6. IK converges within 50 iterations for 95% of random reachable poses. |
| 4–5 | **M4: Viewport + IPC** | Sim process, shared memory/ZMQ, PyVista viewport, camera controls, trails, selection, debug draw, gizmo, 2D mode. | SE-02, SE-10, VP-01–VP-07, VP-10, NF-04, NF-10, DS-04–DS-06 | The UC-3 IK drag demo works live. Killing the sim process doesn't crash the UI. |
| 6 | **M5: Timeline + plots** | Timeline playback and scrubbing, pyqtgraph panel, signal tree, synced cursor, XY/scatter/histogram plots, exports. | VP-05, DA-01–DA-04, DA-07, DS-09 | Scrubbing moves the viewport and plot cursor together within 100 ms. |
| 7 | **M6: Console + workspace** | IPython console, editor, workspace browser, live parameter tweaking, CSV/.mat import, project save/load. | SC-01–SC-05, IO-02, IO-04 | `sim.params` changes take effect on the next tick. A project round-trips save→load. |
| 8–9 | **M7: Block editor** | Canvas, core block library, Python Function block, entity blocks, compiler with algebraic-loop detection, subsystems, Scope docking, JSON save. | BD-01–BD-08, DS-10 | A PID block diagram controlling a quadrotor's altitude matches the same controller written as a script within 1e-9. |
| 10 | **M8: Sensors + Aero/Vehicles toolboxes** | IMU, GPS, seeker, camera, lidar. Quadrotor, PN, EKF, bicycle model, pure pursuit. Point clouds and covariance ellipsoids. | SN-01–SN-03, VP-08, VP-09, TB-AERO, TB-VEH | The UC-1 and UC-2 templates run end to end. |
| 11 | **M9: Monte Carlo + RL** | Sweep runner, results view, analysis functions, `make_env`, VecEnv, training panel, click-to-replay. | SE-08, SE-09, DA-05, DA-06, ML-01–ML-04 | 50-trial Monte Carlo finishes. `env_checker` passes. PPO trains drone landing to >80% success, with replay working. |
| 12 | **M10: Polish + hero demo** | Performance pass against NF-01–NF-07, the 4 templates, README with GIFs, a hero demo recording, and `docs/ARCHITECTURE.md`. | NF-01–NF-09, TB-01, TB-02, DS-11 | All MVP requirement IDs pass, all NF targets are met or the gaps are documented, a design QA pass is done (screenshots of every panel in both themes checked against §7), and the demo video is recorded. |

---

## 11. Success metrics

**Portfolio and product:**
- All `[MVP]` requirements have passing tests or documented manual checks.
- The hero demo runs from a clean install in ≤3 commands: `pip install -e .[rl]`, `simview`, open template.
- All 4 flagship templates (UC-1–UC-4) run without errors on Windows, macOS, and Linux CI.

**Technical:**
- The NF-01–NF-07 targets are met on the reference hardware.
- Core test coverage is ≥80%.
- There are zero UI freezes over 250 ms during a 10-minute UC-2 run, measured with the Qt event-loop watchdog.

**Design:**
- Every panel passes the §7 checklist in both themes.
- Zero hard-coded style values outside `ui/theme/`.
- The hero demo screenshot is good enough for a portfolio header with no editing.

**Usability:** a new user can do UC-3 (load arm → drag IK → plot joints) in under 5 minutes by following the README.

---

## 12. Risks and open questions

| # | Risk / question | Mitigation |
|---|---|---|
| R1 | VTK rendering could fall short of 60 FPS with large point clouds and many trails. | Use VTK polydata in-place updates, not actor re-creation. Decimate trails. Profile in M4. If it still falls short, evaluate pygfx for the viewport only, and **ask me before switching**. |
| R2 | Python GIL and overhead could limit the sim RTF targets. | Keep the sim in its own process. Vectorize custom models with NumPy. Hand MuJoCo's C core the heavy lifting. Add optional `numba` JIT for custom ODEs in v1. |
| R3 | Determinism across operating systems isn't guaranteed (floating point, MuJoCo builds). | Scope NF-06 to the same machine and OS. Document this. |
| R4 | The block-diagram editor is large in scope. | The MVP block library is fixed at the list in BD-02. No multi-rate until v1. |
| R5 | Qt binding conflicts (PySide6 vs PyQt6 dependencies such as QScintilla or qtconsole). | Standardize on PySide6 through `qtpy`. Verify in M1 that qtconsole works under PySide6. |
| R6 | Offscreen camera rendering in the sim process could be slow. | Use MuJoCo's offscreen renderer (EGL/OSMesa on Linux) at reduced rate and resolution. The camera is optional per scene. |
| Q1 | Should the block editor also generate the Python script (BD-10) in the MVP, for portfolio value? | Default: no (v1). Revisit after M7. |
| Q2 | Ship a standalone PyInstaller build for the MVP? | Default: no. `pip install` only, and revisit at M10. |
| Q3 | License for SimView itself? | Default: MIT. Confirm before the first public push. |
