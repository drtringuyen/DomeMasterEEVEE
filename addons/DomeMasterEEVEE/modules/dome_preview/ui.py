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
        self.layout.prop(context.scene.domemastereevee_props,
                         "preview_enabled", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.domemastereevee_props

        col = layout.column()
        col.active = props.preview_enabled

        if props.preview_source == 'CAMERA' and scene.camera is None:
            box = col.box()
            box.alert = True
            box.label(text="No active scene camera", icon='ERROR')

        col.prop(props, "preview_source")
        col.prop(props, "preview_placement")

        if props.preview_placement == 'CAMERA_FRAME':
            r3d = getattr(context, "region_data", None)
            if r3d is not None and r3d.view_perspective != 'CAMERA':
                hint = col.row()
                hint.enabled = False
                hint.label(text="Not in camera view - showing corner",
                           icon='INFO')
        if props.preview_placement == 'CORNER' or (
                props.preview_placement == 'CAMERA_FRAME'
                and getattr(context, "region_data", None) is not None
                and context.region_data.view_perspective != 'CAMERA'):
            col.prop(props, "preview_corner")
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

        if props.debug_mode and props.preview_enabled and props.preview_info:
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
