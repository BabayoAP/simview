# SimView UX guidelines: tooltips, help, and guidance

Rules for how SimView explains itself: tooltips, status tips, empty states, the Help menu, and
the user guide. They narrow PRD §7 (design standards), which still wins where the two differ.
Each rule cites the published guideline it comes from. Every UI change is checked against the
checklist at the end; `tests/ui/test_help.py` enforces the parts a test can (D-147).

## Sources

| Source | What we took |
|---|---|
| Apple HIG, [Offering help](https://developer.apple.com/design/human-interface-guidelines/offering-help) | Tooltips (help tags) on pointer rest; context-sensitive text, e.g. different text per state; keep them short |
| Microsoft, [Tooltips (Windows App SDK)](https://learn.microsoft.com/windows/apps/design/controls/tooltips) | Use tooltips sparingly; label controls inline; icon-only buttons need one; show the keyboard accelerator |
| Microsoft, [Win32 tooltips and infotips](https://learn.microsoft.com/windows/win32/uxguide/ctrl-tooltips-and-infotips) (Windows 7 era, principles still apply) | Never a substitute for good design: if users keep checking a tip to understand a control, fix the control |
| GNOME HIG, [Tooltips](https://developer.gnome.org/hig/patterns/feedback/tooltips.html) | Tooltips for controls without labels; brief; no tooltips that repeat the label |
| Nielsen Norman Group, [Tooltip guidelines](https://www.nngroup.com/articles/tooltip-guidelines/) | Never put information needed to finish a task only in a tooltip; don't repeat the visible label; label icons instead where possible |
| Nielsen Norman Group, [Onboarding tutorials](https://www.nngroup.com/articles/onboarding-tutorials/) | Walkthrough tutorials are overused and skipped; prefer contextual help with progressive disclosure |
| W3C, [WCAG 2.2 SC 1.4.13 Content on hover or focus](https://www.w3.org/WAI/WCAG22/Understanding/content-on-hover-or-focus) | Hover content must be dismissible, hoverable, and persistent; whatever appears on hover must also be reachable by keyboard focus |
| PRD §7.2, §7.8, §7.9 | Keyboard-first and mouse-complete; every action in the command palette; empty states; no modal dialogs; WCAG AA contrast |

## 1. Labels first, tooltips second

1. A control with a clear visible label needs no tooltip. Add one only when it says something
   the label doesn't, such as the shortcut or what happens to your data. *(Microsoft, NN/g, GNOME)*
2. **Every icon-only button has a tooltip.** This includes the 3D view's heads-up toolbar,
   which VTK draws, so its tooltips are shown by hand (`view._show_toolbar_tip`). *(Microsoft, GNOME)*
3. If a control keeps needing its tooltip to be understood, give it a label or a better icon.
   *(Microsoft Win32)*

## 2. What a tooltip says

1. **Name, then shortcut**: `Group into a subsystem (Ctrl+G)`. Build it with
   `actions.tooltip_text` / `describe_action`, which spells the shortcut the platform's way
   (`⌘G` on macOS). Never type "Ctrl+" into a tooltip by hand. *(Microsoft: show accelerators)*
2. Short: aim for under ~60 characters, one line, no full stops, no numbered steps. *(Apple)*
3. Sentence case, the same words as the menu item or command palette entry, no trailing `…`.
4. Context-sensitive where it helps: toggles say their state (`Ground grid (on)`); a button
   whose key is shared says so (Run and Pause both show Space). *(Apple)*
5. Never the only place for something needed to finish a task: errors, units, and required
   formats go in the UI itself (inline message, placeholder, empty state). *(NN/g)*
6. Don't repeat the label. `Save` with the tooltip "Save" adds nothing; "Save (Ctrl+S)" does.
   *(NN/g, GNOME)*

## 3. Status tips

Registered actions take an optional `tip`: one sentence on what the action does, shown in the
status bar on hover. Use it where the name alone could surprise, e.g. "Stop, save the run to the
runs folder, and reset to t = 0." Otherwise the status tip is the action's name.

## 4. Hover content and accessibility

1. Qt's native tooltips meet WCAG 1.4.13 in the way that applies to platform-drawn hover text:
   they persist while the pointer stays, close on Esc or when the pointer moves away, and never
   cover the control that triggered them. Don't build custom hover popups; if one is needed it
   must be dismissible with Esc, stay open while hovered, and open on keyboard focus too.
   *(W3C 1.4.13)*
2. Anything a tooltip reveals must also be reachable without a mouse: the command palette
   (Ctrl+K) lists every command, and Help > Keyboard Shortcuts lists every key. *(PRD §7.2, §7.9)*
3. Tooltip text inherits the theme tokens; no colours or sizes in tooltip code. *(DS-01)*

## 5. Guidance beyond tooltips

1. **No forced tours or walkthroughs.** Help is contextual and on demand. *(NN/g)*
2. **Empty states teach**: every empty panel says what goes there in one line and offers the
   button that fills it (§7.8). This is SimView's onboarding.
3. **Progressive disclosure**: the start screen shows five templates and two buttons; advanced
   features (sweeps, scenario tests, training) are a menu or panel away, not on first view.
   *(NN/g)*
4. **Help menu**: Keyboard Shortcuts (Ctrl+/, non-modal, filterable, built from the live
   bindings so it can't drift) and SimView User Guide (the platform's help key: F1, or Cmd+? on
   macOS), which opens [USER_GUIDE.md](USER_GUIDE.md).
5. **The user guide** is task-based ("Run a simulation", "Investigate runs"), in plain words,
   and lists only what the app does today. Update it in the same change as the feature.

## 6. Checklist for UI changes

- [ ] Icon-only buttons have tooltips; labelled ones only where the tooltip adds something.
- [ ] Actions are registered through `ActionRegistry.register` (or call `describe_action`), so
      their tooltips show the shortcut in the platform's spelling.
- [ ] New shortcuts appear in Help > Keyboard Shortcuts (automatic for registered actions;
      add non-action keys to `help.EXTRA_KEYS`).
- [ ] Toggles' tooltips say their state.
- [ ] New panels have an empty state with a hint and an action.
- [ ] Nothing needed to finish a task is hidden in a tooltip.
- [ ] `docs/USER_GUIDE.md` is updated if the feature is user-facing.
- [ ] `pytest tests/ui/test_help.py` passes.
