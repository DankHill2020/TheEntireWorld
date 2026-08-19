#include "tc_runtime_core.h"
#include "tc_force_tree.h"
#include "tc_spatial_index.h"

#include <cmath>
#include <filesystem>
#include <fstream>
#include <string>
#include <stdexcept>

int main() {
    using namespace tc::runtime;
    SpatialNeighborhoodIndex spatial_index(0.5);
    spatial_index.rebuild({{3,{1.0e12+0.2,2.0,3.0}},{1,{1.0e12,2.0,3.0}},{2,{1.0e12+0.6,2.0,3.0}}});
    const auto nearby=spatial_index.query_radius({1.0e12,2.0,3.0},0.25);
    if(nearby!=std::vector<std::uint32_t>{1,3})return 28;
    bool invalid_cell_rejected=false;
    try{SpatialNeighborhoodIndex invalid(0.0);static_cast<void>(invalid);}catch(const std::invalid_argument&){invalid_cell_rejected=true;}
    if(!invalid_cell_rejected)return 29;
    BarnesHutMassTree mass_tree({{1,{0.0,0.0,0.0},1.0},{2,{10.0,0.0,0.0},10.0}});
    const auto tree_acceleration=mass_tree.acceleration_at(1,{0.0,0.0,0.0},1.0,0.0,0.6);
    if(std::fabs(tree_acceleration.x-0.1)>1.0e-12||tree_acceleration.y!=0.0||tree_acceleration.z!=0.0)return 30;
    const auto manifest = std::filesystem::temp_directory_path() / "tc_runtime_core_test.tcruntime";
    {
        std::ofstream stream(manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\n"
               << "ASSET\ttc.asset.cube\tmesh\tbuiltin%3Acube\tstable\n"
               << "ENTITY\tPlayer\n"
               << "TRANSFORM\tPlayer\t0\t2\t0\t0\t0\t0\t1\t1\t1\n"
               << "RENDER\tPlayer\ttc.asset.cube\tmat.blue\t0.1\t0.5\t0.9\t0.1\t0.4\t1\n"
               << "RIGID\tPlayer\t0\t0\t0\t1\t0\t1\t0\t1\t0\t0\t0\t1\t0\t1\n"
               << "COLLIDER\tPlayer\t0.5\t0.5\t0.5\t0\tsphere\t0.5\t0.5\t1\t4294967295\t0.75\t0.4\n"
               << "PROBE\tPlayer\ttc.asset.studio\t4\t3\t5\t1.25\t2\n"
               << "GRAPH\tbegin\tn1\tvariable.set\tsample.tcgraph\t4\tscore\t1\n"
               << "GRAPH\ttick\tn2\ttime.accumulate\tsample.tcgraph\t8\telapsed\n"
               << "GRAPH\ttick\tn3\tinput.move\tsample.tcgraph\t9\tPlayer\t4\n"
               << "GRAPH\ttick\tn4\tbranch.greater\tsample.tcgraph\t10\telapsed\t0.01\tReady\n"
               << "GRAPH\ttick\tread\tinput.read_axis\tsample.tcgraph\t11\tMove\n"
               << "GRAPH\ttick\tcalculate\tmovement.calculate_velocity\tsample.tcgraph\t12\t@graph:read:value\t7.5\t30\tSelf\n"
               << "GRAPH\ttick\tapply\tactor.set_velocity\tsample.tcgraph\t13\tSelf\t@graph:calculate:velocity\n";
    }

    Runtime runtime;
    std::string error;
    if (!runtime.load_manifest(manifest, error)) return 1;
    if (runtime.world().entities().size() != 1) return 2;
    if (runtime.world().assets.size() != 1) return 3;
    if (runtime.world().reflection_probes.size() != 1) return 15;
    if (runtime.world().reflection_probes.begin()->second.priority != 2) return 16;
    const auto loaded_player = runtime.world().find_entity("Player");
    if (runtime.world().colliders.at(loaded_player).shape != ColliderShape::sphere) return 38;
    if (!runtime.world().rigid_bodies.at(loaded_player).continuous_collision) return 39;
    PhysicsRayHit ray_hit;
    if (!runtime.raycast({-2.0, 2.0, 0.0}, {1.0, 0.0, 0.0}, 10.0, ray_hit) || ray_hit.entity != loaded_player) return 40;
    runtime.begin_play();
    runtime.set_input_axis(1.0F, 0.0F);
    runtime.tick(1.0F / 30.0F);
    const auto player = runtime.world().find_entity("Player");
    if (player == 0U) return 4;
    if (runtime.world().transforms[player].position.x <= 0.0F) return 5;
    if (runtime.world().variables["score"] != 1.0F) return 6;
    if (runtime.world().variables["@graph:calculate:velocity.x"] <= 0.0F) return 78;
    if (runtime.world().events.empty()) return 7;
    const auto obstacle = runtime.world().create_entity("Obstacle");
    runtime.world().transforms[obstacle].position = {0.8F, runtime.world().transforms[player].position.y, 0.0F};
    runtime.world().colliders[obstacle] = Collider{{0.5F, 0.5F, 0.5F}, false};
    runtime.tick(1.0F / 60.0F);
    if (runtime.profile().broadphase_pairs == 0) return 13;
    if (runtime.profile().collision_contacts == 0) return 14;
    if (runtime.profile().physics_collision_ms <= 0.0 || runtime.profile().physics_integration_ms < 0.0) return 76;
    if (runtime.physics_contacts().empty() || runtime.physics_contacts().front().penetration <= 0.0) return 41;

    const auto joint_manifest = std::filesystem::temp_directory_path() / "tc_runtime_joint_test.tcruntime";
    {
        std::ofstream stream(joint_manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\n"
               << "ENTITY\tAnchor\nTRANSFORM\tAnchor\t0\t3\t0\t0\t0\t0\t1\t1\t1\n"
               << "RIGID\tAnchor\t0\t0\t0\t1\t0\t0\n"
               << "ENTITY\tWeight\nTRANSFORM\tWeight\t0\t1\t0\t0\t0\t0\t1\t1\t1\n"
               << "RIGID\tWeight\t0\t0\t0\t1\t0\t1\n"
               << "PHYSICSJOINT\thanger\tdistance\tAnchor\tWeight\t0\t0\t0\t0\t0\t0\t0\t1\t0\t2\t2\t1\t0.2\t0\t0\t0\t0\t1\t0\t0\t1\n"
               << "SIMULATION\teveryday\t1\t1\t0\t-9.80665\t0\t0.008333333333333333\t8\t10000\t1\t0\t293.15\t0.001\t1\t1\t0.6\t16\n";
    }
    Runtime joint_runtime;
    if (!joint_runtime.load_manifest(joint_manifest, error)) return 42;
    if (joint_runtime.world().physics_joints.size() != 1U) return 43;
    for (int frame = 0; frame < 120; ++frame) joint_runtime.tick(1.0F / 60.0F);
    if (joint_runtime.profile().physics_joint_ms <= 0.0) return 77;
    const auto anchor_id = joint_runtime.world().find_entity("Anchor");
    const auto weight_id = joint_runtime.world().find_entity("Weight");
    const auto separation = joint_runtime.world().transforms.at(anchor_id).position.y - joint_runtime.world().transforms.at(weight_id).position.y;
    if (std::fabs(separation - 2.0) > 0.02) return 44;
    if (joint_runtime.physics_joint_diagnostics().size() != 1U || joint_runtime.physics_joint_diagnostics().front().joint_id != "hanger") return 45;
    joint_runtime.world().physics_joints.at("hanger").break_force = 1.0;
    joint_runtime.world().transforms.at(weight_id).position.y = -10.0;
    joint_runtime.tick(1.0F / 60.0F);
    if (!joint_runtime.world().physics_joints.at("hanger").broken) return 46;
    if (joint_runtime.physics_joint_diagnostics().empty() || !joint_runtime.physics_joint_diagnostics().front().broken) return 47;
    const auto joint_save = std::filesystem::temp_directory_path() / "tc_runtime_joint_test.tcsave";
    joint_runtime.world().transforms.at(weight_id).rotation = {12.0F, 23.0F, 34.0F};
    joint_runtime.world().rigid_bodies.at(weight_id).velocity = {4.0, 5.0, 6.0};
    if (!joint_runtime.save(joint_save, error)) return 48;
    joint_runtime.world().transforms.at(weight_id).rotation = {};
    joint_runtime.world().rigid_bodies.at(weight_id).velocity = {};
    joint_runtime.world().physics_joints.at("hanger").broken = false;
    if (!joint_runtime.load_save(joint_save, error)) return 49;
    if (joint_runtime.world().transforms.at(weight_id).rotation.y != 23.0F) return 50;
    if (joint_runtime.world().rigid_bodies.at(weight_id).velocity.z != 6.0) return 51;
    if (!joint_runtime.world().physics_joints.at("hanger").broken) return 52;

    const auto local_anchor_manifest = std::filesystem::temp_directory_path() / "tc_runtime_local_anchor_test.tcruntime";
    {
        std::ofstream stream(local_anchor_manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\n"
               << "ENTITY\tRotated\nTRANSFORM\tRotated\t0\t0\t0\t0\t0\t90\t1\t1\t1\nRIGID\tRotated\t0\t0\t0\t1\t0\t0\n"
               << "ENTITY\tFollower\nTRANSFORM\tFollower\t0\t1\t0\t0\t0\t90\t1\t1\t1\nRIGID\tFollower\t0\t0\t0\t1\t0\t1\n"
               << "PHYSICSJOINT\tlocal_anchor\tball\tRotated\tFollower\t1\t0\t0\t0\t0\t0\t1\t0\t0\t0\t0\t1\t0.1\t0\t0\t0\t0\t0\t0\t0\t1\n"
               << "SIMULATION\teveryday\t1\t1\t0\t0\t0\t0.008333333333333333\t8\t10000\t1\t0\t293.15\t0.001\t1\t1\t0.6\t12\n";
    }
    Runtime local_anchor_runtime;
    if (!local_anchor_runtime.load_manifest(local_anchor_manifest, error)) return 53;
    local_anchor_runtime.tick(1.0F / 60.0F);
    const auto follower_id = local_anchor_runtime.world().find_entity("Follower");
    if (std::fabs(local_anchor_runtime.world().transforms.at(follower_id).position.x) > 1.0e-6 ||
        std::fabs(local_anchor_runtime.world().transforms.at(follower_id).position.y - 1.0) > 1.0e-6) return 54;

    Runtime stress_runtime;
    stress_runtime.world().simulation_settings.floor_enabled = false;
    stress_runtime.world().simulation_settings.gravity_meters_per_second_squared = {};
    stress_runtime.world().simulation_settings.maximum_substeps = 1;
    stress_runtime.world().simulation_settings.joint_solver_iterations = 8;
    EntityId previous_body = 0U;
    for (int index = 0; index <= 1000; ++index) {
        std::ostringstream body_name;
        body_name << "StressBody::" << std::setw(4) << std::setfill('0') << index;
        const EntityId body_id = stress_runtime.world().create_entity(body_name.str());
        stress_runtime.world().transforms[body_id].position = {static_cast<double>(index), 2.0, 0.0};
        RigidBody body;
        body.dynamic = index != 0;
        stress_runtime.world().rigid_bodies[body_id] = body;
        if (index > 0) {
            std::ostringstream joint_name;
            joint_name << "StressJoint::" << std::setw(4) << std::setfill('0') << index;
            PhysicsJoint joint;
            joint.id = joint_name.str();
            joint.type = PhysicsJointType::ball;
            joint.first = previous_body;
            joint.second = body_id;
            joint.first_anchor = {0.5, 0.0, 0.0};
            joint.second_anchor = {-0.5, 0.0, 0.0};
            joint.rest_distance = 0.0;
            stress_runtime.world().physics_joints[joint.id] = joint;
        }
        previous_body = body_id;
    }
    stress_runtime.tick(1.0F / 120.0F);
    if (stress_runtime.physics_joint_diagnostics().size() != 1000U) return 55;
    if (stress_runtime.profile().physics_joint_iterations != 5) return 79;
    if (!std::isfinite(stress_runtime.profile().maximum_joint_position_error) ||
        stress_runtime.profile().maximum_joint_position_error > 0.1) return 81;
    for (const auto& diagnostic : stress_runtime.physics_joint_diagnostics()) {
        if (!std::isfinite(diagnostic.position_error) || diagnostic.position_error > 0.1) return 80;
    }
    if (stress_runtime.physics_joint_diagnostics().front().joint_id != "StressJoint::0001" ||
        stress_runtime.physics_joint_diagnostics().back().joint_id != "StressJoint::1000") return 56;

    Runtime oriented_collision;
    oriented_collision.world().simulation_settings.floor_enabled = false;
    oriented_collision.world().simulation_settings.gravity_meters_per_second_squared = {};
    const auto box_a = oriented_collision.world().create_entity("OrientedA");
    const auto box_b = oriented_collision.world().create_entity("OrientedB");
    oriented_collision.world().transforms[box_a].rotation.z = 45.0F;
    oriented_collision.world().transforms[box_b].position = {0.0, 0.2, 0.0};
    oriented_collision.world().transforms[box_b].rotation.z = -45.0F;
    oriented_collision.world().rigid_bodies[box_a].dynamic = false;
    oriented_collision.world().rigid_bodies[box_b] = RigidBody{};
    oriented_collision.world().colliders[box_a].half_extents = {1.0, 0.1, 0.1};
    oriented_collision.world().colliders[box_b].half_extents = {1.0, 0.1, 0.1};
    oriented_collision.tick(1.0F / 120.0F);
    if (oriented_collision.physics_contacts().empty()) return 57;

    Runtime capsule_collision;
    capsule_collision.world().simulation_settings.floor_enabled = false;
    capsule_collision.world().simulation_settings.gravity_meters_per_second_squared = {};
    const auto capsule_a = capsule_collision.world().create_entity("CapsuleA");
    const auto capsule_b = capsule_collision.world().create_entity("CapsuleB");
    capsule_collision.world().transforms[capsule_a].rotation.z = 90.0F;
    capsule_collision.world().transforms[capsule_b].position = {0.0, 0.8, 0.0};
    capsule_collision.world().transforms[capsule_b].rotation.z = 90.0F;
    capsule_collision.world().rigid_bodies[capsule_a].dynamic = false;
    capsule_collision.world().rigid_bodies[capsule_b] = RigidBody{};
    Collider capsule;
    capsule.shape = ColliderShape::capsule;
    capsule.radius = 0.5;
    capsule.half_height = 1.0;
    capsule.half_extents = {0.5, 1.5, 0.5};
    capsule_collision.world().colliders[capsule_a] = capsule;
    capsule_collision.world().colliders[capsule_b] = capsule;
    capsule_collision.tick(1.0F / 120.0F);
    if (capsule_collision.physics_contacts().empty()) return 58;

    Runtime capsule_box_collision;
    capsule_box_collision.world().simulation_settings.floor_enabled = false;
    capsule_box_collision.world().simulation_settings.gravity_meters_per_second_squared = {};
    const auto capsule_body = capsule_box_collision.world().create_entity("CapsuleBody");
    const auto box_body = capsule_box_collision.world().create_entity("BoxBody");
    capsule_box_collision.world().transforms[capsule_body].position = {0.0, 0.6, 0.0};
    capsule_box_collision.world().transforms[capsule_body].rotation.z = 35.0F;
    capsule_box_collision.world().transforms[box_body].rotation.y = 20.0F;
    capsule_box_collision.world().rigid_bodies[capsule_body] = RigidBody{};
    capsule_box_collision.world().rigid_bodies[box_body].dynamic = false;
    capsule_box_collision.world().colliders[capsule_body] = capsule;
    capsule_box_collision.world().colliders[box_body].half_extents = {0.75, 0.25, 0.75};
    capsule_box_collision.tick(1.0F / 120.0F);
    if (capsule_box_collision.physics_contacts().empty()) return 78;

    Runtime ccd_runtime;
    ccd_runtime.world().simulation_settings.floor_enabled = false;
    ccd_runtime.world().simulation_settings.gravity_meters_per_second_squared = {};
    ccd_runtime.world().simulation_settings.maximum_substeps = 1;
    const auto projectile = ccd_runtime.world().create_entity("Projectile");
    const auto wall = ccd_runtime.world().create_entity("Wall");
    ccd_runtime.world().transforms[projectile].position = {-10.0, 0.0, 0.0};
    ccd_runtime.world().rigid_bodies[projectile] = RigidBody{};
    ccd_runtime.world().rigid_bodies[projectile].velocity = {2400.0, 0.0, 0.0};
    ccd_runtime.world().rigid_bodies[projectile].continuous_collision = true;
    ccd_runtime.world().colliders[projectile].shape = ColliderShape::sphere;
    ccd_runtime.world().colliders[projectile].radius = 0.25;
    ccd_runtime.world().colliders[projectile].half_extents = {0.25, 0.25, 0.25};
    ccd_runtime.world().rigid_bodies[wall].dynamic = false;
    ccd_runtime.world().colliders[wall].half_extents = {0.1, 2.0, 2.0};
    ccd_runtime.tick(1.0F / 120.0F);
    if (ccd_runtime.physics_contacts().empty() || ccd_runtime.world().transforms.at(projectile).position.x >= 0.0) return 59;

    Runtime cooked_collision;
    cooked_collision.world().simulation_settings.floor_enabled = false;
    cooked_collision.world().simulation_settings.gravity_meters_per_second_squared = {};
    const auto cooked_surface = cooked_collision.world().create_entity("CookedSurface");
    const auto cooked_sphere = cooked_collision.world().create_entity("CookedSphere");
    cooked_collision.world().transforms[cooked_sphere].position = {0.0, 0.2, 0.0};
    cooked_collision.world().rigid_bodies[cooked_surface].dynamic = false;
    cooked_collision.world().rigid_bodies[cooked_sphere] = RigidBody{};
    cooked_collision.world().colliders[cooked_sphere].shape = ColliderShape::sphere;
    cooked_collision.world().colliders[cooked_sphere].radius = 0.5;
    auto cooked_asset = std::make_shared<CookedCollisionAsset>();
    cooked_asset->shape = ColliderShape::triangle_mesh;
    cooked_asset->bounds_min = {-1.0, 0.0, -1.0}; cooked_asset->bounds_max = {1.0, 0.0, 1.0};
    cooked_asset->vertices = {{-1.0,0.0,-1.0},{1.0,0.0,-1.0},{1.0,0.0,1.0},{-1.0,0.0,1.0}};
    cooked_asset->triangles = {{{0,1,2}},{{0,2,3}}};
    cooked_collision.world().colliders[cooked_surface].shape = ColliderShape::triangle_mesh;
    cooked_collision.world().colliders[cooked_surface].half_extents = {1.0, 0.01, 1.0};
    cooked_collision.world().colliders[cooked_surface].cooked = cooked_asset;
    cooked_collision.tick(1.0F / 120.0F);
    if (cooked_collision.physics_contacts().empty()) return 60;

    Runtime physical_animation;
    physical_animation.world().simulation_settings.floor_enabled = false;
    physical_animation.world().simulation_settings.gravity_meters_per_second_squared = {};
    const auto muscle_body = physical_animation.world().create_entity("MuscleBody");
    physical_animation.world().rigid_bodies[muscle_body] = RigidBody{};
    Skeleton muscle_skeleton;
    muscle_skeleton.id = "MuscleSkeleton";
    SkeletonJoint muscle_joint;
    muscle_joint.id = "Hip"; muscle_joint.rest_local = Matrix4{1,0,0,0,0,1,0,0,0,0,1,0,2,0,0,1};
    muscle_joint.local = muscle_joint.rest_local; muscle_joint.world = muscle_joint.rest_local;
    muscle_skeleton.joint_indices["Hip"] = 0; muscle_skeleton.joints.push_back(muscle_joint);
    physical_animation.world().skeletons[muscle_skeleton.id] = muscle_skeleton;
    physical_animation.world().physical_animation_bindings.push_back({"MuscleSkeleton", "Hip", muscle_body, 1.0, 0.5, 10000.0, 1.0, 1.0});
    physical_animation.tick(1.0F / 60.0F);
    if (physical_animation.world().rigid_bodies.at(muscle_body).velocity.x <= 0.0) return 61;
    if (physical_animation.world().skeletons.at("MuscleSkeleton").joints[0].world[12] <= 0.0) return 62;
    if (stable_asset_id("mesh", R"(C:\Project\Hero.fbx)") != stable_asset_id("MESH", "c:/project/hero.fbx")) return 11;
    if (stable_asset_id("mesh", "hero.fbx") == stable_asset_id("material", "hero.fbx")) return 12;

    const auto save = std::filesystem::temp_directory_path() / "tc_runtime_core_test.tcsave";
    if (!runtime.save(save, error)) return 8;
    runtime.world().variables["score"] = 0.0F;
    if (!runtime.load_save(save, error)) return 9;
    if (std::fabs(runtime.world().variables["score"] - 1.0F) >= 0.001F) return 10;

    const auto orbital_manifest = std::filesystem::temp_directory_path() / "tc_runtime_orbital_test.tcruntime";
    {
        std::ofstream stream(orbital_manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\n"
               << "SIMULATION\tastronomical\t1000000000\t1\t0\t0\t0\t0.001\t64\t1000000\t1000000\t0\n"
               << "ENTITY\tSun\nTRANSFORM\tSun\t0\t0\t0\t0\t0\t0\t1\t1\t1\n"
               << "RIGID\tSun\t0\t0\t0\t1.98847e30\t0\t0\n"
               << "ENTITY\tEarth\nTRANSFORM\tEarth\t149.59787070000001\t0\t0\t0\t0\t0\t1\t1\t1\n"
               << "RIGID\tEarth\t0\t0\t2.978e-5\t5.9722e24\t0\t1\n";
    }
    Runtime orbital;
    if (!orbital.load_manifest(orbital_manifest, error)) return 17;
    const auto earth = orbital.world().find_entity("Earth");
    if (std::fabs(orbital.world().transforms.at(earth).position.x - 149.59787070000001) > 1.0e-13) return 18;
    orbital.tick(1.0F / 60.0F);
    if (orbital.world().rigid_bodies.at(earth).velocity.x >= -1.0e-15) return 19;

    const auto microscopic_manifest = std::filesystem::temp_directory_path() / "tc_runtime_microscopic_test.tcruntime";
    {
        std::ofstream stream(microscopic_manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\nSIMULATION\tmicroscopic\t1e-9\t1\t0\t0\t0\t1e-6\t1\t10000\t1e-12\t0\t300\t0.001\t1\t7\n"
               << "ENTITY\tA\nTRANSFORM\tA\t-1\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tA\t0\t0\t0\t1e-18\t0\t1\nPARTICLE\tA\t1e-10\t1e-24\t0\t1e-9\t1000\t0.001\t2000\t0\t0\n"
               << "ENTITY\tB\nTRANSFORM\tB\t1\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tB\t0\t0\t0\t1e-18\t0\t1\nPARTICLE\tB\t1e-10\t1e-24\t0\t1e-9\t1000\t0.001\t2000\t0\t0\n";
    }
    Runtime microscopic;
    if (!microscopic.load_manifest(microscopic_manifest, error)) return 20;
    microscopic.tick(1.0e-6F);
    if (!(microscopic.world().rigid_bodies.at(microscopic.world().find_entity("A")).velocity.x < 0.0 &&
          microscopic.world().rigid_bodies.at(microscopic.world().find_entity("B")).velocity.x > 0.0)) return 21;

    const auto molecular_manifest = std::filesystem::temp_directory_path() / "tc_runtime_molecular_test.tcruntime";
    {
        std::ofstream stream(molecular_manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\nSIMULATION\tmolecular\t1e-9\t1\t0\t0\t0\t1e-6\t1\t10000\t1e-12\t0\t0\t0.001\t1\t9\n"
               << "ENTITY\tA\nTRANSFORM\tA\t0\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tA\t0\t0\t0\t1e-18\t0\t1\nPARTICLE\tA\t1e-10\t0\t1e-21\t1e-9\t1000\t0.001\t2000\t0\t0\n"
               << "ENTITY\tB\nTRANSFORM\tB\t0.8\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tB\t0\t0\t0\t1e-18\t0\t1\nPARTICLE\tB\t1e-10\t0\t1e-21\t1e-9\t1000\t0.001\t2000\t0\t0\n";
    }
    Runtime molecular;
    if (!molecular.load_manifest(molecular_manifest, error)) return 22;
    molecular.tick(1.0e-6F);
    if (!(molecular.world().rigid_bodies.at(molecular.world().find_entity("A")).velocity.x < 0.0 &&
          molecular.world().rigid_bodies.at(molecular.world().find_entity("B")).velocity.x > 0.0)) return 23;

    const auto thermal_manifest = std::filesystem::temp_directory_path() / "tc_runtime_thermal_test.tcruntime";
    {
        std::ofstream stream(thermal_manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\nSIMULATION\tmicroscopic\t1e-9\t1\t0\t0\t0\t1e-6\t1\t10000\t1e-12\t0\t300\t0.001\t1\t42\n"
               << "ENTITY\tP\nTRANSFORM\tP\t0\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tP\t0\t0\t0\t1e-18\t0\t1\nPARTICLE\tP\t1e-9\t0\t0\t1e-9\t1000\t0.001\t2000\t1\t0\n";
    }
    Runtime thermal_first,thermal_second;
    if(!thermal_first.load_manifest(thermal_manifest,error)||!thermal_second.load_manifest(thermal_manifest,error))return 24;
    thermal_first.tick(1.0e-6F);thermal_second.tick(1.0e-6F);
    const auto first_position=thermal_first.world().transforms.at(thermal_first.world().find_entity("P")).position;
    const auto second_position=thermal_second.world().transforms.at(thermal_second.world().find_entity("P")).position;
    if(first_position.x==0.0||first_position.x!=second_position.x||first_position.y!=second_position.y||first_position.z!=second_position.z)return 25;

    const auto fluid_manifest = std::filesystem::temp_directory_path() / "tc_runtime_fluid_test.tcruntime";
    {
        std::ofstream stream(fluid_manifest, std::ios::binary | std::ios::trunc);
        stream << "TCRUNTIME\t1\nSIMULATION\tfluid\t1\t1\t0\t0\t0\t0.001\t1\t10000\t0.01\t0\t0\t0.001\t1\t3\n"
               << "ENTITY\tA\nTRANSFORM\tA\t-0.5\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tA\t0\t0\t0\t1\t0\t1\nPARTICLE\tA\t1\t0\t0\t1\t0.01\t0.001\t10\t0\t0\n"
               << "ENTITY\tB\nTRANSFORM\tB\t0.5\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tB\t0\t0\t0\t1\t0\t1\nPARTICLE\tB\t1\t0\t0\t1\t0.01\t0.001\t10\t0\t0\n";
    }
    Runtime fluid;
    if(!fluid.load_manifest(fluid_manifest,error))return 26;fluid.tick(0.001F);
    const double fluid_a=fluid.world().rigid_bodies.at(fluid.world().find_entity("A")).velocity.x;
    const double fluid_b=fluid.world().rigid_bodies.at(fluid.world().find_entity("B")).velocity.x;
    if(!std::isfinite(fluid_a)||!std::isfinite(fluid_b)||!(fluid_a<0.0&&fluid_b>0.0))return 27;
    const auto animation_manifest=std::filesystem::temp_directory_path()/"tc_runtime_animation_test.tcruntime";
    const auto inverse_bind_file=std::filesystem::temp_directory_path()/"ib.f32";
    {std::ofstream stream(inverse_bind_file,std::ios::binary|std::ios::trunc);const float identity_values[32]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1,1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};stream.write(reinterpret_cast<const char*>(identity_values),sizeof(identity_values));}
    {
        std::ofstream stream(animation_manifest,std::ios::binary|std::ios::trunc);
        stream<<"TCRUNTIME\t1\nASSET\tib\trig_blob\tib.f32\th\nASSET\trp\trig_blob\trp.f32\th\nASSET\tio\trig_blob\tio.u32\th\nASSET\tji\trig_blob\tji.u32\th\nASSET\twt\trig_blob\twt.f32\th\nSKELETON\trig\t2\n"
              <<"JOINT\trig\troot\t\tRoot\t1\t0\t0\t0\t0\t1\t0\t0\t0\t0\t1\t0\t0\t0\t0\t1\n"
              <<"JOINT\trig\thip\troot\tHip\t1\t0\t0\t0\t0\t1\t0\t0\t0\t0\t1\t0\t0\t1\t0\t1\n"
              <<"ANIMATION\twalk\tWalk\trig\t1\t25\t24\t1\n"
              <<"ANIMCURVE\twalk\thip\ttranslateY\t1\t0\t2\t1\t1\tauto\t25\t13\tauto\n"
              <<"SKIN\tskin\tmesh\trig\tlinear_blend_skinning\t1\t1\t2\troot\thip\tib\trp\tio\tji\twt\n"
              <<"GRAPH\tbegin\tplay_walk\tanimation.play\ttest.tcgraph\t1\twalk\trestart\n"
              <<"GRAPH\ttick\thalf_speed\tanimation.set_speed\ttest.tcgraph\t2\t0.5\n";
    }
    Runtime animated;if(!animated.load_manifest(animation_manifest,error))return 31;animated.begin_play();
    if(animated.world().skin_bindings.at("skin").weights_asset!="wt")return 35;
    if(animated.world().skeletons.at("rig").joints.at(1).world[13]!=1.0)return 32;
    animated.tick(0.5F);
    if(std::fabs(animated.world().skeletons.at("rig").joints.at(1).world[13]-4.0)>1.0e-12)return 33;
    animated.tick(0.5F);
    if(std::fabs(animated.world().skeletons.at("rig").joints.at(1).world[13]-7.0)>1.0e-12)return 34;
    std::vector<Matrix4> skin_palette;if(!build_skin_matrix_palette(animated.world(),"skin",skin_palette,error)||skin_palette.size()!=2U)return 36;
    if(std::fabs(skin_palette[1][13]-7.0)>1.0e-12)return 37;
    std::filesystem::remove(manifest);
    std::filesystem::remove(save);
    std::filesystem::remove(orbital_manifest);
    std::filesystem::remove(microscopic_manifest);std::filesystem::remove(molecular_manifest);
    std::filesystem::remove(thermal_manifest);std::filesystem::remove(fluid_manifest);
    std::filesystem::remove(animation_manifest);
    std::filesystem::remove(inverse_bind_file);
    return 0;
}
