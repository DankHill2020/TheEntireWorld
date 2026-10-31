import maya.cmds as cmds
import maya.mel as mel
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.OpenMaya as om1
import maya.OpenMayaUI as omui1
from collections import OrderedDict
from array import array
import difflib
import importlib
import json
import math
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET

from tech_connector.game_engine.deformation import spatial_skin_smoothing_service as _spatial_smoothing

# Maya keeps imported modules alive between tool reloads.  Refresh the shared
# service when this adapter expects a newer API, avoiding a required Maya restart
# after updating the tools checkout.
if not all(hasattr(_spatial_smoothing, name) for name in (
        "detect_weight_outlier_indices", "detect_deformation_ripple_indices")):
    _spatial_smoothing = importlib.reload(_spatial_smoothing)
detect_weight_outlier_indices = _spatial_smoothing.detect_weight_outlier_indices
detect_deformation_ripple_indices = _spatial_smoothing.detect_deformation_ripple_indices
estimate_spatial_smoothing_radius = _spatial_smoothing.estimate_spatial_smoothing_radius

try:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance


_ACTIVE_SURFACE_SMOOTH_BRUSH = None
_SURFACE_SMOOTH_BRUSH_KEY_FILTER = None
_SURFACE_SMOOTH_BRUSH_TOOL_JOB = None


