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


def _ensure_dome_camera(context):
    """Force the dome camera active for a render, regardless of what the
    scene camera currently is. Returns (prev_camera, dome_camera) so the
    caller can restore the original camera afterwards."""
    scene = context.scene
    dome_cam = _props(context).dome_camera
    if dome_cam is None:
        raise RuntimeError(
            "No Dome Camera selected - pick one in the Live Preview panel")
    prev_cam = scene.camera
    if prev_cam is not dome_cam:
        scene.camera = dome_cam
    return prev_cam, dome_cam


def _restore_camera(context, prev_cam, dome_cam):
    if dome_cam is None:
        return
    scene = context.scene
    if prev_cam is not dome_cam and scene.camera is dome_cam:
        scene.camera = prev_cam


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
        return (context.scene is not None
                and _props(context).dome_camera is not None)

    def execute(self, context):
        props = _props(context)
        scene = context.scene
        start_frame = scene.frame_current
        workdir = capture.make_workdir()
        t0 = time.time()
        prev_cam = dome_cam = None
        try:
            prev_cam, dome_cam = _ensure_dome_camera(context)
            out, backend, face_res, num_faces, kind = _render_one_frame(
                context, scene.frame_current, workdir)
        except Exception as exc:      # noqa: BLE001 - surface any failure to the UI
            self.report({'ERROR'}, "Domemaster render failed: %s" % exc)
            return {'CANCELLED'}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            scene.frame_set(start_frame)
            _restore_camera(context, prev_cam, dome_cam)

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
        return (context.scene is not None
                and _props(context).dome_camera is not None)

    def execute(self, context):
        scene = context.scene
        props = _props(context)
        start_frame = scene.frame_current
        workdir = capture.make_workdir()
        frames = range(scene.frame_start, scene.frame_end + 1, scene.frame_step)
        t0 = time.time()
        done = 0
        prev_cam = dome_cam = None
        try:
            prev_cam, dome_cam = _ensure_dome_camera(context)
            for frame in frames:
                _render_one_frame(context, frame, workdir)
                done += 1
        except Exception as exc:      # noqa: BLE001
            self.report({'ERROR'}, "Stopped after %d frame(s): %s" % (done, exc))
            return {'CANCELLED'}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            scene.frame_set(start_frame)
            _restore_camera(context, prev_cam, dome_cam)

        dt = time.time() - t0
        props.last_render_info = "%d frames in %.1fs" % (done, dt)
        self.report({'INFO'}, "Domemaster sequence: %s" % props.last_render_info)
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_RenderDomeMarkers(bpy.types.Operator):
    """Render only the frames that have a timeline marker"""

    bl_idname = "domemastereevee.render_dome_markers"
    bl_label = "Render Domemaster Markers"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return (context.scene is not None
                and _props(context).dome_camera is not None
                and len(context.scene.timeline_markers) > 0)

    def execute(self, context):
        scene = context.scene
        props = _props(context)
        start_frame = scene.frame_current
        frames = sorted({m.frame for m in scene.timeline_markers})
        if not frames:
            self.report({'WARNING'}, "No timeline markers found")
            return {'CANCELLED'}

        workdir = capture.make_workdir()
        t0 = time.time()
        done = 0
        prev_cam = dome_cam = None
        try:
            prev_cam, dome_cam = _ensure_dome_camera(context)
            for frame in frames:
                _render_one_frame(context, frame, workdir)
                done += 1
        except Exception as exc:      # noqa: BLE001
            self.report({'ERROR'}, "Stopped after %d marker frame(s): %s" % (done, exc))
            return {'CANCELLED'}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            scene.frame_set(start_frame)
            _restore_camera(context, prev_cam, dome_cam)

        dt = time.time() - t0
        props.last_render_info = "%d marker frames in %.1fs" % (done, dt)
        self.report({'INFO'}, "Domemaster markers: %s" % props.last_render_info)
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


RIG_COLLECTION_NAME = "DOMEMASTER-CameraRig"
RIG_TAG = "dme_rig"
DOME_CAMERA_TAG = "dme_dome_camera"
DIRECTOR_BONE_NAME = "DEF-CAM-Director"


def _remember_original_camera(props, scene):
    """Snapshot the camera/resolution in place before switching to the dome camera."""
    r = scene.render
    props.prev_camera = scene.camera
    props.prev_resolution_x = r.resolution_x
    props.prev_resolution_y = r.resolution_y


def _rig_asset_path():
    addon_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(addon_root, "assets", "camera_rig.blend")


def _find_tagged_object(scene, tag):
    """Search only the given scene's objects, not the whole file -- a
    director's file can have more than one scene, and bpy.data.objects would
    also match a tagged rig that belongs to a different one."""
    for obj in scene.objects:
        if obj.get(tag):
            return obj
    return None


