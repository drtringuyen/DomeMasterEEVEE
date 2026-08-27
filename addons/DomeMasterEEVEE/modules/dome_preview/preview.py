"""
Live dome preview.

Architecture, and why it is split in two:

  * A **timer** renders the cube faces with GPUOffScreen.draw_view3d() and
    remaps them into a result offscreen.
  * A **SpaceView3D draw handler** only blits that result into the region.

The obvious implementation puts everything in the draw handler, but that means
calling draw_view3d() with the very region currently being drawn as its
temporary target, which risks re-entrancy. Timer callbacks were verified to
have a valid GPU context in Blender 5.2, so the render can live there instead
and the draw callback stays trivial.

The whole path stays on the GPU: an offscreen's .texture_color is a GPUTexture,
so the face renders feed the remap shader directly with no CPU readback. Only
the final blit touches the screen.

Unlike the render operator this is *viewport* quality -- viewport sampling, no
final-render passes, no compositor.
"""

import math
import time

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Matrix

from ..dome_render import projection
from ..dome_render.operators import CAMERA_NAME

# --------------------------------------------------------------------------- #
# Module state                                                                 #
# --------------------------------------------------------------------------- #
_handle = None
_face_offs = []
_face_key = None            # (num_faces, face_res)
_result_off = None
_result_res = 0
_remap_shader = None
_blit_shader = None
_last_sig = None
_last_ms = 0.0
_dep_counter = 0
_rendering = False


def is_running():
    return _handle is not None


def last_ms():
    return _last_ms


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _find_view3d():
    """First 3D viewport across all windows: (window, area, space, region)."""
    wm = bpy.context.window_manager
    for win in wm.windows:
        screen = win.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return win, area, area.spaces.active, region
    return None, None, None, None


def _tag_redraw():
    wm = bpy.context.window_manager
    for win in wm.windows:
        if win.screen is None:
            continue
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _base_matrix(scene, space, props):
    """Rotation+translation the dome looks out from. Scale is stripped."""
    if props.preview_source == 'VIEWPORT':
        r3d = getattr(space, "region_3d", None)
        if r3d is None:
            return None
        m = r3d.view_matrix.inverted()
    else:
        cam = bpy.data.objects.get(CAMERA_NAME) or scene.camera
        if cam is None:
            return None
        m = cam.matrix_world
    loc, rot, _scale = m.decompose()
    return Matrix.Translation(loc) @ rot.to_matrix().to_4x4()


def _projection_matrix(face_fov_rad, near, far):
    f = 1.0 / math.tan(face_fov_rad * 0.5)
    return Matrix(((f, 0.0, 0.0, 0.0),
                   (0.0, f, 0.0, 0.0),
                   (0.0, 0.0, (far + near) / (near - far),
                    (2.0 * far * near) / (near - far)),
                   (0.0, 0.0, -1.0, 0.0)))


def _frustum_matrix(face_fov_rad, near, far, rect):
    """
    Asymmetric frustum covering only `rect` of the full face, in ndc units.

    draw_view3d has no render-border equivalent, so half faces here have to be
    done with an off-centre projection instead of by cropping.
    """
    x0, x1, y0, y1 = rect
    t = math.tan(face_fov_rad * 0.5)
    l, r = near * t * x0, near * t * x1
    b, tp = near * t * y0, near * t * y1
    return Matrix(((2.0 * near / (r - l), 0.0, (r + l) / (r - l), 0.0),
                   (0.0, 2.0 * near / (tp - b), (tp + b) / (tp - b), 0.0),
                   (0.0, 0.0, -(far + near) / (far - near),
                    -2.0 * far * near / (far - near)),
                   (0.0, 0.0, -1.0, 0.0)))


def _plan(props):
    return projection.face_plan(props.fisheye_fov, props.overscan_deg,
                                mode=props.face_mode,
                                out_res=int(props.preview_resolution),
                                half_faces=props.use_half_faces)


