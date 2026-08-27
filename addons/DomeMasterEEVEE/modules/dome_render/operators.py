import math
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


CAMERA_NAME = "Camera-DOME-Master"


def _remember_original_camera(props, scene):
    """Snapshot the camera/resolution in place before switching to the dome camera."""
    r = scene.render
    props.prev_camera = scene.camera
    props.prev_resolution_x = r.resolution_x
    props.prev_resolution_y = r.resolution_y


class DOMEMASTEREEVEE_OT_OptimizeSceneRendering(bpy.types.Operator):
    """Create the dome master camera (from the selected camera's position,
    or the 3D cursor if none is selected), point it straight up, make it the
    scene camera, set it to orthographic with a size-6 view and full
    passepartout, match the render resolution to the domemaster Output
    Resolution, and then apply the usual render-time optimizations: enable
    Persistent Data (avoids re-uploading geometry/BVH for each of the 5 cube
    faces), cap render samples, disable Ray Tracing, cap shadow step count,
    and turn off Motion Blur"""

    bl_idname = "domemastereevee.optimize_scene_rendering"
    bl_label = "Setup Camera & Optimize Scene"
    bl_options = {'REGISTER', 'UNDO'}

    max_samples: bpy.props.IntProperty(
        name="Max Render Samples", default=32, min=1, max=4096,
        description="Render samples are capped to this value if higher")
    max_shadow_steps: bpy.props.IntProperty(
        name="Max Shadow Steps", default=4, min=1, max=32,
        description="Shadow step count is capped to this value if higher")

    def execute(self, context):
        scene = context.scene
        props = _props(context)
        eevee = scene.eevee
        r = scene.render
        changes = []

        active = context.view_layer.objects.active
        selected_cams = [o for o in context.selected_objects if o.type == 'CAMERA']
        if active is not None and active.type == 'CAMERA' and active in selected_cams:
            position = active.matrix_world.translation.copy()
        elif selected_cams:
            position = selected_cams[0].matrix_world.translation.copy()
        else:
            position = scene.cursor.location.copy()

        main_cam = scene.camera
        target_collections = list(main_cam.users_collection) if main_cam is not None else []
        if not target_collections:
            target_collections = [context.collection]

        if scene.camera is None or scene.camera.name != CAMERA_NAME:
            _remember_original_camera(props, scene)

        existing = bpy.data.objects.get(CAMERA_NAME)
        if existing is not None:
            old_data = existing.data
            bpy.data.objects.remove(existing, do_unlink=True)
            if old_data is not None and old_data.users == 0:
                bpy.data.cameras.remove(old_data)

        cam_data = bpy.data.cameras.new(CAMERA_NAME)
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = 6.0
        cam_data.passepartout_alpha = 1.0

        cam_obj = bpy.data.objects.new(CAMERA_NAME, cam_data)
        cam_obj.location = position
        cam_obj.rotation_euler = (math.pi, 0.0, 0.0)
        for coll in target_collections:
            coll.objects.link(cam_obj)

        scene.camera = cam_obj
        props.using_dome_camera = True
        changes.append("Created '%s' (ortho, size 6, facing up)" % CAMERA_NAME)

        if r.resolution_x != props.output_resolution or r.resolution_y != props.output_resolution:
            r.resolution_x = props.output_resolution
            r.resolution_y = props.output_resolution
            changes.append("Render Resolution -> %dx%d"
                            % (props.output_resolution, props.output_resolution))

        if not r.use_persistent_data:
            r.use_persistent_data = True
            changes.append("Persistent Data on")

        if eevee.taa_render_samples > self.max_samples:
            eevee.taa_render_samples = self.max_samples
            changes.append("Render Samples -> %d" % self.max_samples)

        if getattr(eevee, "use_raytracing", False):
            eevee.use_raytracing = False
            changes.append("Ray Tracing off")

        if eevee.shadow_step_count > self.max_shadow_steps:
            eevee.shadow_step_count = self.max_shadow_steps
            changes.append("Shadow Steps -> %d" % self.max_shadow_steps)

        if r.use_motion_blur:
            r.use_motion_blur = False
            changes.append("Motion Blur off")

        if changes:
            self.report({'INFO'}, "Optimized: " + ", ".join(changes))
        else:
            self.report({'INFO'}, "Already optimized - no changes made")
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_SwitchCamera(bpy.types.Operator):
    """Toggle the scene camera and render resolution between the dome master
    camera and whatever camera/resolution was active before it"""

    bl_idname = "domemastereevee.switch_camera"
    bl_label = "Switch Camera"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = _props(context)
        return props.using_dome_camera or bpy.data.objects.get(CAMERA_NAME) is not None

    def execute(self, context):
        scene = context.scene
        props = _props(context)
        r = scene.render

        if props.using_dome_camera:
            scene.camera = props.prev_camera
            r.resolution_x = props.prev_resolution_x
            r.resolution_y = props.prev_resolution_y
            props.using_dome_camera = False
            self.report({'INFO'}, "Switched to previous camera (%s, %dx%d)" % (
                props.prev_camera.name if props.prev_camera else "None",
                r.resolution_x, r.resolution_y))
        else:
            dome_cam = bpy.data.objects.get(CAMERA_NAME)
            if dome_cam is None:
                self.report({'ERROR'}, "No dome camera yet - run Setup Camera & Optimize Scene first")
                return {'CANCELLED'}

            if scene.camera is not dome_cam:
                _remember_original_camera(props, scene)

            scene.camera = dome_cam
            r.resolution_x = props.output_resolution
            r.resolution_y = props.output_resolution
            props.using_dome_camera = True
            self.report({'INFO'}, "Switched to %s (%dx%d)" % (
                CAMERA_NAME, r.resolution_x, r.resolution_y))

        return {'FINISHED'}


_CLASSES = (
    DOMEMASTEREEVEE_OT_RenderDomeStill,
    DOMEMASTEREEVEE_OT_RenderDomeAnimation,
    DOMEMASTEREEVEE_OT_OpenOutputFolder,
    DOMEMASTEREEVEE_OT_OptimizeSceneRendering,
    DOMEMASTEREEVEE_OT_SwitchCamera,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