def _append_rig(context):
    """Append (not link) the bundled camera-rig collection, so the
    director's file gets its own independent copy with no dependency on
    camera_rig.blend ever again -- a linked library override still needs
    the source file reachable to resync, and that file lives inside each
    artist's local addon install (a per-machine path), which breaks the
    moment the .blend is opened on a different computer. Returns the
    appended CameraRig armature object. No-op (just returns the existing
    one) if a rig is already present from an earlier run."""
    existing = _find_tagged_object(context.scene, RIG_TAG)
    if existing is not None:
        return existing, False

    asset_path = _rig_asset_path()
    if not os.path.isfile(asset_path):
        raise RuntimeError("Camera rig asset missing: %s" % asset_path)

    with bpy.data.libraries.load(asset_path, link=False) as (data_from, data_to):
        if RIG_COLLECTION_NAME not in data_from.collections:
            raise RuntimeError(
                "'%s' not found in %s" % (RIG_COLLECTION_NAME, asset_path))
        data_to.collections = [RIG_COLLECTION_NAME]

    appended_coll = data_to.collections[0]
    context.scene.collection.children.link(appended_coll)

    cam_rig = None
    for obj in appended_coll.objects:
        if obj.get(RIG_TAG):
            cam_rig = obj
            break
    if cam_rig is None:
        raise RuntimeError(
            "Appended rig is missing the '%s' tag on its armature" % RIG_TAG)
    return cam_rig, True


def _retarget_rig(cam_rig, director_cam):
    """Point both places the rig references the director's camera at the
    given object: the armature's object-level Copy Transforms, and the
    DEF-CAM-Director bone's own Copy Transforms."""
    obj_ct = cam_rig.constraints.get("Copy Transforms")
    if obj_ct is None:
        raise RuntimeError("CameraRig has no 'Copy Transforms' constraint")
    obj_ct.target = director_cam

    def_bone = cam_rig.pose.bones.get(DIRECTOR_BONE_NAME)
    if def_bone is None:
        raise RuntimeError("Rig has no '%s' bone" % DIRECTOR_BONE_NAME)
    bone_ct = def_bone.constraints.get("Copy Transforms")
    if bone_ct is None:
        raise RuntimeError(
            "'%s' bone has no 'Copy Transforms' constraint" % DIRECTOR_BONE_NAME)
    bone_ct.target = director_cam


class DOMEMASTEREEVEE_OT_OptimizeSceneRendering(bpy.types.Operator):
    """Append the Dome Camera Rig asset as a private local copy (on first
    run, or reusing one already in the file), point its Copy Transforms
    constraints at the selected camera so CAM-Dome tracks it, set CAM-Dome as
    the Dome Camera, and then apply the usual render-time optimizations:
    enable Persistent Data (avoids re-uploading geometry/BVH for each of the
    5 cube faces), cap render samples, disable Ray Tracing, cap shadow step
    count, and turn off Motion Blur. Leaves the scene's render resolution
    and aspect ratio alone -- the domemaster capture/preview pipeline reads
    Output Resolution directly and never looks at scene.render, so there is
    nothing to keep in sync, and the director's own resolution stays intact
    for their own non-dome renders"""

    bl_idname = "domemastereevee.optimize_scene_rendering"
    bl_label = "Setup Camera & Optimize Scene"
    bl_options = {'REGISTER', 'UNDO'}

    max_samples: bpy.props.IntProperty(
        name="Max Render Samples", default=32, min=1, max=4096,
        description="Render samples are capped to this value if higher")
    max_shadow_steps: bpy.props.IntProperty(
        name="Max Shadow Steps", default=4, min=1, max=32,
        description="Shadow step count is capped to this value if higher")

    @classmethod
    def poll(cls, context):
        active = context.view_layer.objects.active
        if active is None or active.type != 'CAMERA':
            cls.poll_message_set("Select the director's camera first")
            return False
        return True

    def execute(self, context):
        scene = context.scene
        props = _props(context)
        eevee = scene.eevee
        r = scene.render
        changes = []

        director_cam = context.view_layer.objects.active
        if director_cam.get(DOME_CAMERA_TAG) or director_cam.get(RIG_TAG):
            self.report({'ERROR'},
                        "Selected camera is the dome rig itself - select "
                        "the director's own camera instead")
            return {'CANCELLED'}

        try:
            cam_rig, created = _append_rig(context)
            _retarget_rig(cam_rig, director_cam)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        cam_dome = _find_tagged_object(scene, DOME_CAMERA_TAG)
        if cam_dome is None:
            self.report({'ERROR'}, "Appended rig is missing its CAM-Dome camera")
            return {'CANCELLED'}

        props.dome_camera = cam_dome
        changes.append(
            "%s dome rig, retargeted to '%s'"
            % ("Appended" if created else "Reused", director_cam.name))

        for obj in context.selected_objects:
            obj.select_set(False)
        cam_dome.select_set(True)
        context.view_layer.objects.active = cam_dome

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
        return props.using_dome_camera or props.dome_camera is not None

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
            dome_cam = props.dome_camera
            if dome_cam is None:
                self.report({'ERROR'}, "No Dome Camera selected - pick one in the Live Preview panel")
                return {'CANCELLED'}

            if scene.camera is not dome_cam:
                _remember_original_camera(props, scene)

            scene.camera = dome_cam
            r.resolution_x = props.output_resolution
            r.resolution_y = props.output_resolution
            props.using_dome_camera = True
            self.report({'INFO'}, "Switched to %s (%dx%d)" % (
                dome_cam.name, r.resolution_x, r.resolution_y))

        return {'FINISHED'}


_CLASSES = (
    DOMEMASTEREEVEE_OT_RenderDomeStill,
    DOMEMASTEREEVEE_OT_RenderDomeAnimation,
    DOMEMASTEREEVEE_OT_RenderDomeMarkers,
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
