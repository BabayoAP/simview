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
