import math
import bpy

from . import projection


class DOMEMASTEREEVEE_PT_DomeRender(bpy.types.Panel):
    bl_label = "Dome Render"
    bl_idname = "DOMEMASTEREEVEE_PT_dome_render"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_main"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.domemastereevee_props

        if scene.camera is None:
            box = layout.box()
            box.alert = True
            box.label(text="No active scene camera", icon='ERROR')
            return

        if scene.render.engine != 'BLENDER_EEVEE':
            row = layout.row()
            row.alert = True
            row.label(text="Engine is %s" % scene.render.engine, icon='INFO')

        box1 = layout.box()
        col = box1.column(align=True)
        row = col.row(align=True)
        row.label(text="", icon='HIDE_OFF')
        row.prop(props, "fisheye_fov")
        row = col.row(align=True)
        row.label(text="", icon='IMAGE_REFERENCE')
        row.prop(props, "output_resolution")

        from .operators import effective_face_scale, plan_for, _face_resolution
        plan = plan_for(props, 'RENDER')
        n_faces, face_fov_rad, kind = plan

        split = box1.split(factor=0.4, align=True)
        sub = split.row(align=True)
        sub.label(text="", icon='ORIENTATION_CURSOR')
        sub.prop(props, "image_rotation", text="Dome Rotation")
        rest = split.split(factor=0.6667, align=True)
        sub = rest.row(align=True)
        sub.label(text="", icon='SPHERE')
        sub.prop(props, "dome_tilt", text="Dome Tilt")
        rest.prop(props, "flip_horizontal", text="", icon='MOD_MIRROR')

        scale = effective_face_scale(props, plan)
        face_res = _face_resolution(props, plan)
        halved = projection.half_applicable(props.fisheye_fov,
                                            props.use_half_faces, kind)
        mf = projection.half_margin_for(face_res)[0] if halved else -1.0
        mpix = sum(
            projection.face_pixels(i, face_res, mf)[0]
            * projection.face_pixels(i, face_res, mf)[1]
            for i in range(n_faces)) / 1.0e6

        if props.debug_mode:
            box = box1.box()
            box.label(
                text="%d face%s at %d px  (%.0f deg, %.1f MPix total)"
                     % (n_faces, "" if n_faces == 1 else "s", face_res,
                        math.degrees(face_fov_rad), mpix),
                icon='RENDER_STILL' if kind == 'single' else 'MESH_CUBE')
            note = box.column(align=True)
            note.enabled = False
            if kind == 'single':
                note.label(text="Seam-free: SSR, AO, bloom, DOF, blur all correct.",
                           text_ctxt="extra-info-label")
            else:
                if halved:
                    full = n_faces * face_res * face_res / 1.0e6
                    note.label(text="Half side faces: %.1f -> %.1f MPix"
                                    % (full, mpix), text_ctxt="extra-info-label")
                note.label(text="Screen-space effects will seam at face joins.",
                           text_ctxt="extra-info-label")
                if props.fisheye_fov < 180.0:
                    note.label(text="Under 180 deg, Single Face avoids that.",
                               text_ctxt="extra-info-label")

        row = box1.row(align=True)
        row.operator("domemastereevee.optimize_scene_rendering",
                     icon='SHADERFX')

        box2 = layout.box()
        split = box2.split(factor=0.8, align=True)
        split.prop(props, "output_dir")
        split.prop(props, "output_format", text="")

        col = box2.column(align=True)
        col.scale_y = 1.3
        col.operator("domemastereevee.render_dome_still", icon='RENDER_STILL')
        row = col.row(align=True)
        row.operator("domemastereevee.render_dome_animation", icon='RENDER_ANIMATION')
        row.operator("domemastereevee.open_output_folder", text="", icon='FILE_FOLDER')

        if props.debug_mode and props.last_render_info:
            row = layout.row()
            row.enabled = False
            row.label(text=props.last_render_info, text_ctxt="extra-info-label")


class DOMEMASTEREEVEE_PT_DomeFaceMapping(bpy.types.Panel):
    bl_label = "Dome Face Mapping"
    bl_idname = "DOMEMASTEREEVEE_PT_dome_face_mapping"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_dome_render"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.domemastereevee_props

        from .operators import plan_for
        n_faces, face_fov_rad, kind = plan_for(props, 'RENDER')

        col = layout.column(align=True)
        col.prop(props, "face_mode")
        col.prop(props, "use_half_faces")
        sub = col.column(align=True)
        sub.enabled = (kind == 'cube')
        sub.prop(props, "overscan_deg")
        col.prop(props, "auto_face_scale")
        sub = col.column(align=True)
        sub.enabled = not props.auto_face_scale
        sub.prop(props, "face_scale")
        col.prop(props, "use_gpu_remap")
        col.prop(props, "keep_faces")


class DOMEMASTEREEVEE_PT_DomeRenderStretch(bpy.types.Panel):
    bl_label = "Stretch Debug"
    bl_idname = "DOMEMASTEREEVEE_PT_dome_render_stretch"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_main"
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.domemastereevee_props,
                         "debug_stretch", text="")

    def draw(self, context):
        layout = self.layout
        props = context.scene.domemastereevee_props

        col = layout.column(align=True)
        col.active = props.debug_stretch
        col.prop(props, "allowed_undersampling")
        col.prop(props, "allowed_perfect_range")

        legend = layout.column(align=True)
        legend.enabled = False
        legend.label(text="Red: undersampled, raise Face Scale")
        legend.label(text="Green: 1:1, correct")
        legend.label(text="Blue: oversampled, lower Face Scale")


_CLASSES = (
    DOMEMASTEREEVEE_PT_DomeRender,
    DOMEMASTEREEVEE_PT_DomeFaceMapping,
    DOMEMASTEREEVEE_PT_DomeRenderStretch,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
