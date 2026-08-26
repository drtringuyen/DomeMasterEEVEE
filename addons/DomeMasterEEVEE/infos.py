"""Info panel operators: Build popup, Reload, Debug toggle, Console toggle, Clear console."""
import bpy
import os
import json


def _read_build_info():
    build_file = os.path.join(os.path.dirname(__file__), "build_info.json")
    if os.path.exists(build_file):
        try:
            with open(build_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


class DOMEMASTEREEVEE_OT_Build(bpy.types.Operator):
    """Show addon info and last build time"""
    bl_idname = "domemastereevee.build"
    bl_label = "Build"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.label(text="DomeMasterEEVEE", icon='ARMATURE_DATA')
        layout.separator()
        layout.label(text="Fulldome fisheye rendering and preview for EEVEE, with adjustable FOV and sampling diagnostics")
        layout.separator()
        layout.label(text="Version: 0.0.1")
        layout.label(text="Author: Nguyen Duc Tri")
        layout.separator()
        build = _read_build_info()
        if build:
            layout.label(text="Last built: " + build.get("time", "Unknown"), icon='TIME')
        else:
            layout.label(text="Not built yet - run install.py first", icon='ERROR')

    def execute(self, context):
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_Reload(bpy.types.Operator):
    """Reload addon in Blender (disable -> purge modules -> enable).
    Use when you want to apply in-place changes without running install.py."""
    bl_idname = "domemastereevee.reload"
    bl_label = "Reload Addon"

    def execute(self, context):
        import sys
        addon = "DomeMasterEEVEE"
        bpy.ops.preferences.addon_disable(module=addon)
        mods = [k for k in sys.modules if k == addon or k.startswith(addon + ".")]
        for m in mods:
            del sys.modules[m]
        bpy.ops.preferences.addon_enable(module=addon)
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_ToggleDebug(bpy.types.Operator):
    """Toggle debug mode - show/hide extra-info-label"""
    bl_idname = "domemastereevee.toggle_debug"
    bl_label = "Debug"

    def execute(self, context):
        props = context.scene.domemastereevee_props
        props.debug_mode = not props.debug_mode
        self.report({'INFO'}, "Debug: " + ("ON" if props.debug_mode else "OFF"))
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_ToggleConsole(bpy.types.Operator):
    """Toggle Blender system console"""
    bl_idname = "domemastereevee.toggle_console"
    bl_label = "Console"

    def execute(self, context):
        import sys
        if sys.platform == "win32":
            try:
                bpy.ops.wm.console_toggle()
            except AttributeError:
                import subprocess
                subprocess.Popen(
                    'start cmd',
                    shell=True,
                    creationflags=subprocess.DETACHED_PROCESS
                )
        else:
            self.report({'INFO'}, "Use Window > Toggle System Console")
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_ClearConsole(bpy.types.Operator):
    """Clear the system console output"""
    bl_idname = "domemastereevee.clear_console"
    bl_label = "Clear"

    def execute(self, context):
        import sys
        os.system("cls" if sys.platform == "win32" else "clear")
        return {'FINISHED'}



class DOMEMASTEREEVEE_OT_ToggleDomeRender(bpy.types.Operator):
    """Toggle DomeRender module on/off"""
    bl_idname = "domemastereevee.toggle_dome_render"
    bl_label = "DomeRender"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("dome_render")
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_ToggleDomeDebug(bpy.types.Operator):
    """Toggle DomeDebug module on/off"""
    bl_idname = "domemastereevee.toggle_dome_debug"
    bl_label = "DomeDebug"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("dome_debug")
        return {'FINISHED'}


class DOMEMASTEREEVEE_OT_ToggleDomePreview(bpy.types.Operator):
    """Toggle DomePreview module on/off"""
    bl_idname = "domemastereevee.toggle_dome_preview"
    bl_label = "DomePreview"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("dome_preview")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_Build)
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_Reload)
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_ToggleDebug)
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_ToggleConsole)
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_ClearConsole)
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_ToggleDomeRender)
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_ToggleDomeDebug)
    bpy.utils.register_class(DOMEMASTEREEVEE_OT_ToggleDomePreview)


def unregister():
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_ToggleDomePreview)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_ToggleDomeDebug)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_ToggleDomeRender)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_ClearConsole)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_ToggleConsole)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_ToggleDebug)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_Reload)
    bpy.utils.unregister_class(DOMEMASTEREEVEE_OT_Build)