class _SurfaceSmoothBrushOverlay(QtWidgets.QWidget):
    """Mouse-transparent viewport overlay for the brush radius."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.center = None
        self.radius = 0.0
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.hide()

    def set_circle(self, center, radius):
        self.center = QtCore.QPointF(float(center[0]), float(center[1]))
        self.radius = max(1.0, float(radius))
        self.show()
        self.raise_()
        self.update()

    def clear_circle(self):
        self.center = None
        self.hide()

    def paintEvent(self, _event):
        if self.center is None:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 220, 40, 235), 2.0))
        painter.drawEllipse(self.center, self.radius, self.radius)
        painter.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20, 210), 1.0))
        painter.drawEllipse(self.center, max(1.0, self.radius - 2.0), max(1.0, self.radius - 2.0))
        painter.end()


def transfer_skin_weights_from_selection(remove_unused_influences=True):
    """
    Transfer skin weights from selected source meshes to the last selected mesh.
    """
    selection = cmds.ls(selection=True)

    if len(selection) < 2:
        cmds.error("Select one or more source meshes and a target mesh last.")
        return False

    return transfer_skin_weights(
        source_meshes=selection[:-1],
        target_mesh=selection[-1],
    )


def transfer_skin_weights(
    source_meshes,
    target_mesh,
):
    """
    Transfer skin weights from source meshes to a target mesh.

    Args:
        source_meshes (list[str])
        target_mesh (str)

    Returns:
        dict | bool
    """
    cmds.undoInfo(openChunk=True)

    try:
        if _has_skin_cluster(target_mesh):
            cmds.warning("Target mesh already has a skinCluster.")
            return False

        skin_data = _collect_skin_data(source_meshes)
        if not skin_data["influences"]:
            cmds.warning("No valid influences found on source meshes.")
            return False

        target_skin = _create_target_skin(target_mesh, skin_data)
        _copy_weights(source_meshes, target_mesh)

        cmds.setAttr(
            f"{target_mesh}.inheritsTransform",
            skin_data["inherits_transform"]
        )

        return {
            "skinCluster": target_skin,
            "influences": skin_data["influences"]
        }

    except Exception as exc:
        cmds.warning(f"Skin weight transfer failed: {exc}")
        return False

    finally:
        cmds.undoInfo(closeChunk=True)


def _has_skin_cluster(mesh):
    return bool(cmds.ls(cmds.listHistory(mesh), type="skinCluster"))


def _find_skin_cluster(mesh):
    # History is ordered from the visible shape upstream, so prefer its first
    # skinCluster. A broad listConnections query can return an older cluster
    # first on meshes that have been rebound or carry parallel deformers.
    history = cmds.listHistory(mesh, pruneDagObjects=True) or []
    skins = cmds.ls(history, type="skinCluster") or []
    if not skins:
        skins = cmds.ls(cmds.listConnections(mesh, type="skinCluster"), type="skinCluster") or []
    return skins[0] if skins else None


def _mesh_shape(mesh):
    """Resolve a polygon transform or shape to its visible mesh shape."""
    matches = cmds.ls(mesh, long=True) or []
    if not matches:
        raise ValueError("Mesh does not exist: {}".format(mesh))
    node = matches[0]
    if cmds.nodeType(node) == "mesh":
        return node
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, type="mesh", fullPath=True) or []
    if not shapes:
        raise ValueError("Selection is not a polygon mesh: {}".format(mesh))
    return shapes[0]


def _selected_mesh_and_vertices():
    """Return one selected mesh and optional explicitly selected vertices."""
    selection = cmds.ls(selection=True, flatten=True, long=True) or []
    components = cmds.filterExpand(selection, selectionMask=31) or []
    if components:
        meshes = list(OrderedDict.fromkeys(item.split(".vtx[", 1)[0] for item in components))
        if len(meshes) != 1:
            raise ValueError("Select vertices from only one skinned mesh.")
        indices = []
        for item in cmds.ls(components, flatten=True) or []:
            match = re.search(r"\.vtx\[(\d+)\]$", item)
            if match:
                indices.append(int(match.group(1)))
        return meshes[0], sorted(set(indices))

    meshes = []
    for node in cmds.ls(selection=True, objectsOnly=True, long=True) or []:
        try:
            shape = _mesh_shape(node)
        except ValueError:
            continue
        meshes.append((cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0])
    meshes = list(OrderedDict.fromkeys(meshes))
    if len(meshes) != 1:
        raise ValueError("Select one skinned mesh, or vertices from one skinned mesh.")
    return meshes[0], None


def _vertex_surface_area_weights(mesh_path):
    """Return per-vertex world-space area weights for irregular meshes.

    Plain vertex averaging heavily favors densely tessellated patches.  That
    can make a spatial brush appear to do nothing when the nearby surface on
    the other side of a bad topology boundary has far fewer vertices.  Area
    weights approximate integration over the actual surface instead.
    """
    vertex_count = om.MFnMesh(mesh_path).numVertices
    weights = [0.0] * vertex_count
    polygon_iterator = om.MItMeshPolygon(mesh_path)
    while not polygon_iterator.isDone():
        vertices = polygon_iterator.getVertices()
        if vertices:
            share = float(polygon_iterator.getArea(om.MSpace.kWorld)) / float(len(vertices))
            for vertex_index in vertices:
                weights[int(vertex_index)] += share
        polygon_iterator.next()

    positive = [value for value in weights if value > 1.0e-12]
    fallback = sum(positive) / float(len(positive)) if positive else 1.0
    return [value if value > 1.0e-12 else fallback for value in weights]


def _pre_skin_surface_points(transform, visible_shape, vertex_count):
    """Return the undeformed sibling mesh points when Maya exposes a shapeOrig."""
    candidates = cmds.listRelatives(
        transform, shapes=True, fullPath=True, type="mesh"
    ) or []
    for candidate in candidates:
        if candidate == visible_shape:
            continue
        if not cmds.getAttr(candidate + ".intermediateObject"):
            continue
        selection = om.MSelectionList()
        selection.add(candidate)
        path = selection.getDagPath(0)
        mesh_fn = om.MFnMesh(path)
        if mesh_fn.numVertices == vertex_count:
            return mesh_fn.getPoints(om.MSpace.kWorld)
    return None


def smooth_skin_weights_spatial_from_selection(
        radius=1.0, iterations=4, strength=0.5, max_influences=4,
        normal_angle=75.0, max_neighbors=48, cross_region_share=0.10,
        entire_mesh=False, automatic_radius=False, artifact_only=False):
    """Smooth the selected skin using surface position instead of edge topology.

    The automatic batch path intentionally ignores a component subset.  It is
    the one-click alternative to painting and should repair the full selected
    skinned surface, including disconnected and mixed-density regions.
    """
    mesh, vertices = _selected_mesh_and_vertices()
    return smooth_skin_weights_spatial(
        mesh,
        vertex_indices=None if entire_mesh else vertices,
        radius=radius,
        iterations=iterations,
        strength=strength,
        max_influences=max_influences,
        normal_angle=normal_angle,
        max_neighbors=max_neighbors,
        adaptive_radius=True,
        cross_region_share=cross_region_share,
        automatic_radius=automatic_radius,
        topology_share=0.8,
        artifact_only=artifact_only,
    )


def smooth_skin_weights_spatial(
        mesh,
        vertex_indices=None,
        radius=1.0,
        iterations=4,
        strength=0.5,
        max_influences=4,
        normal_angle=75.0,
        max_neighbors=48,
        sample_weights=None,
        adaptive_radius=False,
        cross_region_share=0.45,
        automatic_radius=False,
        topology_share=0.0,
        artifact_only=False,
        outlier_threshold=0.06,
):
    """Diffuse weights through world-space neighborhoods, ignoring mesh edges.

    The normal-angle gate reduces bleeding between nearby opposing surfaces.
    Locked influences retain their exact input weights.
    """
    radius = float(radius)
    requested_radius = radius
    iterations = int(iterations)
    strength = float(strength)
    max_influences = int(max_influences)
    normal_angle = float(normal_angle)
    max_neighbors = int(max_neighbors)
    cross_region_share = max(0.0, min(0.49, float(cross_region_share)))
    topology_share = max(0.0, min(1.0, float(topology_share)))
    if radius <= 0.0:
        raise ValueError("Radius must be greater than zero.")
    if iterations < 1:
        raise ValueError("Iterations must be at least one.")
    if not 0.0 < strength <= 1.0:
        raise ValueError("Strength must be greater than zero and at most one.")
    if max_influences < 1:
        raise ValueError("Maximum influences must be at least one.")
    if max_neighbors < 2:
        raise ValueError("Neighbor limit must be at least two.")

    shape = _mesh_shape(mesh)
    transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0]
    skin = _find_skin_cluster(shape) or _find_skin_cluster(transform)
    if not skin:
        raise ValueError("Mesh has no skinCluster: {}".format(transform))

    maya_selection = om.MSelectionList()
    maya_selection.add(shape)
    mesh_path = maya_selection.getDagPath(0)
    maya_selection.clear()
    maya_selection.add(skin)
    skin_fn = oma.MFnSkinCluster(maya_selection.getDependNode(0))
    mesh_fn = om.MFnMesh(mesh_path)
    vertex_count = mesh_fn.numVertices

    if vertex_indices is None:
        targets = list(range(vertex_count))
    else:
        targets = sorted(set(int(index) for index in vertex_indices))
        if any(index < 0 or index >= vertex_count for index in targets):
            raise ValueError("Selected vertex index is outside the mesh.")
    if not targets:
        raise ValueError("No vertices were selected for smoothing.")

    all_component_fn = om.MFnSingleIndexedComponent()
    all_component = all_component_fn.create(om.MFn.kMeshVertComponent)
    all_component_fn.addElements(om.MIntArray(range(vertex_count)))
    weights, influence_count = skin_fn.getWeights(mesh_path, all_component)
    working = array("d", weights)
    original = array("d", weights)

    locked = set()
    for index, influence in enumerate(skin_fn.influenceObjects()):
        lock_plug = influence.fullPathName() + ".liw"
        if cmds.objExists(lock_plug) and cmds.getAttr(lock_plug):
            locked.add(index)

    points = mesh_fn.getPoints(om.MSpace.kWorld)
    normals = mesh_fn.getVertexNormals(True, om.MSpace.kWorld)
    if sample_weights is None:
        sample_weights = _vertex_surface_area_weights(mesh_path)
    else:
        sample_weights = [float(value) for value in sample_weights]
        if len(sample_weights) != vertex_count:
            raise ValueError("Surface-area weight count does not match the mesh vertex count.")
    auto_sized_radius = False
    if automatic_radius:
        radius = estimate_spatial_smoothing_radius(
            [(point.x, point.y, point.z) for point in points],
            sample_weights=sample_weights,
        )
        auto_sized_radius = True
    dominant_influences = []
    for vertex_index in range(vertex_count):
        offset = vertex_index * influence_count
        dominant_influences.append(max(
            range(influence_count),
            key=lambda influence: original[offset + influence],
        ))

    connected_vertices = [[] for _index in range(vertex_count)]
    vertex_iterator = om.MItMeshVertex(mesh_path)
    while not vertex_iterator.isDone():
        vertex_index = int(vertex_iterator.index())
        connected_vertices[vertex_index] = [
            int(value) for value in vertex_iterator.getConnectedVertices()
        ]
        vertex_iterator.next()

    inspected_vertex_count = len(targets)
    detected_artifacts = ()
    if artifact_only:
        weight_rows = []
        for vertex_index in range(vertex_count):
            offset = vertex_index * influence_count
            weight_rows.append({
                str(influence): original[offset + influence]
                for influence in range(influence_count)
                if original[offset + influence] > 1.0e-12
            })
        weight_artifacts = detect_weight_outlier_indices(
            weight_rows,
            connected_vertices,
            minimum_difference=outlier_threshold,
        )
        input_points = _pre_skin_surface_points(transform, shape, vertex_count)
        deformation_artifacts = ()
        if input_points is not None:
            deformation_artifacts = detect_deformation_ripple_indices(
                [(point.x, point.y, point.z) for point in input_points],
                [(point.x, point.y, point.z) for point in points],
                connected_vertices,
            )
        detected_artifacts = tuple(sorted(set(weight_artifacts) | set(deformation_artifacts)))
        allowed_targets = set(targets)
        targets = [index for index in detected_artifacts if index in allowed_targets]
        # A few restrained passes emulate repeated Weight Hammer application;
        # allowing dozens of passes would erase intentional cape stiffness.
        iterations = min(iterations, 3)
        if not targets:
            return {
                "cancelled": False,
                "mesh": transform,
                "skinCluster": skin,
                "vertices": 0,
                "inspectedVertices": inspected_vertex_count,
                "artifactVertices": 0,
                "weightArtifactVertices": len(weight_artifacts),
                "deformationArtifactVertices": len(deformation_artifacts),
                "iterations": 0,
                "radius": radius,
                "requestedRadius": requested_radius,
                "autoExpandedRadius": False,
                "automaticRadius": auto_sized_radius,
                "changedVertices": 0,
                "maxDelta": 0.0,
                "weightRegions": len(set(dominant_influences)),
            }

    def build_spatial_index(search_radius):
        inverse = 1.0 / search_radius
        spatial_buckets = {}
        spatial_cells = []
        for index, point in enumerate(points):
            cell = tuple(int(math.floor(value * inverse)) for value in (point.x, point.y, point.z))
            spatial_cells.append(cell)
            spatial_buckets.setdefault(cell, []).append(index)
        return inverse, spatial_cells, spatial_buckets

    inverse_cell, cells, buckets = build_spatial_index(radius)

    # Batch smoothing should not silently no-op just because the world-space
    # default is tiny relative to the asset. The selection wrapper enables this
    # for both object and component selections; the painted brush leaves it off
    # so its visible circle remains the exact affected radius.
    auto_expanded = False
    if adaptive_radius and len(set(dominant_influences)) > 1:
        xs = [point.x for point in points]
        ys = [point.y for point in points]
        zs = [point.z for point in points]
        diagonal = math.sqrt(
            (max(xs) - min(xs)) ** 2
            + (max(ys) - min(ys)) ** 2
            + (max(zs) - min(zs)) ** 2
        )
        contact_search_limit = max(radius, diagonal * 0.1)
        blend_margin_limit = max(radius, diagonal * 0.2)

        def reaches_another_weight_region(search_radius):
            search_squared = search_radius * search_radius
            for vertex_index in targets:
                cell = cells[vertex_index]
                point = points[vertex_index]
                dominant = dominant_influences[vertex_index]
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            for candidate in buckets.get(
                                    (cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                                if dominant_influences[candidate] == dominant:
                                    continue
                                delta = points[candidate] - point
                                if (delta * delta) <= search_squared:
                                    return True
            return False

        while radius < contact_search_limit and not reaches_another_weight_region(radius):
            radius = min(radius * 2.0, contact_search_limit)
            inverse_cell, cells, buckets = build_spatial_index(radius)
            auto_expanded = radius > requested_radius

        # Merely touching another region places it at the kernel's zero-weight
        # edge. Give automatically discovered regions a full falloff margin so
        # the batch operation produces a visible blend rather than a nominal
        # floating-point change on a handful of boundary vertices.
        if auto_expanded and reaches_another_weight_region(radius):
            radius = min(radius * 2.0, blend_margin_limit)
            inverse_cell, cells, buckets = build_spatial_index(radius)

    radius_squared = radius * radius
    normal_limit = math.cos(math.radians(max(0.0, min(180.0, normal_angle))))
    neighbor_cache = {}

    def limit_neighbors(found):
        """Keep spatial samples from every nearby weight region.

        On very dense meshes, a nearest-N cap can be filled entirely by one
        tessellated patch even when another weighted surface lies inside the
        radius. Reserve several strong samples per dominant influence before
        filling the remaining slots by kernel weight.
        """
        if len(found) <= max_neighbors:
            return found
        groups = {}
        for candidate, kernel_weight in found:
            offset = candidate * influence_count
            dominant = max(
                range(influence_count),
                key=lambda influence: original[offset + influence],
            )
            groups.setdefault(dominant, []).append((candidate, kernel_weight))
        for values in groups.values():
            values.sort(key=lambda item: item[1], reverse=True)

        ordered_groups = sorted(
            groups.values(),
            key=lambda values: values[0][1],
            reverse=True,
        )
        quota = max(1, min(4, max_neighbors // max(1, len(ordered_groups) * 2)))
        selected = []
        selected_indices = set()
        for values in ordered_groups:
            for item in values[:quota]:
                if len(selected) >= max_neighbors:
                    break
                selected.append(item)
                selected_indices.add(item[0])
        if len(selected) < max_neighbors:
            remaining = sorted(found, key=lambda item: item[1], reverse=True)
            for item in remaining:
                if item[0] in selected_indices:
                    continue
                selected.append(item)
                if len(selected) >= max_neighbors:
                    break
        return selected

    def spatial_neighbors(vertex_index):
        if vertex_index in neighbor_cache:
            return neighbor_cache[vertex_index]
        point = points[vertex_index]
        normal = normals[vertex_index]
        cell = cells[vertex_index]
        found = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for candidate in buckets.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                        # The current row is already retained by the explicit
                        # strength blend below. Including it again in the
                        # neighbor average weakens the stroke and can make
                        # repeated passes alternate when its dominant weight
                        # changes.
                        if candidate == vertex_index:
                            continue
                        delta = points[candidate] - point
                        distance_squared = delta * delta
                        if distance_squared > radius_squared or (normal * normals[candidate]) < normal_limit:
                            continue
                        distance = math.sqrt(max(0.0, distance_squared))
                        falloff = 1.0 - min(1.0, distance / radius)
                        # Weight by represented surface area, not raw vertex
                        # count, so dense and sparse topology contribute fairly.
                        kernel_weight = max(0.0001, falloff * falloff) * sample_weights[candidate]
                        found.append((candidate, kernel_weight))
        if len(found) > max_neighbors:
            found = limit_neighbors(found)
        neighbor_cache[vertex_index] = found or [(vertex_index, 1.0)]
        return neighbor_cache[vertex_index]

    def balanced_neighbors(vertex_index):
        """Prevent one dense weight region from diluting every other region."""
        found = spatial_neighbors(vertex_index)
        groups = {}
        for candidate, value in found:
            groups.setdefault(dominant_influences[candidate], []).append((candidate, value))
        if len(groups) < 2:
            return found
        totals = {key: sum(value for _candidate, value in values) for key, values in groups.items()}
        total = sum(totals.values())
        if total <= 1.0e-12:
            return found
        dominant_group = max(totals, key=totals.get)
        dominant_share = totals[dominant_group] / total
        maximum_region_share = 1.0 - cross_region_share
        if dominant_share <= maximum_region_share:
            return found
        other_total = total - totals[dominant_group]
        dominant_scale = maximum_region_share / totals[dominant_group]
        other_scale = cross_region_share / other_total
        return [
            (candidate, value * (
                dominant_scale
                if dominant_influences[candidate] == dominant_group
                else other_scale
            ))
            for candidate, value in found
        ]

    def smoothing_neighbors(vertex_index):
        """Favor connected rows so posed deformation cannot form saw teeth."""
        spatial = balanced_neighbors(vertex_index)
        if topology_share <= 0.0 or not connected_vertices[vertex_index]:
            return spatial
        connected = []
        point = points[vertex_index]
        for candidate in connected_vertices[vertex_index]:
            delta = points[candidate] - point
            distance = math.sqrt(max(delta * delta, 1.0e-12))
            # Square-root inverse distance is density aware without starving
            # the long edges common in garment and cape topology.
            connected.append((candidate, 1.0 / math.sqrt(distance)))
        spatial_total = sum(value for _candidate, value in spatial)
        connected_total = sum(value for _candidate, value in connected)
        combined = {}
        spatial_share = 1.0 - topology_share
        if spatial_total > 1.0e-12 and spatial_share > 0.0:
            for candidate, value in spatial:
                combined[candidate] = combined.get(candidate, 0.0) + (
                    spatial_share * value / spatial_total
                )
        for candidate, value in connected:
            combined[candidate] = combined.get(candidate, 0.0) + (
                topology_share * value / connected_total
            )
        return list(combined.items())

    completed = 0
    cancelled = False
    cmds.progressWindow(
        title="Surface Spatial Weight Smoothing",
        progress=0,
        maxValue=iterations * len(targets),
        status="Building spatial neighborhoods...",
        isInterruptable=True,
    )
    try:
        for iteration in range(iterations):
            next_values = array("d")
            for target_offset, vertex_index in enumerate(targets):
                if target_offset % 100 == 0:
                    if cmds.progressWindow(query=True, isCancelled=True):
                        cancelled = True
                        break
                    cmds.progressWindow(
                        edit=True,
                        progress=(iteration * len(targets)) + target_offset,
                        status="Iteration {} of {} — vertex {} of {}".format(
                            iteration + 1, iterations, target_offset + 1, len(targets)),
                    )

                weight_offset = vertex_index * influence_count
                current = [working[weight_offset + influence] for influence in range(influence_count)]
                averaged = [0.0] * influence_count
                total_falloff = 0.0
                for neighbor, falloff in smoothing_neighbors(vertex_index):
                    neighbor_offset = neighbor * influence_count
                    total_falloff += falloff
                    for influence in range(influence_count):
                        averaged[influence] += working[neighbor_offset + influence] * falloff
                divisor = 1.0 / max(total_falloff, 0.000001)
                blended = [
                    current[influence] * (1.0 - strength)
                    + averaged[influence] * divisor * strength
                    for influence in range(influence_count)
                ]

                locked_total = sum(current[index] for index in locked)
                for index in locked:
                    blended[index] = current[index]
                unlocked = [index for index in range(influence_count) if index not in locked]
                # Do not prune during diffusion. Repeated top-N truncation makes
                # radial influence boundaries crack when one driver moves.
                # The finished field is pruned once, after every iteration.
                unlocked_total = sum(blended[index] for index in unlocked)
                available_weight = max(0.0, 1.0 - locked_total)
                if unlocked_total > 0.000001:
                    scale = available_weight / unlocked_total
                    for index in unlocked:
                        blended[index] *= scale
                else:
                    for index in unlocked:
                        blended[index] = current[index]
                next_values.extend(blended)

            if cancelled:
                break
            for target_offset, vertex_index in enumerate(targets):
                source = target_offset * influence_count
                destination = vertex_index * influence_count
                working[destination:destination + influence_count] = next_values[
                    source:source + influence_count]
            completed += 1
    finally:
        cmds.progressWindow(endProgress=True)

    if not completed:
        return {"cancelled": True, "mesh": transform, "vertices": 0, "iterations": 0}

    target_component_fn = om.MFnSingleIndexedComponent()
    target_component = target_component_fn.create(om.MFn.kMeshVertComponent)
    target_component_fn.addElements(om.MIntArray(targets))
    final_weights = om.MDoubleArray()
    maximum_delta = 0.0
    changed_vertices = 0
    for vertex_index in targets:
        offset = vertex_index * influence_count
        row = [working[offset + influence] for influence in range(influence_count)]
        locked_total = sum(row[index] for index in locked)
        unlocked = [index for index in range(influence_count) if index not in locked]
        locked_nonzero = sum(row[index] > 0.000001 for index in locked)
        slots = max(0, max_influences - locked_nonzero)
        if unlocked and locked_total < 0.999999:
            slots = max(1, slots)
        keep = set(sorted(unlocked, key=lambda index: row[index], reverse=True)[:slots])
        for index in unlocked:
            if index not in keep:
                row[index] = 0.0
        unlocked_total = sum(row[index] for index in unlocked)
        available = max(0.0, 1.0 - locked_total)
        if unlocked_total > 0.000001:
            scale = available / unlocked_total
            for index in unlocked:
                row[index] *= scale
        row_changed = False
        for influence, value in enumerate(row):
            delta = abs(value - original[(vertex_index * influence_count) + influence])
            maximum_delta = max(maximum_delta, delta)
            row_changed = row_changed or delta > 1.0e-6
            final_weights.append(value)
        if row_changed:
            changed_vertices += 1
    skin_fn.setWeights(
        mesh_path,
        target_component,
        om.MIntArray(range(influence_count)),
        final_weights,
        True,
        False,
    )
    return {
        "cancelled": cancelled,
        "mesh": transform,
        "skinCluster": skin,
        "vertices": len(targets),
        "inspectedVertices": inspected_vertex_count,
        "artifactVertices": len(detected_artifacts) if artifact_only else len(targets),
        "weightArtifactVertices": len(weight_artifacts) if artifact_only else 0,
        "deformationArtifactVertices": len(deformation_artifacts) if artifact_only else 0,
        "iterations": completed,
        "radius": radius,
        "requestedRadius": requested_radius,
        "autoExpandedRadius": auto_expanded,
        "automaticRadius": auto_sized_radius,
        "strength": strength,
        "maxInfluences": max_influences,
        "normalAngle": normal_angle,
        "maxNeighbors": max_neighbors,
        "changedVertices": changed_vertices,
        "maxDelta": maximum_delta,
        "lockedInfluences": len(locked),
        "weightRegions": len(set(dominant_influences)),
        "crossRegionShare": cross_region_share,
        "topologyShare": topology_share,
        "artifactOnly": bool(artifact_only),
    }


class SurfaceSpatialSmoothBrush:
    """Maya viewport brush that collects a visible-surface stroke and smooths it."""

    CONTEXT_NAME = "tcSurfaceSpatialSmoothSkinCtx"

    def __init__(self, mesh, radius, strength, iterations, max_influences, normal_angle,
                 max_neighbors, cross_region_share):
        self.shape = _mesh_shape(mesh)
        self.transform = (cmds.listRelatives(self.shape, parent=True, fullPath=True) or [self.shape])[0]
        self.skin = _find_skin_cluster(self.shape) or _find_skin_cluster(self.transform)
        if not self.skin:
            raise ValueError("Mesh has no skinCluster: {}".format(self.transform))
        self.radius = float(radius)
        self.strength = float(strength)
        self.iterations = int(iterations)
        self.max_influences = int(max_influences)
        self.normal_angle = float(normal_angle)
        self.max_neighbors = int(max_neighbors)
        self.cross_region_share = float(cross_region_share)
        selection = om.MSelectionList()
        selection.add(self.shape)
        self.mesh_path = selection.getDagPath(0)
        self.mesh_fn = om.MFnMesh(self.mesh_path)
        self.accel_params = self.mesh_fn.autoUniformGridParams()
        self.points = self.mesh_fn.getPoints(om.MSpace.kWorld)
        self.sample_weights = _vertex_surface_area_weights(self.mesh_path)
        self.resize_held = False
        self.resize_anchor_x = 0.0
        self.resize_start_radius = self.radius
        self._rebuild_buckets()
        self.stroke_vertices = set()
        self.last_hit = None
        self.last_hover_time = 0.0
        self.painting = False
        self.overlay = None
        self.overlay_panel = None
        self.outline = self._create_outline()

    def _create_outline(self):
        existing = cmds.ls("tc_surface_spatial_smooth_brush_outline", long=True) or []
        if existing:
            cmds.delete(existing)
        outline = cmds.circle(
            name="tc_surface_spatial_smooth_brush_outline",
            constructionHistory=False,
            normal=(0.0, 0.0, 1.0),
            radius=1.0,
            sections=64,
        )[0]
        shape = (cmds.listRelatives(outline, shapes=True, fullPath=True) or [None])[0]
        if shape:
            cmds.setAttr(shape + ".overrideEnabled", 1)
            cmds.setAttr(shape + ".overrideColor", 17)
            if cmds.attributeQuery("lineWidth", node=shape, exists=True):
                cmds.setAttr(shape + ".lineWidth", 2.0)
            if cmds.attributeQuery("alwaysDrawOnTop", node=shape, exists=True):
                cmds.setAttr(shape + ".alwaysDrawOnTop", 1)
        cmds.setAttr(outline + ".visibility", 0)
        return outline

    def hide_outline(self):
        if self.outline and cmds.objExists(self.outline):
            cmds.setAttr(self.outline + ".visibility", 0)
        if self.overlay is not None:
            self.overlay.clear_circle()

    def delete_outline(self):
        if self.outline and cmds.objExists(self.outline):
            cmds.delete(self.outline)
        self.outline = None
        if self.overlay is not None:
            self.overlay.deleteLater()
        self.overlay = None
        self.overlay_panel = None

    @staticmethod
    def _world_to_view(view, point):
        x_value = om1.MScriptUtil()
        y_value = om1.MScriptUtil()
        x_value.createFromInt(0)
        y_value.createFromInt(0)
        x_pointer = x_value.asShortPtr()
        y_pointer = y_value.asShortPtr()
        view.worldToView(
            om1.MPoint(point.x, point.y, point.z),
            x_pointer,
            y_pointer,
        )
        return (
            float(om1.MScriptUtil.getShort(x_pointer)),
            float(om1.MScriptUtil.getShort(y_pointer)),
        )

    def _ensure_overlay(self, panel, widget):
        if self.overlay is not None and self.overlay_panel != panel:
            self.overlay.deleteLater()
            self.overlay = None
        if self.overlay is None:
            self.overlay = _SurfaceSmoothBrushOverlay(widget)
            self.overlay_panel = panel
        self.overlay.setGeometry(widget.rect())
        return self.overlay

    def _update_overlay(self, hit_data, view, panel, widget):
        overlay = self._ensure_overlay(panel, widget)
        if not hit_data:
            overlay.clear_circle()
            return
        point, normal = hit_data
        normal = om.MVector(normal)
        normal.normalize()
        reference = om.MVector(0.0, 1.0, 0.0)
        if abs(normal * reference) > 0.95:
            reference = om.MVector(1.0, 0.0, 0.0)
        tangent = reference ^ normal
        tangent.normalize()
        center_x, center_y = self._world_to_view(view, point)
        edge_x, edge_y = self._world_to_view(view, om.MPoint(point) + tangent * self.radius)
        pixel_radius = math.hypot(edge_x - center_x, edge_y - center_y)
        overlay.set_circle(
            (center_x, widget.height() - center_y),
            pixel_radius,
        )

    def _update_outline(self, hit_data):
        if not hit_data or not self.outline or not cmds.objExists(self.outline):
            self.hide_outline()
            return
        point, normal = hit_data
        normal = om.MVector(normal)
        normal.normalize()
        reference = om.MVector(0.0, 1.0, 0.0)
        if abs(normal * reference) > 0.95:
            reference = om.MVector(1.0, 0.0, 0.0)
        tangent = reference ^ normal
        tangent.normalize()
        bitangent = normal ^ tangent
        bitangent.normalize()
        display_point = om.MPoint(point) + normal * max(0.0001, self.radius * 0.002)
        matrix = [
            tangent.x, tangent.y, tangent.z, 0.0,
            bitangent.x, bitangent.y, bitangent.z, 0.0,
            normal.x, normal.y, normal.z, 0.0,
            display_point.x, display_point.y, display_point.z, 1.0,
        ]
        cmds.xform(self.outline, worldSpace=True, matrix=matrix)
        cmds.setAttr(self.outline + ".scale", self.radius, self.radius, self.radius, type="double3")
        cmds.setAttr(self.outline + ".visibility", 1)

    def _rebuild_buckets(self):
        self.inverse_cell = 1.0 / max(self.radius, 0.000001)
        self.buckets = {}
        for index, point in enumerate(self.points):
            cell = self._cell(point)
            self.buckets.setdefault(cell, []).append(index)

    def _cell(self, point):
        return (
            int(math.floor(point.x * self.inverse_cell)),
            int(math.floor(point.y * self.inverse_cell)),
            int(math.floor(point.z * self.inverse_cell)),
        )

    def _hit_from_screen(self, screen_point, view=None):
        view = view or omui1.M3dView.active3dView()
        ray_source = om1.MPoint()
        ray_direction = om1.MVector()
        view.viewToWorld(int(screen_point[0]), int(screen_point[1]), ray_source, ray_direction)
        hit = self.mesh_fn.closestIntersection(
            om.MFloatPoint(ray_source.x, ray_source.y, ray_source.z),
            om.MFloatVector(ray_direction.x, ray_direction.y, ray_direction.z),
            om.MSpace.kWorld,
            100000000.0,
            False,
            None,
            None,
            False,
            self.accel_params,
            0.000001,
        )
        if not hit:
            return None
        point = om.MPoint(hit[0].x, hit[0].y, hit[0].z)
        normal = self.mesh_fn.getPolygonNormal(int(hit[2]), om.MSpace.kWorld)
        return point, om.MVector(normal)

    def _collect_at_hit(self, hit_data):
        if hit_data is None:
            return
        hit, _normal = hit_data
        self.last_hit = hit_data
        self._update_outline(hit_data)
        center = self._cell(hit)
        radius_squared = self.radius * self.radius
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for index in self.buckets.get((center[0] + dx, center[1] + dy, center[2] + dz), ()):
                        delta = self.points[index] - hit
                        if (delta * delta) <= radius_squared:
                            self.stroke_vertices.add(index)

    def press(self):
        self.stroke_vertices.clear()
        point = cmds.draggerContext(self.CONTEXT_NAME, query=True, anchorPoint=True)
        if self.resize_held:
            self.resize_anchor_x = float(point[0])
            self.resize_start_radius = self.radius
            return
        self._collect_at_hit(self._hit_from_screen(point))

    def drag(self):
        point = cmds.draggerContext(self.CONTEXT_NAME, query=True, dragPoint=True)
        if self.resize_held:
            pixel_delta = float(point[0]) - self.resize_anchor_x
            self.radius = max(0.0001, self.resize_start_radius * (2.0 ** (pixel_delta / 100.0)))
            self._update_outline(self.last_hit)
            cmds.inViewMessage(
                assistMessage="Surface Smooth Brush Radius: {:.4g}".format(self.radius),
                position="topCenter",
                fade=False,
            )
            return
        self._collect_at_hit(self._hit_from_screen(point))
        cmds.inViewMessage(
            assistMessage="Surface smooth stroke: {} vertices".format(len(self.stroke_vertices)),
            position="topCenter",
            fade=True,
        )

    def _component_and_weights(self, indices):
        selection = om.MSelectionList()
        selection.add(self.skin)
        skin_fn = oma.MFnSkinCluster(selection.getDependNode(0))
        component_fn = om.MFnSingleIndexedComponent()
        component = component_fn.create(om.MFn.kMeshVertComponent)
        component_fn.addElements(om.MIntArray(indices))
        weights, influence_count = skin_fn.getWeights(self.mesh_path, component)
        return skin_fn, component, weights, influence_count

    def release(self):
        if self.resize_held:
            self._rebuild_buckets()
            cmds.inViewMessage(
                assistMessage="Surface Smooth Brush Radius: {:.4g}".format(self.radius),
                position="topCenter",
                fade=True,
            )
            return
        indices = sorted(self.stroke_vertices)
        if not indices:
            return
        skin_fn, component, old_weights, influence_count = self._component_and_weights(indices)
        result = smooth_skin_weights_spatial(
            self.transform,
            vertex_indices=indices,
            radius=self.radius,
            iterations=self.iterations,
            strength=self.strength,
            max_influences=self.max_influences,
            normal_angle=self.normal_angle,
            max_neighbors=self.max_neighbors,
            sample_weights=self.sample_weights,
            cross_region_share=self.cross_region_share,
        )
        _new_skin_fn, _new_component, new_weights, _count = self._component_and_weights(indices)

        # Restore the preview, then commit through skinPercent so Maya records
        # one conventional undo chunk for the entire painted stroke.
        influence_indices = om.MIntArray(range(influence_count))
        skin_fn.setWeights(self.mesh_path, component, influence_indices, old_weights, True, False)
        influence_names = [path.fullPathName() for path in skin_fn.influenceObjects()]
        cmds.undoInfo(openChunk=True, chunkName="Surface Spatial Smooth Stroke")
        try:
            for row_index, vertex_index in enumerate(indices):
                offset = row_index * influence_count
                values = [
                    (influence_names[influence], new_weights[offset + influence])
                    for influence in range(influence_count)
                ]
                cmds.skinPercent(
                    self.skin,
                    "{}.vtx[{}]".format(self.transform, vertex_index),
                    transformValue=values,
                    normalize=True,
                )
        finally:
            cmds.undoInfo(closeChunk=True)
        cmds.dgdirty(self.transform)
        cmds.refresh(force=True)
        changed = int(result.get("changedVertices", 0))
        maximum_delta = float(result.get("maxDelta", 0.0))
        if not changed or maximum_delta <= 1.0e-6:
            cmds.warning(
                "Surface smooth stroke collected {} vertices but produced no weight change. "
                "Increase Radius/Strength or unlock the relevant skin influences.".format(len(indices))
            )
            message = "Surface smooth: no weight change ({} vertices sampled)".format(len(indices))
        else:
            message = "Surface smooth changed {} of {} vertices (max delta {:.4f})".format(
                changed, len(indices), maximum_delta)
        cmds.inViewMessage(
            assistMessage=message,
            position="topCenter",
            fade=True,
        )

    def hover_from_cursor(self, force=False):
        now = time.perf_counter()
        if not force and now - self.last_hover_time < (1.0 / 30.0):
            return
        self.last_hover_time = now
        panel = cmds.getPanel(underPointer=True)
        if not panel or cmds.getPanel(typeOf=panel) != "modelPanel":
            self.hide_outline()
            return
        pointer = omui1.MQtUtil.findControl(panel)
        if not pointer:
            return
        widget = wrapInstance(int(pointer), QtWidgets.QWidget)
        local = widget.mapFromGlobal(QtGui.QCursor.pos())
        view = omui1.M3dView()
        omui1.M3dView.getM3dViewFromModelPanel(panel, view)
        screen_point = (local.x(), max(0, widget.height() - local.y()), 0)
        hit_data = self._hit_from_screen(screen_point, view=view)
        self.last_hit = hit_data
        self._update_outline(hit_data)
        self._update_overlay(hit_data, view, panel, widget)
        return hit_data

    def begin_viewport_stroke(self):
        self.stroke_vertices.clear()
        hit_data = self.hover_from_cursor(force=True)
        if hit_data is None:
            self.painting = False
            return False
        self.painting = True
        self._collect_at_hit(hit_data)
        return True

    def continue_viewport_stroke(self):
        if not self.painting:
            return False
        hit_data = self.hover_from_cursor(force=True)
        if hit_data is not None:
            self._collect_at_hit(hit_data)
        return True

    def finish_viewport_stroke(self):
        if not self.painting:
            return False
        self.painting = False
        self.release()
        return True

    def resize_from_pixels(self, pixel_delta):
        self.radius = max(0.0001, self.resize_start_radius * (2.0 ** (float(pixel_delta) / 100.0)))
        self._rebuild_buckets()
        self.hover_from_cursor(force=True)
        cmds.inViewMessage(
            assistMessage="Surface Smooth Brush Radius: {:.4g}".format(self.radius),
            position="topCenter",
            fade=False,
        )


class _SurfaceSmoothBrushKeyFilter(QtCore.QObject):
    """Give the custom Maya context the standard B-drag brush-size gesture."""

    def eventFilter(self, watched, event):
        brush = _ACTIVE_SURFACE_SMOOTH_BRUSH
        if brush is None:
            return False
        if cmds.currentCtx() != SurfaceSpatialSmoothBrush.CONTEXT_NAME:
            brush.hide_outline()
            return False
        event_type = event.type()
        if event_type == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if event.modifiers() & QtCore.Qt.AltModifier:
                return False
            if brush.resize_held:
                brush.resize_anchor_x = float(QtGui.QCursor.pos().x())
                brush.resize_start_radius = brush.radius
                return True
            if brush.begin_viewport_stroke():
                return True
        if event_type == QtCore.QEvent.MouseMove:
            if brush.resize_held and event.buttons() & QtCore.Qt.LeftButton:
                brush.resize_from_pixels(float(QtGui.QCursor.pos().x()) - brush.resize_anchor_x)
                return True
            if brush.painting:
                brush.continue_viewport_stroke()
                return True
            brush.hover_from_cursor()
            return False
        if event_type == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if brush.resize_held:
                brush._rebuild_buckets()
                brush.hover_from_cursor()
                return True
            if brush.finish_viewport_stroke():
                return True
        if event_type == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_B:
            if not event.isAutoRepeat():
                brush.resize_held = True
            return True
        if event_type == QtCore.QEvent.KeyRelease and event.key() == QtCore.Qt.Key_B:
            if not event.isAutoRepeat():
                brush.resize_held = False
                brush._rebuild_buckets()
            return True
        return False


def _surface_smooth_brush_press():
    if _ACTIVE_SURFACE_SMOOTH_BRUSH:
        _ACTIVE_SURFACE_SMOOTH_BRUSH.press()


def _surface_smooth_brush_drag():
    if _ACTIVE_SURFACE_SMOOTH_BRUSH:
        _ACTIVE_SURFACE_SMOOTH_BRUSH.drag()


def _surface_smooth_brush_release():
    if _ACTIVE_SURFACE_SMOOTH_BRUSH:
        _ACTIVE_SURFACE_SMOOTH_BRUSH.release()


def _surface_smooth_brush_tool_changed():
    global _SURFACE_SMOOTH_BRUSH_TOOL_JOB
    if (
            _ACTIVE_SURFACE_SMOOTH_BRUSH is not None
            and cmds.currentCtx() != SurfaceSpatialSmoothBrush.CONTEXT_NAME
    ):
        # This callback belongs to a run-once job which Maya removes after it
        # returns; clear the id so cleanup does not try to kill its own job.
        _SURFACE_SMOOTH_BRUSH_TOOL_JOB = None
        _cleanup_surface_spatial_smooth_brush()


def _cleanup_surface_spatial_smooth_brush():
    global _ACTIVE_SURFACE_SMOOTH_BRUSH, _SURFACE_SMOOTH_BRUSH_KEY_FILTER
    global _SURFACE_SMOOTH_BRUSH_TOOL_JOB
    application = QtWidgets.QApplication.instance()
    if application is not None and _SURFACE_SMOOTH_BRUSH_KEY_FILTER is not None:
        application.removeEventFilter(_SURFACE_SMOOTH_BRUSH_KEY_FILTER)
    _SURFACE_SMOOTH_BRUSH_KEY_FILTER = None
    if _ACTIVE_SURFACE_SMOOTH_BRUSH is not None:
        _ACTIVE_SURFACE_SMOOTH_BRUSH.delete_outline()
    _ACTIVE_SURFACE_SMOOTH_BRUSH = None
    if _SURFACE_SMOOTH_BRUSH_TOOL_JOB and cmds.scriptJob(exists=_SURFACE_SMOOTH_BRUSH_TOOL_JOB):
        cmds.scriptJob(kill=_SURFACE_SMOOTH_BRUSH_TOOL_JOB, force=True)
    _SURFACE_SMOOTH_BRUSH_TOOL_JOB = None


def activate_surface_spatial_smooth_brush(
        radius=1.0, iterations=1, strength=0.35, max_influences=8,
        normal_angle=120.0, max_neighbors=96, cross_region_share=0.45):
    """Activate the topology-independent Maya skin smoothing brush."""
    global _ACTIVE_SURFACE_SMOOTH_BRUSH, _SURFACE_SMOOTH_BRUSH_KEY_FILTER
    global _SURFACE_SMOOTH_BRUSH_TOOL_JOB
    mesh, _vertices = _selected_mesh_and_vertices()
    _ACTIVE_SURFACE_SMOOTH_BRUSH = SurfaceSpatialSmoothBrush(
        mesh, radius, strength, iterations, max_influences, normal_angle,
        max_neighbors, cross_region_share)
    context = SurfaceSpatialSmoothBrush.CONTEXT_NAME
    if cmds.draggerContext(context, exists=True):
        cmds.deleteUI(context)
    cmds.draggerContext(
        context,
        pressCommand=_surface_smooth_brush_press,
        dragCommand=_surface_smooth_brush_drag,
        releaseCommand=_surface_smooth_brush_release,
        cursor="crossHair",
        projection="viewPlane",
        space="screen",
        undoMode="step",
    )
    cmds.setToolTo(context)
    application = QtWidgets.QApplication.instance()
    if application is not None:
        if _SURFACE_SMOOTH_BRUSH_KEY_FILTER is not None:
            application.removeEventFilter(_SURFACE_SMOOTH_BRUSH_KEY_FILTER)
        _SURFACE_SMOOTH_BRUSH_KEY_FILTER = _SurfaceSmoothBrushKeyFilter(application)
        application.installEventFilter(_SURFACE_SMOOTH_BRUSH_KEY_FILTER)
    _SURFACE_SMOOTH_BRUSH_TOOL_JOB = cmds.scriptJob(
        event=["ToolChanged", _surface_smooth_brush_tool_changed],
        protected=True,
        runOnce=True,
    )
    cmds.inViewMessage(
        assistMessage="Surface Spatial Smooth Brush active — drag to paint; hold B + drag to resize; Q exits",
        position="topCenter",
        fade=True,
    )
    return {"context": context, "mesh": _ACTIVE_SURFACE_SMOOTH_BRUSH.transform}


def deactivate_surface_spatial_smooth_brush():
    """Exit the spatial skin brush and return to Maya's selection context."""
    _cleanup_surface_spatial_smooth_brush()
    cmds.setToolTo("selectSuperContext")


