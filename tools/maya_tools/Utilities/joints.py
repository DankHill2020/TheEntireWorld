import maya.cmds as cmds


def find_skinned_or_top_joints(namespace=''):
    """
    Finds the topmost joint in the skinned joint hierarchy. If no skinClusters exist,
    walks up from any joint in the namespace and returns the highest ancestor.

    :param namespace: Namespace string with colon suffix (e.g., 'MyChar:')
    :return: Name of the topmost joint (str)
    """

    def get_topmost_joint(joint):
        current = joint
        while True:
            parent = cmds.listRelatives(current, parent=True, type='joint')
            if not parent:
                return current
            current = parent[0]

    assembly_nodes = cmds.ls(assemblies=True)

    for node in assembly_nodes:

        if cmds.objectType(node) == "joint" and namespace in node:
            return [node]
    skin_clusters = cmds.ls(type='skinCluster')
    if len(skin_clusters):
        skinned_joints = set()

        for sc in skin_clusters:
            influences = cmds.skinCluster(sc, q=True, inf=True) or []
            skinned_joints.update(influences)
        if namespace:
            skinned_joints = [j for j in skinned_joints if j.startswith(namespace)]
        if skinned_joints:
            topmost_joints = set(get_topmost_joint(joint) for joint in skinned_joints)

            if len(topmost_joints) > 1:
                print(f"Warning: Multiple top-level skinned joints found: {list(topmost_joints)}. Using the first.")
            return list(topmost_joints)
    else:
        all_joints = cmds.ls(type='joint') or []
        namespace_joints = [j for j in all_joints if j.startswith(namespace)]

        if not namespace_joints:
            return None

        topmost_candidates = set(get_topmost_joint(j) for j in namespace_joints)

        if len(topmost_candidates) > 1:
            print(f"Warning: Multiple top-level joints found: {list(topmost_candidates)}. Using the first.")

        return list(topmost_candidates)