from __future__ import annotations

"""Topology-independent skin smoothing brush for 3ds Max/pymxs."""

import pymxs
from pymxs import runtime as rt

from tech_connector.game_engine.deformation.spatial_skin_smoothing_service import spatial_smooth_weight_rows


def _skin_modifier(node):
    for modifier in node.modifiers:
        if rt.isKindOf(modifier, rt.Skin):
            return modifier
    raise ValueError("The selected 3ds Max mesh has no Skin modifier.")


def _point_tuple(value):
    return (float(value.x), float(value.y), float(value.z))


def _vertex_surface_area_weights(node):
    """Approximate represented surface area per triangular mesh vertex."""
    weights = [0.0] * int(rt.getNumVerts(node))
    try:
        for face_index in range(1, int(rt.getNumFaces(node)) + 1):
            face = rt.getFace(node, face_index)
            vertices = (int(face.x), int(face.y), int(face.z))
            share = float(rt.meshop.getFaceArea(node, face_index)) / 3.0
            for vertex_index in vertices:
                weights[vertex_index - 1] += share
    except Exception:
        return [1.0] * len(weights)
    positive = [value for value in weights if value > 1.0e-12]
    fallback = sum(positive) / len(positive) if positive else 1.0
    return [value if value > 1.0e-12 else fallback for value in weights]


class SurfaceSpatialSkinBrush:
    def __init__(self, node, *, radius=1.0, strength=0.5, iterations=1,
                 max_influences=8, normal_angle=120.0, max_neighbors=96,
                 cross_region_share=0.45):
        self.node = node
        self.skin = _skin_modifier(node)
        self.radius = float(radius)
        self.strength = float(strength)
        self.iterations = int(iterations)
        self.max_influences = int(max_influences)
        self.normal_angle = float(normal_angle)
        self.max_neighbors = int(max_neighbors)
        self.cross_region_share = float(cross_region_share)
        self.positions = [
            _point_tuple(rt.getVert(node, index) * node.objectTransform)
            for index in range(1, int(rt.getNumVerts(node)) + 1)
        ]
        self.sample_weights = _vertex_surface_area_weights(node)
        self.bone_names = {}
        self.name_to_id = {}
        for index in range(1, int(rt.skinOps.GetNumberBones(self.skin)) + 1):
            name = str(rt.skinOps.GetBoneName(self.skin, index, 0))
            self.bone_names[index] = name
            self.name_to_id[name] = index

    def _rows(self):
        rows = []
        for vertex in range(1, len(self.positions) + 1):
            row = {}
            count = int(rt.skinOps.GetVertexWeightCount(self.skin, vertex))
            for slot in range(1, count + 1):
                bone_id = int(rt.skinOps.GetVertexWeightBoneID(self.skin, vertex, slot))
                name = self.bone_names.get(bone_id)
                if name:
                    row[name] = float(rt.skinOps.GetVertexWeight(self.skin, vertex, slot))
            rows.append(row)
        return rows

    def dab(self, center):
        output, changed = spatial_smooth_weight_rows(
            self.positions,
            self._rows(),
            center=_point_tuple(center),
            radius=self.radius,
            strength=self.strength,
            iterations=self.iterations,
            max_neighbors=self.max_neighbors,
            max_influences=self.max_influences,
            sample_weights=self.sample_weights,
            cross_region_share=self.cross_region_share,
        )
        with pymxs.undo(True, "Surface Spatial Smooth Stroke"):
            for index in changed:
                row = output[index]
                bone_ids = [self.name_to_id[name] for name in row if name in self.name_to_id]
                values = [float(row[name]) for name in row if name in self.name_to_id]
                if bone_ids:
                    rt.skinOps.ReplaceVertexWeights(
                        self.skin,
                        index + 1,
                        rt.Array(*bone_ids),
                        rt.Array(*values),
                    )
        rt.redrawViews()
        return len(changed)

    def _track(self, *args):
        message = str(args[0]).lower() if args else ""
        intersection = next((value for value in args if hasattr(value, "pos")), None)
        if intersection is not None and ("point" in message or "move" in message):
            self.dab(intersection.pos)
        return "abort" not in message

    def activate(self):
        rt.mouseTrack(on=self.node, trackCallback=self._track)
        return self


def activate(**settings):
    if not rt.selection:
        raise ValueError("Select one skinned 3ds Max mesh.")
    return SurfaceSpatialSkinBrush(rt.selection[0], **settings).activate()


def show_ui():
    """Open a native 3ds Max rollout for activating the spatial brush."""
    rt.execute(r'''
global TCSpatialSkinBrushRollout
try(destroyDialog TCSpatialSkinBrushRollout)catch()
rollout TCSpatialSkinBrushRollout "Surface Spatial Skin Brush" width:280
(
    spinner radius_sp "Radius" range:[0.001,1000000,1.0] type:#worldunits
    spinner strength_sp "Strength" range:[0.01,1.0,0.5] scale:0.05
    spinner iterations_sp "Iterations" range:[1,8,1] type:#integer
    spinner influences_sp "Max Influences" range:[1,32,8] type:#integer
    spinner normal_sp "Normal Gate" range:[0,180,120]
    spinner neighbors_sp "Neighbor Limit" range:[2,256,96] type:#integer
    spinner cross_region_sp "Cross-Region Mix" range:[0.05,0.49,0.45] scale:0.05
    button activate_bt "Activate Smooth Brush" width:240
    on activate_bt pressed do
    (
        command = "from max_tools.Rigging.surface_spatial_skin_brush import activate; activate(" +
            "radius=" + (radius_sp.value as string) + "," +
            "strength=" + (strength_sp.value as string) + "," +
            "iterations=" + (iterations_sp.value as string) + "," +
            "max_influences=" + (influences_sp.value as string) + "," +
            "normal_angle=" + (normal_sp.value as string) + "," +
            "max_neighbors=" + (neighbors_sp.value as string) + "," +
            "cross_region_share=" + (cross_region_sp.value as string) + ")"
        python.execute command
    )
)
createDialog TCSpatialSkinBrushRollout
''')
    return True


__all__ = ["SurfaceSpatialSkinBrush", "activate", "show_ui"]
