"""
Fisheye projection and cube-face remap.

This is the Blender port of the projection math in pfc Dome Tools
(com.pfc.dome-tools, DomemasterInclude.cginc). The relevant original is
UVToDirection(), an equidistant angular fisheye:

    uv2   = uv * 2 - 1
    phi   = atan2(uv2.y, uv2.x)
    theta = length(uv2) * 0.5 * targetAngleRad     <- full FOV, not half
    dir   = (sin t * cos p, cos t, sin t * sin p)  <- Unity, Y-up

Two things change in Blender:

  * Axis convention. Unity is Y-up left-handed; Blender is Z-up right-handed
    and a camera looks down its local -Z. We build the direction in CAMERA
    LOCAL space with the dome axis on -Z, so the centre of the fisheye disc
    is whatever the camera is pointed at. That composes directly with the
    camera matrix and behaves like every other Blender camera.

  * No cubemap sampler. Blender's gpu module has no cube texture type, so the
    six faces are bound as six 2D textures and face selection is done in the
    shader by projecting into each face basis.

GetDebugStretch() is ported verbatim in DEBUG_STRETCH_GLSL.
"""

import math

import numpy as np

# --------------------------------------------------------------------------- #
# Face definitions                                                             #
# --------------------------------------------------------------------------- #
# Camera looks down local -Z. Each entry is (name, euler_xyz_radians) applied
# to the base camera matrix so the temp camera's -Z points along the face axis.
#
# Order matters: index 0..4 covers a hemisphere (FOV <= 180), index 5 (back)
# is only needed above 180.
FACE_DEFS = (
    ("forward", (0.0, 0.0, 0.0)),                       # -Z
    ("right", (0.0, -math.pi / 2, 0.0)),                # +X
    ("left", (0.0, math.pi / 2, 0.0)),                  # -X
    ("up", (math.pi / 2, 0.0, 0.0)),                    # +Y
    ("down", (-math.pi / 2, 0.0, 0.0)),                 # -Y
    ("back", (0.0, math.pi, 0.0)),                      # +Z
)

# Transposed face rotations: dome-local direction -> face-camera space.
# Derived from FACE_DEFS; kept explicit so the GLSL and NumPy paths agree.
#   forward: ( d.x,  d.y,  d.z)
#   right:   ( d.z,  d.y, -d.x)
#   left:    (-d.z,  d.y,  d.x)
#   up:      ( d.x,  d.z, -d.y)
#   down:    ( d.x, -d.z,  d.y)
#   back:    (-d.x,  d.y, -d.z)
_FACE_PERM = (
    ((0, 1), (1, 1), (2, 1)),
    ((2, 1), (1, 1), (0, -1)),
    ((2, -1), (1, 1), (0, 1)),
    ((0, 1), (2, 1), (1, -1)),
    ((0, 1), (2, -1), (1, 1)),
    ((0, -1), (1, 1), (2, -1)),
)


# --------------------------------------------------------------------------- #
# Face planning: how many perspective renders, and how wide is each            #
# --------------------------------------------------------------------------- #
#
# Below 180 degrees a single wide perspective face can cover the whole disc,
# because a square face of FOV F covers every direction with zenith angle
# <= F/2. That is a genuinely exact remap -- unlike the pfc single-pass mode,
# which re-projects a flat render as though the scene were painted on the dome
# surface and is therefore only correct for content at infinity. Here we sample
# real rays of the real scene; the only thing that changes is how many pixels
# the source needs.
#
# It costs resolution, because a perspective face concentrates pixels towards
# its edges (density ~ sec^2) while the fisheye output wants them uniform. The
# source must therefore be sized for its worst-sampled point, the centre:
#
#      1 face at  90 deg -> 1.27x output res ->  1.6 N^2 pixels
#      1 face at 120 deg -> 1.65x            ->  2.7 N^2
#      1 face at 135 deg -> 2.05x            ->  4.2 N^2   <- 5-face costs 4.4
#      1 face at 150 deg -> 2.85x            ->  8.1 N^2
#      1 face at 170 deg -> 7.70x            -> 59.4 N^2
#
# so which wins depends on what you are bound by:
#
#   * The **final render** is fill bound, so it should switch to a cube once
#     single-face pixels exceed 5-face pixels -- around 137 degrees.
#   * The **live preview** is submission bound (measured: a face costs the same
#     2.2 ms at 256 px as at 1024 px), so one big draw beats five small ones
#     well past that. Only the texture budget limits it.
#
# When a single face is used there are no seams at all, which means screen
# space effects -- SSR, ambient occlusion, bloom, depth of field, motion blur,
# volumetrics -- come out correct instead of discontinuous across face joins.
# That is usually a bigger quality win than the resolution cost.

