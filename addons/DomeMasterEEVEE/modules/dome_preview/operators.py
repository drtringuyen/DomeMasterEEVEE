import bpy

from . import preview


class DOMEMASTEREEVEE_OT_TogglePreview(bpy.types.Operator):
    """Turn the live dome preview on or off"""

    bl_idname = "domemastereevee.toggle_preview"
    bl_label = "Live Dome Preview"

    def execute(self, context):
        props = context.scene.domemastereevee_props
        props.preview_enabled = not props.preview_enabled   # update() starts/stops
        self.report({'INFO'}, "Dome preview %s"
                    % ("on" if props.preview_enabled else "off"))
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_RefreshPreview(bpy.types.Operator):
    """Force the preview to re-render on the next tick"""

    bl_idname = "domemastereevee.refresh_preview"
    bl_label = "Refresh Preview"

    def execute(self, context):
        preview.invalidate()
        return {'FINISHED'}


_CLASSES = (
    DOMEMASTEREEVEE_OT_TogglePreview,
    DOMEMASTEREEVEE_OT_RefreshPreview,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
