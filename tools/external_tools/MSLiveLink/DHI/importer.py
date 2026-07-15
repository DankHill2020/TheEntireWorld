import os
import time
from shutil import copyfile

import DHI.core.consts as consts
from DHI.modules.dna_viewer.dnalib import dna
from DHI.plugins.Windows.Maya_version import dnacalib as dnac
from DHI.characterConfig import CharacterConfig
from DHI.core.maya.skin_weights_maya_handler import SkinWeightsMayaHandler
from DHI.core.util import MayaUtil
from DHI.modules.dna_viewer import DNA, RigConfig, build_rig
from maya import cmds, mel

from .core.progress_bar import ProgressBar


class CharacterImporter:
    Instance = None

    def __init__(self):
        self.character_config = None
        CharacterImporter.Instance = self

    def process(self, message):
        print("Received message for MetaHuman assembly...")

        confirm_dialog_response = cmds.confirmDialog(
            title="Confirm dialog",
            message="Are you sure you want to import MetaHuman character? All unsaved progress will be lost.",
            button=["Yes", "No"],
            defaultButton="Yes",
            cancelButton="No",
            dismissString="No",
        )

        if confirm_dialog_response == "Yes":
            print("Importing MetaHuman character...")
            self.character_config = CharacterConfig(message["character"])
            print(self.character_config)
            self.execute()

    def execute(self):
        try:
            start_time = time.time()
            ProgressBar.start_progress_bar("Loading character...", 12)

            # start new scene
            cmds.file(new=True, force=True)
            cmds.upAxis(ax=self.character_config.scene_orientation_string_value, rv=True)

            # start import process

            self.pre_import_character()
            self.import_head()
            self.namespace_head_joints()
            self.import_body_and_parent_constraint()
            self.move_body_meshes_to_lod_groups(self.character_config.body_mesh_name)
            self.move_flipflops(self.character_config.body_mesh_name)
            self.import_flipflops_shader(self.character_config.body_mesh_name)
            self.import_body_shader(self.character_config.body_shader_scene_path, self.character_config.body_mesh_name)
            self.import_head_shaders()
            self.import_head_lights()
            self.adjust_head_gui_position()
            self.post_import_character()

            ProgressBar.end_progress_bar()
            print("--- Import finished in %s seconds ---" % (time.time() - start_time))
        except Exception as ex:
            print("Error building scene", ex)
            ProgressBar.end_progress_bar()

    def transform_dna(self, reader):
        """
        Apply dna rotation and translation to given DNA reader.
        :param reader:
        :return:
        """
        calibrated = dnac.DNACalibDNAReader(reader)
        rotate = dnac.RotateCommand(self.character_config.scene_orientation, [0.0, 0.0, 0.0])
        rotate.run(calibrated)
        translate = dnac.TranslateCommand(self.character_config.scene_flipflop_offset)
        translate.run(calibrated)
        path = os.path.join(self.character_config.dna_path_dir, "character.rotate.dna")
        self.save_dna(calibrated, path)
        return DNA(path)

    def save_dna(self, reader, path):
        stream = dna.FileStream(
            path,
            dna.FileStream.AccessMode_Write,
            dna.FileStream.OpenMode_Binary,
        )
        writer = dna.BinaryStreamWriter(stream)
        writer.setFrom(reader)
        writer.write()

        if not dna.Status.isOk():
            status = dna.Status.get()
            raise RuntimeError(f"Error saving DNA: {status.message}")

    def pre_import_character(self):
        ProgressBar.start_progress_bar("Creating DNA backup...", 1)

        os.environ["PROJECT_ROOT"] = self.character_config.workspace_dir
        self.backup_dna_with_geometry()

    def backup_dna_with_geometry(self):
        print("Backup DNA with geometry started...")
        rl_dna_path = self.resolve_rldna_path(self.character_config.dna_path)
        copyfile(self.character_config.dna_path, rl_dna_path)
        print("Backup DNA with geometry finished...")

    def resolve_rldna_path(self, dna_path):
        """
        returns a string with _rl as a sufix
        """
        return dna_path.replace(".dna", "") + "_rl.dna"

    def scene_cleanup(self):
        """Remove sufficient elements from assembled scene"""
        # remove sufficient meshes
        resolved_body_mesh_name = self.character_config.body_mesh_name.replace("_body", "")

        print("Removing sufficient objects")
        if cmds.objExists("ROM_root"):
            cmds.delete("ROM_root")

        if cmds.objExists(resolved_body_mesh_name + "_lod0"):
            cmds.delete(resolved_body_mesh_name + "_lod0")

        if cmds.objExists(resolved_body_mesh_name + "_lod1"):
            cmds.delete(resolved_body_mesh_name + "_lod1")

        if cmds.objExists(resolved_body_mesh_name + "_lod2"):
            cmds.delete(resolved_body_mesh_name + "_lod2")

        if cmds.objExists(resolved_body_mesh_name + "_lod3"):
            cmds.delete(resolved_body_mesh_name + "_lod3")

        if cmds.objExists(resolved_body_mesh_name + "_body_uExport"):
            cmds.delete(resolved_body_mesh_name + "_body_uExport")

        # remove animation joint chain0
        if cmds.objExists("anim:root"):
            cmds.delete("anim:root")

        # remove unused layers
        print("Removing unused layers...")
        if cmds.objExists(resolved_body_mesh_name + "_LOD0_layer"):
            cmds.delete(resolved_body_mesh_name + "_LOD0_layer")

        if cmds.objExists(resolved_body_mesh_name + "_LOD1_layer"):
            cmds.delete(resolved_body_mesh_name + "_LOD1_layer")

        if cmds.objExists(resolved_body_mesh_name + "_LOD2_layer"):
            cmds.delete(resolved_body_mesh_name + "_LOD2_layer")

        if cmds.objExists(resolved_body_mesh_name + "_LOD3_layer"):
            cmds.delete(resolved_body_mesh_name + "_LOD3_layer")

        if cmds.objExists(resolved_body_mesh_name + "_lod0_layer"):
            cmds.delete(resolved_body_mesh_name + "_lod0_layer")

        if cmds.objExists(resolved_body_mesh_name + "_lod1_layer"):
            cmds.delete(resolved_body_mesh_name + "_lod1_layer")

        if cmds.objExists(resolved_body_mesh_name + "_lod2_layer"):
            cmds.delete(resolved_body_mesh_name + "_lod2_layer")

        if cmds.objExists(resolved_body_mesh_name + "_lod3_layer"):
            cmds.delete(resolved_body_mesh_name + "_lod3_layer")

        # remove unused body group and meshes
        if cmds.objExists("export_geo_GRP"):
            cmds.delete("export_geo_GRP")

    def create_joints_group_and_move_joints(self):
        cmds.group(parent="rig", empty=True, name="joints_grp")
        cmds.parent("DHIhead:spine_04", "joints_grp")
        cmds.parent("DHIbody:root", "joints_grp")
        if cmds.objExists("root_drv"):
            cmds.parent("root_drv", "joints_grp")

    def post_import_character(self):
        ProgressBar.step_progress_bar("Assembly done... Cleaning up the scene")
        print("Post import reached...")
        MayaUtil.create_workspace(self.character_config.workspace_dir)
        MayaUtil.remove_geometry_from_dna(self.resolve_rldna_path(self.character_config.dna_path))
        self.remove_unknown_plugins()
        self.scene_cleanup()

        print("Moving body to world space...")
        cmds.parent("root_drv", world=True)

        if cmds.objExists("Skeletons"):
            cmds.delete("Skeletons")

        cmds.select("root")
        body_joint_names = cmds.listRelatives(allDescendents=True, type="joint")
        body_joint_names.append("root")
        body_joints = []
        for maya_joint in body_joint_names:
            # get joint node
            joint_nodes = cmds.ls(maya_joint, type="joint")
            body_joints.append(joint_nodes[0])

        print("Creating control sets...")
        self.create_facial_controls_set()
        self.create_body_joints_set(body_joint_names)
        self.add_joints_to_namespace(consts.BODY_NAMESPACE, body_joints)

        cmds.group(world=True, empty=True, name="rig")
        cmds.parent("head_grp", "rig")
        self.create_joints_group_and_move_joints()

        if cmds.objExists("rig_setup_GRP"):
            cmds.rename("rig_setup_GRP", "rig_setup_grp")
            cmds.parent("rig_setup_grp", "rig")

        cmds.group(parent="rig", empty=True, name="body_grp")
        cmds.group(parent="body_grp", empty=True, name="geometry_grp")
        cmds.parent("body_lod0_grp", "body_grp|geometry_grp")
        cmds.parent("body_lod1_grp", "body_grp|geometry_grp")
        cmds.parent("body_lod2_grp", "body_grp|geometry_grp")
        cmds.parent("body_lod3_grp", "body_grp|geometry_grp")

        MayaUtil.delete_history(consts.MESH_NAMES)

        MayaUtil.save_maya_scene(
            self.character_config.dna_path_dir + "/" + self.character_config.character_name + "_full_rig",
            file_type="mayaBinary",
        )

    def get_gui_translation(self, gender, height):
        val = "_".join([gender, height])
        if val in consts.GUI_TRANSLATIONS:
            if consts.GUI_TRANSLATIONS[val] is not None:
                return [
                    consts.GUI_TRANSLATIONS[val][0],
                    consts.GUI_TRANSLATIONS[val][1],
                    consts.GUI_TRANSLATIONS[val][2],
                ]
            else:
                return None
        else:
            return None

    def get_gui_scale(self, gender, height):
        val = "_".join([gender, height])
        if val in consts.GUI_SCALES:
            return consts.GUI_SCALES[val]
        else:
            return None

    def adjust_head_gui_position(self):
        ProgressBar.step_progress_bar("Adjusting head gui position...")
        print("Adjusting head gui position...")
        resolved_translation = self.get_gui_translation(self.character_config.gender, self.character_config.height)
        resolved_scale = self.get_gui_scale(self.character_config.gender, self.character_config.height)
        if cmds.objExists("GRP_faceGUI"):
            if resolved_translation:
                cmds.select(clear=True)
                cmds.xform("CTRL_faceGUI", translation=resolved_translation, relative=True)

            if resolved_scale:
                cmds.select(clear=True)
                cmds.select("GRP_faceGUI", add=True)
                cmds.scale(resolved_scale, resolved_scale, resolved_scale)

            cmds.xform("CTRL_faceGUI", ws=True, rp=[0, 0, 0])
            cmds.xform("CTRL_faceGUI", ro=self.character_config.scene_orientation, relative=True)
            cmds.xform("GRP_convergenceGUI", translation=[0.0, 0.0, 0.0], relative=True)

    def create_body_joints_set(self, body_joints):
        cmds.select(clear=True)
        for bj in body_joints:
            if cmds.objExists(bj):
                cmds.select(bj, add=True)
        cmds.sets(n="Body joints")

    def create_facial_controls_set(self):
        file_stream = dna.FileStream(
            str(self.character_config.dna_path),
            dna.FileStream.AccessMode_Read,
            dna.FileStream.OpenMode_Binary,
        )
        reader = dna.BinaryStreamReader(file_stream, dna.DataLayer_All)
        reader.read()
        cmds.select(clear=True)
        for i in range(reader.getGUIControlCount()):
            control_name = reader.getGUIControlName(i).split(".")[0]
            if cmds.objExists(control_name):
                cmds.select(control_name, add=True)

        if cmds.objExists("CTRL_C_eye"):
            cmds.select("CTRL_C_eye", add=True)

        if cmds.objExists("CTRL_rigLogicSwitch"):
            cmds.select("CTRL_rigLogicSwitch", add=True)

        if cmds.objExists("CTRL_lookAtSwitch"):
            cmds.select("CTRL_lookAtSwitch", add=True)

        if cmds.objExists("CTRL_C_eyesAim"):
            cmds.select("CTRL_C_eyesAim", add=True)

        if cmds.objExists("CTRL_C_neck_swallow"):
            cmds.select("CTRL_C_neck_swallow", add=True)

        if cmds.objExists("CTRL_L_eyeAim"):
            cmds.select("CTRL_L_eyeAim", add=True)

        if cmds.objExists("CTRL_R_eyeAim"):
            cmds.select("CTRL_R_eyeAim", add=True)

        if cmds.objExists("CTRL_convergenceSwitch"):
            cmds.select("CTRL_convergenceSwitch", add=True)

        if cmds.objExists("CTRL_neckCorrectivesMultiplyerU"):
            cmds.select("CTRL_neckCorrectivesMultiplyerU", add=True)

        if cmds.objExists("CTRL_neckCorrectivesMultiplyerM"):
            cmds.select("CTRL_neckCorrectivesMultiplyerM", add=True)

        if cmds.objExists("CTRL_neckCorrectivesMultiplyerD"):
            cmds.select("CTRL_neckCorrectivesMultiplyerD", add=True)

        if cmds.objExists("CTRL_faceGUIfollowHead"):
            cmds.select("CTRL_faceGUIfollowHead", add=True)

        if cmds.objExists("CTRL_eyesAimFollowHead"):
            cmds.select("CTRL_eyesAimFollowHead", add=True)

        cmds.sets(n="FacialControls")

    def move_body_meshes_to_lod_groups(self, body_mesh_name):
        ProgressBar.step_progress_bar("Organizing body meshes to LOD groups...")
        try:
            # create layer groups
            print("Creating layer groups...")
            cmds.group(parent="geometry_grp", empty=True, name="body_lod0_grp")
            cmds.group(parent="geometry_grp", empty=True, name="body_lod1_grp")
            cmds.group(parent="geometry_grp", empty=True, name="body_lod2_grp")
            cmds.group(parent="geometry_grp", empty=True, name="body_lod3_grp")

            cmds.select(clear=True)
            cmds.select("body_lod3_grp", replace=True)
            cmds.createDisplayLayer(name="body_lod3_layer", noRecurse=True)
            cmds.setAttr("body_lod3_layer.visibility", 0)

            cmds.select("body_lod2_grp", replace=True)
            cmds.createDisplayLayer(name="body_lod2_layer", noRecurse=True)
            cmds.setAttr("body_lod2_layer.visibility", 0)

            cmds.select("body_lod1_grp", replace=True)
            cmds.createDisplayLayer(name="body_lod1_layer", noRecurse=True)
            cmds.setAttr("body_lod1_layer.visibility", 0)

            cmds.select("body_lod0_grp", replace=True)
            cmds.createDisplayLayer(name="body_lod0_layer", noRecurse=True)
            cmds.setAttr("body_lod0_layer.visibility", 1)
            cmds.select(clear=True)

            # move body meshes to world, so we can group them in LOD (no parents allowed)
            print("Moving body meshes to world...")
            scene_body_mesh_name = self.character_config.body_mesh_name.replace("_body", "")

            for i in range(0, 4):
                mesh_name = "{}_lod{}_mesh".format(body_mesh_name, str(i))
                if cmds.objExists(mesh_name):
                    cmds.parent(mesh_name, "body_lod" + str(i) + "_grp")

            # move combined mesh to LOD_0
            resolved_body_mesh_name = (scene_body_mesh_name + "_combined_lod0_mesh")
            print("Moving combined mesh to LOD_0 %s" % resolved_body_mesh_name)

            if cmds.objExists(resolved_body_mesh_name):
                # set default shader
                cmds.select(clear=True)
                cmds.select(resolved_body_mesh_name, r=True)
                mel.eval("sets -e -forceElement initialShadingGroup")
                cmds.hide(resolved_body_mesh_name)
                cmds.parent(resolved_body_mesh_name, "body_lod0_grp")

        except Exception as err:
            print("Error moving body meshes to their corresponding LOD groups", err)
            pass

    def move_flipflops(self, body_mesh_name):
        ProgressBar.step_progress_bar("Moving flip flips...")
        print("Moving flip flops...")
        # move flip flops
        flip_flops_meshes = []
        for i in range(0, 4):
            flip_flops_mesh_name = (body_mesh_name.replace("_body", "") + "_flipflops")
            flip_flops_mesh = "{}_lod{}_mesh".format(flip_flops_mesh_name, str(i))
            flip_flops_meshes.append((str(i), flip_flops_mesh))

            # quick fix for bodies with non-aligned flipflop names
            flip_flops_mesh = "f_med_shs_flipflops_lod%s_mesh" % (str(i))
            flip_flops_meshes.append((str(i), flip_flops_mesh))

            flip_flops_mesh = "OBJ_m_srt_shs_flipflops_lod%s_mesh" % (str(i))
            flip_flops_meshes.append((str(i), flip_flops_mesh))

        for lod, mesh_name in flip_flops_meshes:
            if cmds.objExists(mesh_name):
                cmds.parent(mesh_name, "body_lod" + lod + "_grp")

    def import_flipflops_shader(self, mesh_name):
        ProgressBar.step_progress_bar("Importing flip flops shader...")
        print("Importing flip flops shader...")
        MESH_SHADER_MAPPING = {}
        MESH_SHADER_MAPPING[mesh_name.replace("_body", "") + "_flipflops_lod"] = "flipflop_shader"
        MESH_SHADER_MAPPING["f_med_shs_flipflops_lod"] = "flipflop_shader"
        MESH_SHADER_MAPPING["OBJ_m_srt_shs_flipflops_lod"] = "flipflop_shader"

        MayaUtil.import_shader(self.character_config.flipflops_scene_path, MESH_SHADER_MAPPING)
        MayaUtil.set_map_textures(consts.FLIP_FLOP_SHADERS, self.character_config.flipflops_dir_path)

    def remove_unknown_plugins(self):
        print("Removing unknown plugins...")
        unknown_plugins = cmds.unknownPlugin(query=True, list=True)
        if unknown_plugins:
            for plugin in unknown_plugins:
                try:
                    cmds.unknownPlugin(plugin, remove=True)
                except Exception as err:
                    print(err)

    def namespace_head_joints(self):
        ProgressBar.step_progress_bar("Namespacing head joints...")
        head_joints = [joint for joint in cmds.ls(type="joint")]
        self.add_joints_to_namespace(consts.HEAD_NAMESPACE, head_joints)

    def import_body_and_parent_constraint(self):
        print(f"Importing body scene from path {self.character_config.body_scene_path}")
        ProgressBar.step_progress_bar(f"Importing body scene from path {self.character_config.body_scene_path}")

        head_joints = [joint for joint in cmds.ls(type="joint")]
        # import body to scene
        cmds.file(self.character_config.body_scene_path, op="v=0", typ="mayaAscii", i=True)
        cmds.select("root")
        body_joints = cmds.listRelatives(allDescendents=True, type="joint")

        # fetch all mesh names and skin weights and remove mesh clusters
        body_mesh_name = self.character_config.body_mesh_name
        mesh_names = []
        for i in range(0, 4):
            # body mesh
            mesh_name = "{}_lod{}_mesh".format(body_mesh_name, str(i))
            mesh_names.append(mesh_name)

            # flip flops mesh
            flip_flops_mesh_name = body_mesh_name.replace("_body", "") + ("_flipflops")
            flip_flops_mesh = "{}_lod{}_mesh".format(flip_flops_mesh_name, str(i))
            mesh_names.append(flip_flops_mesh)

        meshes_to_adapt = []
        skin_weights = []

        swmh = SkinWeightsMayaHandler()
        print("Removing skin clusters...")
        for mesh_name in mesh_names:
            if cmds.objExists(mesh_name):
                meshes_to_adapt.append(mesh_name)
                skin_weights.append(swmh.get_skin_weights_from_scene(mesh_name))
                cmds.delete(str(swmh.get_skin_weights_data(mesh_name)[1]))

        print("Moving pelvis...")
        cmds.move(0, 0, 2, 'pelvis_drv', r=True)

        print("Adapting meshes...")
        MayaUtil._adapt_meshes(consts.SCALE, consts.SCALE_PIVOT, [0.0, 0.0, 0.0], mesh_names, consts.TRANSLATE_FACTOR)

        print("Moving pivots...")
        for mesh_name in mesh_names:
            if cmds.objExists(mesh_name):
                cmds.move(0, 0, 0, mesh_name + ".scalePivot", mesh_name + ".rotatePivot", absolute=True)

        print("Applying skin weights...")
        # apply skin weights
        for mesh_name, skin_weight in zip(meshes_to_adapt, skin_weights):
            swmh.create_skin_cluster(
                skin_weight.joints,
                mesh_name,
                mesh_name + "_skinCluster",
                skin_weight.noOfInfluences,
            )
            swmh.setSkinWeightsToScene(mesh_name, skin_weight)

        # add parent constraint for all matching head joints to body joints
        body_joints.append("root")

        for joint in body_joints:
            head_joint = consts.HEAD_NAMESPACE + ":" + joint
            if head_joint in head_joints:
                cmds.parentConstraint(joint, head_joint, maintainOffset=True)
                cmds.scaleConstraint(joint, head_joint, maintainOffset=True)

    def add_joints_to_namespace(self, namespace, joints):
        print(f"Adding joints to namespace {namespace}...")
        for joint in joints:
            if cmds.objExists(joint):
                cmds.rename(joint, ":" + namespace + ":" + joint.replace("", ""))

    def import_head_shaders(self):
        ProgressBar.step_progress_bar(f"Importing head shader: {self.character_config.shader_scene_path}")
        ProgressBar.step_progress_bar("Importing head shader: %s" % self.character_config.shader_scene_path)
        MayaUtil.import_shader(self.character_config.shader_scene_path, consts.MESH_SHADER_MAPPING)

        if self.character_config.platform == "Windows":
            MayaUtil.resolve_scene_shader_paths(consts.SHADERS, self.character_config.shaders_dir_path)

        MayaUtil.set_mask_textures(consts.MASKS, self.character_config.masks_dir_path)
        MayaUtil.set_map_textures(consts.COMMON_MAP_INFOS, self.character_config.head_maps_path)
        MayaUtil.set_map_textures(consts.MAP_INFOS, self.character_config.maps_dir_path)

        MayaUtil.connect_attributes_to_shader(consts.SHADER_ATTRIBUTES_MAPPING)

    def import_body_shader(self, shader_scene_path, body_mesh_name):
        ProgressBar.step_progress_bar("Importing body shader...")
        print("Importing body shader...")
        cmds.file(shader_scene_path, op="v=0", typ="mayaAscii", i=True)

        for lod_lvl in range(0, 4):
            try:
                # Apply shader to all meshes based on LOD level
                resolved_mesh_name = body_mesh_name + "_lod" + str(lod_lvl) + "_mesh"
                cmds.select(resolved_mesh_name, replace=True)
                mel.eval("sets -e -forceElement shader_body_shaderSG")
            except Exception as ex:
                print(f"Error: {ex}")
                print("Skipped adding shader for body mesh %s." % lod_lvl)

        MayaUtil.set_map_textures(consts.BODY_MAP_INFOS, self.character_config.maps_dir_path)

        # does not apply to linux
        if self.character_config.platform == "Windows":
            MayaUtil.resolve_scene_shader_paths(consts.BODY_SHADERS, self.character_config.shaders_dir_path)

        MayaUtil.set_map_textures(consts.COMMON_MAP_INFOS_BODY, self.character_config.head_maps_path)

    def import_head_lights(self):
        ProgressBar.step_progress_bar("Importing head lights...")
        MayaUtil.create_lights(self.character_config.light_scene_path, self.character_config.scene_orientation)

    def import_head(self):
        ProgressBar.step_progress_bar("Importing head...")
        dna = DNA(self.character_config.dna_path)
        dna = self.transform_dna(dna.reader)

        config = RigConfig(
            gui_path=self.character_config.gui_path,
            analog_gui_path=self.character_config.ac_path,
            aas_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets",
                                  self.character_config.dna_version, "additional_assemble_script.py"),
            aas_parameter={"dna": dna, "gender": self.character_config.gender, "height": self.character_config.height},
        )
        build_rig(dna=dna, config=config)