def _face_resolution(props, out_res, plan):
    if props.auto_face_scale:
        scale = projection.optimal_face_scale(props.fisheye_fov, plan[1])
    else:
        scale = props.face_scale
    res = max(64, int(round(out_res * scale)))
    res -= res % 2
    try:
        limit = gpu.capabilities.max_texture_size_get()
    except Exception:
        limit = 16384
    return max(64, min(res, limit))


def _ensure_resources(num_faces, face_res, out_res, half_mf):
    global _face_offs, _face_key, _result_off, _result_res, _remap_shader

    if _remap_shader is None:
        _remap_shader = projection.build_shader()

    key = (num_faces, face_res, round(half_mf, 6))
    if key != _face_key:
        _free_faces()
        _face_offs = []
        for i in range(num_faces):
            w, h = projection.face_pixels(i, face_res, half_mf)
            _face_offs.append(gpu.types.GPUOffScreen(w, h, format='RGBA16F'))
        _face_key = key

    if _result_off is None or _result_res != out_res:
        if _result_off is not None:
            _result_off.free()
        _result_off = gpu.types.GPUOffScreen(out_res, out_res, format='RGBA16F')
        _result_res = out_res


def _free_faces():
    global _face_offs, _face_key
    for off in _face_offs:
        try:
            off.free()
        except Exception:
            pass
    _face_offs = []
    _face_key = None


def _free():
    global _result_off, _result_res, _remap_shader, _last_sig
    _free_faces()
    if _result_off is not None:
        try:
            _result_off.free()
        except Exception:
            pass
    _result_off = None
    _result_res = 0
    _remap_shader = None
    _last_sig = None


def _signature(scene, props, base, out_res, face_res):
    return (
        tuple(round(v, 6) for row in base for v in row),
        round(props.fisheye_fov, 4), round(props.overscan_deg, 4),
        round(props.image_rotation, 4), round(props.dome_tilt, 4),
        bool(props.flip_horizontal), bool(props.debug_stretch),
        round(props.allowed_undersampling, 4), round(props.allowed_perfect_range, 5),
        out_res, face_res, props.preview_source, props.preview_shading,
        props.face_mode, scene.frame_current, _dep_counter,
    )


