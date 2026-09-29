#ifndef TC_RUNTIME_CORE_H
#define TC_RUNTIME_CORE_H

#include "tc_graph_runtime.h"

#include <cstdint>
#include <array>
#include <filesystem>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace tc::runtime {

using EntityId = std::uint32_t;

struct WorldVector3 {
    double x{0.0};
    double y{0.0};
    double z{0.0};
};

struct Transform {
    WorldVector3 position{};
    TcGraphVector3 rotation{};
    TcGraphVector3 scale{1.0F, 1.0F, 1.0F};
};

struct Renderable {
    std::string mesh_asset;
    std::string material_asset;
    std::string base_color_texture;
    std::string normal_texture;
    std::string roughness_texture;
    std::string metallic_texture;
    std::string emission_texture;
    std::string skin_binding;
    TcGraphVector3 base_color{0.18F, 0.62F, 0.82F};
    float metallic{0.0F};
    float roughness{0.45F};
    bool casts_shadow{true};
};

struct RigidBody {
    WorldVector3 velocity{};
    WorldVector3 angular_velocity{};
    double mass{1.0};
    float restitution{0.2F};
    float linear_damping{0.01F};
    float angular_damping{0.05F};
    float gravity_scale{1.0F};
    WorldVector3 inertia_diagonal{1.0, 1.0, 1.0};
    double sleep_timer{0.0};
    bool dynamic{true};
    bool kinematic{false};
    bool continuous_collision{false};
    bool allow_sleep{true};
    bool sleeping{false};
};

enum class ColliderShape : std::uint8_t { box, sphere, capsule, convex_hull, triangle_mesh, compound };

struct CookedCollisionChild {
    ColliderShape shape{ColliderShape::box};
    WorldVector3 translation{};
    std::array<float, 4> rotation{0.0F, 0.0F, 0.0F, 1.0F};
    WorldVector3 half_extents{0.5, 0.5, 0.5};
    double radius{0.5};
    double half_height{0.5};
};

struct CookedCollisionAsset {
    ColliderShape shape{ColliderShape::triangle_mesh};
    WorldVector3 bounds_min{};
    WorldVector3 bounds_max{};
    std::vector<WorldVector3> vertices;
    std::vector<std::array<std::uint32_t, 3>> triangles;
    std::vector<CookedCollisionChild> children;
};

enum class PhysicsJointType : std::uint8_t {
    fixed, ball, hinge, slider, distance, spring, cone_twist, six_dof
};

struct Collider {
    WorldVector3 half_extents{0.5, 0.5, 0.5};
    bool trigger{false};
    ColliderShape shape{ColliderShape::box};
    double radius{0.5};
    double half_height{0.5};
    std::uint32_t layer{1U};
    std::uint32_t mask{0xFFFFFFFFU};
    float friction{0.5F};
    float restitution{0.2F};
    std::string collision_asset;
    std::shared_ptr<const CookedCollisionAsset> cooked;
};

struct PhysicsContact {
    EntityId first{0};
    EntityId second{0};
    WorldVector3 point{};
    WorldVector3 normal{};
    double penetration{0.0};
    bool trigger{false};
};

struct PhysicsRayHit {
    EntityId entity{0};
    WorldVector3 point{};
    WorldVector3 normal{};
    double distance{0.0};
};

