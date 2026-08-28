import bpy

from . import preview


class DOMEMASTEREEVEE_PT_DomePreview(bpy.types.Panel):
    bl_label = "Live Preview"
    bl_idname = "DOMEMASTEREEVEE_PT_dome_preview"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_main"
    bl_order = 1

    def draw_header(self, context):
        enabled = preview.is_active_for_area(context.area)
        self.layout.operator(
            "domemastereevee.toggle_viewport_preview", text="",
            icon='CHECKBOX_HLT' if enabled else 'CHECKBOX_DEHLT',
            emboss=False, depress=enabled)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.domemastereevee_props
        space_enabled = preview.is_active_for_area(context.area)

        col = layout.column()
        col.active = space_enabled

        hint = col.row()
        hint.enabled = False
        hint.label(text="On/off is per viewport. Settings below are global.",
                   icon='INFO')

        if props.dome_camera is None:
            box = col.box()
            box.alert = True
            box.label(text="No Dome Camera selected", icon='ERROR')

        col.prop(props, "dome_camera")
        col.prop(props, "preview_placement")

        r3d = getattr(context.space_data, "region_3d", None)
        in_camera_view = r3d is not None and r3d.view_perspective == 'CAMERA'

        if props.preview_placement == 'CAMERA_FRAME' and not in_camera_view:
            hint = col.row()
            hint.enabled = False
            hint.label(text="Not in camera view - showing corner",
                       icon='INFO')
        if props.preview_placement == 'CORNER' or (
                props.preview_placement == 'CAMERA_FRAME' and not in_camera_view):
            col.prop(props, "preview_vertical_pos", slider=True)
            col.prop(props, "preview_corner_scale")

        sub = col.column(align=True)
        sub.prop(props, "preview_resolution")
        sub.prop(props, "preview_fps")
        sub.prop(props, "preview_shading")

        from ..dome_render import projection
        plan = projection.face_plan(props.fisheye_fov, props.overscan_deg,
                                    mode=props.face_mode,
                                    out_res=int(props.preview_resolution))
        n, fov_rad, kind = plan
        scale = projection.optimal_face_scale(props.fisheye_fov, fov_rad)
        px = max(64, int(round(props.preview_resolution * scale)))

        if props.debug_mode:
            perf = col.box()
            perf.label(text="%s: %d face%s at %d px"
                            % (kind, n, "" if n == 1 else "s", px), icon='SORTTIME')
            note = perf.column(align=True)
            note.enabled = False
            note.label(text="Levers: Resolution, Updates/sec, Shading.",
                       text_ctxt="extra-info-label")
            if kind == 'single' and px > 2048:
                note.label(text="Large single face - try Cube if slow.",
                           text_ctxt="extra-info-label")

        col.operator("domemastereevee.refresh_preview", icon='FILE_REFRESH')

        if props.debug_mode and space_enabled and props.preview_info:
            row = col.row()
            row.enabled = False
            row.label(text=props.preview_info, text_ctxt="extra-info-label")

        if props.debug_mode:
            note = layout.column(align=True)
            note.enabled = False
            note.label(text="Viewport quality, not final render.",
                       text_ctxt="extra-info-label")
            if props.debug_stretch:
                note.label(text="Stretch Debug is on: preview shows the readout.",
                           text_ctxt="extra-info-label")


def register():
    bpy.utils.register_class(DOMEMASTEREEVEE_PT_DomePreview)


def unregister():
    bpy.utils.unregister_class(DOMEMASTEREEVEE_PT_DomePreview)
