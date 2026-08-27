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

        col = layout.column(align=True)
        col.prop(props, "fisheye_fov")
        col.prop(props, "output_resolution")

        col.prop(props, "face_mode")

        from .operators import effective_face_scale, plan_for, _face_resolution
        plan = plan_for(props, 'RENDER')
        n_faces, face_fov_rad, kind = plan

        sub = col.column(align=True)
        sub.enabled = (kind == 'cube')
        sub.prop(props, "overscan_deg")
        sub.prop(props, "use_half_faces")

        col.prop(props, "auto_face_scale")
        sub = col.row(align=True)
        sub.enabled = not props.auto_face_scale
        sub.prop(props, "face_scale")

        scale = effective_face_scale(props, plan)
        face_res = _face_resolution(props, plan)
        halved = projection.half_applicable(props.fisheye_fov,
                                            props.use_half_faces, kind)
        mf = projection.half_margin_for(face_res)[0] if halved else -1.0
        mpix = sum(
            projection.face_pixels(i, face_res, mf)[0]
            * projection.face_pixels(i, face_res, mf)[1]
            for i in range(n_faces)) / 1.0e6

        box = layout.box()
        box.label(
            text="%d face%s at %d px  (%.0f deg, %.1f MPix total)"
                 % (n_faces, "" if n_faces == 1 else "s", face_res,
                    math.degrees(face_fov_rad), mpix),
            icon='RENDER_STILL' if kind == 'single' else 'MESH_CUBE')
        note = box.column(align=True)
        note.enabled = False
        if kind == 'single':
            note.label(text="Seam-free: SSR, AO, bloom, DOF, blur all correct.")
        else:
            if halved:
                full = n_faces * face_res * face_res / 1.0e6
                note.label(text="Half side faces: %.1f -> %.1f MPix"
                                % (full, mpix))
            note.label(text="Screen-space effects will seam at face joins.")
            if props.fisheye_fov < 180.0:
                note.label(text="Under 180 deg, Single Face avoids that.")

        head = layout.column(align=True)
        head.prop(props, "image_rotation")
        head.prop(props, "dome_tilt")
        head.prop(props, "flip_horizontal")

        out = layout.column(align=True)
        out.prop(props, "output_dir")
        out.prop(props, "output_format")

        opts = layout.column(align=True)
        opts.prop(props, "keep_faces")
        opts.prop(props, "use_gpu_remap")
        opts.operator("domemastereevee.optimize_scene_rendering",
                      icon='SHADERFX')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("domemastereevee.render_dome_still", icon='RENDER_STILL')
        col.operator("domemastereevee.render_dome_animation", icon='RENDER_ANIMATION')
        layout.operator("domemastereevee.open_output_folder", icon='FILE_FOLDER')

        if props.last_render_info:
            row = layout.row()
            row.enabled = False
            row.label(text=props.last_render_info)


class DOMEMASTEREEVEE_PT_DomeRenderStretch(bpy.types.Panel):
    bl_label = "Stretch Debug"
    bl_idname = "DOMEMASTEREEVEE_PT_dome_render_stretch"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_dome_render"
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
    DOMEMASTEREEVEE_PT_DomeRenderStretch,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
