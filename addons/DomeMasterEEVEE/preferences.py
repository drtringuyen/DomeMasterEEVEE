import bpy


class DOMEMASTEREEVEE_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    last_output_dir: bpy.props.StringProperty(
        name="Last Output Folder",
        description=(
            "Remembers the most recently used domemaster output folder so a "
            "new file starts with a real path instead of the generic "
            "//domemaster/ default"
        ),
        default="",
        subtype='DIR_PATH',
    )


def register():
    bpy.utils.register_class(DOMEMASTEREEVEE_AddonPreferences)


def unregister():
    bpy.utils.unregister_class(DOMEMASTEREEVEE_AddonPreferences)