def _collect_skin_data(meshes):
    influences = []
    max_influences = 1
    inherits_transform = False

    for mesh in meshes:
        skin = _find_skin_cluster(mesh)
        if not skin:
            continue

        influences.extend(cmds.skinCluster(skin, q=True, inf=True))
        inherits_transform |= cmds.getAttr(f"{mesh}.inheritsTransform")

        if cmds.getAttr(f"{skin}.maintainMaxInfluences"):
            max_influences = max(
                max_influences,
                cmds.skinCluster(skin, q=True, maximumInfluences=True)
            )
        else:
            max_influences = max(max_influences, 4)

    unique_influences = list(OrderedDict.fromkeys(influences))

    return {
        "influences": unique_influences,
        "joints": [i for i in unique_influences if cmds.nodeType(i) == "joint"],
        "transforms": [i for i in unique_influences if cmds.nodeType(i) == "transform"],
        "max_influences": max_influences,
        "inherits_transform": inherits_transform,
    }


def _create_target_skin(target_mesh, skin_data):
    joints = skin_data["joints"] or [
        cmds.createNode("joint", name="temp_transfer_joint")
    ]

    skin = cmds.skinCluster(
        joints,
        target_mesh,
        maximumInfluences=skin_data["max_influences"],
        dropoffRate=3.0,
        toSelectedBones=True
    )[0]

    for transform in skin_data["transforms"]:
        cmds.skinCluster(
            target_mesh,
            e=True,
            ai=transform,
            lw=True,
            wt=0.0
        )

    for influence in cmds.skinCluster(skin, q=True, inf=True):
        if cmds.getAttr(f"{influence}.liw"):
            cmds.setAttr(f"{influence}.liw", 0)

    return skin