SINGLE_FACE_CEILING = 170.0        # tan(F/2) runs away past this
MAX_SINGLE_FACE_PX = 8192          # refuse absurd single-face textures
_SINGLE_MARGIN_DEG = 2.0           # keeps the rim off the exact face edge

# Cost model, measured on an RTX 4080 at Material Preview shading, with a GPU
# sync (texture read) after each draw:
#
#      512 px ->   5.0 ms        3072 px ->  65.6 ms
#     1024 px ->   7.6 ms        4096 px -> 115.0 ms
#     2048 px ->  33.6 ms        6144 px -> 309.4 ms
#
# IMPORTANT: an earlier version of this file used a threshold derived from a
# benchmark taken WITHOUT forcing completion. That measured submission time
# only and appeared flat at ~2.2 ms from 256 px to 1024 px, which led to the
# false conclusion that face resolution was free and that the preview could
# use a single face up to 160 degrees. It cannot: at 160 degrees a single face
# needs ~4.5x the output resolution, and the fill cost dominates completely.
#
# Fitting cost = fixed + perMegapixel * MPix to the numbers above. Only the
# ratio matters, since these are used to compare two plans, not to predict
# absolute time.
_DRAW_FIXED_MS = 4.0
_DRAW_PER_MPIX_MS = 7.0


# --------------------------------------------------------------------------- #
# Asymmetric half faces                                                        #
# --------------------------------------------------------------------------- #
# For a fisheye of 180 degrees or less every needed direction has zenith angle
# <= 90, so d.z <= 0 in camera-local space. Look at what each side face's
# transform does with that:
#
#     right  c = ( d.z,  d.y, -d.x)   -> c.x = d.z <= 0   left half only
#     left   c = (-d.z,  d.y,  d.x)   -> c.x = -d.z >= 0  right half only
#     up     c = ( d.x,  d.z, -d.y)   -> c.y = d.z <= 0   bottom half only
#     down   c = ( d.x, -d.z,  d.y)   -> c.y = -d.z >= 0  top half only
#
# So exactly half of each side face is never sampled. Rendering only the used
# half turns 5 full faces into 1 + 4 x 0.5 = about 3 faces' worth of pixels,
# a ~39% saving. The forward face is fully used, and the rear face (above 180)
# is not halvable, so this only applies at 180 and below.
#
# The kept region reaches a small margin past the halfway line so that bilinear
# filtering near the boundary never samples outside the rendered area.
#
# The margin is quantised to a whole pixel: pick the kept pixel count first,
# then derive the exact ndc boundary from it. Otherwise the render border and
# the shader's uv mapping would disagree by a fraction of a pixel and leave a
# seam.

HALF_MARGIN = 0.04                 # desired ndc margin past the halfway line


def half_margin_for(face_res, desired=HALF_MARGIN):
    """Return (margin_in_ndc, kept_pixels) with the boundary on a pixel edge."""
    kept = int(round(face_res * (1.0 + desired) * 0.5))
    kept = max(2, min(kept, face_res))
    return (2.0 * kept / float(face_res)) - 1.0, kept


def half_applicable(fisheye_fov_deg, enabled, kind):
    return bool(enabled) and kind == 'cube' and fisheye_fov_deg <= 180.0 + 1e-6


