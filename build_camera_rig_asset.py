"""Regenerate addons/DomeMasterEEVEE/assets/camera_rig.blend from the
DOMEMASTER-CameraRig / WGTS_Armature collections in the currently open file.

Usage: from the .blend that has the up-to-date rig, open this file in
Blender's Text Editor via File > Open (not New/paste -- Blender only sets
__file__ for a text block loaded from disk, which this needs to find the
repo root), then Run Script (Alt+P).

What it does:
  1. Finds CameraRig (tagged "dme_rig") and CAM-Dome (tagged "dme_dome_camera")
     inside DOMEMASTER-CameraRig. Tags them if this is the first run.
  2. Temporarily clears the two places the rig references CAM-Director --
     the object-level Copy Transforms on CameraRig, and the Copy Transforms
     on the DEF-CAM-Director bone -- so linking the asset elsewhere never
     drags an external camera in as a dependency. See docs/ for why.
  3. Writes DOMEMASTER-CameraRig + WGTS_Armature, plus a throwaway Scene with
     them linked in, to camera_rig.blend -- the Scene exists purely so
     opening the asset file directly in Blender shows something instead of
     an empty viewport (bpy.data.libraries.write() never includes a scene
     unless you hand it one).
  4. Restores both constraint targets and removes the throwaway scene from
     THIS file. Nothing about the working file is left changed.
"""

import os
import bpy

RIG_COLLECTION_NAME = "DOMEMASTER-CameraRig"
WIDGETS_COLLECTION_NAME = "WGTS_Armature"
RIG_TAG = "dme_rig"
DOME_CAMERA_TAG = "dme_dome_camera"
DIRECTOR_BONE_NAME = "DEF-CAM-Director"


def _repo_root():
    path = globals().get("__file__")
    if not path:
        raise RuntimeError(
            "No __file__ available -- open this script via File > Open in "
            "the Text Editor (not New/paste) so Blender knows its path on "
            "disk, then Run Script")
    return os.path.dirname(os.path.abspath(bpy.path.abspath(path)))


def build():
    rig_coll = bpy.data.collections.get(RIG_COLLECTION_NAME)
    wgts_coll = bpy.data.collections.get(WIDGETS_COLLECTION_NAME)
    if rig_coll is None or wgts_coll is None:
        raise RuntimeError(
            "Expected collections '%s' and '%s' not found in this file"
            % (RIG_COLLECTION_NAME, WIDGETS_COLLECTION_NAME))

    cam_rig = next((o for o in rig_coll.objects if o.type == 'ARMATURE'), None)
    cam_dome = next((o for o in rig_coll.objects if o.type == 'CAMERA'), None)
    if cam_rig is None or cam_dome is None:
        raise RuntimeError(
            "'%s' must contain an armature and a camera" % RIG_COLLECTION_NAME)

    extra = [o.name for o in rig_coll.objects if o not in (cam_rig, cam_dome)]
    if extra:
        raise RuntimeError(
            "'%s' has extra objects that shouldn't ship with the rig: %s "
            "-- move them out first" % (RIG_COLLECTION_NAME, extra))

    obj_ct = cam_rig.constraints.get("Copy Transforms")
    if obj_ct is None:
        raise RuntimeError("CameraRig has no 'Copy Transforms' constraint")
    def_bone = cam_rig.pose.bones.get(DIRECTOR_BONE_NAME)
    if def_bone is None:
        raise RuntimeError("Rig has no '%s' bone" % DIRECTOR_BONE_NAME)
    bone_ct = def_bone.constraints.get("Copy Transforms")
    if bone_ct is None:
        raise RuntimeError(
            "'%s' bone has no 'Copy Transforms' constraint" % DIRECTOR_BONE_NAME)

    cam_rig[RIG_TAG] = True
    cam_dome[DOME_CAMERA_TAG] = True

    prev_obj_target = obj_ct.target
    prev_bone_target = bone_ct.target
    preview_scene = None

    try:
        obj_ct.target = None
        bone_ct.target = None

        preview_scene = bpy.data.scenes.new("DomeCameraRig Preview")
        preview_scene.collection.children.link(rig_coll)
        preview_scene.collection.children.link(wgts_coll)
        preview_scene.camera = cam_dome

        datablocks = {rig_coll, wgts_coll, preview_scene}
        for obj in list(rig_coll.objects) + list(wgts_coll.objects):
            datablocks.add(obj)
            if obj.data is not None:
                datablocks.add(obj.data)

        out_path = os.path.join(_repo_root(), "addons", "DomeMasterEEVEE",
                                 "assets", "camera_rig.blend")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        bpy.data.libraries.write(out_path, datablocks, fake_user=True)
        print("[build_camera_rig_asset] wrote %s (%d objects, %d collections)"
              % (out_path,
                 sum(1 for d in datablocks if isinstance(d, bpy.types.Object)),
                 sum(1 for d in datablocks if isinstance(d, bpy.types.Collection))))
    finally:
        # Unlink before removing the scene -- Scene.collection.children are
        # the *working* collections, not copies, so removing the scene
        # first would try to take the real rig collections down with it.
        if preview_scene is not None:
            for coll in (rig_coll, wgts_coll):
                if coll.name in preview_scene.collection.children:
                    preview_scene.collection.children.unlink(coll)
            bpy.data.scenes.remove(preview_scene)
        obj_ct.target = prev_obj_target
        bone_ct.target = prev_bone_target


build()
