import bpy

from . import preview


class DOMEMASTEREEVEE_OT_ToggleViewportPreview(bpy.types.Operator):
    """Turn the live dome preview on or off for this viewport only"""

    bl_idname = "domemastereevee.toggle_viewport_preview"
    bl_label = "Live Dome Preview"

    def execute(self, context):
        area = context.area
        if area is None or area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Not run from a 3D viewport")
            return {'CANCELLED'}
        if preview.is_active_for_area(area):
            preview.disable_for_area(area)
            self.report({'INFO'}, "Dome preview off in this viewport")
        else:
            preview.enable_for_area(area)
            self.report({'INFO'}, "Dome preview on in this viewport")
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_RefreshPreview(bpy.types.Operator):
    """Force the preview to re-render on the next tick"""

    bl_idname = "domemastereevee.refresh_preview"
    bl_label = "Refresh Preview"

    def execute(self, context):
        preview.invalidate()
        return {'FINISHED'}


_CLASSES = (
    DOMEMASTEREEVEE_OT_ToggleViewportPreview,
    DOMEMASTEREEVEE_OT_RefreshPreview,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