def _copy_weights(source_meshes, target_mesh):
    cmds.select(source_meshes + [target_mesh], r=True)
    cmds.copySkinWeights(
        noMirror=True,
        ia=["oneToOne", "label", "closestJoint"],
        sa="closestPoint",
        normalize=True
    )


def _run_weight_hammer(mesh):
    previous_selection = cmds.ls(selection=True) or []
    try:
        vertex_count = cmds.polyEvaluate(mesh, vertex=True) or 0
        if vertex_count < 1:
            cmds.warning(f"Weight Hammer skipped for '{mesh}': no vertices found.")
            return

        cmds.select(f"{mesh}.vtx[0]", replace=True)
        mel.eval("WeightHammer;")
    except Exception as exc:
        cmds.warning(f"Weight Hammer failed for '{mesh}': {exc}")
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)
        else:
            cmds.select(clear=True)


def _canonical_skin_meshes(meshes):
    """Return unique long transform paths for mesh shapes or transforms."""
    canonical = []
    seen = set()
    for mesh in meshes or []:
        node = mesh
        if cmds.objExists(node):
            long_names = cmds.ls(node, long=True, objectsOnly=True) or [node]
            node = long_names[0]
            if cmds.nodeType(node) == "mesh":
                parents = cmds.listRelatives(
                    node, parent=True, fullPath=True
                ) or []
                if parents:
                    node = parents[0]
        if node in seen:
            continue
        seen.add(node)
        canonical.append(node)
    return canonical


