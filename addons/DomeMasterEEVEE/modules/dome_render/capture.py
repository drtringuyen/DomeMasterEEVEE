"""
Cube face capture with EEVEE, and writing the remapped domemaster.

The active scene camera is never mutated. A temporary camera is created, given
the source camera's world matrix and clipping, and rotated per face. Everything
touched on the scene is saved and restored in a finally block.
"""

import os
import tempfile

import bpy
import numpy as np
from mathutils import Euler, Matrix

from . import projection


class RenderStateGuard:
    """Save and restore every scene setting the face renders touch."""

    _RENDER_KEYS = ("resolution_x", "resolution_y", "resolution_percentage",
                    "filepath", "use_overwrite", "use_file_extension",
                    "use_border", "use_crop_to_border",
                    "border_min_x", "border_max_x",
                    "border_min_y", "border_max_y")
    _IMAGE_KEYS = ("file_format", "color_mode", "color_depth")

    def __init__(self, scene):
        self.scene = scene
        self.saved_render = {}
        self.saved_image = {}
        self.saved_camera = None

    def __enter__(self):
        r = self.scene.render
        self.saved_render = {k: getattr(r, k) for k in self._RENDER_KEYS}
        self.saved_image = {k: getattr(r.image_settings, k) for k in self._IMAGE_KEYS}
        self.saved_camera = self.scene.camera
        return self

    def __exit__(self, *_exc):
        r = self.scene.render
        for k, v in self.saved_render.items():
            try:
                setattr(r, k, v)
            except Exception:
                pass
        for k, v in self.saved_image.items():
            try:
                setattr(r.image_settings, k, v)
            except Exception:
                pass
        self.scene.camera = self.saved_camera
        return False


def _load_face(path):
    """Load a rendered face as a bottom-up (h, w, 4) float32 array."""
    img = bpy.data.images.load(path)
    try:
        w, h = img.size
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        return buf.reshape(h, w, 4)
    finally:
        bpy.data.images.remove(img)


def render_faces(scene, depsgraph_camera, face_res, face_fov_rad, num_faces,
                 workdir, frame_tag, report=None, half_mf=-1.0):
    """
    Render the cube faces for the current frame.

    Returns a list of (h, w, 4) float32 arrays in projection.FACE_DEFS order,
    plus the list of file paths written.
    """
    base = depsgraph_camera.matrix_world.copy()
    # Strip scale: a scaled camera object would skew the face rotations.
    loc, rot, _scale = base.decompose()
    base = Matrix.Translation(loc) @ rot.to_matrix().to_4x4()

    cam_data = bpy.data.cameras.new("DME_TempCam")
    cam_data.type = 'PERSP'
    cam_data.sensor_fit = 'AUTO'
    cam_data.lens_unit = 'FOV'
    cam_data.angle = face_fov_rad
    cam_data.shift_x = 0.0
    cam_data.shift_y = 0.0
    cam_data.clip_start = depsgraph_camera.data.clip_start
    cam_data.clip_end = depsgraph_camera.data.clip_end

    cam_obj = bpy.data.objects.new("DME_TempCam", cam_data)
    scene.collection.objects.link(cam_obj)

    arrays = []
    paths = []
    try:
        with RenderStateGuard(scene):
            r = scene.render
            r.resolution_x = face_res
            r.resolution_y = face_res
            r.resolution_percentage = 100
            r.use_overwrite = True
            r.use_file_extension = True
            r.image_settings.file_format = 'OPEN_EXR'
            r.image_settings.color_mode = 'RGBA'
            r.image_settings.color_depth = '32'
            scene.camera = cam_obj

            for i in range(num_faces):
                name, euler = projection.FACE_DEFS[i]
                cam_obj.matrix_world = base @ Euler(euler, 'XYZ').to_matrix().to_4x4()

                # Half faces are rendered with a cropped render border rather
                # than an asymmetric frustum. The camera keeps its symmetric
                # 90+overscan FOV, and Blender crops the output to exactly the
                # kept sub-rectangle -- no lens maths, no chance of the border
                # and the shader's uv mapping drifting apart.
                x0, x1, y0, y1 = projection.face_rect_ndc(i, half_mf)
                cropped = (x0, x1, y0, y1) != (-1.0, 1.0, -1.0, 1.0)
                r.use_border = cropped
                r.use_crop_to_border = cropped
                if cropped:
                    r.border_min_x = (x0 + 1.0) * 0.5
                    r.border_max_x = (x1 + 1.0) * 0.5
                    r.border_min_y = (y0 + 1.0) * 0.5
                    r.border_max_y = (y1 + 1.0) * 0.5

                path = os.path.join(workdir, "face_%s_%d_%s.exr" % (frame_tag, i, name))
                r.filepath = path
                if report:
                    report("Rendering face %d/%d (%s)%s"
                           % (i + 1, num_faces, name, " half" if cropped else ""))
                bpy.ops.render.render(write_still=True)

                if not os.path.exists(path):
                    raise RuntimeError("Face render produced no file: %s" % path)
                arrays.append(_load_face(path))
                paths.append(path)
    finally:
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)

    return arrays, paths


def write_output(scene, pixels, filepath, file_format):
    """
    Write a (h, w, 4) float32 bottom-up array using Blender's colour management.

    save_render applies the scene view transform, so PNG/JPEG come out
    display-referred and OpenEXR stays linear.
    """
    h, w = pixels.shape[0], pixels.shape[1]
    name = os.path.basename(filepath)

    img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True)
    try:
        img.pixels.foreach_set(np.ascontiguousarray(pixels, dtype=np.float32).ravel())

        settings = scene.render.image_settings
        prev = (settings.file_format, settings.color_mode, settings.color_depth)
        try:
            settings.file_format = file_format
            settings.color_mode = 'RGB'
            settings.color_depth = '32' if file_format == 'OPEN_EXR' else '8'
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            img.save_render(filepath, scene=scene)
        finally:
            (settings.file_format, settings.color_mode,
             settings.color_depth) = prev
    finally:
        bpy.data.images.remove(img)


def make_workdir():
    return tempfile.mkdtemp(prefix="domemaster_")


def output_path(props, scene, frame):
    base = bpy.path.abspath(props.output_dir)
    ext = {'OPEN_EXR': ".exr", 'PNG': ".png", 'JPEG': ".jpg"}[props.output_format]
    suffix = "_stretch" if props.debug_stretch else ""
    return os.path.join(base, "domemaster%s_%04d%s" % (suffix, frame, ext))
