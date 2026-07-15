import os

import DHI.core.consts as consts
from DHI.modules.dna_viewer.dnalib import dna


class CharacterConfig:
    def __init__(self, config):
        self.current = os.path.dirname(os.path.abspath(__file__))

        self.dna_path = self.prepare_path(config["characterAssets"]["dnaPath"])
        self.dna_path_dir = self.resolve_dna_path_dir(self.dna_path)
        self.character_name = self.resolve_character_name(self.dna_path)
        self.workspace_dir = self.resolve_workspace_path(self.dna_path)
        self.body_scene_path = self.prepare_path(config["characterAssets"]["bodyPath"])
        self.dna_version = self.resolve_dna_version(self.dna_path)
        self.platform = self.resolve_platform()
        """
        Each body has its own body mesh name. This information is needed in later steps of character assembly when
        we are grouping body meshes into their corresponding LOD groups
        """
        self.body_mesh_name = self.resolve_body_mesh_name(self.prepare_path(config["characterAssets"]["bodyPath"]))
        self.shaders_dir_path = config["common"]["shadersDirPath"]
        self.masks_dir_path = config["common"]["masksDirPath"]
        self.scene_orientation_string_value = (self.resolve_scene_orientation_string_value(config["common"]))
        self.scene_orientation = self.resolve_scene_orientation()
        self.scene_flipflop_offset = [0, 0, 2]

        self.gender = self.body_mesh_name.split("_")[0]
        self.height = self.body_mesh_name.split("_")[1]
        self.weight = self.body_mesh_name.split("_")[2]

        """
        Path to head common maps (specular, diffuse, jitter,...). Assets found here are common for all characters and
        are part of plugin
        """
        self.head_maps_path = config["common"]["headMapsPath"]
        self.maps_dir_path = config["characterAssets"]["mapsDirPath"]
        self.db_version_path = os.path.join("assets", self.dna_version)

        """
        Head GUI controls
        """
        self.gui_path = os.path.join(self.current, self.db_version_path, self.resolve_platform(), "head_gui.ma")

        self.flipflops_dir_path = config["characterAssets"]["mapsDirPath"]
        self.flipflops_scene_path = os.path.join(self.current, self.db_version_path, "flipflops", "filplop_mtl_v001.ma")
        """
        Eye controls
        """
        self.ac_path = os.path.join(self.current, self.db_version_path, self.resolve_platform(), "head_ac.ma")
        self.shader_scene_path = os.path.join(self.current,
                                              self.db_version_path,
                                              self.resolve_platform(),
                                              "head_shader.ma",
                                              )
        self.body_shader_scene_path = os.path.join(
            self.current,
            self.db_version_path,
            self.resolve_platform(),
            "body_shader.ma",
        )
        self.light_scene_path = os.path.join(self.current, self.db_version_path, self.resolve_platform(),
                                             "dh_lights.ma")

    def prepare_path(self, val):
        return val.replace("\\", "/")

    def resolve_body_mesh_name(self, body_path):
        file_name = body_path.split("/")[-1]
        return file_name.replace("_rig.ma", "")

    def resolve_dna_path_dir(self, dna_file_path):
        resolved_path = os.path.dirname(dna_file_path).replace("\\", "/")
        return resolved_path.replace("\\", "/")

    def resolve_workspace_path(self, dna_file_path):
        resolved_path = os.path.dirname(dna_file_path).replace("\\", "/")
        resolved_path = os.path.abspath(os.path.join(resolved_path, "../.."))
        return resolved_path.replace("\\", "/")

    def resolve_character_name(self, dna_file_path):
        file_name = dna_file_path.split("/")[-1]
        return file_name.replace(".dna", "")

    def resolve_scene_orientation_string_value(self, config):
        orientation = "z"

        if "scene_orientation" in config:
            orientation = config["scene_orientation"]

        return orientation

    def resolve_scene_orientation(self):
        orientation = self.scene_orientation_string_value

        if orientation == "x":
            return consts.ORIENT_X
        elif orientation == "y":
            return consts.ORIENT_Y
        else:
            return consts.ORIENT_Z

    def resolve_platform(self):
        import platform

        platform = platform.system()

        if platform not in ["Windows", "Linux"]:
            platform = "Windows"

        return platform

    def resolve_dna_version(self, dna_path):
        input_dna = dna.FileStream(
            str(dna_path),
            dna.FileStream.AccessMode_Read,
            dna.FileStream.OpenMode_Binary,
        )
        input_reader = dna.BinaryStreamReader(input_dna)
        input_reader.read()
        db_name = input_reader.getDBName()

        version = "MH.2" if db_name == "DHI" else db_name

        return version

    def __str__(self):
        return """
            DNA path: {}
            DNA Version: {}
            DNA Version Data Path: {}
            Body Scene Path: {}
            Body Mesh Name: {}
            Head Shaders Dir Path: {}
            Head Specific Maps Dir Path: {}
            Head Common Maps Dir Path: {}
            Masks dir path: {}
            Eye controls: {}
            FlipFlops dir path: {}
            Scene Orientation: {}
        """.format(
            self.dna_path,
            self.dna_version,
            self.db_version_path,
            self.body_scene_path,
            self.body_mesh_name,
            self.shaders_dir_path,
            self.maps_dir_path,
            self.head_maps_path,
            self.masks_dir_path,
            self.ac_path,
            self.flipflops_dir_path,
            self.scene_orientation,
        )
