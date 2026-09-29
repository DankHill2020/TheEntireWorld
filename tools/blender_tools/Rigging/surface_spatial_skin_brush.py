"""Topology-independent weight-smoothing brush for Blender."""

import bpy
from bpy_extras import view3d_utils
from mathutils.kdtree import KDTree

from tech_connector.game_engine.deformation.spatial_skin_smoothing_service import spatial_smooth_weight_rows


class TC_OT_surface_spatial_skin_smooth_brush(bpy.types.Operator):
    bl_idname = "tc.surface_spatial_skin_smooth_brush"
    bl_label = "Surface Spatial Skin Smooth Brush"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    radius: bpy.props.FloatProperty(name="Radius", default=1.0, min=0.0001)
    strength: bpy.props.FloatProperty(name="Strength", default=0.5, min=0.01, max=1.0)
    iterations: bpy.props.IntProperty(name="Iterations", default=1, min=1, max=8)
    max_influences: bpy.props.IntProperty(name="Max Influences", default=8, min=1, max=32)
    normal_angle: bpy.props.FloatProperty(name="Normal Gate", default=120.0, min=0.0, max=180.0)
    max_neighbors: bpy.props.IntProperty(name="Neighbor Limit", default=96, min=2, max=256)
    cross_region_share: bpy.props.FloatProperty(name="Cross-Region Mix", default=0.45, min=0.05, max=0.49)

    def invoke(self, context, _event):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select one skinned mesh.")
            return {"CANCELLED"}
        if not obj.vertex_groups:
            self.report({"ERROR"}, "The selected mesh has no skin vertex groups.")
            return {"CANCELLED"}
        self.obj = obj
        self.positions = [tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices]
        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        self.normals = [tuple((normal_matrix @ vertex.normal).normalized()) for vertex in obj.data.vertices]
        self.sample_weights = [0.0] * len(self.positions)
        for polygon in obj.data.polygons:
            if not polygon.vertices:
                continue
            share = float(polygon.area) / float(len(polygon.vertices))
            for vertex_index in polygon.vertices:
                self.sample_weights[int(vertex_index)] += share
        self.kd = KDTree(len(self.positions))
        for index, position in enumerate(self.positions):
            self.kd.insert(position, index)
        self.kd.balance()
        self.stroke_vertices = set()
        self.painting = False
        context.window_manager.modal_handler_add(self)
        context.window.cursor_set("CROSSHAIR")
        self.report({"INFO"}, "Drag to spatially smooth; Esc or right-click exits.")
        return {"RUNNING_MODAL"}

    def _hit(self, context, event):
        region, region_data = context.region, context.region_data
        coordinate = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coordinate)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coordinate)
        hit, location, _normal, _face, hit_object, _matrix = context.scene.ray_cast(
            context.evaluated_depsgraph_get(), origin, direction)
        return location if hit and getattr(hit_object, "original", hit_object) == self.obj else None

    def _collect(self, context, event):
        location = self._hit(context, event)
        if location is None:
            return
        self.stroke_vertices.update(index for _position, index, _distance in self.kd.find_range(location, self.radius))

    def _rows(self):
        group_names = [group.name for group in self.obj.vertex_groups]
        rows = []
        for vertex in self.obj.data.vertices:
            row = {}
            for membership in vertex.groups:
                if membership.group < len(group_names) and membership.weight > 0.0:
                    row[group_names[membership.group]] = float(membership.weight)
            rows.append(row)
        return rows, group_names

    def _apply_stroke(self):
        if not self.stroke_vertices:
            return
        rows, group_names = self._rows()
        locked = [group.name for group in self.obj.vertex_groups if group.lock_weight]
        output, changed = spatial_smooth_weight_rows(
            self.positions,
            rows,
            radius=self.radius,
            strength=self.strength,
            iterations=self.iterations,
            target_indices=self.stroke_vertices,
            normals=self.normals,
            normal_angle=self.normal_angle,
            max_neighbors=self.max_neighbors,
            max_influences=self.max_influences,
            locked_influences=locked,
            sample_weights=self.sample_weights,
            cross_region_share=self.cross_region_share,
        )
        groups = {group.name: group for group in self.obj.vertex_groups}
        for index in changed:
            row = output[index]
            for name in group_names:
                group = groups[name]
                if group.lock_weight:
                    continue
                if row.get(name, 0.0) > 0.0000001:
                    group.add([index], row[name], "REPLACE")
                else:
                    try:
                        group.remove([index])
                    except RuntimeError:
                        pass
        self.obj.data.update()
        bpy.ops.ed.undo_push(message="Surface Spatial Smooth Stroke")

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.window.cursor_set("DEFAULT")
            return {"FINISHED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.stroke_vertices.clear()
            self.painting = True
            self._collect(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and self.painting:
            self._collect(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self.painting:
            self.painting = False
            self._collect(context, event)
            self._apply_stroke()
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}


class TC_PT_surface_spatial_skin_smooth_brush(bpy.types.Panel):
    bl_label = "Surface Spatial Skin Brush"
    bl_idname = "TC_PT_surface_spatial_skin_smooth_brush"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TC Rigging"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "tc_spatial_skin_radius")
        layout.prop(scene, "tc_spatial_skin_strength")
        layout.prop(scene, "tc_spatial_skin_iterations")
        layout.prop(scene, "tc_spatial_skin_max_influences")
        layout.prop(scene, "tc_spatial_skin_normal_angle")
        layout.prop(scene, "tc_spatial_skin_max_neighbors")
        layout.prop(scene, "tc_spatial_skin_cross_region")
        operator = layout.operator(
            TC_OT_surface_spatial_skin_smooth_brush.bl_idname,
            text="Activate Smooth Brush",
            icon="BRUSH_SMOOTH",
        )
        operator.radius = scene.tc_spatial_skin_radius
        operator.strength = scene.tc_spatial_skin_strength
        operator.iterations = scene.tc_spatial_skin_iterations
        operator.max_influences = scene.tc_spatial_skin_max_influences
        operator.normal_angle = scene.tc_spatial_skin_normal_angle
        operator.max_neighbors = scene.tc_spatial_skin_max_neighbors
        operator.cross_region_share = scene.tc_spatial_skin_cross_region


def register():
    properties = {
        "tc_spatial_skin_radius": bpy.props.FloatProperty(name="Radius", default=1.0, min=0.0001),
        "tc_spatial_skin_strength": bpy.props.FloatProperty(name="Strength", default=0.5, min=0.01, max=1.0),
        "tc_spatial_skin_iterations": bpy.props.IntProperty(name="Iterations", default=1, min=1, max=8),
        "tc_spatial_skin_max_influences": bpy.props.IntProperty(name="Max Influences", default=8, min=1, max=32),
        "tc_spatial_skin_normal_angle": bpy.props.FloatProperty(name="Normal Gate", default=120.0, min=0.0, max=180.0),
        "tc_spatial_skin_max_neighbors": bpy.props.IntProperty(name="Neighbor Limit", default=96, min=2, max=256),
        "tc_spatial_skin_cross_region": bpy.props.FloatProperty(
            name="Cross-Region Mix", default=0.45, min=0.05, max=0.49),
    }
    for name, value in properties.items():
        if not hasattr(bpy.types.Scene, name):
            setattr(bpy.types.Scene, name, value)
    for cls in (TC_OT_surface_spatial_skin_smooth_brush, TC_PT_surface_spatial_skin_smooth_brush):
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def activate(**settings):
    register()
    return bpy.ops.tc.surface_spatial_skin_smooth_brush("INVOKE_DEFAULT", **settings)


__all__ = [
    "TC_OT_surface_spatial_skin_smooth_brush",
    "TC_PT_surface_spatial_skin_smooth_brush",
    "activate",
    "register",
]
