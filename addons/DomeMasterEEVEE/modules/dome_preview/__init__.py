import bpy

from . import operators, preview, ui


def _restart_if_enabled():
    """After an addon reload the checkbox may still be on with no handler live."""
    try:
        for scene in bpy.data.scenes:
            props = getattr(scene, "domemastereevee_props", None)
            if props is not None and props.preview_enabled:
                preview.start()
                break
    except Exception:
        pass
    return None


def register():
    operators.register()
    ui.register()
    bpy.app.timers.register(_restart_if_enabled, first_interval=0.2)


def unregister():
    preview.stop()
    ui.unregister()
    operators.unregister()
