import os
import shutil
import time

import bpy

from . import capture, projection


def _props(context):
    return context.scene.domemastereevee_props


def plan_for(props, context='RENDER'):
    out_res = (props.preview_resolution if context == 'PREVIEW'
               else props.output_resolution)
    return projection.face_plan(props.fisheye_fov, props.overscan_deg,
                                mode=props.face_mode, out_res=out_res,
                                half_faces=props.use_half_faces)


def effective_face_scale(props, plan=None):
    if plan is None:
        plan = plan_for(props)
    if props.auto_face_scale:
        return projection.optimal_face_scale(props.fisheye_fov, plan[1])
    return props.face_scale


def _face_resolution(props, plan=None):
    scale = effective_face_scale(props, plan)
    res = max(64, int(round(props.output_resolution * scale)))
    res -= res % 2
    # A single wide face can ask for a very large texture. Clamp to what the
    # GPU will actually allocate rather than failing mid-render.
    try:
        import gpu
        limit = gpu.capabilities.max_texture_size_get()
    except Exception:
        limit = 16384
    return max(64, min(res, limit))


def _render_one_frame(context, frame, workdir):
    scene = context.scene
    props = _props(context)

    if scene.camera is None:
        raise RuntimeError("Scene has no active camera")

    scene.frame_set(frame)

    plan = plan_for(props, 'RENDER')
    num_faces, face_fov_rad, kind = plan
    face_res = _face_resolution(props, plan)

    half_mf = -1.0
    if projection.half_applicable(props.fisheye_fov, props.use_half_faces, kind):
        half_mf, _kept = projection.half_margin_for(face_res)

    arrays, paths = capture.render_faces(
        scene=scene,
        depsgraph_camera=scene.camera,
        face_res=face_res,
        face_fov_rad=face_fov_rad,
        num_faces=num_faces,
        workdir=workdir,
        frame_tag="%04d" % frame,
        report=lambda msg: print("[DomeMasterEEVEE] %s" % msg),
        half_mf=half_mf,
    )

    params = projection.make_params(props, face_res, plan, half_mf)
    pixels, backend = projection.remap(
        arrays, int(props.output_resolution), params,
        prefer_gpu=props.use_gpu_remap,
    )

    out = capture.output_path(props, scene, frame)
    capture.write_output(scene, pixels, out, props.output_format)

    if props.keep_faces:
        keep_dir = os.path.join(os.path.dirname(out), "faces")
        os.makedirs(keep_dir, exist_ok=True)
        for p in paths:
            try:
                shutil.copy2(p, os.path.join(keep_dir, os.path.basename(p)))
            except Exception:
                pass

    return out, backend, face_res, num_faces, kind


class DOMEMASTEREEVEE_OT_RenderDomeStill(bpy.types.Operator):
    """Render the current frame as a fisheye domemaster"""

    bl_idname = "domemastereevee.render_dome_still"
    bl_label = "Render Domemaster"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.scene.camera is not None

    def execute(self, context):
        props = _props(context)
        scene = context.scene
        start_frame = scene.frame_current
        workdir = capture.make_workdir()
        t0 = time.time()
        try:
            out, backend, face_res, num_faces, kind = _render_one_frame(
                context, scene.frame_current, workdir)
        except Exception as exc:      # noqa: BLE001 - surface any failure to the UI
            self.report({'ERROR'}, "Domemaster render failed: %s" % exc)
            return {'CANCELLED'}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            scene.frame_set(start_frame)

        dt = time.time() - t0
        half = ", half faces" if projection.half_applicable(
            props.fisheye_fov, props.use_half_faces, kind) else ""
        info = "%s: %d face%s @ %dpx%s -> %dpx (%s remap, %.1fs)" % (
            kind, num_faces, "" if num_faces == 1 else "s",
            face_res, half, props.output_resolution, backend, dt)
        props.last_render_info = info
        self.report({'INFO'}, "%s  %s" % (os.path.basename(out), info))
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_RenderDomeAnimation(bpy.types.Operator):
    """Render the scene frame range as a fisheye domemaster sequence"""

    bl_idname = "domemastereevee.render_dome_animation"
    bl_label = "Render Domemaster Sequence"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.scene.camera is not None

    def execute(self, context):
        scene = context.scene
        props = _props(context)
        start_frame = scene.frame_current
        workdir = capture.make_workdir()
        frames = range(scene.frame_start, scene.frame_end + 1, scene.frame_step)
        t0 = time.time()
        done = 0
        try:
            for frame in frames:
                _render_one_frame(context, frame, workdir)
                done += 1
        except Exception as exc:      # noqa: BLE001
            self.report({'ERROR'}, "Stopped after %d frame(s): %s" % (done, exc))
            return {'CANCELLED'}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            scene.frame_set(start_frame)

        dt = time.time() - t0
        props.last_render_info = "%d frames in %.1fs" % (done, dt)
        self.report({'INFO'}, "Domemaster sequence: %s" % props.last_render_info)
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_OpenOutputFolder(bpy.types.Operator):
    """Open the domemaster output folder in the system file browser"""

    bl_idname = "domemastereevee.open_output_folder"
    bl_label = "Open Output Folder"

    def execute(self, context):
        path = bpy.path.abspath(_props(context).output_dir)
        if not os.path.isdir(path):
            self.report({'WARNING'}, "Folder does not exist yet: %s" % path)
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


_CLASSES = (
    DOMEMASTEREEVEE_OT_RenderDomeStill,
    DOMEMASTEREEVEE_OT_RenderDomeAnimation,
    DOMEMASTEREEVEE_OT_OpenOutputFolder,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
