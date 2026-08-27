# Session Log — 2026-08-27 — N-Panel UI Rewire

Scope: iterative rewiring of the DomeMasterEEVEE N-panel layout in Blender's 3D viewport
sidebar, driven by screenshot-annotated feedback from the user, verified live via the Blender
MCP connection at every step.

## 1. Panel reorganization

- `Infos` panel ([`panels.py`](../addons/DomeMasterEEVEE/panels.py)): build/reload/debug-toggle/
  console/clear controls merged from two rows into one.
- Reordered top-level sibling panels under `DomeMasterEEVEE` (main) to: **Dome Render → Live
  Preview → Material Alpha Audit → Diagnostics → Stretch Debug**, via `bl_order` (0/1/2/3/4).
  `Stretch Debug` was originally a nested sub-panel of `Dome Render`; the user explicitly chose
  to promote it to a top-level sibling instead of leaving it nested.
- Diagnostic/status text (face-count summary, last-render info, preview perf box, refresh-result
  readout, "viewport quality" note) all gated behind `props.debug_mode` and tagged
  `text_ctxt="extra-info-label"`, matching the existing Modules/Version rows in `Infos` — hidden
  by default, revealed by the same global debug toggle.
- New collapsible sub-panel **"Dome Face Mapping"** (`DOMEMASTEREEVEE_PT_dome_face_mapping`,
  parented to Dome Render, `DEFAULT_CLOSED`) — houses Face Layout, Half Side Faces, Overscan,
  Auto Face Scale, Face Scale, GPU Remap, and Keep Cube Faces, each on its own row.

## 2. Row layout iteration (dome_render/ui.py, dome_preview/ui.py)

Went through several rounds of user-annotated screenshots requesting: packing groups of
properties into single rows via `layout.row(align=True)`, splitting others back into individual
rows via `layout.column(align=True)`, percentage-width splits via nested `layout.split(factor=…)`
(e.g. Output Folder 80% / Format 20%; Dome Rotation 40% / Dome Tilt 40% / Flip 20%), icon-only
toggle buttons (`text=""` on a `BoolProperty` prop collapses it to a plain icon button — this
works reliably), and finally two `layout.box()` groupings around (a) Fisheye FOV/Output
Resolution/Dome Rotation/Dome Tilt/Optimize Scene Rendering and (b) Output Folder/Format/Render
Domemaster/Render Domemaster Sequence.

**Icon behavior discovered:** a custom `icon=` passed directly to `layout.prop()` on a narrow
numeric/slider field is silently dropped by Blender when the column is too narrow to fit both
label and icon — it renders fine on buttons/toggles regardless of width, but not reliably on
number fields. Fix: draw the icon as its own `layout.label(text="", icon=…)` immediately before
the `prop()` call, in the same `row(align=True)`, rather than relying on the prop's own icon
argument. Used for Dome Rotation (`ORIENTATION_CURSOR`), Dome Tilt (`SPHERE`), Fisheye FOV
(`HIDE_OFF`), Output Resolution (`IMAGE_REFERENCE`). Flip Horizontal ended up on `MOD_MIRROR`
after trying a couple of alternatives (`AREA_JOIN_UP`, `FORCE_HARMONIC`) per user preference.

## 3. Blender registration corruption — recurring throughout this session

The known corruption pattern (see [[blender-mcp-registration-corruption]] memory) showed up
**repeatedly** during this iterative UI session, not just once:

- Every code edit was followed by `python install.py` (copies repo → Blender's addons folder,
  writes `build_info.json`, then reloads via the MCP socket: `addon_disable` → purge
  `sys.modules` entries → `addon_enable`).
- After enough consecutive reload cycles in one continuous Blender session (roughly every
  4–6 edit/install cycles), `Panel.__subclasses__()` showed multiple stacked duplicate classes
  per panel, and — critically — **a screenshot would show stale/old UI even though
  `inspect.getsource(bpy.types.<PanelIdName>.draw)` confirmed the *newest* source was bound to
  that type name.** This means neither `hasattr` (already known-unreliable) nor
  `inspect.getsource` on the live `bpy.types.X` class is a trustworthy signal — the RNA draw
  callback Blender actually invokes at UI-draw time can be a stale one even when the Python
  attribute `bpy.types.X` has been rebound to point at the newest class object.
- **The only reliable verification is a real screenshot after forcing a redraw**
  (`area.tag_redraw()` on every area + `bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',
  iterations=1)`), and even then, sometimes only a **full Blender restart** actually flushes the
  stale draw callback (confirmed once mid-session: identical install+reload sequence produced
  correctly-updated UI immediately after a restart, but showed stale UI for the same code change
  several edits later in the same continuous session).
- Practical workflow that emerged: after every `install.py` run, force-redraw + screenshot to
  verify; if the screenshot doesn't reflect the change and the source-of-truth checks
  (`inspect.getsource`, direct draw-call simulation with a mock layout) say the code is correct,
  don't keep debugging the Python — ask for a Blender restart.

## Result

All requested layout changes verified live via Blender MCP screenshots by the end of the
session. Final panel order: Dome Render (with nested Dome Face Mapping foldout) → Live Preview →
Material Alpha Audit → Diagnostics → Stretch Debug.
