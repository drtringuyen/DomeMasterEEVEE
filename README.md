# DomeMasterEEVEE

Fulldome fisheye rendering for Blender's EEVEE, with adjustable FOV and sampling
diagnostics.

EEVEE has no panoramic camera — panoramic types (fisheye, equirectangular) are
Cycles-only, and EEVEE rasterises through a single projection matrix with no
per-pixel ray generation hook. This addon does what real-time fulldome pipelines
do instead: render the scene as cube faces, then remap those faces onto a
fisheye disc.

## Origin of the projection maths

The projection is ported from **pfc Dome Tools** (`com.pfc.dome-tools`) by
[prefrontal cortex](https://prefrontalcortex.de/en/projects/dome-tools/), a Unity
fulldome package. The relevant original is `UVToDirection()` in
`DomemasterInclude.cginc`, an equidistant angular fisheye:

```hlsl
uv2   = uv * 2 - 1;  uv2.y *= -1;
phi   = atan2(uv2.y, uv2.x);
theta = length(uv2) * 0.5 * targetAngleRad;   // full FOV, not half
dir   = float3(sin(theta)*cos(phi), cos(theta), sin(theta)*sin(phi));
```

`GetDebugStretch()` is ported essentially verbatim as the Stretch Debug view.

Two things change in the port:

* **Axis convention.** Unity is Y-up left-handed; Blender is Z-up right-handed
  and a camera looks down its local −Z. Directions are built in *camera-local*
  space with the dome axis on −Z, so the centre of the fisheye disc is whatever
  the camera points at, and the maths composes directly with the camera matrix.
* **No cubemap sampler.** Blender's `gpu` module has no cube texture type, so
  the faces are bound as separate 2D textures and face selection happens in the
  shader by projecting into each face basis.

The pfc package is licensed **Proprietary**. The underlying fisheye maths is
textbook and not theirs to own, but if this goes beyond personal use, ask them.

## Face layout: below 180° you only need one render

A square perspective face of FOV *F* covers every direction with zenith angle
≤ *F*/2. So for a fisheye under 180° a **single wide face** covers the whole
disc — no cube, no seams, one scene draw.

This is an *exact* remap, not an approximation. It samples real rays of the
real scene. (Contrast pfc's single-pass `GetUV` mode, which re-projects a flat
render as though the scene were painted on the dome surface, and is therefore
only correct for content at infinity.)

Verified by A/B against the 5-face path at 140°, same scene:

| | Faces | Source | Time |
|---|---|---|---|
| Cube | 5 × 96° | 464 px each | 0.58 s |
| Single | 1 × 142° | 1216 px | **0.21 s** |

Difference over the disc: mean 0.00113, and **every** pixel differing by more
than 0.02 sits on an object edge — one-pixel antialiasing scatter. Across the
187,307 pixels in smooth regions the maximum difference is exactly **0.0**.

The cost is source resolution, because a perspective face concentrates pixels
towards its edges (density ~ sec²) while the fisheye wants them uniform:

| Fisheye FOV | Single face needs | Single px | 5-face px |
|---|---|---|---|
| 90° | 1.27 × output | 1.6 N² | 10.0 N² |
| 120° | 1.65 × | 2.7 N² | 5.6 N² |
| 135° | 2.05 × | 4.2 N² | 4.4 N² |
| 150° | 2.85 × | 8.1 N² | 3.6 N² |
| 170° | 7.70 × | 59.4 N² | 2.8 N² |

Both preview and render are fill-bound, so **Auto** costs both candidate
layouts with `cost = faces × (4 ms + 7 ms/MPix)` and picks the cheaper. The
crossover moves with output resolution, so it is computed rather than fixed:

| Output | Single face wins up to |
|---|---|
| 1024 px | ~145° |
| 2048 px | ~135° |
| 4096 px | ~133° |

Above 170°, or when a single face would exceed 8192 px, Auto always uses the
cube. Forcing **Single Face** at 160° is a trap: it needs 4.5× the output
resolution and measures roughly 4× *slower* than a 240° cube.

**The bigger win is usually quality, not speed.** One face means no seams,
so SSR, ambient occlusion, bloom, depth of field, motion blur and volumetrics
come out correct instead of discontinuous across face joins — the limitation
listed below simply doesn't apply under 180°.

Override with **Face Layout** → Single Face / Cube Faces if you want to force
one or the other.

## What it does

* Adaptive face layout: one wide seam-free face under 180°, 5 cube faces up to
  180°, 6 above.
* Overscan on each face with a cross-faded overlap, which softens the seams
  that screen-space effects produce at face boundaries.
* GLSL remap on the GPU, with a NumPy fallback if the driver rejects the shader.
* Adjustable fisheye FOV (30–360°), dome tilt, image rotation, horizontal flip.
* OpenEXR (linear) / PNG / JPEG output, single frame or frame range.
* **Stretch Debug** — sampling-density readout. Red = undersampled (raise Face
  Scale), green = 1:1, blue = oversampled (lower it).
* **Test Pattern** — fisheye graticule with coloured cardinal spokes.
* **Dome Preview** — hemisphere with equidistant UVs baked per vertex, for
  viewing a domemaster from inside. No shader maths, works natively in EEVEE.
* **Orientation Rig** — coloured markers on known world axes plus a
  zenith-facing camera, for verifying handedness end to end.
* **Live Preview** — the dome drawn over the 3D viewport, updated as you work.
  Follows either the scene camera or the viewport view; corner or fullscreen.

### How the live preview works

A **timer** renders the cube faces with `GPUOffScreen.draw_view3d()` and remaps
them; a **SpaceView3D draw handler** only blits the result. The obvious
single-callback design would call `draw_view3d()` with the region currently
being drawn as its temporary target, which risks re-entrancy — timer callbacks
were verified to hold a valid GPU context in 5.2, so the render lives there
instead.

The whole path stays on the GPU: an offscreen's `.texture_color` is a
`GPUTexture`, so face renders feed the remap shader directly with no CPU
readback. It also only re-renders when something actually changed (view matrix,
depsgraph, frame, or any projection setting), so a static scene costs nothing.
`Max Updates/sec` is a ceiling, not a constant cost.

**It is viewport quality, not render quality** — viewport sampling, no
final-render passes, no compositor. Use it for framing and composition, not for
judging noise or final look.

Placement is **Camera Frame** by default: in camera view the dome fills the
camera frame, so looking through the camera shows what the dome shows. It uses
`camera.data.view_frame()` projected through the region, so it tracks camera
zoom and pan for free, and falls back to Corner when you leave camera view.

### Preview performance — what actually costs

Profiled on an RTX 4080, 72-object scene, EEVEE, Material Preview shading,
**with a GPU sync after each draw**:

| Face resolution | Per face |
|---|---|
| 512 px | 5.0 ms |
| 1024 px | 7.6 ms |
| 2048 px | 33.6 ms |
| 3072 px | 65.6 ms |
| 4096 px | 115.0 ms |
| 6144 px | 309.4 ms |

Cost is **fill-bound and roughly quadratic in resolution** above ~1024 px.

> An earlier version of this file reported a flat 2.2 ms from 256 px to
> 1024 px. That benchmark did not force GPU completion, so it measured
> *submission* time, not work done. The conclusions drawn from it — that
> resolution was free, that the preview could use a single face up to 160°, and
> that half-height side faces were pointless — were all wrong. Always sync
> before you stop the clock.

The three real levers, in order:

* **Resolution** — quadratic above 1024 px. It also sets the face size, so it
  compounds.
* **Max Updates/sec** — linear. An unchanged scene costs 0.08 ms per tick.
* **Preview Shading → Solid** — measured 10.3 ms → 6.9 ms, about a third off.
  The main viewport is unaffected; the space is flipped only for the face
  draws, on a timer, between viewport draws.

### Half side faces

For a fisheye of 180° or less every needed direction has zenith angle ≤ 90°,
so `d.z ≤ 0` in camera-local space. Each side face's transform puts `d.z` on
one axis:

```
right  c = ( d.z,  d.y, -d.x)   -> c.x = d.z  <= 0   left half only
left   c = (-d.z,  d.y,  d.x)   -> c.x = -d.z >= 0   right half only
up     c = ( d.x,  d.z, -d.y)   -> c.y = d.z  <= 0   bottom half only
down   c = ( d.x, -d.z,  d.y)   -> c.y = -d.z >= 0   top half only
```

So exactly half of each side face is never sampled. Rendering only the used
half turns 5 full faces into ~3 faces' worth of pixels — a **38.4% pixel
saving**, verified.

The final render does this with a **cropped render border** rather than an
asymmetric frustum: the camera keeps its symmetric FOV and Blender crops the
output, so there is no lens maths and no chance of the border and the shader's
uv mapping drifting apart. The margin past the halfway line is quantised to a
whole pixel for the same reason.

Measured wall-clock, 180°, this scene:

| Output | Full faces | Half faces | Saving |
|---|---|---|---|
| 512 px | 0.48 s | 0.37 s | 23% |
| 1024 px | 0.84 s | 0.56 s | **33%** |
| 2048 px | 0.89 s | 0.73 s | 18% |

**It is deliberately not used in the live preview.** Measured with a GPU sync,
it saves 3.1% at 1024 and 0.3% at 2048 — `draw_view3d` is bound by per-draw
setup, not fill, so removing pixels buys nothing there.

Correctness was checked two ways. Against the orientation rig the output is
bit-identical in flat regions (max difference exactly 0.0). On a real scene the
error is analysed by radius:

| Disc radius | Mean diff | % over 0.02 |
|---|---|---|
| 0.00–0.45 | 0.000000 | 0.00 |
| 0.45–0.55 (seam band) | 0.000014 | 0.00 |
| 0.60–0.80 | 0.000255 | 0.17 |
| 0.80–0.96 | 0.000421 | 0.19 |

The seam band — where the forward and side faces join, and the thing most at
risk from a half-face alignment bug — is the *cleanest* part of the image,
16× better than average. Alignment is correct.

The small residual grows toward the rim, which is the part of each side face
nearest the cut. Raising TAA from 16 to 64 samples does not change it at all,
so it is not sampling noise: it is EEVEE's screen-space effects seeing a
smaller render target and resolving slightly differently near that edge. It
affects 0.19% of pixels at above 0.02, and does not touch the seams.

## Known limitations

* **Screen-space effects seam at face boundaries — in cube mode only.** EEVEE's
  screen-space raytracing, fast GI, bloom, DOF, motion blur and screen-space
  shadows are computed per face and will not agree across a seam. Overscan
  blending helps; it does not eliminate the problem. Apply post *after* the
  remap where you can. **Under 180° use Single Face and this disappears
  entirely** — there is only one render, so there is nothing to disagree.
* **Volumetrics** are per-frustum and seam for the same reason, with the same
  fix.
* Rendering blocks the UI — the operator is not modal yet.
* **The NumPy fallback does not implement Stretch Debug.** If the GPU path is
  unavailable it silently returns the image instead of the readout.
* Green everywhere in the Stretch view is not achievable. The centre of a cube
  face is its worst-sampled point and the edges are oversampled by up to 2×;
  that is inherent to mapping a cube onto a disc. Aim for green at the disc
  centre and accept blue towards the rim — which is what Auto Face Scale does.
* Side faces are rendered at full 90°+overscan. For FOV ≤ 180° only their
  forward half is actually used, so roughly 40% of side-face pixels are wasted.
  Asymmetric-frustum side faces would cut a 5-face frame to about 3 faces'
  worth of pixels. Not implemented yet.
* Live viewport preview (`GPUOffScreen.draw_view3d`) is planned for v2.

## Usage

1. Point the scene camera where the centre of the dome should be — typically
   straight up.
2. N-panel → **DomeMasterEEVEE** → **Dome Render**.
3. Set FOV (180 for a standard domemaster) and output resolution.
4. Leave **Auto Face Scale** on. It derives face resolution from
   `tan(faceFov/2) / halfFov` — the smallest size that never undersamples
   (0.707 for a 180° dome at the default 3° overscan). Turn it off and use
   Stretch Debug only if you want to trade quality for speed.
5. **Render Domemaster** or **Render Domemaster Sequence**.

### Verifying orientation

Diagnostics → **Build Orientation Rig**, then render. A correct 180° domemaster
shows:

| Marker | World position | Expected in image |
|---|---|---|
| RED | +X | right |
| YELLOW | −Y | top |
| GREEN | +Y | bottom |
| BLUE | −X | left |
| WHITE | +Z (zenith) | centre |

If your target pipeline disagrees, fix it with **Image Rotation** and
**Flip Horizontal** rather than editing the shader.

## Project structure

```
DomeMasterEEVEE/
├── addons/DomeMasterEEVEE/
│   ├── __init__.py
│   ├── properties.py            # all global properties
│   ├── panels.py                # Infos + main container panel
│   ├── infos.py                 # build/reload/debug/console operators
│   ├── module_manager.py
│   └── modules/
│       ├── dome_render/
│       │   ├── projection.py    # GLSL + NumPy remap  <- the ported maths
│       │   ├── capture.py       # cube face rendering, output writing
│       │   ├── operators.py
│       │   └── ui.py
│       └── dome_debug/
│           ├── operators.py     # test pattern, dome preview, orientation rig
│           └── ui.py
├── manifest.toml
├── install.py                   # copy to Blender + MCP auto-reload
├── zip_addon.py
└── build_extension.py
```

## Development

```bash
python install.py     # copies to Blender 5.2 scripts/addons and reloads via MCP
```

Requires Blender 4.0+; developed and tested against **Blender 5.2 LTS**.

## Author

Nguyen Duc Tri