# --------------------------------------------------------------------------- #
# Render                                                                       #
# --------------------------------------------------------------------------- #
def _render():
    """Returns True when the result changed and the viewport needs a redraw."""
    global _last_sig, _last_ms, _rendering

    if _rendering:
        return False

    win, _area, space, region = _find_view3d()
    if space is None:
        return False

    scene = win.scene
    props = scene.domemastereevee_props
    base = _base_matrix(scene, space, props)
    if base is None:
        return False

    out_res = int(props.preview_resolution)
    plan = _plan(props)
    num_faces, face_fov_rad, kind = plan
    face_res = _face_resolution(props, out_res, plan)

    # Half side faces are deliberately NOT used in the preview. Measured with a
    # GPU sync, they save 3.1% at 1024 and 0.3% at 2048 here -- draw_view3d is
    # dominated by per-draw setup, not fill, so removing pixels buys nothing.
    # They do help the final render (18-33%), where the full render pipeline is
    # fill bound. Skipping them here also avoids the small screen-space-effect
    # difference that shrinking the render target introduces near the cut edge.
    half_mf = -1.0

    sig = _signature(scene, props, base, out_res, face_res) + (round(half_mf, 6),)
    if sig == _last_sig:
        return False

    _rendering = True
    try:
        _ensure_resources(num_faces, face_res, out_res, half_mf)

        t0 = time.perf_counter()
        near = max(getattr(space, "clip_start", 0.05), 1e-4)
        far = max(getattr(space, "clip_end", 1000.0), near + 1.0)
        view_layer = bpy.context.view_layer

        # draw_view3d takes its shading from the space, so an override means
        # flipping the space for the duration of the face draws. Safe because
        # this runs on a timer, between viewport draws, and is restored before
        # returning -- the main viewport never sees the changed value.
        shading = space.shading
        saved_shading = None
        if props.preview_shading != 'FOLLOW' and shading.type != props.preview_shading:
            saved_shading = shading.type
            shading.type = props.preview_shading
        try:
            for i in range(num_faces):
                rot = Euler(projection.FACE_DEFS[i][1], 'XYZ').to_matrix().to_4x4()
                rect = projection.face_rect_ndc(i, half_mf)
                proj = _frustum_matrix(face_fov_rad, near, far, rect)
                _face_offs[i].draw_view3d(
                    scene, view_layer, space, region,
                    (base @ rot).inverted(), proj,
                    do_color_management=False,
                )
        finally:
            if saved_shading is not None:
                shading.type = saved_shading

        params = projection.make_params(props, face_res, plan, half_mf)
        sh = _remap_shader

        with _result_off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 1.0))
            sh.bind()
            for i in range(6):
                tex = _face_offs[min(i, num_faces - 1)].texture_color
                projection._set_uniform(sh, 's', "f%d" % i, tex)
            projection._set_uniform(sh, 'f', "u_half_fov", params["half_fov"])
            projection._set_uniform(sh, 'f', "u_face_s", params["face_s"])
            projection._set_uniform(sh, 'f', "u_core_s", params["core_s"])
            projection._set_uniform(sh, 'f', "u_face_res", float(face_res))
            projection._set_uniform(sh, 'f', "u_allowed_under", params["allowed_under"])
            projection._set_uniform(sh, 'f', "u_perfect_range", params["perfect_range"])
            projection._set_uniform(sh, 'f', "u_half_mf", params["half_mf"])
            projection._set_uniform(sh, 'i', "u_num_faces", num_faces)
            projection._set_uniform(sh, 'i', "u_debug", 1 if params["debug"] else 0)
            projection._set_uniform(sh, 'f', "u_rot0", params["rot"][0])
            projection._set_uniform(sh, 'f', "u_rot1", params["rot"][1])
            projection._set_uniform(sh, 'f', "u_rot2", params["rot"][2])
            batch_for_shader(
                sh, 'TRI_FAN',
                {"pos": ((-1, -1), (1, -1), (1, 1), (-1, 1)),
                 "texco": ((0, 0), (1, 0), (1, 1), (0, 1))},
            ).draw(sh)

        _last_ms = (time.perf_counter() - t0) * 1000.0
        _last_sig = sig
        props.preview_info = "%s: %d face%s @ %dpx%s -> %dpx, %.1f ms" % (
            kind, num_faces, "" if num_faces == 1 else "s", face_res,
            " half" if half_mf >= 0.0 else "", out_res, _last_ms)
        return True
    finally:
        _rendering = False


