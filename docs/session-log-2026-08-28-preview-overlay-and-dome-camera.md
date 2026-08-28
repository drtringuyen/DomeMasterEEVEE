# Session Log — 2026-08-28 — Preview Overlay Rework & Dome Camera Picker

Scope: three separate changes to the live dome preview, done in sequence in one session.

## 1. Corner overlay: vertical slider + circular mask

Files: [`properties.py`](../addons/DomeMasterEEVEE/properties.py),
[`dome_preview/ui.py`](../addons/DomeMasterEEVEE/modules/dome_preview/ui.py),
[`dome_preview/preview.py`](../addons/DomeMasterEEVEE/modules/dome_preview/preview.py).

- `preview_corner` (`TOP_LEFT`/`BOTTOM_LEFT` enum) replaced with `preview_vertical_pos`
  (`FloatProperty`, 0–1 slider, `subtype='FACTOR'`). 0 = top, 1 = bottom.
- In `_draw()`, the corner overlay's pivot is now fixed to the left edge
  (`x0 = inset_l + margin`); only `y0` moves, lerped between the top and bottom usable
  positions by `preview_vertical_pos`.
- The blit is masked to a circle instead of a square (the fisheye disc sits inside a square
  render target with black corners outside the circle). `_blit()` gained a `circular` param
  (default `True`) and a hand-written GLSL fragment shader that discards pixels where
  `dot(d,d) > 0.25` (`d` = uv − 0.5).
