from __future__ import annotations

"""Read-only SkeletalMesh and Skeleton inspection helpers."""

import json


def _load_mesh(unreal, skeletal_mesh_path):
    mesh = unreal.EditorAssetLibrary.load_asset(str(skeletal_mesh_path or ""))
    if not mesh:
        raise ValueError(f"SkeletalMesh does not exist: {skeletal_mesh_path}")
    if str(mesh.get_class().get_name()) != "SkeletalMesh":
        raise TypeError(
            f"Expected SkeletalMesh, got {mesh.get_class().get_name()}"
        )
    return mesh


def inspect_bones(skeletal_mesh_path, include_hierarchy=True):
    """Return bone names and parent/child readback for a SkeletalMesh."""
    import unreal

    mesh = _load_mesh(unreal, skeletal_mesh_path)
    skeleton = mesh.get_editor_property("skeleton")
    if not skeleton:
        return json.dumps(
            {
                "ok": False,
                "status": "skeleton_not_found",
                "skeletal_mesh_path": str(skeletal_mesh_path or ""),
            },
            indent=2,
        )
    pose = skeleton.get_reference_pose()
    names = [str(name) for name in pose.get_bone_names()]
    rows = []
    if include_hierarchy:
        for name in names:
            parent = str(mesh.get_bone_parent(name))
            children = [str(child) for child in mesh.get_bone_children(name)]
            rows.append(
                {
                    "name": name,
                    "parent": "" if parent in {"", "None"} else parent,
                    "children": children,
                }
            )
    return json.dumps(
        {
            "ok": bool(names),
            "status": "inspected" if names else "no_bones",
            "skeletal_mesh_path": mesh.get_path_name(),
            "skeleton_path": skeleton.get_path_name(),
            "bone_count": len(names),
            "bone_names": names,
            "bones": rows,
            "root_bones": [
                row["name"] for row in rows if not row["parent"]
            ],
        },
        indent=2,
        default=str,
    )


def inspect_sockets(skeletal_mesh_path):
    """Return indexed socket names, parent bones, and local transforms."""
    import unreal

    mesh = _load_mesh(unreal, skeletal_mesh_path)
    rows = []
    for index in range(int(mesh.num_sockets())):
        socket = mesh.get_socket_by_index(index)
        if not socket:
            continue
        rows.append(
            {
                "index": index,
                "socket_name": str(socket.get_editor_property("socket_name")),
                "bone_name": str(socket.get_editor_property("bone_name")),
                "relative_location": str(
                    socket.get_editor_property("relative_location")
                ),
                "relative_rotation": str(
                    socket.get_editor_property("relative_rotation")
                ),
                "relative_scale": str(
                    socket.get_editor_property("relative_scale")
                ),
            }
        )
    skeleton = mesh.get_editor_property("skeleton")
    return json.dumps(
        {
            "ok": True,
            "status": "inspected",
            "skeletal_mesh_path": mesh.get_path_name(),
            "skeleton_path": skeleton.get_path_name() if skeleton else "",
            "socket_count": len(rows),
            "socket_names": [row["socket_name"] for row in rows],
            "sockets": rows,
        },
        indent=2,
        default=str,
    )