# --------------------------------------------------------------------------- #
# Draw (blit only)                                                             #
# --------------------------------------------------------------------------- #
def _camera_frame_rect(context, region):
    """
    Bounding rect of the camera frame in region pixels, or None if the viewport
    is not looking through the camera.

    Uses camera.data.view_frame() projected through the region, so it tracks
    camera zoom, pan and any lens/shift changes for free.
    """
    r3d = context.region_data
    if r3d is None or r3d.view_perspective != 'CAMERA':
        return None
    scene = context.scene
    cam = scene.camera
    if cam is None or cam.type != 'CAMERA':
        return None
    try:
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        mw = cam.matrix_world
        pts = []
        for corner in cam.data.view_frame(scene=scene):
            co = location_3d_to_region_2d(region, r3d, mw @ corner)
            if co is None:
                return None
            pts.append(co)
    except Exception:
        return None
    if len(pts) < 4:
        return None
    xs = [pt.x for pt in pts]
    ys = [pt.y for pt in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if (x1 - x0) < 8 or (y1 - y0) < 8:
        return None
    return x0, y0, x1, y1


def _blit(x0, y0, x1, y1):
    global _blit_shader
    if _blit_shader is None:
        _blit_shader = gpu.shader.from_builtin('IMAGE')

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')
    try:
        _blit_shader.bind()
        _blit_shader.uniform_sampler("image", _result_off.texture_color)
        batch_for_shader(
            _blit_shader, 'TRI_FAN',
            {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
             "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))},
        ).draw(_blit_shader)
    finally:
        gpu.state.blend_set('NONE')


def _draw():
    if _result_off is None:
        return
    context = bpy.context
    scene = context.scene
    props = getattr(scene, "domemastereevee_props", None)
    if props is None or not props.preview_enabled:
        return
    region = context.region
    if region is None:
        return

    w, h = region.width, region.height

    # The WINDOW region extends underneath the overlapping toolbar and side
    # panel, so a naive corner placement draws behind them. Inset by whatever
    # those regions actually occupy right now.
    inset_l = inset_r = inset_t = inset_b = 0
    area = context.area
    if area is not None:
        for r in area.regions:
            if r.width <= 1 or r.height <= 1:
                continue
            if r.type == 'TOOLS':
                inset_l = max(inset_l, r.width)
            elif r.type == 'UI':
                inset_r = max(inset_r, r.width)
            elif r.type == 'HEADER':
                inset_t = max(inset_t, r.height)
            elif r.type == 'ASSET_SHELF':
                inset_b = max(inset_b, r.height)

    placement = props.preview_placement
    if placement == 'CAMERA_FRAME' and not props.using_dome_camera:
        # The camera frame only lines up with the dome projection when the
        # dome camera is actually the one being looked through. Otherwise the
        # frame belongs to an unrelated camera, so fall back to the corner.
        placement = 'CORNER'
    if placement == 'CAMERA_FRAME':
        rect = _camera_frame_rect(context, region)
        if rect is None:
            placement = 'CORNER'          # not in camera view
        else:
            fx0, fy0, fx1, fy1 = rect
            size = min(fx1 - fx0, fy1 - fy0)
            x0 = fx0 + (fx1 - fx0 - size) * 0.5
            y0 = fy0 + (fy1 - fy0 - size) * 0.5
            _blit(x0, y0, x0 + size, y0 + size)
            return

    if placement == 'FULL':
        size = min(w, h)
        x0, y0 = (w - size) // 2, (h - size) // 2
    else:
        avail_w = max(64, w - inset_l - inset_r)
        avail_h = max(64, h - inset_t - inset_b)
        size = max(64, int(min(avail_w, avail_h) * props.preview_corner_scale))
        margin = 16
        corner = props.preview_corner
        if 'LEFT' in corner:
            x0 = inset_l + margin
        else:
            x0 = w - inset_r - size - margin
        if 'BOTTOM' in corner:
            y0 = inset_b + margin
        else:
            y0 = h - inset_t - size - margin
    _blit(x0, y0, x0 + size, y0 + size)


# --------------------------------------------------------------------------- #
# Timer + handlers                                                             #
# --------------------------------------------------------------------------- #
def _tick():
    scene = bpy.context.scene
    props = getattr(scene, "domemastereevee_props", None)
    if props is None or not props.preview_enabled:
        return None                      # unregister
    try:
        if _render():
            _tag_redraw()
    except Exception as exc:             # noqa: BLE001 - never kill the timer
        print("[DomeMasterEEVEE] preview error: %s: %s" % (type(exc).__name__, exc))
        return 1.0
    return 1.0 / max(1, props.preview_fps)


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph=None):
    global _dep_counter
    _dep_counter += 1


def start():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw, (), 'WINDOW', 'POST_PIXEL')
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.05)
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    if _on_depsgraph not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_on_depsgraph)
    _tag_redraw()


def stop():
    global _handle
    if _handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        except Exception:
            pass
        _handle = None
    if bpy.app.timers.is_registered(_tick):
        try:
            bpy.app.timers.unregister(_tick)
        except Exception:
            pass
    for lst in (bpy.app.handlers.depsgraph_update_post,
                bpy.app.handlers.frame_change_post):
        if _on_depsgraph in lst:
            lst.remove(_on_depsgraph)
    _free()
    _tag_redraw()


def invalidate():
    """Force the next tick to re-render even if nothing looks changed."""
    global _last_sig
    _last_sig = None
