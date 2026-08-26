import bpy


class DOMEMASTEREEVEE_PT_DomeDebug(bpy.types.Panel):
    bl_label = "Diagnostics"
    bl_idname = "DOMEMASTEREEVEE_PT_dome_debug"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_main"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        props = context.scene.domemastereevee_props

        box = layout.box()
        box.label(text="Test Pattern", icon='GRID')
        col = box.column(align=True)
        col.prop(props, "pattern_resolution")
        col.prop(props, "pattern_az_step")
        col.prop(props, "pattern_el_step")
        box.operator("domemastereevee.make_test_pattern", icon='IMAGE_DATA')

        box = layout.box()
        box.label(text="Dome Preview", icon='MESH_UVSPHERE')
        box.prop(props, "preview_image", text="")
        box.operator("domemastereevee.make_dome_preview", icon='MESH_UVSPHERE')

        box = layout.box()
        box.label(text="Orientation Check", icon='ORIENTATION_GIMBAL')
        box.operator("domemastereevee.make_orientation_rig", icon='EMPTY_AXIS')
        note = box.column(align=True)
        note.enabled = False
        note.label(text="Expected: RED right, YELLOW top,")
        note.label(text="GREEN bottom, BLUE left, WHITE centre")


def register():
    bpy.utils.register_class(DOMEMASTEREEVEE_PT_DomeDebug)


def unregister():
    bpy.utils.unregister_class(DOMEMASTEREEVEE_PT_DomeDebug)