struct PhysicsJoint {
    std::string id;
    PhysicsJointType type{PhysicsJointType::fixed};
    EntityId first{0};
    EntityId second{0};
    WorldVector3 first_anchor{};
    WorldVector3 second_anchor{};
    WorldVector3 axis{1.0, 0.0, 0.0};
    double minimum_limit{0.0};
    double maximum_limit{0.0};
    double stiffness{1.0};
    double damping{0.1};
    double motor_target_velocity{0.0};
    double motor_maximum_force{0.0};
    double break_force{0.0};
    double break_torque{0.0};
    double rest_distance{0.0};
    WorldVector3 rest_rotation{};
    std::array<double, 4> rest_orientation{0.0, 0.0, 0.0, 1.0};
    WorldVector3 accumulated_linear_impulse{};
    WorldVector3 accumulated_angular_impulse{};
    WorldVector3 linear_lower_limit{};
    WorldVector3 linear_upper_limit{};
    WorldVector3 angular_lower_limit{};
    WorldVector3 angular_upper_limit{};
    WorldVector3 linear_spring_stiffness{};
    WorldVector3 linear_spring_damping{};
    WorldVector3 angular_spring_stiffness{};
    WorldVector3 angular_spring_damping{};
    WorldVector3 linear_drive_velocity{};
    WorldVector3 angular_drive_velocity{};
    WorldVector3 linear_drive_maximum_force{};
    WorldVector3 angular_drive_maximum_force{};
    bool extended_six_dof{false};
    bool limits_enabled{false};
    bool motor_enabled{false};
    bool collision_enabled{false};
    bool enabled{true};
    bool broken{false};
};

struct PhysicsJointDiagnostic {
    std::string joint_id;
    WorldVector3 first_anchor{};
    WorldVector3 second_anchor{};
    double position_error{0.0};
    double applied_force{0.0};
    bool broken{false};
};

struct ParticlePhysics {
    double radius_meters{1.0e-9};
    double charge_coulombs{0.0};
    double lennard_jones_epsilon_joules{0.0};
    double lennard_jones_sigma_meters{1.0e-9};
    double rest_density_kg_per_m3{1000.0};
    double viscosity_pascal_seconds{0.001};
    double pressure_stiffness{2000.0};
    bool thermal_motion{true};
};

struct Camera {
    float field_of_view_degrees{55.0F};
    float near_plane{0.05F};
    float far_plane{5000.0F};
    bool active{true};
    WorldVector3 look_at{0.0, 1.0, 0.0};
};

struct DirectionalLight {
    TcGraphVector3 direction{-0.4F, -1.0F, -0.25F};
    TcGraphVector3 color{1.0F, 0.95F, 0.85F};
    float intensity{4.0F};
    bool casts_shadow{true};
    float angular_radius_degrees{0.266F};
};

struct ReflectionProbe {
    std::string environment_texture;
    TcGraphVector3 half_extents{5.0F, 5.0F, 5.0F};
    float intensity{1.0F};
    int priority{0};
};

struct AssetRecord {
    std::string id;
    std::string type;
    std::filesystem::path source;
    std::string content_hash;
};

struct GraphInstruction {
    std::string node_id;
    std::string operation;
    std::vector<std::string> arguments;
    std::string source_file;
    int source_line{0};
};

using Matrix4 = std::array<double, 16>;

struct SkeletonJoint {
    std::string id;
    std::string name;
    int parent_index{-1};
    Matrix4 rest_local{};
    Matrix4 local{};
    Matrix4 world{};
};

struct Skeleton {
    std::string id;
    std::size_t declared_joint_count{0};
    std::vector<SkeletonJoint> joints;
    std::unordered_map<std::string, std::size_t> joint_indices;
};

struct AnimationKey {
    double frame{0.0};
    double value{0.0};
    std::string interpolation{"auto"};
};

struct AnimationCurve {
    std::string joint_id;
    std::string attribute;
    double layer_weight{1.0};
    bool additive{false};
    std::vector<AnimationKey> keys;
};

struct AnimationClip {
    std::string id;
    std::string name;
    std::string skeleton_id;
    double start_frame{1.0};
    double end_frame{1.0};
    double frame_rate{24.0};
    bool looping{true};
    std::vector<AnimationCurve> curves;
};

struct SkinBinding {
    std::string id;
    std::string mesh_id;
    std::string skeleton_id;
    std::string deformation_mode{"linear_blend_skinning"};
    std::size_t vertex_count{0};
    std::size_t maximum_influences{0};
    std::vector<std::string> joint_ids;
    std::string inverse_bind_asset;
    std::string rest_positions_asset;
    std::string influence_offsets_asset;
    std::string joint_indices_asset;
    std::string weights_asset;
};

struct PhysicalAnimationBinding {
    std::string skeleton_id;
    std::string joint_id;
    EntityId body{0};
    double pose_drive_strength{0.8};
    double damping{0.5};
    double maximum_force{10000.0};
    double physics_blend{1.0};
    double muscle_strength{1.0};
};

