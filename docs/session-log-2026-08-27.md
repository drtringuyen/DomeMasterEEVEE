# Session Log — 2026-08-27 — Render Debugging & Performance Work

Scope: fixed a real render-blocking bug, added two new addon features, and did a full
render-performance investigation for the fulldome pipeline on Blender 5.2 LTS / EEVEE Next.

## 1. MCP reload diagnosis ("addon not showing up in Blender")

`install.py` and the MCP reload path were fine — the addon was actually installed, discovered,
and enabled with no import errors. The real cause was **accumulated Blender session corruption**
from many repeated hot-reloads in one running Blender process: panel/operator Python classes
pile up as duplicate `bpy.types.Panel`/`Operator` subclasses across reload cycles, and eventually
new registrations stop binding to `bpy.types` even though `register()` reports success with no
exception.

- **Fix / workaround:** close and fully reopen Blender periodically during heavy iterative
  reload sessions (roughly every dozen or so reloads). No in-session Python fix reliably
  recovers from this once it happens.
- **Important trap discovered later in the session:** `hasattr(bpy.types, "SomeClassName")`
  is **not a reliable signal** for "is this actually registered and visible in the UI."
  Operators kept working via `bpy.ops.*` and the panel was confirmed visible via an actual
  screenshot even when `hasattr` reported `False`. Always verify with
  `get_screenshot_of_window_as_image` (or ask the user) rather than trusting `hasattr` checks
  when diagnosing registration state.
- **Do not manually call `module.register()` / `module.unregister()` directly** during
  diagnostics — always go through `bpy.ops.preferences.addon_enable/disable`. A bare manual
  `register()` call desyncs `addon_utils`' internal "is this enabled" bookkeeping from the
  actual registered classes, and stacks further registrations on top instead of fixing anything.

## 2. Real bug fixed: `OPEN_EXR`/media_type render crash

**Symptom:** `Domemaster render failed: bpy_struct: item.attr = val: enum "OPEN_EXR" not found
in ('FFMPEG')`

**Root cause:** Blender 4.x+ splits `render.image_settings` into `media_type` (`'IMAGE'` /
`'VIDEO'`). When the scene's Output tab is left on a video/FFmpeg format, `file_format`'s enum
is restricted to movie containers only. `capture.py` was setting `file_format = 'OPEN_EXR'`
directly without first switching `media_type` back to `'IMAGE'`.

**Fix** ([`capture.py`](../addons/DomeMasterEEVEE/modules/dome_render/capture.py)):
- `RenderStateGuard` now also saves/restores `media_type`.
- `render_faces()` forces `media_type = 'IMAGE'` before setting `file_format = 'OPEN_EXR'` for
  per-face captures.
- `write_output()` does the same around the final domemaster write, and critically **restores
  `media_type` before `file_format` on the way out** — restoring in the wrong order re-triggers
  the same enum error in reverse (this was a real mistake made and caught during this session).

Net effect: the addon no longer depends on Blender's native Output tab setting at all — nothing
to mis-click there anymore.

## 3. New feature: Optimize Scene Rendering button

