"""
Diagnostics for the dome projection.

  * Test Pattern    - graticule of azimuth spokes and elevation rings, the
                      analog of pfc DebugDomeAngles. Coloured cardinal spokes
                      make orientation unambiguous.
  * Dome Preview    - hemisphere with equidistant fisheye UVs baked in, so a
                      domemaster maps onto it with no shader maths. The analog
                      of pfc DisplayDome.
  * Orientation Rig - throwaway scene with coloured markers on known world axes
                      plus a zenith-facing camera, for verifying handedness
                      end to end.
"""

import math

import bpy
import numpy as np

CARDINALS = (
    (0.0, (1.0, 0.15, 0.15)),     # red    -> +u, right
    (90.0, (0.15, 1.0, 0.25)),    # green  -> +v, top
    (180.0, (0.3, 0.45, 1.0)),    # blue   -> -u, left
    (270.0, (1.0, 0.85, 0.15)),   # yellow -> -v, bottom
)

# Markers sit at 45 degrees elevation, not on the horizon. A horizon marker
# lands exactly on the rim of a 180 degree disc and gets half clipped, which
# makes it a poor read. At 45 degrees an equidistant projection must place them
# at exactly half the disc radius, so this doubles as a check on the radial
# profile: if the ring is not at r = 0.5, the projection is not equidistant.
_D = 4.2426406871  # 6 * cos(45)

MARKERS = (
    ("RED_plusX", (_D, 0.0, _D), (1.0, 0.05, 0.05)),
    ("GREEN_plusY", (0.0, _D, _D), (0.05, 1.0, 0.1)),
    ("BLUE_minusX", (-_D, 0.0, _D), (0.1, 0.2, 1.0)),
    ("YELLOW_minusY", (0.0, -_D, _D), (1.0, 0.8, 0.05)),
    ("WHITE_zenith", (0.0, 0.0, 6.0), (1.0, 1.0, 1.0)),
)

EXPECTED = ("RED right, YELLOW top, GREEN bottom, BLUE left, WHITE centre; "
            "coloured markers at half the disc radius")


def _props(context):
    return context.scene.domemastereevee_props


# --------------------------------------------------------------------------- #
# Test pattern                                                                 #
# --------------------------------------------------------------------------- #
def _build_pattern(n, fov_deg, az_step, el_step):
    """Return an (n, n, 4) float32 bottom-up RGBA graticule."""
    axis = (np.arange(n, dtype=np.float32) + 0.5) / n * 2.0 - 1.0
    px, py = np.meshgrid(axis, axis)

    length = np.sqrt(px * px + py * py)
    inside = length <= 1.0
    safe_len = np.maximum(length, 1e-6)

    half_fov = math.radians(fov_deg) * 0.5
    theta_deg = np.degrees(length * half_fov)
    az_deg = np.degrees(np.arctan2(py, px)) % 360.0

    # Angular size of one pixel, so line width stays constant on screen.
    px_step = 2.0 / n
    d_az = np.degrees(px_step / safe_len)
    d_el = math.degrees(half_fov) * px_step

    def _lines(value, step, width):
        d = np.abs((value % step) - step * 0.5)
        d = step * 0.5 - d                       # distance to nearest multiple
        return np.clip(1.0 - d / np.maximum(width, 1e-6), 0.0, 1.0)

    az_lines = _lines(az_deg, az_step, d_az * 1.2)
    el_lines = _lines(theta_deg, el_step, d_el * 1.2)

    rgb = np.zeros((n, n, 3), dtype=np.float32)
    grid = np.maximum(az_lines, el_lines).astype(np.float32)
    rgb += grid[..., None] * 0.55

    # Coloured cardinal spokes, drawn over the white graticule.
    for angle, colour in CARDINALS:
        delta = np.abs(((az_deg - angle + 180.0) % 360.0) - 180.0)
        spoke = np.clip(1.0 - delta / np.maximum(d_az * 2.0, 1e-6), 0.0, 1.0)
        spoke = spoke * (length > 0.05)
        rgb = np.maximum(rgb, spoke[..., None] * np.array(colour, dtype=np.float32))

    # Zenith dot.
    rgb = np.maximum(rgb, (length < 0.02)[..., None].astype(np.float32))

    out = np.zeros((n, n, 4), dtype=np.float32)
    out[..., :3] = rgb
    out[..., 3] = inside.astype(np.float32)
    out[~inside] = 0.0
    return out


class DOMEMASTEREEVEE_OT_MakeTestPattern(bpy.types.Operator):
    """Generate a fisheye graticule test pattern image"""

    bl_idname = "domemastereevee.make_test_pattern"
    bl_label = "Generate Test Pattern"

    def execute(self, context):
        props = _props(context)
        n = int(props.pattern_resolution)
        pixels = _build_pattern(n, props.fisheye_fov,
                                props.pattern_az_step, props.pattern_el_step)

        name = "DomeTestPattern"
        img = bpy.data.images.get(name)
        if img is not None and tuple(img.size) != (n, n):
            bpy.data.images.remove(img)
            img = None
        if img is None:
            img = bpy.data.images.new(name, width=n, height=n,
                                      alpha=True, float_buffer=True)

        img.pixels.foreach_set(pixels.ravel())
        img.update()
        props.preview_image = img

        if context.screen is not None:
            for area in context.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    area.spaces.active.image = img
                    break

        self.report({'INFO'},
                    "%s: red spoke = right, green = top, "
                    "blue = left, yellow = bottom" % name)
        return {'FINISHED'}