def export_skin_weights(meshes, export_dir="C:/temp/weights"):
    """
    Exports skin weights for a list of meshes to XML using deformerWeights.
    Saves influence order in individual JSON sidecar files.
    :param meshes: list of mesh names to export
    :param export_dir: target directory to save all files
    """
    export_dir = os.path.normpath(export_dir)
    if not os.path.exists(export_dir):
        os.makedirs(export_dir)

    for mesh in _canonical_skin_meshes(meshes):
        if not cmds.objExists(mesh):
            print(f"[!] Skipping '{mesh}': does not exist.")
            continue

        mesh_name = _influence_node_name(mesh)

        shape_node = cmds.listRelatives(mesh, shapes=True, fullPath=True)
        if not shape_node:
            print(f"[!] Skipping '{mesh}': no shape node found.")
            continue
        shape_node = shape_node[0]

        skin_cluster = None
        for hist in cmds.listHistory(mesh, pdo=True) or []:
            if cmds.nodeType(hist) == "skinCluster":
                skin_cluster = hist
                break

        if not skin_cluster:
            print(f"[!] Skipping '{mesh}': no skinCluster found.")
            continue

        influences = cmds.skinCluster(skin_cluster, query=True, influence=True)
        if not influences:
            print(f"[!] Skipping '{mesh}': no influences found.")
            continue

        export_name = f"{mesh_name}_weights.xml"
        json_name = f"{mesh_name}_weights_influences.json"

        try:
            cmds.deformerWeights(export_name,
                                 path=export_dir,
                                 deformer=skin_cluster,
                                 export=True,
                                 shape=shape_node)
        except Exception as e:
            print(f"[!] Failed to export weights for '{mesh_name}': {e}")
            continue

        with open(os.path.join(export_dir, json_name), 'w') as f:
            json.dump(influences, f, indent=2)

        print(f"[?] Exported: {mesh_name}")