struct RuntimeProfile {
    double frame_ms{0.0};
    double graph_ms{0.0};
    double physics_ms{0.0};
    double physics_integration_ms{0.0};
    double physics_joint_ms{0.0};
    double physics_collision_ms{0.0};
    int physics_joint_iterations{0};
    double maximum_joint_position_error{0.0};
    std::size_t entities{0};
    std::size_t draw_calls{0};
    std::size_t broadphase_pairs{0};
    std::size_t collision_contacts{0};
    std::size_t solver_islands{0};
    std::size_t sleeping_bodies{0};
};

struct RenderSettings {
    std::string upscaler{"native"};
    std::string quality{"native"};
    float render_scale{1.0F};
    float exposure{1.0F};
    float sharpness{0.2F};
    std::string environment_texture;
    float environment_intensity{1.0F};
    bool dynamic_resolution{false};
    float minimum_render_scale{0.5F};
    float maximum_render_scale{1.0F};
    float target_frame_ms{16.6667F};
    std::string lighting_model{"physically_based"};
    std::string global_illumination{"probe"};
    TcGraphVector3 sky_color{0.08F, 0.18F, 0.42F};
    TcGraphVector3 ground_color{0.025F, 0.035F, 0.045F};
    float indirect_intensity{1.0F};
    float toon_bands{4.0F};
    float rim_intensity{0.15F};
    bool dynamic_diffuse_gi{false};
    float dynamic_gi_intensity{0.35F};
    float dynamic_gi_distance{12.0F};
    int maximum_dynamic_gi_sources{8};
    bool atmosphere_enabled{true};
    float atmosphere_density{1.0F};
    float atmospheric_haze{1.0F};
    float horizon_falloff{4.0F};
};

struct SimulationSettings {
    std::string domain{"everyday"};
    double meters_per_world_unit{1.0};
    double time_scale{1.0};
    WorldVector3 gravity_meters_per_second_squared{0.0, -9.80665, 0.0};
    double fixed_timestep_seconds{1.0 / 120.0};
    int maximum_substeps{8};
    double render_origin_threshold_world_units{10000.0};
    double gravity_softening_meters{1.0};
    bool floor_enabled{true};
    double temperature_kelvin{293.15};
    double medium_viscosity_pascal_seconds{0.001};
    double relative_permittivity{1.0};
    std::uint64_t random_seed{1};
    double long_range_approximation_theta{0.6};
    int joint_solver_iterations{12};
    int contact_solver_iterations{4};
    double shock_propagation_factor{0.35};
    double sleep_linear_threshold{0.05};
    double sleep_angular_threshold{0.05};
    double sleep_delay_seconds{0.5};
};

class World {
public:
    EntityId create_entity(std::string stable_name);
    bool destroy_entity(EntityId entity);
    [[nodiscard]] EntityId find_entity(const std::string& stable_name) const;
    [[nodiscard]] const std::vector<EntityId>& entities() const noexcept;
    [[nodiscard]] const std::string& name(EntityId entity) const;

    std::unordered_map<EntityId, Transform> transforms;
    std::unordered_map<EntityId, Renderable> renderables;
    std::unordered_map<EntityId, RigidBody> rigid_bodies;
    std::unordered_map<EntityId, Collider> colliders;
    std::unordered_map<std::string, PhysicsJoint> physics_joints;
    std::unordered_map<EntityId, ParticlePhysics> particles;
    std::unordered_map<EntityId, Camera> cameras;
    std::unordered_map<EntityId, DirectionalLight> lights;
    std::unordered_map<EntityId, ReflectionProbe> reflection_probes;
    std::unordered_map<std::string, AssetRecord> assets;
    std::unordered_map<std::string, Skeleton> skeletons;
    std::unordered_map<std::string, AnimationClip> animation_clips;
    std::unordered_map<std::string, SkinBinding> skin_bindings;
    std::vector<PhysicalAnimationBinding> physical_animation_bindings;
    std::vector<GraphInstruction> begin_play;
    std::vector<GraphInstruction> tick;
    std::unordered_map<std::string, double> variables;
    std::vector<std::string> events;
    std::string hud_text{"TC Runtime"};
    std::string save_slot{"autosave"};
    RenderSettings render_settings;
    SimulationSettings simulation_settings;

private:
    EntityId next_entity_{1};
    std::vector<EntityId> entities_;
    std::unordered_map<EntityId, std::string> names_;
    std::unordered_map<std::string, EntityId> ids_by_name_;
};