def face_rect_ndc(index, margin):
    """
    Kept region of face `index` in full-face ndc, as (x0, x1, y0, y1).

    margin < 0 disables halving.
    """
    if margin < 0.0 or index == 0 or index == 5:
        return (-1.0, 1.0, -1.0, 1.0)
    if index == 1:
        return (-1.0, margin, -1.0, 1.0)      # right
    if index == 2:
        return (-margin, 1.0, -1.0, 1.0)      # left
    if index == 3:
        return (-1.0, 1.0, -1.0, margin)      # up
    return (-1.0, 1.0, -margin, 1.0)          # down


def face_pixels(index, face_res, margin):
    """Texture size for one face, honouring halving."""
    x0, x1, y0, y1 = face_rect_ndc(index, margin)
    w = max(2, int(round(face_res * (x1 - x0) * 0.5)))
    h = max(2, int(round(face_res * (y1 - y0) * 0.5)))
    return w, h


def plan_cost(num_faces, face_px, margin=-1.0):
    """Relative cost estimate for a face layout."""
    full = (face_px * face_px) / 1.0e6
    total = 0.0
    for i in range(num_faces):
        x0, x1, y0, y1 = face_rect_ndc(i, margin)
        frac = ((x1 - x0) * 0.5) * ((y1 - y0) * 0.5)
        total += _DRAW_FIXED_MS + _DRAW_PER_MPIX_MS * full * frac
    return total


def _cube_spec(fov, overscan_deg, out_res, half_fish):
    num = 6 if fov > 180.0 + 1e-6 else 5
    face_fov_rad = math.radians(90.0 + 2.0 * max(0.0, overscan_deg))
    px = max(64, int(round(out_res * math.tan(face_fov_rad * 0.5) / half_fish)))
    return num, face_fov_rad, px


def _single_spec(fov, out_res, half_fish):
    if fov > SINGLE_FACE_CEILING:
        return None
    face_fov_rad = math.radians(min(fov + _SINGLE_MARGIN_DEG, SINGLE_FACE_CEILING))
    px = max(64, int(round(out_res * math.tan(face_fov_rad * 0.5) / half_fish)))
    if px > MAX_SINGLE_FACE_PX:
        return None
    return 1, face_fov_rad, px


def face_plan(fisheye_fov_deg, overscan_deg, mode='AUTO', out_res=1024,
              half_faces=True):
    """
    Decide the face layout by estimated cost, not by a fixed FOV threshold.

    A single wide face is seam-free and needs one draw, but its resolution
    demand grows as tan(FOV/2): 1.65x output at 120 degrees, 2.9x at 150,
    4.5x at 160. Since cost is dominated by fill above ~1024 px, the crossover
    depends on the output resolution as well as the FOV, so both candidate
    plans are costed and the cheaper one wins.

    Returns (num_faces, face_fov_radians, kind), kind in {'single', 'cube'}.
    """
    fov = float(fisheye_fov_deg)
    half_fish = math.radians(max(fov, 1e-3)) * 0.5

    cube_n, cube_fov, cube_px = _cube_spec(fov, overscan_deg, out_res, half_fish)
    cube = (cube_n, cube_fov, 'cube')

    single_spec = _single_spec(fov, out_res, half_fish)
    if mode == 'CUBE' or single_spec is None:
        return cube
    single_n, single_fov, single_px = single_spec
    single = (1, single_fov, 'single')
    if mode == 'SINGLE':
        return single

    # Cost the cube with halving applied, since that is what it will actually
    # render -- otherwise the comparison would understate it.
    cube_mf = -1.0
    if half_applicable(fov, half_faces, 'cube'):
        cube_mf, _kept = half_margin_for(cube_px)
    return (single if plan_cost(1, single_px) < plan_cost(cube_n, cube_px, cube_mf)
            else cube)


def face_count(fisheye_fov_deg):
    """Cube-only face count. Kept for callers that do not plan."""
    return 6 if fisheye_fov_deg > 180.0 + 1e-6 else 5


def face_fov(overscan_deg):
    """Cube face FOV in radians, including overscan on both sides."""
    return math.radians(90.0 + 2.0 * max(0.0, overscan_deg))


def face_scale_factor(face_fov_rad):
    """1/tan(faceFov/2): converts a face-space slope into normalised device coords."""
    return 1.0 / math.tan(face_fov_rad * 0.5)