def _influence_leaf_name(influence):
    """Return an influence name without its DAG path or Maya namespace."""
    leaf_name = str(influence).rsplit("|", 1)[-1]
    return leaf_name.rsplit(":", 1)[-1]


def _influence_node_name(influence):
    """Return an influence leaf name while retaining its Maya namespace."""
    return str(influence).rsplit("|", 1)[-1]


def _influence_match_key(influence):
    """Normalize harmless punctuation differences for influence-name matching."""
    return re.sub(r"[^a-z0-9]+", "", _influence_leaf_name(influence).lower())


def _find_similar_scene_influences(missing_influences, scene_influences,
                                   limit=3, cutoff=0.6, short_names=True):
    """Return likely scene-name matches without silently remapping influences."""
    unique_candidates = list(OrderedDict.fromkeys(scene_influences or []))
    candidate_keys = {
        candidate: _influence_match_key(candidate)
        for candidate in unique_candidates
    }
    suggestions = {}
    for missing in missing_influences:
        missing_key = _influence_match_key(missing)
        ranked = []
        for candidate, candidate_key in candidate_keys.items():
            if not missing_key or not candidate_key:
                continue
            score = difflib.SequenceMatcher(
                None, missing_key, candidate_key
            ).ratio()
            if score >= cutoff:
                ranked.append((score, _influence_leaf_name(candidate), candidate))
        ranked.sort(key=lambda item: (-item[0], item[1].lower(), item[2]))
        ranked_short_names = OrderedDict()
        for score, short_name, _candidate in ranked:
            ranked_short_names.setdefault(short_name, score)
            if len(ranked_short_names) >= limit:
                break
        if short_names:
            suggestions[missing] = list(ranked_short_names)
        else:
            suggestions[missing] = [item[2] for item in ranked[:limit]]
    return suggestions


def _twist_influence_match_key(influence):
    """Canonicalize the two supported limb-twist ordinal conventions."""
    leaf_name = _influence_leaf_name(influence).lower()
    limb_pattern = r"(thigh|knee|upperarm|lowerarm)"
    match = re.match(
        r"^([lr])_{}(\d+)_twist$".format(limb_pattern), leaf_name
    )
    if not match:
        match = re.match(
            r"^([lr])_{}_twist(\d+)$".format(limb_pattern), leaf_name
        )
    if not match:
        return None
    side, limb, ordinal = match.groups()
    return "{}_{}_twist{}".format(side, limb, ordinal)


def _resolve_scene_influences(saved_influences, scene_influences):
    """Resolve saved influences to scene joints without renaming any nodes.

    Matching is deliberately conservative. Full paths and namespaced leaf names
    win first, followed by unique namespace-free leaf names. The only fuzzy
    rule accepted is the studio limb-twist ordinal swap for thighs, knees,
    upper arms, and lower arms (for example, ``l_upperarm1_twist`` to
    ``l_upperarm_twist1``). A tier with multiple candidates is ambiguous and is
    never resolved by falling through to a weaker tier.
    """
    candidates = list(OrderedDict.fromkeys(scene_influences or []))
    mapping = OrderedDict()
    missing = []
    ambiguous = OrderedDict()

    for saved in saved_influences or []:
        saved_text = str(saved)
        saved_node = _influence_node_name(saved_text)
        saved_leaf = _influence_leaf_name(saved_text)
        twist_key = _twist_influence_match_key(saved_text)
        tiers = [
            [candidate for candidate in candidates if str(candidate) == saved_text],
            [candidate for candidate in candidates
             if _influence_node_name(candidate) == saved_node],
            [candidate for candidate in candidates
             if _influence_leaf_name(candidate) == saved_leaf],
        ]
        if twist_key:
            tiers.append([
                candidate for candidate in candidates
                if _twist_influence_match_key(candidate) == twist_key
            ])

        matches = next((tier for tier in tiers if tier), [])
        if len(matches) == 1:
            mapping[saved] = matches[0]
        elif len(matches) > 1:
            ambiguous[saved] = matches
        else:
            missing.append(saved)

    # Two weight-map entries may not target the same scene joint. Importing
    # that collision would silently merge or overwrite weights.
    destinations = {}
    for saved, scene_joint in list(mapping.items()):
        destinations.setdefault(scene_joint, []).append(saved)
    for scene_joint, saved_names in destinations.items():
        if len(saved_names) < 2:
            continue
        for saved in saved_names:
            mapping.pop(saved, None)
            ambiguous[saved] = [scene_joint]

    return {
        "mapping": mapping,
        "missing": missing,
        "ambiguous": ambiguous,
    }


