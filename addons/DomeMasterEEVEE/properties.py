import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


class DOMEMASTEREEVEEProperties(bpy.types.PropertyGroup):
    """Global properties shared across all modules"""

    # ------------------------------------------------------------------ #
    # Scaffold                                                            #
    # ------------------------------------------------------------------ #
    debug_mode: BoolProperty(
        name="Debug Mode",
        description="Show extra-info-label and debug information",
        default=False,
    )

    last_build_time: StringProperty(
        name="Last Build Time",
        description="Timestamp of last install.py run",
        default="Never",
    )

    addon_version: StringProperty(
        name="Version",
        description="Current addon version",
        default="0.4.1",
    )

    # ------------------------------------------------------------------ #
    # Projection                                                          #
    # ------------------------------------------------------------------ #
    fisheye_fov: FloatProperty(
        name="Fisheye FOV",
        description=(
            "Full field of view across the fisheye disc, in degrees. "
            "180 is a standard domemaster. Above 180 the rear cube face is "
            "rendered as well, which costs one extra face per frame"
        ),
        default=180.0,
        min=30.0,
        max=360.0,
        soft_min=150.0,
        step=100,
        precision=1,
    )

    output_resolution: IntProperty(
        name="Output Resolution",
        description="Width and height of the square domemaster output",
        default=2048,
        min=64,
        max=16384,
        subtype='PIXEL',
    )

    face_mode: EnumProperty(
        name="Face Layout",
        description=(
            "How many perspective renders make up the dome. Below 180 degrees "
            "a single wide face can cover the whole disc, which is both faster "
            "and seam-free -- screen space effects come out correct instead of "
            "breaking across face joins"
        ),
        items=[
            ('AUTO', "Auto",
             "Cost both layouts and pick the cheaper. A single face needs "
             "tan(FOV/2) times the output resolution, so it wins at low FOV "
             "and loses badly at high FOV. The crossover moves with output "
             "resolution too, so it is computed rather than fixed"),
            ('SINGLE', "Single Face",
             "Always one wide face. Seam-free, but source resolution grows as "
             "tan(FOV/2): 1.7x output at 120 degrees, 2.9x at 150, 4.5x at "
             "160. Above 170, or past 8192 px, it falls back to cube"),
            ('CUBE', "Cube Faces",
             "Always 5 faces (6 above 180 degrees). Needed for a true 180 "
             "degree dome or wider"),
        ],
        default='AUTO',
    )

    use_half_faces: BoolProperty(
        name="Half Side Faces",
        description=(
            "At 180 degrees or below, exactly half of each of the four side "
            "cube faces is never sampled, so only the used half is rendered "
            "via a cropped render border. Measured 33 percent faster at 1024 "
            "and 18 percent at 2048. Applies to final renders only -- the live "
            "preview is bound by per-draw setup rather than fill, where this "
            "saves nothing"
        ),
        default=True,
    )

    auto_face_scale: BoolProperty(
        name="Auto Face Scale",
        description=(
            "Derive the cube face resolution from the fisheye FOV and overscan "
            "so the centre of each face samples the output 1:1. This is the "
            "smallest face size that never undersamples. Turn off to set it by "
            "hand with the Stretch Debug view"
        ),
        default=True,
    )

    face_scale: FloatProperty(
        name="Face Scale",
        description=(
            "Cube face resolution as a multiple of the output resolution. "
            "Use the Stretch Debug view to tune this: aim for green at the "
            "disc centre and accept blue towards the rim"
        ),
        default=0.7071,      # correct for 180 deg FOV with 3 deg overscan
        min=0.10,
        max=2.00,
        step=5,
        precision=3,
    )

    overscan_deg: FloatProperty(
        name="Overscan",
        description=(
            "Extra degrees rendered beyond each cube face's 90 degrees. "
            "The overlap is cross-faded, which softens seams from "
            "screen-space effects. 0 disables blending"
        ),
        default=3.0,
        min=0.0,
        max=20.0,
        step=50,
        precision=1,
    )

    image_rotation: FloatProperty(
        name="Image Rotation",
        description="Rotate the fisheye disc about its centre, in degrees",
        default=0.0,
        min=-360.0,
        max=360.0,
        step=100,
        precision=1,
    )

    dome_tilt: FloatProperty(
        name="Dome Tilt",
        description=(
            "Tilt the projection axis, in degrees. Use for tilted planetarium "
            "domes where the spring line is not horizontal"
        ),
        default=0.0,
        min=-90.0,
        max=90.0,
        step=100,
        precision=1,
    )

    flip_horizontal: BoolProperty(
        name="Flip Horizontal",
        description=(
            "Mirror the disc left/right. Needed when matching a pipeline that "
            "uses the opposite handedness convention"
        ),
        default=False,
    )

    # ------------------------------------------------------------------ #
    # Dome camera switch                                                  #
    # ------------------------------------------------------------------ #
    using_dome_camera: BoolProperty(
        name="Using Dome Camera",
        description="Internal: whether Camera-DOME-Master is the active scene camera",
        default=False,
    )

    prev_camera: PointerProperty(
        name="Previous Camera",
        description="Scene camera in place before switching to Camera-DOME-Master",
        type=bpy.types.Object,
    )

    prev_resolution_x: IntProperty(
        name="Previous Resolution X",
        description="Render resolution X in place before switching to Camera-DOME-Master",
        default=1920,
    )

    prev_resolution_y: IntProperty(
        name="Previous Resolution Y",
        description="Render resolution Y in place before switching to Camera-DOME-Master",
        default=1080,
    )

    # ------------------------------------------------------------------ #
    # Output                                                              #
    # ------------------------------------------------------------------ #
    output_dir: StringProperty(
        name="Output Folder",
        description="Where domemaster frames are written",
        default="//domemaster/",
        subtype='DIR_PATH',
    )

    output_format: EnumProperty(
        name="Format",
        description="File format for the domemaster output",
        items=[
            ('OPEN_EXR', "OpenEXR",
             "32-bit linear float, no clipping. Correct for a fulldome pipeline"),
            ('PNG', "PNG", "8/16-bit, view transform applied"),
            ('JPEG', "JPEG", "8-bit lossy, view transform applied"),
        ],
        default='OPEN_EXR',
    )

    keep_faces: BoolProperty(
        name="Keep Cube Faces",
        description="Leave the intermediate cube face renders on disk for inspection",
        default=False,
    )

    use_gpu_remap: BoolProperty(
        name="GPU Remap",
        description=(
            "Run the fisheye remap as a GLSL shader on the GPU. "
            "Disable to use the slower NumPy path if your driver rejects the shader"
        ),
        default=True,
    )

    # ------------------------------------------------------------------ #
    # Stretch diagnostics (port of pfc GetDebugStretch)                   #
    # ------------------------------------------------------------------ #
    debug_stretch: BoolProperty(
        name="Stretch Debug",
        description=(
            "Output a sampling-density readout instead of the image. "
            "Red = undersampled (source too small), green = 1:1, "
            "blue = oversampled (wasting render time)"
        ),
        default=False,
    )

    allowed_undersampling: FloatProperty(
        name="Allowed Undersampling",
        description="How much undersampling still counts as acceptable",
        default=2.0,
        min=1.0,
        max=2.0,
        step=5,
        precision=2,
    )

    allowed_perfect_range: FloatProperty(
        name="Perfect Range",
        description="Width of the green 'perfect 1:1' band",
        default=0.01,
        min=0.0001,
        max=0.1,
        step=1,
        precision=4,
    )

    # ------------------------------------------------------------------ #
    # Test pattern                                                        #
    # ------------------------------------------------------------------ #
    pattern_resolution: IntProperty(
        name="Pattern Resolution",
        description="Size of the generated graticule test pattern",
        default=2048,
        min=64,
        max=8192,
        subtype='PIXEL',
    )

    pattern_az_step: FloatProperty(
        name="Azimuth Step",
        description="Degrees between radial spokes",
        default=15.0,
        min=1.0,
        max=90.0,
        step=100,
        precision=1,
    )

    pattern_el_step: FloatProperty(
        name="Elevation Step",
        description="Degrees between concentric rings",
        default=10.0,
        min=1.0,
        max=45.0,
        step=100,
        precision=1,
    )

    preview_image: PointerProperty(
        name="Preview Image",
        description="Domemaster image to map onto the dome preview mesh",
        type=bpy.types.Image,
    )

    # ------------------------------------------------------------------ #
    # Status                                                              #
    # ------------------------------------------------------------------ #
    last_render_info: StringProperty(
        name="Last Render",
        description="Summary of the most recent domemaster render",
        default="",
    )

    preview_info: StringProperty(
        name="Preview Info",
        description="Live preview timing readout",
        default="",
    )

    # ------------------------------------------------------------------ #
    # Live preview                                                        #
    #                                                                      #
    # Whether the preview is drawn is a per-viewport setting -- see        #
    # SpaceView3D.domemastereevee_preview_enabled in dome_preview.preview  #
    # -- so every property below is a *global* setting shared by every     #
    # viewport that has the preview turned on, and none of them live here. #
    # ------------------------------------------------------------------ #
    preview_resolution: IntProperty(
        name="Preview Resolution",
        description=(
            "Size of the live preview disc. Cost scales roughly with the "
            "square of this above about 1024 px, and it also drives the cube "
            "face size, so it is a real performance lever"
        ),
        default=768,
        min=128,
        max=4096,
        subtype='PIXEL',
    )

    preview_fps: IntProperty(
        name="Max Updates/sec",
        description=(
            "Upper bound on preview refresh rate. An unchanged scene costs "
            "nothing, so this only bites while you navigate"
        ),
        default=12,
        min=1,
        max=60,
    )

    preview_shading: EnumProperty(
        name="Preview Shading",
        description=(
            "Shading used for the cube face renders. Overriding to Solid is "
            "roughly 40 percent cheaper than Material Preview and is the "
            "second real performance lever. The main viewport is unaffected"
        ),
        items=[
            ('FOLLOW', "Follow Viewport", "Use whatever the viewport is set to"),
            ('SOLID', "Solid", "Cheapest. Good for blocking and framing"),
            ('MATERIAL', "Material Preview", "Materials without full lighting"),
            ('RENDERED', "Rendered", "Most expensive, closest to the render"),
        ],
        default='FOLLOW',
    )

    preview_corner_scale: FloatProperty(
        name="Corner Size",
        description="Preview size as a fraction of the viewport's short edge",
        default=0.40,
        min=0.10,
        max=1.00,
        step=5,
        precision=2,
    )

    dome_camera: PointerProperty(
        name="Dome Camera",
        description=(
            "Camera the dome looks out from. Drives both the Live Preview and "
            "the Render Domemaster / Markers / Sequence operators -- there is "
            "one dome camera for the whole addon, not a separate choice per "
            "feature"
        ),
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CAMERA',
    )

    preview_placement: EnumProperty(
        name="Placement",
        description="Where the preview disc is drawn",
        items=[
            ('CAMERA_FRAME', "Camera Frame",
             "Fill the camera frame, so looking through the camera shows the "
             "dome instead of the flat view. Falls back to Corner when the "
             "viewport is not in camera view"),
            ('CORNER', "Corner", "Picture-in-picture, viewport stays visible"),
            ('FULL', "Fullscreen", "Fill the viewport with the dome"),
        ],
        default='CAMERA_FRAME',
    )

    preview_vertical_pos: FloatProperty(
        name="Vertical Position",
        description=(
            "Slide the picture-in-picture preview up or down along the left "
            "edge, 0 is top and 1 is bottom. The preview is inset to clear "
            "the toolbar, header and side panel automatically"
        ),
        subtype='FACTOR',
        default=0.0,
        min=0.0,
        max=1.0,
    )


def register():
    bpy.utils.register_class(DOMEMASTEREEVEEProperties)
    bpy.types.Scene.domemastereevee_props = bpy.props.PointerProperty(
        type=DOMEMASTEREEVEEProperties
    )


def unregister():
    del bpy.types.Scene.domemastereevee_props
    bpy.utils.unregister_class(DOMEMASTEREEVEEProperties)