def optimal_face_scale(fisheye_fov_deg, face_fov_rad):
    """
    Face resolution (as a multiple of output resolution) that makes the centre
    of the face sample the output exactly 1:1.

    Angular resolution at the centre of a perspective face is
        dPixel/dTheta = (F/2) / tan(faceFov/2)
    and for an equidistant fisheye output it is
        dPixel/dTheta = (N/2) / halfFov
    Setting them equal:
        F = N * tan(faceFov/2) / halfFov

    The centre is the worst-sampled point; everything towards the edges is
    oversampled. So this is the smallest face that never undersamples.

    For a 180 degree dome on the 5-face cube this gives 0.637 with no overscan,
    rising to 0.707 at the default 3 degrees. Measured against the stretch
    readout, 0.707 is exactly where the disc centre turns green.
    """
    half_fish = math.radians(max(fisheye_fov_deg, 1e-3)) * 0.5
    return math.tan(face_fov_rad * 0.5) / half_fish


def build_rotation(image_rotation_deg, dome_tilt_deg, flip_horizontal):
    """
    Compose the 3x3 applied to each sampling direction, as three row vectors.

    Order is  R_tilt @ R_roll @ M_flip  -- flip first so it mirrors the disc
    rather than the tilt axis.
    """
    roll = math.radians(image_rotation_deg)
    tilt = math.radians(dome_tilt_deg)

    cr, sr = math.cos(roll), math.sin(roll)
    ct, st = math.cos(tilt), math.sin(tilt)

    # Roll about the dome axis (camera local Z).
    r_roll = np.array(
        [[cr, -sr, 0.0],
         [sr, cr, 0.0],
         [0.0, 0.0, 1.0]], dtype=np.float64)

    # Tilt about camera local X.
    r_tilt = np.array(
        [[1.0, 0.0, 0.0],
         [0.0, ct, -st],
         [0.0, st, ct]], dtype=np.float64)

    m_flip = np.diag([-1.0, 1.0, 1.0]) if flip_horizontal else np.eye(3)

    m = r_tilt @ r_roll @ m_flip
    return [tuple(float(v) for v in row) for row in m]


# --------------------------------------------------------------------------- #
# GLSL                                                                         #
# --------------------------------------------------------------------------- #
# Blender 5.x removed direct GPUShader(vertexcode, fragcode) construction --
# "cannot create 'GPUShader' instances". Shaders are declared through
# GPUShaderCreateInfo instead, which supplies the in/out/uniform declarations,
# so the sources below are bodies only.
#
# Caution when editing: a push constant that the GLSL compiler can prove has no
# effect on the output is stripped, and uniform_float() then raises
# "uniform not found". _set_uniform() below tolerates that.

VERTEX_SOURCE = """
void main()
{
    uv = texco;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

FRAGMENT_SOURCE = """
vec3 face_transform(int i, vec3 d)
{
    if (i == 0) return vec3( d.x,  d.y,  d.z);
    if (i == 1) return vec3( d.z,  d.y, -d.x);
    if (i == 2) return vec3(-d.z,  d.y,  d.x);
    if (i == 3) return vec3( d.x,  d.z, -d.y);
    if (i == 4) return vec3( d.x, -d.z,  d.y);
    return             vec3(-d.x,  d.y, -d.z);
}

// Maps full-face ndc into the actually-rendered sub-rectangle of a face:
// returns (u_scale, u_offset, v_scale, v_offset). u_half_mf < 0 = no halving.
vec4 face_rect(int i)
{
    float m = u_half_mf;
    if (m < 0.0 || i == 0 || i == 5) {
        return vec4(0.5, 0.5, 0.5, 0.5);
    }
    float s = 1.0 / (1.0 + m);
    if (i == 1) return vec4(s, s, 0.5, 0.5);        // right: x in [-1,  m]
    if (i == 2) return vec4(s, m * s, 0.5, 0.5);    // left:  x in [-m,  1]
    if (i == 3) return vec4(0.5, 0.5, s, s);        // up:    y in [-1,  m]
    return             vec4(0.5, 0.5, s, m * s);    // down:  y in [-m,  1]
}

