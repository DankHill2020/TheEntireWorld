import os

import maya.mel as mel
from maya import cmds
from DHI.core.maya.adapter import AdditionalAdapterBuilder

class MayaUtil:
    ATTRIBUTE_NAMES = ["tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"]
    @staticmethod
    def create_workspace(maya_project_path):
        if os.path.exists(maya_project_path):
            cmd = 'setProject "' + maya_project_path + '";'
            mel.eval(cmd)

    @staticmethod
    def delete_history(mesh_names):
        for meshName in mesh_names:
            if cmds.objExists(meshName):
                cmds.select(clear=True)
                cmds.select(meshName)
                mel.eval('doBakeNonDefHistory( 1, {"prePost" });')

    @staticmethod
    def import_shader(shader_scene_path, mesh_shader_mapping):
        print("Shader scene imported")
        cmds.file(shader_scene_path, options="v=0", type="mayaAscii", i=True)
        try:
            items = mesh_shader_mapping.iteritems()
        except:
            items = mesh_shader_mapping.items()
        for meshName, shaderName in items:
            for lodLvl in range(0, 8):
                try:
                    # Apply shader to all meshes based on LOD level
                    resolved_mesh_name = meshName + str(lodLvl) + "_mesh"
                    shader = "shader_" + shaderName
                    cmds.select(resolved_mesh_name, replace=True)
                    mel.eval("sets -e -forceElement " + shader + "SG")
                except:
                    print("Skipped adding shader for mesh %s." % meshName)

    @staticmethod
    def set_map_textures(map_infos, folder_name):
        for mapInfo in map_infos:
            node_name = "mapFile_" + mapInfo[0]
            if mapInfo[1]:
                node_name = "baseMapFile_" + mapInfo[0]

            if not cmds.objExists(node_name):
                continue

            file_texture_name = cmds.getAttr(node_name + ".fileTextureName")
            texture_folder_name, texture_file_name = os.path.split(file_texture_name)
            texture_folder_name = folder_name
            cmds.setAttr(
                node_name + ".fileTextureName",
                texture_folder_name + "/" + texture_file_name,
                type="string",
            )

    @staticmethod
    def set_mask_textures(masks, folder_name):
        for mask in masks:
            node_name = "maskFile_" + mask

            if not cmds.objExists(node_name):
                continue

            file_texture_name = cmds.getAttr(node_name + ".fileTextureName")
            texture_folder_name, texture_file_name = os.path.split(file_texture_name)
            texture_folder_name = folder_name
            cmds.setAttr(
                node_name + ".fileTextureName",
                texture_folder_name + "/" + texture_file_name,
                type="string",
            )

    @staticmethod
    def resolve_scene_shader_paths(shaders, folder_name):
        for shader in shaders:
            node_name = "shader_" + shader
            if not cmds.objExists(node_name):
                continue
            file_shader_name = cmds.getAttr(node_name + ".shader")
            shader_folder_name, shader_file_name = os.path.split(file_shader_name)
            shader_folder_name = folder_name
            cmds.setAttr(
                node_name + ".shader",
                shader_folder_name + "/" + shader_file_name,
                type="string",
            )

    @staticmethod
    def create_lights(lights_file_path, orient):
        print("Creating lights...")
        cmds.file(lights_file_path, defaultNamespace=True, i=True)

        # Set viewport 2.0 properties needed:
        model_panel_list = []
        model_editor_list = cmds.lsUI(editors=True)
        for my_model_panel in model_editor_list:
            if my_model_panel.find("modelPanel") != -1:
                model_panel_list.append(my_model_panel)
                try:
                    for modelPanel in model_panel_list:
                        cmds.modelEditor(modelPanel=modelPanel, lights=True, displayAppearance='smoothShaded',
                                         nurbsCurves=True, joints=False, nurbsSurfaces=True, polymeshes=True,
                                         textures=True, dl="all", useDefaultMaterial=False, backfaceCulling=False,
                                         displayTextures=True, grid=False)
                except:
                    print("An error has occured importing lights scene!.\n")

        cmds.xform("Lights", ro=orient)
        cmds.makeIdentity("Lights", apply=True)


    @staticmethod
    def save_maya_scene(file_path, file_type="mayaAscii"):
        print(f"Saving maya scene to {file_path}.")
        cmds.file(rename=file_path)
        cmds.file(save=True, type=file_type)


    @staticmethod
    def load_plugin(name, path, platform, forced_extension=None):
        """
        Loads plugin for given name.
        @param name: Plugin name. (string)
        @param path: Path to plugin. (string)
        @param platform: OS platform. (string)
        @param forced_extension: Forced extension. (string)
        """
        print(f"Loading plugin {name}.")
        is_loaded = False
        extension = ".so" if platform == "Linux" else ".mll"

        if forced_extension:
            extension = forced_extension

        if not (cmds.pluginInfo(name, query=True, loaded=True)):
            try:
                print(f"Loading plugin: {path} / {name}{extension}")
                cmds.loadPlugin(path + "/" + name + extension)
                is_loaded = True
            except:
                print(f"Error loading plugin {name}")
                pass
        else:
            print(f"Plugin {name} already loaded")
            is_loaded = True
        return is_loaded


    @staticmethod
    def connect_attributes_to_shader(shader_attributes_mapping):
        print("Connecting attributes to shader...")
        try:
            items = shader_attributes_mapping.iteritems()
        except Exception as ex:
            print(f"Error: {ex}")
            items = shader_attributes_mapping.items()

        for frm_attribute, shaderAttribute in items:
            if cmds.objExists(frm_attribute) and cmds.objExists(shaderAttribute):
                cmds.connectAttr(frm_attribute, shaderAttribute, force=True)

    @staticmethod
    def get_objects(name, type=None, root=False):
        """
        Gets scene objects by name and type.

        @param name: Object name. (string)
        @param type: Object type. (string)
        @param root: Indicates if object is root object. (boolean)
        @return List of object node instances. (DagNode[])
        """

        obj_name = "|" + name if root else name
        obj_nodes = []
        if type:
            obj_nodes = cmds.ls(obj_name, type=type)
        else:
            obj_nodes = cmds.ls(obj_name)
        return obj_nodes

    @staticmethod
    def remove_geometry_from_dna(dna_file_path):
        import dna

        try:
            file_stream = dna.FileStream(
                str(dna_file_path),
                dna.FileStream.AccessMode_Read,
                dna.FileStream.OpenMode_Binary,
            )
            reader = dna.StreamReader(file_stream, dna.DataLayer_Behavior)
            reader.read()

            stream = dna.FileStream(
                str(dna_file_path),
                dna.FileStream.AccessMode_Write,
                dna.FileStream.OpenMode_Binary,
            )
            writer = dna.StreamWriter(stream)

            writer.setFrom(reader)
            writer.write()
        except Exception as ex:
            print(ex)

    @staticmethod
    def _adapt_meshes(scale, scale_pivot, orient, mesh_names, translate):
        mesh_adapter = AdditionalAdapterBuilder.buildMeshAA(scale, scale_pivot, orient, translate)

        for mesh_name in mesh_names:
            try:
                for attr_name in MayaUtil.ATTRIBUTE_NAMES:
                    cmds.setAttr(mesh_name + "." + attr_name, lock=0)
                mesh_adapter.adapt(mesh_name)
                for attr_name in MayaUtil.ATTRIBUTE_NAMES:
                    cmds.setAttr(mesh_name + "." + attr_name, lock=1)
                cmds.select(mesh_name, replace=True)
                mel.eval('doBakeNonDefHistory( 1, {"pre" });')
                cmds.polySoftEdge(mesh_name, a=180, ch=False)
            except Exception as ex:
                print(ex)
                print("Mesh %s adaptation skipped." % mesh_name)
        cmds.select(clear=True)
