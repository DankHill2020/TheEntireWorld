#pragma once

#include <cstddef>
#include <cstdint>

#if defined(_WIN32)
#  if defined(TC_GPU_COMPUTE_BUILD)
#    define TC_GPU_COMPUTE_API __declspec(dllexport)
#  else
#    define TC_GPU_COMPUTE_API __declspec(dllimport)
#  endif
#else
#  define TC_GPU_COMPUTE_API
#endif

extern "C" {

TC_GPU_COMPUTE_API int tc_gpu_compute_available(char* message, std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_integrate_particles(
    float* positions_xyzw,
    float* velocities_xyzw,
    std::uint32_t particle_count,
    float acceleration_x,
    float acceleration_y,
    float acceleration_z,
    float delta_time,
    std::uint32_t substep_count,
    char* message,
    std::size_t message_size);

// A deliberately small, single-stream resident API. Upload once, dispatch any
// number of steps without CPU synchronization, then read back on demand.
TC_GPU_COMPUTE_API int tc_gpu_upload_particles(
    const float* positions_xyzw,
    const float* velocities_xyzw,
    std::uint32_t particle_count,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_dispatch_particles(
    float acceleration_x,
    float acceleration_y,
    float acceleration_z,
    float delta_time,
    std::uint32_t substep_count,
    float plane_normal_x,
    float plane_normal_y,
    float plane_normal_z,
    float plane_offset,
    float plane_friction,
    float plane_restitution,
    std::uint32_t plane_enabled,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_readback_particles(
    float* positions_xyzw,
    float* velocities_xyzw,
    std::uint32_t particle_count,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API std::uint32_t tc_gpu_resident_particle_count();

using tc_gpu_session_handle = std::uint64_t;

TC_GPU_COMPUTE_API tc_gpu_session_handle tc_gpu_session_create(
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_session_destroy(
    tc_gpu_session_handle session,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_session_upload_particles(
    tc_gpu_session_handle session,
    const float* positions_xyzw,
    const float* velocities_xyzw,
    std::uint32_t particle_count,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_session_dispatch_particles(
    tc_gpu_session_handle session,
    float acceleration_x,
    float acceleration_y,
    float acceleration_z,
    float delta_time,
    std::uint32_t substep_count,
    float plane_normal_x,
    float plane_normal_y,
    float plane_normal_z,
    float plane_offset,
    float plane_friction,
    float plane_restitution,
    std::uint32_t plane_enabled,
    float sphere_center_x,
    float sphere_center_y,
    float sphere_center_z,
    float sphere_radius,
    float sphere_friction,
    float sphere_restitution,
    std::uint32_t sphere_enabled,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_session_readback_particles(
    tc_gpu_session_handle session,
    float* positions_xyzw,
    float* velocities_xyzw,
    std::uint32_t particle_count,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API std::uint32_t tc_gpu_session_particle_count(tc_gpu_session_handle session);

TC_GPU_COMPUTE_API int tc_gpu_session_upload_physics_fields(
    tc_gpu_session_handle session,
    const float* field_records,
    std::uint32_t field_count,
    float simulation_time,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API std::uint32_t tc_gpu_session_physics_field_count(
    tc_gpu_session_handle session);

TC_GPU_COMPUTE_API int tc_gpu_session_upload_mesh_bvh(
    tc_gpu_session_handle session,
    const float* node_bounds,
    const std::uint32_t* node_metadata,
    std::uint32_t node_count,
    const float* triangle_vertices,
    std::uint32_t triangle_count,
    float friction,
    float restitution,
    float velocity_x,
    float velocity_y,
    float velocity_z,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_session_dispatch_mesh_bvh(
    tc_gpu_session_handle session,
    float delta_time,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API std::uint32_t tc_gpu_session_mesh_triangle_count(
    tc_gpu_session_handle session);

TC_GPU_COMPUTE_API int tc_gpu_session_dispatch_self_collision(
    tc_gpu_session_handle session,
    float cell_size,
    float delta_time,
    std::uint32_t iteration_count,
    std::uint32_t maximum_bucket_visits,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_session_upload_distance_constraints(
    tc_gpu_session_handle session,
    const std::uint32_t* endpoint_pairs,
    const float* rest_compliance_weights,
    std::uint32_t constraint_count,
    const std::uint32_t* color_offsets,
    std::uint32_t color_count,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API int tc_gpu_session_dispatch_distance_constraints(
    tc_gpu_session_handle session,
    float delta_time,
    std::uint32_t iteration_count,
    char* message,
    std::size_t message_size);

TC_GPU_COMPUTE_API std::uint32_t tc_gpu_session_distance_constraint_count(
    tc_gpu_session_handle session);

}
