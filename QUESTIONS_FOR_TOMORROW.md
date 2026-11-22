# Questions for tomorrow (2026-11-23)

Short answers are fine. Each has a recommended default that will be used if you say "defaults".

## Product scope

1. **PRD 1.5 draft (§5.13–§5.17): approve as written?** Scenario tests (ST), sim-to-real (SR),
   policy evaluation (PE), synthetic data (SD), reproducibility and review (RP); all `v1`/`Future`.
   *Default: approve, keep all out of MVP.*
2. **Which of them gets built first, and as a milestone?** *Default: an M12 after M11 with ST-01–ST-03
   and RP-01–RP-02, since they reuse RI and the sweep runner and make the hero demo CI-checkable.*
3. **Scenario file format:** Python only, or Python plus TOML? *Default: both; TOML via stdlib
   `tomllib`, no YAML dependency.*
4. **Remote policies (PE-04) in v1?** It is what makes VLA/GPU models testable. *Default: yes; uses
   pyzmq, which is already a dependency.*
5. **Keep NG5–NG7 (no cloud, no HIL, no ROS runtime)?** ROS 2 and PX4 bridges sit in BACKLOG.md
   because of them. *Default: keep the non-goals; revisit after v1.*
6. **opencv for webcam/video (VW-20) in v1?** *Default: yes, as an optional extra
   (`simview[video]`, `opencv-python-headless`), not a core dependency.*

## Technical

7. **NF-02 / NF-03 real-time-factor targets need a rerun on the Mac reference machine.** Can you run
   the M10 benchmark there after pulling `m10-polish-demo`? *Default: yes; results go in PROGRESS.md.*
8. **Visual checks pending (screen was locked):** ViewCube colors, the light-theme speed combo
   border, and the M11 perception views (voxels, Cameras panel, BEV panel). *Default: a 10-minute
   check in both themes tomorrow; fixes go on the current branch.*
9. **Run manifests (RP-01) record the project's git commit and machine info, and bundles (RP-03)
   carry them.** OK to include by default? *Default: yes, with a flag to strip machine info.*

## Process

10. **Order: M11 was built before M10 parts 3–5** (design QA, README GIFs + ARCHITECTURE.md, hero
    demo recording) because you asked for M11 while away. Finish M10 next, then review M11?
    *Default: yes, finish M10 parts 3–5 first, then the M11 review.*
11. **Merges: M8 PR #2 and M9 still need merging into `main`.** *Default: you merge M8 (PR #2),
    then M9, then M10/M11 branches get rebased on the new `main`.*
12. **Drafts like this one:** OK to keep proposing PRD changes as "draft, pending approval" with
    nothing built until you approve? *Default: yes.*
