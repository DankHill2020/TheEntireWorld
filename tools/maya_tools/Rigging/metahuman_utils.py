import maya.cmds as cmds
import os
from external_tools.MetaHumanDNA.dnacalib import dnacalib
from external_tools.MetaHumanDNA.dnacalib import dna


def rebind_metahuman_face_to_body(face_mesh, face_joints, body_joints, skin_weights_path, dna_file_path):
    """
    Rebind MetaHuman head mesh to a different body rig, transfer skin weights, and update the DNA.

    :param face_mesh: Name of the MetaHuman face mesh (e.g. "Face_Mesh")
    :param face_joints: List of face rig joints to snap (e.g. ["root", "pelvis", "spine_01", "spine_02","spine_03",
    "spine_04", "spine_05", "neck_01",  "neck_02", "head"])
    :param body_joints: Corresponding joints on the new body rig.
    :param skin_weights_path: File path to export/import skin weights.
    :param dna_file_path: Path to the MetaHuman DNA file to update.
    """
    if len(face_joints) != len(body_joints):
        raise ValueError("Joint lists must match in length.")

    # Step 1: Export skin weights
    if not os.path.exists(skin_weights_path):
        os.makedirs(os.path.dirname(skin_weights_path), exist_ok=True)

    cmds.select(face_mesh, r=True)
    cmds.deformerWeights("face_weights.xml", export=True, path=skin_weights_path)

    # Step 2: Snap the first spine joint to the body rig
    for i, (fj, bj) in enumerate(zip(face_joints, body_joints)):
        pos = cmds.xform(bj, q=True, ws=True, t=True)
        rot = cmds.xform(bj, q=True, ws=True, ro=True)
        cmds.xform(fj, ws=True, t=pos)
        cmds.xform(fj, ws=True, ro=rot)

    # Step 3: Delete the skinCluster on the face mesh
    skin_clusters = cmds.ls(cmds.listHistory(face_mesh), type='skinCluster')
    if skin_clusters:
        cmds.delete(skin_clusters)

    # Step 4: Bind face mesh to new skeleton
    cmds.select(face_joints, face_mesh, r=True)
    cmds.skinCluster(tsb=True, bm=0, sm=0, nw=1, omi=True)

    # Step 5: Reimport the skin weights
    cmds.deformerWeights("face_weights.xml", im=True, method="index", path=skin_weights_path)

    # Step 6: Update the MetaHuman DNA file (requires plugin loaded)
    if cmds.pluginInfo("dnacalib", q=True, loaded=True):

        # Read existing DNA file
        with open(dna_file_path, "rb") as f:
            reader = dna.BinaryStreamReader(f.read())

        # Modify in-memory data (optional)
        reader.read()  # Parse the file

        # Apply changes — if `recalculate_rest_pose_from_scene()` is part of `dnacalib`
        config = dnacalib.Config()
        config.input_dna = reader
        config.recalculate_rest_pose = True  # or whatever the actual field is

        calibrated_dna = dnacalib.run(config)

        # Save updated file
        updated_path = dna_file_path.replace(".dna", "_updated.dna")
        with open(updated_path, "wb") as f:
            writer = dna.BinaryStreamWriter(calibrated_dna)
            writer.write(f)

        print(f"Updated DNA file written to: {updated_path}")
    else:
        cmds.warning("DNA plugin not loaded. Cannot update DNA file.")