# --------------------------------------------------------------------------- #
# Dome preview mesh                                                            #
# --------------------------------------------------------------------------- #
def _build_dome_mesh(name, fov_deg, rings=48, segments=96, radius=10.0):
    """
    Hemisphere with equidistant fisheye UVs baked per vertex.

    Because the UV is (cos phi, sin phi) based, phi = 0 and phi = 2*pi map to
    the same UV, so there is no seam to split.
    """
    half_fov = math.radians(fov_deg) * 0.5
    theta_max = min(half_fov, math.pi)

    verts = [(0.0, 0.0, radius)]
    uvs = [(0.5, 0.5)]

    for i in range(1, rings + 1):
        theta = theta_max * i / rings
        st, ct = math.sin(theta), math.cos(theta)
        r_uv = 0.5 * (theta / half_fov)
        for j in range(segments):
            phi = 2.0 * math.pi * j / segments
            cp, sp = math.cos(phi), math.sin(phi)
            verts.append((radius * st * cp, radius * st * sp, radius * ct))
            uvs.append((0.5 + r_uv * cp, 0.5 + r_uv * sp))

    faces = []
    for j in range(segments):
        nxt = (j + 1) % segments
        faces.append((0, 1 + j, 1 + nxt))

    for i in range(rings - 1):
        a = 1 + i * segments
        b = 1 + (i + 1) * segments
        for j in range(segments):
            nxt = (j + 1) % segments
            faces.append((a + j, b + j, b + nxt, a + nxt))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()

    uv_layer = mesh.uv_layers.new(name="DomeUV")
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uvs[loop.vertex_index]

    mesh.flip_normals()      # viewed from inside
    mesh.update()
    return mesh


def _dome_material(image):
    mat = bpy.data.materials.get("DomePreview")
    if mat is None:
        mat = bpy.data.materials.new("DomePreview")
    mat.use_nodes = True
    mat.use_backface_culling = False

    nt = mat.node_tree
    nt.nodes.clear()

    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.name = "Domemaster"
    tex.label = "Domemaster"
    tex.location = (-320, 0)
    tex.extension = 'CLIP'
    tex.interpolation = 'Cubic'
    if image is not None:
        tex.image = image

    emit = nt.nodes.new("ShaderNodeEmission")
    emit.location = (-60, 0)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (160, 0)

    nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


class DOMEMASTEREEVEE_OT_MakeDomePreview(bpy.types.Operator):
    """Create a hemisphere with fisheye UVs for viewing a domemaster from inside"""

    bl_idname = "domemastereevee.make_dome_preview"
    bl_label = "Create Dome Preview"

    def execute(self, context):
        props = _props(context)

        old = bpy.data.objects.get("DomePreview")
        if old is not None:
            data = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)

        mesh = _build_dome_mesh("DomePreview", props.fisheye_fov)
        obj = bpy.data.objects.new("DomePreview", mesh)
        obj.data.materials.append(_dome_material(props.preview_image))
        context.scene.collection.objects.link(obj)

        self.report({'INFO'},
                    "DomePreview created. Assign the image in the Domemaster "
                    "node of the DomePreview material")
        return {'FINISHED'}


# --------------------------------------------------------------------------- #
# Orientation rig                                                              #
# --------------------------------------------------------------------------- #
def _emissive_cube(name, location, colour, collection, size=0.9):
    verts = [(x * size, y * size, z * size)
             for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    collection.objects.link(obj)

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (colour[0], colour[1], colour[2], 1.0)
    emit.inputs["Strength"].default_value = 3.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    obj.data.materials.append(mat)
    return obj


class DOMEMASTEREEVEE_OT_MakeOrientationRig(bpy.types.Operator):
    """Build coloured markers on known world axes plus a zenith-facing camera"""

    bl_idname = "domemastereevee.make_orientation_rig"
    bl_label = "Build Orientation Rig"

    def execute(self, context):
        scene = context.scene

        coll = bpy.data.collections.get("DomeOrientationRig")
        if coll is None:
            coll = bpy.data.collections.new("DomeOrientationRig")
            scene.collection.children.link(coll)
        else:
            for obj in list(coll.objects):
                bpy.data.objects.remove(obj, do_unlink=True)

        for name, loc, colour in MARKERS:
            _emissive_cube("DME_%s" % name, loc, colour, coll)

        cam_data = bpy.data.cameras.new("DME_DomeCam")
        cam_data.clip_start = 0.01
        cam_data.clip_end = 1000.0
        cam_obj = bpy.data.objects.new("DME_DomeCam", cam_data)
        cam_obj.location = (0.0, 0.0, 0.0)
        cam_obj.rotation_euler = (math.pi, 0.0, 0.0)   # look straight up, +Z
        coll.objects.link(cam_obj)
        scene.camera = cam_obj

        self.report({'INFO'}, "Rig built. Expected domemaster: %s" % EXPECTED)
        return {'FINISHED'}


_CLASSES = (
    DOMEMASTEREEVEE_OT_MakeTestPattern,
    DOMEMASTEREEVEE_OT_MakeDomePreview,
    DOMEMASTEREEVEE_OT_MakeOrientationRig,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
