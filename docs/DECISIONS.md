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
