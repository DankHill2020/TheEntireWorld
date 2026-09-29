import maya.cmds as cmds
import maya.mel as mel
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.OpenMaya as om1
import maya.OpenMayaUI as omui1
from collections import OrderedDict
from array import array
import json
import math
import os
import re
import time

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


def smooth_skin_weights_spatial_from_selection(
        radius=1.0, iterations=4, strength=0.5, max_influences=4,
        normal_angle=75.0, max_neighbors=48, cross_region_share=0.45):
    """Smooth the selected skin using surface position instead of edge topology."""
    mesh, vertices = _selected_mesh_and_vertices()
    return smooth_skin_weights_spatial(
        mesh,
        vertex_indices=vertices,
        radius=radius,
        iterations=iterations,
        strength=strength,
        max_influences=max_influences,
        normal_angle=normal_angle,
        max_neighbors=max_neighbors,
        adaptive_radius=True,
        cross_region_share=cross_region_share,
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
    dominant_influences = []
    for vertex_index in range(vertex_count):
        offset = vertex_index * influence_count
        dominant_influences.append(max(
            range(influence_count),
            key=lambda influence: original[offset + influence],
        ))

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
                for neighbor, falloff in balanced_neighbors(vertex_index):
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
        "iterations": completed,
        "radius": radius,
        "requestedRadius": requested_radius,
        "autoExpandedRadius": auto_expanded,
        "strength": strength,
        "maxInfluences": max_influences,
        "normalAngle": normal_angle,
        "maxNeighbors": max_neighbors,
        "changedVertices": changed_vertices,
        "maxDelta": maximum_delta,
        "lockedInfluences": len(locked),
        "weightRegions": len(set(dominant_influences)),
        "crossRegionShare": cross_region_share,
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

    for mesh in meshes:
        if not cmds.objExists(mesh):
            print(f"[!] Skipping '{mesh}': does not exist.")
            continue

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

        export_name = f"{mesh}_weights.xml"
        json_name = f"{mesh}_weights_influences.json"

        try:
            cmds.deformerWeights(export_name,
                                 path=export_dir,
                                 deformer=skin_cluster,
                                 export=True,
                                 shape=shape_node)
        except Exception as e:
            print(f"[!] Failed to export weights for '{mesh}': {e}")
            continue

        with open(os.path.join(export_dir, json_name), 'w') as f:
            json.dump(influences, f, indent=2)

        print(f"[?] Exported: {mesh}")


def import_skin_weights(meshes, export_dir="C:/temp/weights"):
    """
    Imports skin weights for a list of meshes from XML and JSON files.
    :param meshes: list of mesh names to import to
    :param export_dir: directory where XML and JSON files are stored
    """
    export_dir = os.path.normpath(export_dir)

    for mesh in meshes:
        if not cmds.objExists(mesh):
            print(f"[!] Skipping '{mesh}': does not exist.")
            continue

        export_file = f"{mesh}_weights.xml"
        json_file = f"{mesh}_weights_influences.json"

        xml_path = os.path.join(export_dir, export_file)
        json_path = os.path.join(export_dir, json_file)

        if not os.path.exists(json_path):
            print(f"[!] Skipping '{mesh}': missing JSON {json_path}")
            continue

        if not os.path.exists(xml_path):
            print(f"[!] Skipping '{mesh}': missing XML {xml_path}")
            continue

        with open(json_path, "r") as f:
            influences = json.load(f)

        if not all(cmds.objExists(jnt) for jnt in influences):
            print(f"[!] Skipping '{mesh}': missing influences in scene.")
            continue

        # Remove old skinCluster
        existing = cmds.listHistory(mesh, pdo=True) or []
        existing_skin = next((h for h in existing if cmds.nodeType(h) == "skinCluster"), None)
        if existing_skin:
            cmds.delete(existing_skin)

        # Create new skinCluster
        try:
            skin_cluster = cmds.skinCluster(influences, mesh, toSelectedBones=True,
                                            normalizeWeights=1, bindMethod=0,
                                            skinMethod=0, removeUnusedInfluence=False)[0]
        except Exception as e:
            print(f"[!] Failed to create skinCluster for '{mesh}': {e}")
            continue

        try:
            cmds.deformerWeights(export_file,
                                 path=export_dir,
                                 deformer=skin_cluster,
                                 im=True,
                                 method="index")
        except Exception as e:
            print(f"[!] Failed to import weights for '{mesh}': {e}")
            continue

        _run_weight_hammer(mesh)
        print(f"[?] Imported: {mesh}")



#export_skin_weights(cmds.ls(sl=True), "C:/temp/weights")
# import_skin_weights(cmds.ls(sl=True), export_dir)
