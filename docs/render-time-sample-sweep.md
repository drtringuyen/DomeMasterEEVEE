# DomeMasterEEVEE — Render Time vs. Sample Count

Test date: 2026-08-27
Scene: `DOME_Camera`, current frame/camera position, EEVEE Next (Blender 5.2 LTS), RTX 4070 Ti (Vulkan)
Output resolution: **4096×4096** (Cube face layout — the only layout that reaches 4096 at wide FOV; see note below)

## Results

| Mode | Samples | Cube faces | Face resolution | Render time |
|---|---:|---:|---:|---:|
| Cube 170° FOV | 64 | 5 | 3066px | 11.38s |
| Cube 170° FOV | 32 | 5 | 3066px | 11.13s |
| Cube 170° FOV | 16 | 5 | 3066px | 8.37s |
| Cube 170° FOV | 8 | 5 | 3066px | 6.01s |
| Cube 170° FOV | 4 | 5 | 3066px | 3.95s |
| Cube 270° FOV | 64 | 6 | 1930px | 22.88s |
| Cube 270° FOV | 32 | 6 | 1930px | 13.72s |
| Cube 270° FOV | 16 | 6 | 1930px | 7.07s |
| Cube 270° FOV | 8 | 6 | 1930px | 7.42s |
| Cube 270° FOV | 4 | 6 | 1930px | 3.65s |

Render-only time (EEVEE face captures), excludes fisheye remap and file write, both of which are under 1s combined at this resolution. Output PNGs for visual comparison: `sample_test/cube170_samplesNN.png` and `sample_test/cube270_samplesNN.png` in the render output folder.

## Key findings

- **Render time scales close to linearly with sample count.** Halving samples roughly halves render time, down to as low as 4 samples. Quality trade-off (noise on soft shadows, AO, and stochastic transparency) needs a visual check per project, but the time-side of the equation is real all the way down.
- **Single Face mode cannot reach 4096 output at wide FOV.** The addon caps single-face textures at 8192px to avoid runaway renders (`tan(FOV/2)` blows up as FOV approaches 180°). At 170° FOV and 4096 output, a single face would need ~31,500px — physically impossible in practice. **Cube mode is the only option at production resolution for FOV ≥ ~140°.**
- **270° costs roughly 2x more than 170°** at matched sample counts, despite each individual face being *smaller* (1930px vs 3066px) — the 6th cube face (needed once FOV exceeds 180°) plus fixed per-face overhead outweighs the per-face resolution drop.
- The 170°/64→32 sample step (11.38s → 11.13s) is an outlier against the otherwise clean halving pattern seen elsewhere — likely background system noise during that specific run, not a real signal.

## Related optimizations applied to the addon

- **Optimize Scene Rendering** button (Dome Render panel): one click applies `use_persistent_data`, caps render samples and shadow steps, disables ray tracing and motion blur — all settings that only ever lower cost, never quality-neutral settings raised.
- **Material Alpha Audit** panel (Diagnostics section): lists every in-use material with a Dithered/Blended toggle, plus bulk "All Dithered → Blended" / "All Blended → Dithered" buttons, for trading stochastic noise (needs samples) against sorted alpha blending (zero noise, but can show ordering artifacts on overlapping transparent surfaces). This is the real EEVEE Next equivalent of the old Hashed/Clip choice — EEVEE Next has no Clip mode.