vec3 sample_face(int i, vec2 t)
{
    if (i == 0) return texture(f0, t).rgb;
    if (i == 1) return texture(f1, t).rgb;
    if (i == 2) return texture(f2, t).rgb;
    if (i == 3) return texture(f3, t).rgb;
    if (i == 4) return texture(f4, t).rgb;
    return             texture(f5, t).rgb;
}

float inv_lerp(float a, float b, float v)
{
    return (v - a) / (b - a);
}

// Direct port of GetDebugStretch() from DomemasterInclude.cginc.
vec4 debug_stretch(vec2 face_uv)
{
    vec2 tc = face_uv * u_face_res;
    vec2 dx = dFdx(tc);
    vec2 dy = dFdy(tc);
    float delta_max_sqr = max(dot(dx, dx), dot(dy, dy));
    float stretch = sqrt(delta_max_sqr);

    float under = clamp(1.0 / u_allowed_under - stretch, 0.0, 1.0);
    float over  = clamp(stretch - 1.0, 0.0, 1.0);
    float pr    = u_perfect_range;
    float perfect = inv_lerp(1.0 - pr, 1.0 + pr, stretch)
                  * inv_lerp(1.0 + pr, 1.0 - pr, stretch) * 4.0;

    // The Unity original leans on the display render target clamping this
    // product. Ours is RGBA32F and does not clamp, so a stretch value far from
    // 1.0 leaks a large negative into the green channel. Clamp explicitly.
    perfect = clamp(perfect, 0.0, 1.0);

    return mix(vec4(0.0, 0.0, 0.0, 1.0), vec4(1.0),
               vec4(under, perfect, over, 1.0));
}

