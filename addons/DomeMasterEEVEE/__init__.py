bl_info = {
    "name": "DomeMasterEEVEE",
    "version": (0, 4, 1),
    "blender": (4, 0, 0),
    "category": "Render",
    "description": "Fulldome fisheye rendering and preview for EEVEE, with adjustable FOV and sampling diagnostics",
    "author": "Nguyen Duc Tri",
    "doc_url": "",
    "tracker_url": "",
}

# Module registry - easily enable/disable modules
MODULES = {}

def register():
    from . import preferences, properties, infos, panels
    preferences.register()
    properties.register()
    infos.register()
    panels.register()

    from . import module_manager
    module_manager.load_all()

def unregister():
    from . import module_manager
    module_manager.unload_all()

    from . import preferences, properties, infos, panels
    panels.unregister()
    infos.unregister()
    properties.unregister()
    preferences.unregister()
