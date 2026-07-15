# Copyright Epic Games, Inc. All Rights Reserved.

import re

import maya.api.OpenMaya as om2
import maya.api.OpenMayaAnim as oma2
from maya import cmds, mel

from DHI.core.maya.skin_weights import MayaSkinWeights
from DHI.core.util import MayaUtil

class SkinWeightsMayaHandler:
    """
    Skin weights Maya handler.

    Contains methods for manipulation with skin weights and split maps in scene.
    """

    def __init__(self):
        super().__init__()

    def get_skin_cluster(self, obj_name):
        """
        Gets skin cluster object for given object name.

        @param obj_name: Object name. (string)
        @return Skin cluster object. (SkinCluster)
        """

        skin_cluster = None
        skin_cluster_name = mel.eval("findRelatedSkinCluster " + obj_name)
        if skin_cluster_name:
            skin_cluster = skin_cluster_name
        return skin_cluster

    def get_skin_cluster_influence(self, skin_cluster):
        """
        Gets skin cluster influence joint names.

        This method is implemented because of differences in API in
        Maya 2009 and Maya 2012 for method skinCluster.getInfluence().
        Maya 2009 returns list of strings representing joint names.
        Maya 2012 returns list of Joint objects.
        This method should be called, and it returns list of strings
        representing joint names, like in Maya 2009.
        @param skin_cluster: Skin cluster object. (SkinCluster)
        @return List of joint names. (string[])
        """

        influences = cmds.skinCluster(skin_cluster, q=True, inf=True)
        if influences and (not isinstance(influences[0], bytes) and not isinstance(influences[0], str)):
            influences = [obj.name() for obj in influences]
        return influences

    @staticmethod
    def get_object(name, type=None, root=False, strict=False):
        """
        Gets exactly one scene object by name.

        If multiple objects exist with same name, first one will be returned.
        @param name: Object name. (string)
        @param type: Object type. (string)
        @param root: Indicates if object is root object. (boolean)
        @param strict: If object does not exist and strict is set to True, error will be raised. (boolean)
        @return Object node instance if object exists, otherwise None.
        @throws MayaSceneError: If node is not unique and strict is set to True.
        """

        obj_nodes = MayaUtil.get_objects(name, type=type, root=root)
        if strict:
            if len(obj_nodes) == 0:
                raise Exception("Unable to find object: " + name)
            if len(obj_nodes) > 1:
                raise Exception("Multiple objects with name: " + name)
        if obj_nodes:
            return obj_nodes[0]
        return None

    def create_skin_cluster(self, influences, mesh, skin_cluster_name, max_influences=4, skinning_method=0):
        """
        Creates skin cluster deformer for given list of joints and mesh.

        @param influences: List of influence objects. (DagNode[] or string[])
        @param mesh: Mesh for which is created skin cluster. (DagNode or string)
        @param skin_cluster_name: Newly created skin cluster name. (string)
        @param max_influences: Maximum number of influences per vertex. (int)
        @param skinning_method: Skinning method, linear, dual quaternion... (int)
        @return Skin cluster object. (SkinCluster)
        """

        cmds.select(influences[0], replace=True)
        cmds.select(mesh, add=True)
        skin_cluster = cmds.skinCluster(
            toSelectedBones=True,
            name=skin_cluster_name,
            maximumInfluences=max_influences,
            skinMethod=skinning_method,
            obeyMaxInfluences=True,
        )
        if len(influences) > 1:
            cmds.skinCluster(skin_cluster, edit=True, addInfluence=influences[1:], weight=0.0)
        return skin_cluster

    # ---------------------------
    # Scene skin weights methods
    # ---------------------------
    def get_skin_weights_data(self, mesh_name):
        """
        Gets mesh Maya node and skin cluster for given mesh.

        @param mesh_name: Mesh name. (string)
        @return Mesh node object and skin cluster object. ([DagNode, SkinCluster])
        @throws  MayaSceneError: If unable to find unique mesh and its skin cluster.
        """

        # find mesh
        mesh_node = self.get_object(mesh_name, type="transform", root=False, strict=True)
        if not mesh_node or not cmds.objectType(mesh_node, isType="transform"):
            raise RuntimeWarning(f"Unable to find mesh: {mesh_name}")

        # find skinCluster
        skin_cluster = self.get_skin_cluster(mesh_name)
        if not skin_cluster:
            raise RuntimeWarning(f"Unable to find skin for given mesh: {mesh_name}")
        return (mesh_node, skin_cluster)

    def get_skin_weights_from_scene(self, mesh_name):
        """
        Gets skin weights data from scene.

        @param mesh_name: Mesh name to work with. (string)
        @return Skin weights data. (trilateral.api.maya.node.MayaSkinWeights)
        @throws MayaSceneError: If unable to find mesh or skin cluster.
        """

        skin_cluster_name = self.get_skin_weights_data(mesh_name)[1]
        skin_weights = MayaSkinWeights()

        # joints
        skin_weights.noOfInfluences = cmds.skinCluster(
            skin_cluster_name, q=True, maximumInfluences=True
        )  # .getMaximumInfluences()
        skin_weights.skinningMethod = cmds.skinCluster(skin_cluster_name, q=True, skinMethod=True)  # .getSkinMethod()
        skin_weights.joints = self.get_skin_cluster_influence(skin_cluster_name)

        # weights
        # .getWeights(meshName + ".vtx[:]")
        vertex_count = cmds.polyEvaluate(mesh_name, v=True)

        sel_list = om2.MSelectionList()
        sel_list.add(mesh_name)
        sel_list.add(skin_cluster_name)

        shape_dag = sel_list.getDagPath(0)
        skin_dep = sel_list.getDependNode(1)
        skin_fn = oma2.MFnSkinCluster(skin_dep)

        comp_ids = list(range(vertex_count))
        single_fn = om2.MFnSingleIndexedComponent()
        shape_comp = single_fn.create(om2.MFn.kMeshVertComponent)
        single_fn.addElements(comp_ids)

        flat_weights, inf_count = skin_fn.getWeights(shape_dag, shape_comp)

        weight_plug = skin_fn.findPlug("weights", False)
        list_plug = skin_fn.findPlug("weightList", False).attribute()

        inf_dags = skin_fn.influenceObjects()
        inf_count = len(inf_dags)
        sparse_map = {skin_fn.indexForInfluenceObject(inf_dag): i for i, inf_dag in enumerate(inf_dags)}

        for c, comp_id in enumerate(comp_ids):
            weight_plug.selectAncestorLogicalIndex(comp_id, list_plug)
            valid_ids = weight_plug.getExistingArrayAttributeIndices()

            # ignore non-valid influences
            valid_ids = set(valid_ids) & sparse_map.keys()

            vertex_weights = []
            skin_weights.verticesInfo.append(vertex_weights)
            flat_index = c * inf_count
            for valid_id in sorted(valid_ids):
                inf_index = sparse_map[valid_id]
                if flat_weights[flat_index + inf_index]:
                    vertex_weights.append(inf_index)
                    vertex_weights.append(flat_weights[flat_index + inf_index])

        return skin_weights

    def setSkinWeightsToScene(self, mesh_name, skin_weights):
        """
        Sets skin weights to scene.
        This function will guess all influences are given to first influence in list for all vertices.
        Function will set only this influence to 0.0 before setting provided skin weights.
        If this is not case and current skin has some weights that don't exist in provided skinWeights,
        resulting skin after set function might not be normalized anymore.

        @param mesh_name: Mesh name to work with. (string)
        @param skin_weights: Skin weights data. (trilateral.api.maya.node.MayaSkinWeights)
        @throws MayaSceneError: If unable to find unique mesh.
        """

        mesh_node, skin_cluster_name = self.get_skin_weights_data(mesh_name)
        vtx_ids = range(cmds.polyEvaluate(mesh_node, vertex=True))

        # prepare mapping data
        file_joint_mapping = []
        for jointName in skin_weights.joints:
            # .indexForInfluenceObject(jointName))
            file_joint_mapping.append(self.get_index_for_influence_object(skin_cluster_name, jointName))

        # import skin weights
        temp_str = skin_cluster_name + ".wl["
        for vtx_id in vtx_ids:
            # file vertices weights
            vtx_info = skin_weights.verticesInfo[vtx_id]

            # set all skin weights to zero
            vtx_str = temp_str + str(vtx_id) + "].w["
            cmds.setAttr(vtx_str + "0]", 0.0)

            # import skin weights
            for w in range(0, len(vtx_info), 2):
                cmds.setAttr(vtx_str + str(file_joint_mapping[vtx_info[w]]) + "]", vtx_info[w + 1])


    def get_index_for_influence_object(self, skin_cluster_name, joint_name):
        sel = om2.MGlobal.getSelectionListByName(skin_cluster_name)
        skin_node = sel.getDependNode(0)
        skin_cluster = oma2.MFnSkinCluster(skin_node)
        influence_dags = skin_cluster.influenceObjects()
        inf_dag = [i.partialPathName() for i in influence_dags]
        return inf_dag.index(joint_name)

    def set_skin_weights_to_scene(self, mesh_name, skin_weights):
        influences_count = len(skin_weights.joints)
        # zero all influences
        single_w = [0.0] * influences_count * len(skin_weights.verticesInfo)
        for vtx_id, vtx_info in enumerate(skin_weights.verticesInfo):
            for i, jnt_index in enumerate(vtx_info[::2]):
                single_w[vtx_id * influences_count + jnt_index] = vtx_info[i * 2 + 1]
        single_weights = om2.MDoubleArray(single_w)

        # get shape
        mesh_path = om2.MSelectionList().add(mesh_name).getDagPath(0)

        # Find the skin cluster connected to the mesh
        skin_cluster_name = cmds.ls(cmds.listHistory(mesh_name), type="skinCluster")[0]
        skin_cluster = oma2.MFnSkinCluster(om2.MSelectionList().add(skin_cluster_name).getDependNode(0))

        inf_dags = skin_cluster.influenceObjects()
        inf_index = om2.MIntArray()
        for x in range(len(inf_dags)):
            inf_index.append(int(skin_cluster.indexForInfluenceObject(inf_dags[x])))

        # get influences
        component = om2.MFnSingleIndexedComponent()
        vertex_comp = component.create(om2.MFn.kMeshVertComponent)
        indices = [int(re.findall(r"\d+", vert)[-1]) for vert in cmds.ls(f"{mesh_name}.vtx[*]", fl=1)]
        component.addElements(indices)
        cmds.setAttr(f"{skin_cluster_name}.normalizeWeights", 0)
        skin_cluster.setWeights(mesh_path, vertex_comp, inf_index, single_weights, False)
        cmds.setAttr(f"{skin_cluster_name}.normalizeWeights", 1)