void main()
{
    vec2 p = uv * 2.0 - 1.0;
    float len = length(p);
    if (len > 1.0) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // --- UVToDirection, in Blender camera-local space (dome axis on -Z) ---
    float phi   = atan(p.y, p.x);
    float theta = len * u_half_fov;
    vec3 d = vec3(sin(theta) * cos(phi),
                  sin(theta) * sin(phi),
                  -cos(theta));

    d = vec3(dot(u_rot0, d), dot(u_rot1, d), dot(u_rot2, d));

    // --- gather across cube faces, cross-fading in the overscan band ---
    vec3 acc = vec3(0.0);
    float wsum = 0.0;
    vec2 best_uv = vec2(0.5);
    float best_w = -1.0;

    for (int i = 0; i < 6; i++) {
        if (i >= u_num_faces) { break; }

        vec3 c = face_transform(i, d);
        float behind = -c.z;
        if (behind <= 1e-6) { continue; }

        vec2 n = (c.xy / behind) * u_face_s;
        float m = max(abs(n.x), abs(n.y));
        if (m > 1.0) { continue; }

        // Map into the rendered sub-rectangle; half faces only cover part of
        // the full-face ndc square, so this also rejects the unrendered half.
        vec4 R = face_rect(i);
        vec2 fuv = vec2(n.x * R.x + R.y, n.y * R.z + R.w);
        if (fuv.x < 0.0 || fuv.x > 1.0 || fuv.y < 0.0 || fuv.y > 1.0) { continue; }

        float w = 1.0 - smoothstep(u_core_s, 1.0, m);
        w = max(w, 1e-4);

        acc += sample_face(i, fuv) * w;
        wsum += w;

        if (w > best_w) { best_w = w; best_uv = fuv; }
    }

    if (u_debug == 1) {
        fragColor = debug_stretch(best_uv);
        return;
    }

    vec3 col = (wsum > 0.0) ? acc / wsum : vec3(0.0);
    fragColor = vec4(col, 1.0);
}
"""


# --------------------------------------------------------------------------- #
# GPU path                                                                     #
# --------------------------------------------------------------------------- #
_PUSH_FLOATS = ("u_half_fov", "u_face_s", "u_core_s", "u_face_res",
                "u_allowed_under", "u_perfect_range", "u_half_mf")
_PUSH_INTS = ("u_num_faces", "u_debug")
_PUSH_VEC3 = ("u_rot0", "u_rot1", "u_rot2")


def build_shader():
    """Compile the remap shader via GPUShaderCreateInfo (Blender 4.0+/5.x)."""
    import gpu

    iface = gpu.types.GPUStageInterfaceInfo("dme_remap_iface")
    iface.smooth('VEC2', "uv")

    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_in(1, 'VEC2', "texco")
    info.vertex_out(iface)
    info.fragment_out(0, 'VEC4', "fragColor")

    for i in range(6):
        info.sampler(i, 'FLOAT_2D', "f%d" % i)
    for name in _PUSH_FLOATS:
        info.push_constant('FLOAT', name)
    for name in _PUSH_INTS:
        info.push_constant('INT', name)
    for name in _PUSH_VEC3:
        info.push_constant('VEC3', name)

    info.vertex_source(VERTEX_SOURCE)
    info.fragment_source(FRAGMENT_SOURCE)
    return gpu.shader.create_from_info(info)


def _set_uniform(shader, kind, name, value):
    """Set a uniform, ignoring ones the compiler optimised away."""
    try:
        if kind == 'f':
            shader.uniform_float(name, value)
        elif kind == 'i':
            shader.uniform_int(name, value)
        else:
            shader.uniform_sampler(name, value)
    except ValueError as exc:
        if "not found" not in str(exc):
            raise


def remap_gpu(faces, out_res, params):
    """
    faces:   list of (h, w, 4) float32 arrays, bottom-up, in FACE_DEFS order
    out_res: square output resolution
    params:  dict from make_params()

    Returns (out_res, out_res, 4) float32, bottom-up. Raises on any GPU failure
    so the caller can fall back to remap_cpu.
    """
    import gpu
    from gpu_extras.batch import batch_for_shader

    shader = build_shader()

    textures = []
    for arr in faces:
        h, w = arr.shape[0], arr.shape[1]
        flat = np.ascontiguousarray(arr, dtype=np.float32).ravel()
        buf = gpu.types.Buffer('FLOAT', flat.size, flat)
        textures.append(gpu.types.GPUTexture((w, h), format='RGBA32F', data=buf))

    # Pad to six bindings; unused slots reuse the first texture.
    while len(textures) < 6:
        textures.append(textures[0])

    offscreen = gpu.types.GPUOffScreen(out_res, out_res, format='RGBA32F')
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 1.0))

            shader.bind()
            for i in range(6):
                _set_uniform(shader, 's', "f%d" % i, textures[i])

            _set_uniform(shader, 'f', "u_half_fov", params["half_fov"])
            _set_uniform(shader, 'f', "u_face_s", params["face_s"])
            _set_uniform(shader, 'f', "u_core_s", params["core_s"])
            _set_uniform(shader, 'f', "u_face_res", float(params["face_res"]))
            _set_uniform(shader, 'f', "u_allowed_under", params["allowed_under"])
            _set_uniform(shader, 'f', "u_perfect_range", params["perfect_range"])
            _set_uniform(shader, 'f', "u_half_mf", params["half_mf"])
            _set_uniform(shader, 'i', "u_num_faces", params["num_faces"])
            _set_uniform(shader, 'i', "u_debug", 1 if params["debug"] else 0)
            _set_uniform(shader, 'f', "u_rot0", params["rot"][0])
            _set_uniform(shader, 'f', "u_rot1", params["rot"][1])
            _set_uniform(shader, 'f', "u_rot2", params["rot"][2])

            batch = batch_for_shader(
                shader, 'TRI_FAN',
                {"pos": ((-1, -1), (1, -1), (1, 1), (-1, 1)),
                 "texco": ((0, 0), (1, 0), (1, 1), (0, 1))},
            )
            batch.draw(shader)

        out = np.array(offscreen.texture_color.read(), dtype=np.float32)
    finally:
        offscreen.free()

    return out.reshape(out_res, out_res, 4)


# --------------------------------------------------------------------------- #
# NumPy fallback                                                               #
# --------------------------------------------------------------------------- #
def remap_cpu(faces, out_res, params):
    """Same math as the shader, vectorised. Used when the GPU path is unavailable."""
    n = out_res
    axis = (np.arange(n, dtype=np.float32) + 0.5) / n * 2.0 - 1.0
    px, py = np.meshgrid(axis, axis)          # py row 0 = bottom, matches GL

    length = np.sqrt(px * px + py * py)
    inside = length <= 1.0

    phi = np.arctan2(py, px)
    theta = length * params["half_fov"]
    st, ct = np.sin(theta), np.cos(theta)

    d = np.stack([st * np.cos(phi), st * np.sin(phi), -ct], axis=-1)

    rot = np.array(params["rot"], dtype=np.float32)
    d = d @ rot.T

    acc = np.zeros((n, n, 3), dtype=np.float32)
    wsum = np.zeros((n, n), dtype=np.float32)

    face_s = params["face_s"]
    core_s = params["core_s"]

    for i in range(params["num_faces"]):
        (ax, sx), (ay, sy), (az, sz) = _FACE_PERM[i]
        cx = d[..., ax] * sx
        cy = d[..., ay] * sy
        cz = d[..., az] * sz

        behind = -cz
        ok = behind > 1e-6
        safe = np.where(ok, behind, 1.0)

        nx = (cx / safe) * face_s
        ny = (cy / safe) * face_s
        m = np.maximum(np.abs(nx), np.abs(ny))
        ok &= m <= 1.0

        # Same sub-rectangle mapping as the shader's face_rect().
        rx0, rx1, ry0, ry1 = face_rect_ndc(i, params.get("half_mf", -1.0))
        fu = (nx - rx0) / (rx1 - rx0)
        fv = (ny - ry0) / (ry1 - ry0)
        ok &= (fu >= 0.0) & (fu <= 1.0) & (fv >= 0.0) & (fv <= 1.0)

        t = np.clip((m - core_s) / max(1.0 - core_s, 1e-6), 0.0, 1.0)
        w = (1.0 - (t * t * (3.0 - 2.0 * t))).astype(np.float32)
        w = np.where(ok, np.maximum(w, 1e-4), 0.0).astype(np.float32)

        src = faces[i]
        fh, fw = src.shape[0], src.shape[1]
        u = np.clip((np.clip(fu, 0.0, 1.0) * fw).astype(np.int32), 0, fw - 1)
        v = np.clip((np.clip(fv, 0.0, 1.0) * fh).astype(np.int32), 0, fh - 1)

        acc += src[v, u, :3] * w[..., None]
        wsum += w

    safe_w = np.where(wsum > 0.0, wsum, 1.0)
    col = acc / safe_w[..., None]
    col[~inside] = 0.0

    out = np.ones((n, n, 4), dtype=np.float32)
    out[..., :3] = col
    return out


def make_params(props, face_res, plan, half_mf=-1.0):
    """
    Bundle the shader/NumPy parameters from the addon PropertyGroup.

    `plan` is the (num_faces, face_fov_rad, kind) tuple from face_plan().
    `half_mf` is the quantised half-face margin, or negative to disable.
    """
    num_faces, face_fov_rad, _kind = plan
    fov = float(props.fisheye_fov)
    face_s = face_scale_factor(face_fov_rad)
    return {
        "half_fov": math.radians(fov) * 0.5,
        "face_s": face_s,
        "core_s": min(face_s, 0.999),
        "num_faces": num_faces,
        "rot": build_rotation(props.image_rotation, props.dome_tilt,
                              props.flip_horizontal),
        "debug": bool(props.debug_stretch),
        "allowed_under": float(props.allowed_undersampling),
        "perfect_range": float(props.allowed_perfect_range),
        "face_res": int(face_res),
        "half_mf": float(half_mf),
    }


def remap(faces, out_res, params, prefer_gpu=True):
    """Try the GPU shader, fall back to NumPy. Returns (array, backend_name)."""
    if prefer_gpu:
        try:
            return remap_gpu(faces, out_res, params), "gpu"
        except Exception as exc:      # noqa: BLE001 - any GPU failure falls back
            print("[DomeMasterEEVEE] GPU remap unavailable (%s: %s), "
                  "falling back to NumPy" % (type(exc).__name__, exc))
    return remap_cpu(faces, out_res, params), "cpu"