Added to the Dome Render panel, directly below GPU Remap
([`operators.py`](../addons/DomeMasterEEVEE/modules/dome_render/operators.py),
[`ui.py`](../addons/DomeMasterEEVEE/modules/dome_render/ui.py)). One click, only ever lowers
settings (never raises quality it didn't touch):

- `render.use_persistent_data = True`
- `eevee.taa_render_samples` capped to 32
- `eevee.use_raytracing = False`
- `eevee.shadow_step_count` capped to 4
- `render.use_motion_blur = False`

Measured impact on this scene: `use_persistent_data` and `use_fast_gi` toggling both turned out
to be **negligible** (scene is too low-poly/no-lights for either to matter) — the real win is
almost entirely from the sample cap. Kept in the operator anyway since they're harmless and may
matter on heavier scenes.

## 4. New feature: Material Alpha Audit panel

Added under Diagnostics
([`operators.py`](../addons/DomeMasterEEVEE/modules/dome_debug/operators.py),
[`ui.py`](../addons/DomeMasterEEVEE/modules/dome_debug/ui.py)): lists every in-use material with
its current alpha render mode and a per-material toggle, plus bulk "All Dithered → Blended" /
"All Blended → Dithered" buttons.

**Important correction made mid-session:** initially built against the old 4-value
`blend_method` enum (`OPAQUE`/`CLIP`/`HASHED`/`BLEND`) — that property still exists on
`Material` for API compatibility but **does not drive the actual EEVEE Next render** in Blender
5.2; writing `'CLIP'` to it is a silent no-op. The real, render-affecting property is
`Material.surface_render_method`, with only two values: `DITHERED` (stochastic, needs samples —
this is what the legacy `HASHED` display maps to) and `BLENDED` (traditional back-to-front alpha
blend). There is **no CLIP-equivalent hard-cutout mode in EEVEE Next**. The operators now target
`surface_render_method` directly with a version-guarded fallback to the legacy `blend_method`
enum for pre-4.2 Blender.

### Dithered vs. Blended — measured, not assumed

Bulk-switched every material to Blended and measured against the known Dithered baseline, same
settings (170° FOV, cube, 4096 output, 32 samples):

| Mode | Time |
|---|---|
| Dithered (original) | 11.13s |
| Blended (all switched) | 18.57s |

**Blended is 67% slower**, not faster, on this scene — the opposite of the naive assumption
that removing per-pixel noise would be free or cheaper. In EEVEE Next, Dithered alpha is
stochastic per-sample discard that can ride the fast near-opaque path; Blended forces sorted
back-to-front compositing in a separate transparent pass, and with ~18 materials switched at
once (including overlapping glass/water pairs) that sorting/compositing overhead outweighs
whatever sample-noise cost Dithered was paying. **Recommendation: leave materials on Dithered**
(the user also independently preferred its visual look). If noise bothers you, raise samples
while staying Dithered — Dithered at 64 samples (11.38s) is still faster than Blended at 32
samples (18.57s).

The one place `surface_render_method` audit is still genuinely useful: **`MAT_water.opaque`**
is named "opaque" but was found set to `DITHERED` — likely an authoring oversight worth a
one-off look, independent of the bulk-switch conclusion above.

## 5. Single Face vs. Cube — the real constraint

Single Face mode's required texture size grows as `tan(FOV/2)`, uncapped exactly at 180°. The
addon caps single-face textures at `MAX_SINGLE_FACE_PX = 8192px` to prevent runaway renders.

- At the production target (170°–180° FOV, 4096 output), **Single Face is not achievable at
  all** — it needs ~18,500–31,500px depending on exact FOV, silently falls back to Cube
  regardless of what the UI mode picker says.
- Single Face only becomes viable at output resolutions up to ~1024px for FOV near 170°, or at
  lower FOV (≤ ~140°) for higher output resolutions.
- Where both are viable (tested at 120° FOV / 4096 output): **Single (8.33s) was over 2x faster
  than Cube (18.07s)** — worth switching to Single for any shot under ~140–150° FOV. For this
  project's 170–180° range, **Cube is the only option**, full stop.

## 6. Render time vs. sample count — full sweep

Full results and methodology in
[`render-time-sample-sweep.md`](render-time-sample-sweep.md) (already shared with the team).
Headline: render time scales almost linearly with `taa_render_samples` all the way down to 4
samples — halving samples roughly halves render time. This is the single largest lever available
for this scene. 270° FOV costs ~2x more than 170° FOV at matched sample counts (6 faces vs 5,
plus fixed per-face overhead, despite each individual face being smaller).

## Open items / not done this session

- `MAT_water.opaque`'s Dithered-despite-the-name mismatch was flagged but not changed —
  worth a one-off visual check.
- `REF-CHR_Ru` has `hide_viewport=True` but `hide_render=False`, meaning it's silently included
  in every render despite being a "reference" object hidden from view. Not yet fixed — worth
  setting `hide_render = True` if it's truly never meant to appear in output.
- No compositor/OIDN denoise integration was built (discussed as a way to push samples even
  lower without visible noise — the pipeline currently bypasses Blender's compositor entirely,
  going straight from EEVEE's EXR output to the custom remap code).