def _influence_requires_remap(saved_influence, scene_influence):
    """Return whether Maya's XML source name actually needs remapping."""
    return (
        _influence_node_name(saved_influence)
        != _influence_node_name(scene_influence)
    )


def _prepare_deformer_weights_xml(
        source_path, influence_mapping, target_deformer, target_shape):
    """Create a temporary XML copy addressed directly to the target skin."""
    source_names = OrderedDict(
        (
            _influence_node_name(saved_name),
            _influence_node_name(scene_influence),
        )
        for saved_name, scene_influence in influence_mapping.items()
    )
    tree = ET.parse(source_path)
    root = tree.getroot()
    matched_sources = set()

    for shape_element in root.iter("shape"):
        shape_element.set("name", _influence_node_name(target_shape))
    for weights_element in root.iter("weights"):
        source_name = weights_element.get("source")
        if source_name in source_names:
            weights_element.set("source", source_names[source_name])
            matched_sources.add(source_name)
        weights_element.set("deformer", _influence_node_name(target_deformer))
        weights_element.set("shape", _influence_node_name(target_shape))

    unmatched_sources = sorted(set(source_names) - matched_sources)
    if unmatched_sources:
        raise ValueError(
            "Influence sidecar does not match the XML sources: {}".format(
                ", ".join(unmatched_sources)
            )
        )

    handle, prepared_path = tempfile.mkstemp(
        prefix="tc_skin_weights_", suffix=".xml"
    )
    os.close(handle)
    try:
        tree.write(prepared_path, encoding="utf-8", xml_declaration=True)
    except Exception:
        if os.path.exists(prepared_path):
            os.remove(prepared_path)
        raise
    return prepared_path


def _deformer_weights_vertex_count(source_path):
    """Read the exported point count used by Maya's index mapping method."""
    for _event, element in ET.iterparse(source_path, events=("start",)):
        if element.tag != "shape":
            continue
        size = element.get("size")
        return int(size) if size is not None else None
    return None


def _influence_alias_keys(influence):
    """Return conservative keys for common exported-joint name variants."""
    leaf_name = _influence_leaf_name(influence).lower()
    normalized = re.sub(
        r"\d+", lambda match: str(int(match.group(0))), leaf_name
    )
    keys = {
        re.sub(r"[^a-z0-9]+", "", normalized),
    }
    # A trailing 1 is commonly omitted for the first/only joint in a group.
    # Do not strip the final digit from multi-digit ordinals such as brow11.
    without_default_one = re.sub(r"(?<!\d)_?1$", "", normalized)
    keys.add(re.sub(r"[^a-z0-9]+", "", without_default_one))
    return {key for key in keys if key}


def _influence_side(influence):
    """Return l/r for explicitly sided influences, otherwise None."""
    match = re.match(r"^([lr])(?:_|$)", _influence_leaf_name(influence).lower())
    return match.group(1) if match else None


def _propose_safe_influence_renames(missing_influences, scene_joints):
    """Propose unique formatting-only joint renames for user confirmation."""
    candidates = list(OrderedDict.fromkeys(scene_joints or []))
    proposals = OrderedDict()
    unresolved = []
    ambiguous = OrderedDict()
    used_nodes = set()

    for saved_name in missing_influences or []:
        saved_keys = _influence_alias_keys(saved_name)
        saved_side = _influence_side(saved_name)
        matches = [
            candidate for candidate in candidates
            if _influence_side(candidate) == saved_side
            and saved_keys.intersection(_influence_alias_keys(candidate))
        ]
        matches = [candidate for candidate in matches if candidate not in used_nodes]
        if len(matches) == 1:
            proposals[saved_name] = matches[0]
            used_nodes.add(matches[0])
        elif len(matches) > 1:
            ambiguous[saved_name] = matches
        else:
            unresolved.append(saved_name)

    return {
        "proposals": proposals,
        "unresolved": unresolved,
        "ambiguous": ambiguous,
    }


def _rename_scene_influences(rename_requests):
    """Atomically rename confirmed scene joints while retaining namespaces."""
    renamed = OrderedDict()
    failures = OrderedDict()
    ordered_requests = sorted(
        (rename_requests or {}).items(),
        key=lambda item: str(item[1]).count("|"),
        reverse=True,
    )
    cmds.undoInfo(openChunk=True, chunkName="Rename Skin Import Influences")
    try:
        for saved_name, scene_joint in ordered_requests:
            source_node = _influence_node_name(scene_joint)
            namespace = source_node.rpartition(":")[0]
            target_leaf = _influence_leaf_name(saved_name)
            target_name = (
                "{}:{}".format(namespace, target_leaf)
                if namespace else target_leaf
            )
            try:
                renamed_joint = cmds.rename(scene_joint, target_name)
            except Exception as exc:
                failures[saved_name] = str(exc)
                continue
            if _influence_leaf_name(renamed_joint) != target_leaf:
                failures[saved_name] = (
                    "Maya returned '{}' instead of the requested name '{}'."
                ).format(_influence_leaf_name(renamed_joint), target_leaf)
                continue
            renamed[saved_name] = {
                "previous_scene_influence": scene_joint,
                "scene_influence": renamed_joint,
            }
    finally:
        cmds.undoInfo(closeChunk=True)
    if failures:
        cmds.undo()
        renamed = OrderedDict()
    return renamed, failures


def _format_missing_influence_failure(mesh, missing_influences, suggestions):
    lines = [
        "[!] Skipping '{}': {} required skin influence(s) are missing from "
        "the scene.".format(mesh, len(missing_influences)),
    ]
    for influence in missing_influences:
        matches = suggestions.get(influence) or []
        if matches:
            lines.append(
                "    - {} (similar scene joint{}: {})".format(
                    influence,
                    "s" if len(matches) != 1 else "",
                    ", ".join(matches),
                )
            )
        else:
            lines.append("    - {} (no similar scene joint found)".format(influence))
    lines.append(
        "    Skin weights were not imported because every saved influence "
        "must resolve to an existing scene node. Rename/remap the joints or "
        "restore the missing influences, then import again."
    )
    return "\n".join(lines)