class Runtime {
public:
    bool load_manifest(const std::filesystem::path& path, std::string& error);
    void begin_play();
    void set_input_axis(float x, float y) noexcept;
    void set_jump_pressed(bool pressed) noexcept;
    void tick(float delta_seconds);
    bool save(const std::filesystem::path& path, std::string& error) const;
    bool load_save(const std::filesystem::path& path, std::string& error);

    [[nodiscard]] World& world() noexcept;
    [[nodiscard]] const World& world() const noexcept;
    [[nodiscard]] const RuntimeProfile& profile() const noexcept;
    [[nodiscard]] const std::vector<std::string>& debug_trace() const noexcept;
    [[nodiscard]] const std::vector<PhysicsContact>& physics_contacts() const noexcept;
    [[nodiscard]] const std::vector<PhysicsJointDiagnostic>& physics_joint_diagnostics() const noexcept;
    [[nodiscard]] const std::string& active_animation_id() const noexcept { return active_animation_id_; }
    [[nodiscard]] const std::string& previous_animation_id() const noexcept { return previous_animation_id_; }
    [[nodiscard]] double animation_blend_alpha() const noexcept {
        return animation_blend_duration_seconds_ <= 0.0 ? 1.0 :
            std::clamp(animation_blend_elapsed_seconds_ / animation_blend_duration_seconds_, 0.0, 1.0);
    }
    [[nodiscard]] bool raycast(const WorldVector3& origin, const WorldVector3& direction,
                               double maximum_distance, PhysicsRayHit& hit,
                               std::uint32_t layer_mask = 0xFFFFFFFFU) const;

private:
    void execute(const std::vector<GraphInstruction>& instructions, float delta_seconds);
    void simulate(double delta_seconds);
    void simulate_step(double step_seconds);
    void solve_physics_joints(double step_seconds);
    void simulate_microscopic_forces(double step_seconds, bool molecular);
    void simulate_fluid_forces(double step_seconds);
    void apply_thermal_motion(double step_seconds);
    void evaluate_animation(double delta_seconds);
    void apply_physical_animation_drives(double step_seconds);
    void blend_physical_animation_pose();

    World world_;
    RuntimeProfile profile_;
    std::vector<std::string> debug_trace_;
    TcGraphVector2 input_axis_{};
    bool jump_pressed_{false};
    bool jump_was_pressed_{false};
    std::unordered_map<EntityId, double> character_ground_grace_seconds_;
    std::unordered_map<EntityId, double> character_jump_buffer_seconds_;
    std::unordered_map<EntityId, bool> character_was_grounded_;
    std::unordered_map<EntityId, double> character_land_seconds_;
    std::size_t broadphase_pairs_{0};
    std::size_t collision_contacts_{0};
    std::size_t solver_islands_{0};
    std::vector<PhysicsContact> physics_contacts_;
    std::vector<PhysicsJointDiagnostic> physics_joint_diagnostics_;
    std::uint64_t simulation_step_index_{0};
    std::string active_animation_id_;
    std::string previous_animation_id_;
    double animation_time_seconds_{0.0};
    double previous_animation_time_seconds_{0.0};
    double animation_blend_duration_seconds_{0.0};
    double animation_blend_elapsed_seconds_{0.0};
    double animation_playback_speed_{1.0};
    bool animation_playing_{true};
};

std::string stable_asset_id(const std::string& type, const std::string& canonical_path);
bool build_skin_matrix_palette(const World& world, const std::string& skin_id, std::vector<Matrix4>& palette, std::string& error);

}  // namespace tc::runtime

#endif
