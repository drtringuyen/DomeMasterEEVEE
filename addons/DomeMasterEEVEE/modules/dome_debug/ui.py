import bpy


class DOMEMASTEREEVEE_PT_DomeDebug(bpy.types.Panel):
    bl_label = "Diagnostics"
    bl_idname = "DOMEMASTEREEVEE_PT_dome_debug"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_main"
    bl_order = 3

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


class DOMEMASTEREEVEE_PT_MaterialAudit(bpy.types.Panel):
    bl_label = "Material Alpha Audit"
    bl_idname = "DOMEMASTEREEVEE_PT_material_audit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DomeMasterEEVEE"
    bl_parent_id = "DOMEMASTEREEVEE_PT_main"
    bl_order = 2
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.operator("domemastereevee.set_all_hashed_to_clip", icon='MOD_MASK')
        row.operator("domemastereevee.set_all_clip_to_hashed", icon='LOOP_BACK')

        from . import operators as ops

        mats = [m for m in bpy.data.materials
                if m.users > 0 and ops._current_mode(m) in ('HASHED', 'CLIP',
                                                              'DITHERED', 'BLENDED')]
        mats.sort(key=lambda m: m.name.lower())

        if not mats:
            layout.label(text="No Hashed/Clip materials in use", icon='INFO')
            return

        col = layout.column(align=True)
        for m in mats:
            row = col.row(align=True)
            row.label(text=m.name, icon='MATERIAL')
            mode = ops._current_mode(m)
            sub = row.row(align=True)
            sub.alert = (mode == ops._noisy_mode(m))
            op = sub.operator("domemastereevee.toggle_material_alpha",
                              text=mode)
            op.material_name = m.name


def register():
    bpy.utils.register_class(DOMEMASTEREEVEE_PT_DomeDebug)
    bpy.utils.register_class(DOMEMASTEREEVEE_PT_MaterialAudit)


def unregister():
    bpy.utils.unregister_class(DOMEMASTEREEVEE_PT_MaterialAudit)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_PT_DomeDebug)