def import_skin_weights(meshes, export_dir="C:/temp/weights",
                        missing_influence_resolver=None):
    """
    Import skin weights without rebuilding an existing skinCluster.

    Existing influences and dagPose membership are preserved. Influences present
    in the saved data but missing from the cluster are added at zero weight
    before the weights are loaded.
    :param meshes: list of mesh names to import to
    :param export_dir: directory where XML and JSON files are stored
    :param missing_influence_resolver: optional confirmation callback. It
        receives ``mesh, proposals, unresolved, ambiguous`` and returns truthy
        to rename the proposed scene joints before retrying influence matching.
    """
    export_dir = os.path.normpath(export_dir)
    imported_meshes = []
    influence_reports = []
    failure_reports = []

    for mesh in _canonical_skin_meshes(meshes):
        mesh_name = _influence_node_name(mesh)
        if not cmds.objExists(mesh):
            message = "Mesh does not exist in the scene."
            print(f"[!] Skipping '{mesh_name}': {message}")
            failure_reports.append({
                "mesh": mesh_name,
                "reason": "mesh_not_found",
                "message": message,
            })
            continue

        export_file = f"{mesh_name}_weights.xml"
        json_file = f"{mesh_name}_weights_influences.json"

        xml_path = os.path.join(export_dir, export_file)
        json_path = os.path.join(export_dir, json_file)

        if not os.path.exists(json_path):
            message = "Missing influence file: {}".format(json_path)
            print(f"[!] Skipping '{mesh_name}': {message}")
            failure_reports.append({
                "mesh": mesh_name,
                "reason": "missing_influence_file",
                "message": message,
            })
            continue

        if not os.path.exists(xml_path):
            message = "Missing weight file: {}".format(xml_path)
            print(f"[!] Skipping '{mesh_name}': {message}")
            failure_reports.append({
                "mesh": mesh_name,
                "reason": "missing_weight_file",
                "message": message,
            })
            continue

        with open(json_path, "r") as f:
            influences = json.load(f)

        scene_joints = cmds.ls(type="joint", long=True) or []
        scene_influences = list(scene_joints)
        for saved_influence in influences:
            for exact_node in cmds.ls(saved_influence, long=True) or []:
                if exact_node not in scene_influences:
                    scene_influences.append(exact_node)
        resolution = _resolve_scene_influences(influences, scene_influences)
        influence_mapping = resolution["mapping"]
        missing_influences = resolution["missing"]
        ambiguous_influences = resolution["ambiguous"]
        renamed_influences = []
        rename_failures = {}
        rename_candidates = {}
        if missing_influences and missing_influence_resolver:
            rename_plan = _propose_safe_influence_renames(
                missing_influences, scene_joints
            )
            rename_candidates = rename_plan["proposals"]
            if rename_candidates and missing_influence_resolver(
                    mesh_name,
                    rename_candidates,
                    rename_plan["unresolved"],
                    rename_plan["ambiguous"],
            ):
                renamed, rename_failures = _rename_scene_influences(
                    rename_candidates
                )
                renamed_influences = list(renamed.values())
                if renamed and not rename_failures:
                    scene_joints = cmds.ls(type="joint", long=True) or []
                    scene_influences = list(scene_joints)
                    for saved_influence in influences:
                        for exact_node in cmds.ls(
                                saved_influence, long=True
                        ) or []:
                            if exact_node not in scene_influences:
                                scene_influences.append(exact_node)
                    resolution = _resolve_scene_influences(
                        influences, scene_influences
                    )
                    influence_mapping = resolution["mapping"]
                    missing_influences = resolution["missing"]
                    ambiguous_influences = resolution["ambiguous"]
        if missing_influences or ambiguous_influences:
            suggestions = _find_similar_scene_influences(
                missing_influences, scene_joints
            )
            if missing_influences:
                message = _format_missing_influence_failure(
                    mesh_name, missing_influences, suggestions
                )
            else:
                message = (
                    "[!] Skipping '{}': saved skin influences do not map "
                    "uniquely to scene joints."
                ).format(mesh_name)
            if ambiguous_influences:
                ambiguity_lines = [
                    "    Ambiguous influence mappings were refused:"
                ]
                for saved_name, matches in ambiguous_influences.items():
                    ambiguity_lines.append(
                        "    - {}: {}".format(saved_name, ", ".join(matches))
                    )
                ambiguity_lines.append(
                    "    No scene joints were renamed and no weights were imported."
                )
                message = "{}\n{}".format(message, "\n".join(ambiguity_lines))
            print(message)
            failure_reports.append({
                "mesh": mesh_name,
                "reason": (
                    "ambiguous_influences"
                    if ambiguous_influences else "missing_influences"
                ),
                "message": message,
                "missing_influences": missing_influences,
                "ambiguous_influences": ambiguous_influences,
                "similar_influences": suggestions,
                "rename_candidates": rename_candidates,
                "rename_failures": rename_failures,
                "renamed_influences": renamed_influences,
            })
            continue

        resolved_influences = [influence_mapping[name] for name in influences]
        mapped_influences = [
            {
                "weight_map_influence": saved_name,
                "scene_influence": scene_joint,
            }
            for saved_name, scene_joint in influence_mapping.items()
            if _influence_requires_remap(saved_name, scene_joint)
        ]
        exported_vertex_count = _deformer_weights_vertex_count(xml_path)
        scene_vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
        if (
                exported_vertex_count is not None
                and exported_vertex_count != scene_vertex_count
        ):
            message = (
                "Topology mismatch: weight file contains {} vertices, but "
                "the target mesh contains {}. Index-based weights were not "
                "imported."
            ).format(exported_vertex_count, scene_vertex_count)
            failure_reports.append({
                "mesh": mesh_name,
                "reason": "topology_mismatch",
                "message": message,
                "exported_vertex_count": exported_vertex_count,
                "scene_vertex_count": scene_vertex_count,
            })
            print("[!] Skipping '{}': {}".format(mesh_name, message))
            continue

        # Reuse an existing skinCluster so every current influence and its
        # dagPose membership remain intact. Imported influences missing from the
        # cluster are added at zero weight; no influence is ever removed.
        existing = cmds.listHistory(mesh, pdo=True) or []
        existing_skin = next(
            (node for node in existing if cmds.nodeType(node) == "skinCluster"),
            None,
        )
        existing_influences = (
            list(cmds.skinCluster(existing_skin, query=True, influence=True) or [])
            if existing_skin else []
        )
        original_influence_names = {
            (cmds.ls(influence, long=True) or [influence])[0]
            for influence in existing_influences
        }
        original_bind_poses = {
            influence: set(cmds.listConnections(
                influence + ".bindPose",
                source=True,
                destination=False,
                type="dagPose",
            ) or [])
            for influence in existing_influences
            if cmds.objExists(influence + ".bindPose")
        }
        added_influences = []

        import_stage = "skin_cluster_setup"
        transaction_open = False
        transaction_started = False
        try:
            cmds.undoInfo(
                openChunk=True,
                chunkName="Prepare and Import Skin Weights",
            )
            transaction_open = True
            transaction_started = True
            if existing_skin:
                skin_cluster = existing_skin
                current_names = set(original_influence_names)
                for influence in resolved_influences:
                    long_name = (cmds.ls(influence, long=True) or [influence])[0]
                    if long_name in current_names:
                        continue
                    cmds.skinCluster(
                        skin_cluster,
                        edit=True,
                        addInfluence=influence,
                        lockWeights=False,
                        weight=0.0,
                    )
                    current_names.add(long_name)
                    added_influences.append(influence)
            else:
                skin_cluster = cmds.skinCluster(
                    resolved_influences,
                    mesh,
                    toSelectedBones=True,
                    normalizeWeights=1,
                    bindMethod=0,
                    skinMethod=0,
                    removeUnusedInfluence=False,
                )[0]
            import_stage = "weight_import"
            shape_nodes = cmds.listRelatives(
                mesh, shapes=True, noIntermediate=True, fullPath=True
            ) or cmds.listRelatives(mesh, shapes=True, fullPath=True) or []
            if not shape_nodes:
                raise RuntimeError("Target mesh has no importable shape node.")
            prepared_xml_path = _prepare_deformer_weights_xml(
                xml_path,
                influence_mapping,
                skin_cluster,
                shape_nodes[0],
            )
            import_options = {
                "path": os.path.dirname(prepared_xml_path),
                "deformer": skin_cluster,
                "im": True,
                "method": "index",
            }
            try:
                cmds.deformerWeights(
                    os.path.basename(prepared_xml_path), **import_options
                )
            finally:
                if os.path.exists(prepared_xml_path):
                    os.remove(prepared_xml_path)
        except Exception as e:
            if transaction_open:
                cmds.undoInfo(closeChunk=True)
                transaction_open = False
            rollback_error = None
            if transaction_started:
                try:
                    cmds.undo()
                except Exception as undo_exc:
                    rollback_error = str(undo_exc)
            else:
                rollback_error = "The import undo transaction could not be opened."
            if import_stage == "skin_cluster_setup":
                reason = "skin_cluster_setup_failed"
                message = "Failed to prepare skinCluster: {}".format(e)
            else:
                reason = "weight_import_failed"
                message = "Failed to load weight data: {}".format(e)
            if rollback_error:
                message += " Automatic rollback also failed: {}".format(
                    rollback_error
                )
            else:
                message += " Skin setup changes were rolled back."
            print("[!] {} for '{}'.".format(message, mesh_name))
            failure_reports.append({
                "mesh": mesh_name,
                "reason": reason,
                "message": message,
                "rolled_back": rollback_error is None,
            })
            continue
        else:
            if transaction_open:
                cmds.undoInfo(closeChunk=True)
                transaction_open = False

        final_influences = list(
            cmds.skinCluster(skin_cluster, query=True, influence=True) or []
        )
        final_influence_names = {
            (cmds.ls(influence, long=True) or [influence])[0]
            for influence in final_influences
        }
        removed_influences = sorted(original_influence_names - final_influence_names)
        changed_bind_poses = []
        for influence, bind_poses in original_bind_poses.items():
            current_bind_poses = set(cmds.listConnections(
                influence + ".bindPose",
                source=True,
                destination=False,
                type="dagPose",
            ) or [])
            if not bind_poses.issubset(current_bind_poses):
                changed_bind_poses.append(influence)
        if removed_influences or changed_bind_poses:
            raise RuntimeError(
                "Skin import changed the existing bind: removed influences={} "
                "changed bind poses={}".format(
                    removed_influences,
                    changed_bind_poses,
                )
            )

        _run_weight_hammer(mesh)
        imported_meshes.append(mesh_name)
        influence_reports.append({
            "mesh": mesh_name,
            "skin_cluster": skin_cluster,
            "preserved_influences": existing_influences,
            "added_influences": added_influences,
            "renamed_influences": renamed_influences,
            "mapped_influences": mapped_influences,
            "final_influences": final_influences,
            "bind_pose_preserved": True,
        })
        print(f"[?] Imported: {mesh_name}")

    # Skin import must not reposition rig pivots. Reverse-foot helpers are snapped
    # only after the deformation legs have been normalized by set_t_pose().
    return {
        "imported_meshes": imported_meshes,
        "influence_reports": influence_reports,
        "failure_reports": failure_reports,
        "rfl_snap": {
            "stage": "skin_import_deferred_to_t_pose",
            "skipped": True,
            "skeleton_count": 0,
            "reports": [],
        },
    }


#export_skin_weights(cmds.ls(sl=True), "C:/temp/weights")
# import_skin_weights(cmds.ls(sl=True), export_dir)