- **Gotcha hit and fixed**: `gpu.types.GPUShader(vertexcode, fragcode)` direct construction is
  removed in Blender 5.x — raises `TypeError: cannot create 'GPUShader' instances`, and this
  happens *silently* from inside a draw handler (prints a traceback to console but doesn't
  crash Blender, so it's easy to miss). Fixed the same way `dome_render/projection.build_shader()`
  already did it: build via `gpu.types.GPUShaderCreateInfo` + `gpu.shader.create_from_info()`
  instead. Documented as a comment on the new `_build_circle_shader()`.

## 2. Per-viewport (window-aware) live preview on/off

Files: [`properties.py`](../addons/DomeMasterEEVEE/properties.py),
[`dome_preview/operators.py`](../addons/DomeMasterEEVEE/modules/dome_preview/operators.py),
[`dome_preview/ui.py`](../addons/DomeMasterEEVEE/modules/dome_preview/ui.py),
[`dome_preview/preview.py`](../addons/DomeMasterEEVEE/modules/dome_preview/preview.py),
[`dome_preview/__init__.py`](../addons/DomeMasterEEVEE/modules/dome_preview/__init__.py).

Requirement: turning the preview on/off in one 3D viewport must not affect any other open
viewport, while every other preview setting (camera, shading, resolution, fps, placement)
stays global; and the actual render must still happen once per tick no matter how many
viewports have it on.

- Removed the old scene-level `preview_enabled` `BoolProperty` (and its `_preview_toggled`
  update callback) entirely — there is no global on/off anymore.
- **First approach tried and reverted**: registering a `BoolProperty` directly on
  `bpy.types.SpaceView3D` (the common pattern for viewport-scoped addon state) so the header
  checkbox could bind to real RNA data. Confirmed by direct experiment that this does **not**
  work in this Blender 5.2 build — `SpaceView3D` doesn't support dynamic property registration
  *or* raw ID-property assignment (`space["key"] = val` raises
  `"id properties not supported for this type"`). Reading the "registered" property back off an
  instance just returns the `_PropertyDeferred` descriptor object, not a value. This is a
  genuine Blender/Space limitation, not a bug in the addon code — worth remembering before
  trying this pattern again on `Space*` types.
- Working design instead: track active viewports as a plain Python `set()` of `VIEW_3D` area
  `as_pointer()` values (`_active_area_ptrs` in `preview.py`) — the same identity-by-pointer
  technique the pre-existing (and now removed) pin-to-viewport mechanic already used. This is
  runtime-only state: it does **not** survive a file reload or an addon reload (same limitation
  the old pin mechanic had). A `_prune_active_areas()` call each tick drops pointers for areas
  that no longer exist, since addresses can be reused once a struct is freed.
- New operator `DOMEMASTEREEVEE_OT_ToggleViewportPreview`
  (`domemastereevee.toggle_viewport_preview`) toggles `context.area`'s membership in that set.
  The old `TogglePreview`/`PinPreviewViewport`/`UnpinPreviewViewport` operators were deleted —
  the pin/unpin model is fully superseded by per-viewport toggling.
- UI: since there's no real bool property to bind to, the header checkbox in
  `DOMEMASTEREEVEE_PT_DomePreview.draw_header()` is drawn as an `operator()` button with
  `depress=` reflecting `preview.is_active_for_area(context.area)`, using
  `CHECKBOX_HLT`/`CHECKBOX_DEHLT` icons to mimic a native bool prop's look.
- `_find_view3d()` now returns any *one* area whose pointer is in `_active_area_ptrs` (arbitrary
  choice among active ones) to drive the single shared `draw_view3d()` render each tick.
  `_draw()` gates blitting per-region with `is_active_for_area(context.area)` — every open
  `VIEW_3D` fires the same draw handler, but only active ones draw anything.
- **Bug found and fixed during verification**: `_tick()`'s auto-stop path (`if not
  _active_area_ptrs: return None`) only unregistered the *timer* — it skipped `stop()`, which
  also removes the draw handler and frees the GPU offscreen textures. Fixed to call `stop()`
  before returning `None`, so the last-viewport-closed case doesn't leak GPU resources.
- Verification note: the Blender-MCP screenshot tool could not be trusted to visually confirm
  the *second* (non-default) viewport once its area's `.type` was temporarily swapped to hide
  the other one for isolation — screenshots of that specific area came back blank even with a
  forced full-viewport blit and no exceptions anywhere in the pipeline, while direct Python
  introspection of module state (`is_active_for_area`, `_blit` call args, texture pixel reads)
  all confirmed correctness. Concluded this was a screenshot-tool capture artifact tied to the
  `area.type` swap trick, not a real bug — proven by a *second*, untouched-layout test where
  toggling the non-default viewport on left the default (screenshotted) viewport correctly blank.
  If this needs re-verifying visually in a future session, resize/split the areas instead of
  changing `.type`, or just trust the module-state introspection.

## 3. `dome_camera` picker replaces "Follow" (Scene Camera / Viewport View)

Files: [`properties.py`](../addons/DomeMasterEEVEE/properties.py),
[`dome_preview/ui.py`](../addons/DomeMasterEEVEE/modules/dome_preview/ui.py),
[`dome_preview/preview.py`](../addons/DomeMasterEEVEE/modules/dome_preview/preview.py),
[`dome_render/operators.py`](../addons/DomeMasterEEVEE/modules/dome_render/operators.py).

Requirement: the "Follow" dropdown (previously `preview_source` enum: Scene Camera / Viewport
View) becomes a single camera picker that drives *both* the live preview *and* the
Render Domemaster / Markers / Sequence operators — no more implicit "whatever `scene.camera`
happens to be" or viewport-follow mode.

- `preview_source` (`EnumProperty`) replaced with `dome_camera`
  (`PointerProperty(type=bpy.types.Object, poll=lambda self, obj: obj.type == 'CAMERA')`).
  Blender's object picker naturally renders as a searchable dropdown pre-filtered to cameras —
  no custom UIList needed.
- `preview.py`'s `_base_matrix()` simplified to just `props.dome_camera.matrix_world` (dropped
  the `space` param entirely, and the whole viewport-follow branch). Returns `None` — pausing
  the preview — when no camera is selected.
- `dome_render/operators.py`: `_ensure_dome_camera()` and the `poll()` classmethods on
  `RenderDomeStill`/`RenderDomeAnimation`/`RenderDomeMarkers`/`SwitchCamera` now check
  `props.dome_camera` instead of looking up the object literally named `Camera-DOME-Master`
  (`CAMERA_NAME`). The render operators no longer require that specific named object to exist —
  any camera assigned to `dome_camera` works.
- `Setup Camera & Optimize Scene` (`OptimizeSceneRendering`) is unchanged in what it creates
  (still makes/replaces the `Camera-DOME-Master` ortho camera by that fixed name as a
  convenience), but now also sets `props.dome_camera = cam_obj` so the picker auto-populates
  after running it. `CAMERA_NAME` / the fixed-name object is now just *one way* to get a camera
  into `dome_camera`, not the only way.

## Verification

All three changes installed via `install.py` + Blender MCP and checked live in-session:
- Circular mask + vertical slider: screenshotted at slider 0.0 and 1.0, circle slid cleanly
  top-to-bottom along the left edge with no black corners.
- Per-viewport toggle: toggled on in one `VIEW_3D` area, confirmed via screenshot the other
  stayed blank; reversed and got the same result the other way — see caveat above about the
  screenshot tool and area-type swapping.
- `dome_camera` picker: assigned `CAM-Dome` from the dropdown (populated with `CAM-Director` and
  `CAM-Dome`, the scene's two cameras), preview started rendering through it immediately, and
  the previously poll-disabled Render Domemaster / Render Domemaster Sequence buttons became
  enabled.

## Open items for next session

- `dome_camera` is a fresh property with no default/migration — existing scenes that relied on
  `preview_source == 'CAMERA'` + `scene.camera` will show "No Dome Camera selected" until the
  user either runs `Setup Camera & Optimize Scene` or picks a camera manually. Worth deciding
  whether to auto-populate `dome_camera` from `scene.camera` or the `Camera-DOME-Master` object
  on addon load/register, if that friction turns out to matter in practice.
- The per-viewport preview on/off truly does not persist across a file reload or addon reload
  (see the `SpaceView3D` limitation above) — this is a known, accepted trade-off, not a bug to
  fix, but worth remembering if it comes up again as a complaint.
