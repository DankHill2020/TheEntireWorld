#include "tc_gpu_compute.h"

#include <algorithm>
#include <cstring>
#include <mutex>
#include <memory>
#include <string>
#include <unordered_map>

#if defined(_WIN32)
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>

using Microsoft::WRL::ComPtr;

namespace {

constexpr const char* shader_source = R"(
RWStructuredBuffer<float4> positions : register(u0);
RWStructuredBuffer<float4> velocities : register(u1);
cbuffer SimulationParameters : register(b0) {
    float4 accelerationAndDt;
    uint particleCount;
    uint substepCount;
    uint2 padding;
    float4 collisionPlane;
    float4 collisionProperties;
    float4 collisionSphere;
    float4 sphereProperties;
};
[numthreads(256, 1, 1)]
void main(uint3 dispatchId : SV_DispatchThreadID) {
    const uint index = dispatchId.x;
    if (index >= particleCount) return;
    if (positions[index].w <= 0.0f) {
        velocities[index].xyz = float3(0.0f, 0.0f, 0.0f);
        return;
    }
    const uint steps = max(1u, substepCount);
    const float stepDt = accelerationAndDt.w / float(steps);
    float3 position = positions[index].xyz;
    float3 velocity = velocities[index].xyz;
    const float damping = max(0.0f, velocities[index].w);
    const float radius = positions[index].w;
    const float3 planeNormal = collisionPlane.xyz;
    for (uint step = 0; step < steps; ++step) {
        const float3 previous = position;
        bool collided = false;
        float responseFriction = 0.0f;
        float responseRestitution = 0.0f;
        float3 responseNormal = planeNormal;
        velocity += accelerationAndDt.xyz * stepDt;
        position += velocity * stepDt;
        if (collisionProperties.w > 0.5f) {
            const float distance = dot(position, planeNormal) - collisionPlane.w;
            if (distance < radius) {
                position += planeNormal * (radius - distance);
                collided = true;
                responseNormal = planeNormal;
                responseFriction = collisionProperties.x;
                responseRestitution = collisionProperties.y;
            }
        }
        if (sphereProperties.z > 0.5f) {
            const float3 delta = position - collisionSphere.xyz;
            const float distance = length(delta);
            const float minimumDistance = radius + collisionSphere.w;
            if (distance < minimumDistance) {
                const float3 sphereNormal = distance > 1.0e-12f ? delta / distance : float3(0.0f, 1.0f, 0.0f);
                position = collisionSphere.xyz + sphereNormal * minimumDistance;
                collided = true;
                responseNormal = sphereNormal;
                responseFriction = sphereProperties.x;
                responseRestitution = sphereProperties.y;
            }
        }
        if (collisionProperties.w > 0.5f || sphereProperties.z > 0.5f) {
            // The reference XPBD loop reconstructs velocity from corrected positions.
            velocity = (position - previous) / max(stepDt, 1.0e-12f);
        }
        velocity *= max(0.0f, 1.0f - damping * stepDt);
        if (collided) {
            const float normalSpeed = dot(velocity, responseNormal);
            const float3 normalVelocity = responseNormal * normalSpeed;
            const float3 tangentVelocity = velocity - normalVelocity;
            const float3 reflectedNormal = normalSpeed < 0.0f
                ? normalVelocity * -max(0.0f, responseRestitution)
                : normalVelocity;
            velocity = reflectedNormal + tangentVelocity * max(0.0f, 1.0f - responseFriction);
        }
    }
    positions[index] = float4(position, positions[index].w);
    velocities[index] = float4(velocity, velocities[index].w);
}
)";

void write_message(char* output, std::size_t size, const std::string& value) {
    if (output == nullptr || size == 0) return;
    const auto count = std::min(size - 1, value.size());
    std::memcpy(output, value.data(), count);
    output[count] = '\0';
}

struct ParticleStream {
    ComPtr<ID3D11Buffer> position_buffer, velocity_buffer, position_staging, velocity_staging;
    ComPtr<ID3D11UnorderedAccessView> position_uav, velocity_uav;
    std::uint32_t capacity{0};
    std::uint32_t count{0};
};

class ComputeDevice {
public:
    bool initialize(std::string& error) {
        std::scoped_lock lock(mutex_);
        if (device_ && context_ && shader_) return true;
        D3D_FEATURE_LEVEL level{};
        const D3D_FEATURE_LEVEL requested[] = {
            D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0
        };
        auto result = D3D11CreateDevice(
            nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, requested,
            static_cast<UINT>(std::size(requested)), D3D11_SDK_VERSION,
            &device_, &level, &context_);
        if (result == E_INVALIDARG) {
            result = D3D11CreateDevice(
                nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, requested + 1,
                static_cast<UINT>(std::size(requested) - 1), D3D11_SDK_VERSION,
                &device_, &level, &context_);
        }
        if (FAILED(result)) {
            error = "D3D11 hardware compute device creation failed.";
            return false;
        }
        ComPtr<ID3DBlob> bytecode;
        ComPtr<ID3DBlob> errors;
        result = D3DCompile(
            shader_source, std::strlen(shader_source), "tc_particle_integrate", nullptr, nullptr,
            "main", "cs_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &bytecode, &errors);
        if (FAILED(result)) {
            error = errors ? std::string(static_cast<const char*>(errors->GetBufferPointer()), errors->GetBufferSize())
                           : "D3D11 particle compute shader compilation failed.";
            return false;
        }
        if (FAILED(device_->CreateComputeShader(bytecode->GetBufferPointer(), bytecode->GetBufferSize(), nullptr, &shader_))) {
            error = "D3D11 particle compute shader creation failed.";
            return false;
        }
        feature_level_ = level;
        return true;
    }

    tc_gpu_session_handle create_session(std::string& error) {
        if (!initialize(error)) return 0;
        std::scoped_lock lock(mutex_);
        const auto handle = next_session_++;
        sessions_.emplace(handle, std::make_unique<ParticleStream>());
        return handle;
    }

    bool destroy_session(tc_gpu_session_handle session, std::string& error) {
        if (session == 0) {
            error = "The legacy default GPU session cannot be destroyed.";
            return false;
        }
        std::scoped_lock lock(mutex_);
        if (sessions_.erase(session) == 0) {
            error = "GPU session handle is invalid or already released.";
            return false;
        }
        return true;
    }

    bool upload_session(
        tc_gpu_session_handle session, const float* positions, const float* velocities,
        std::uint32_t count, std::string& error) {
        if (!validate_buffers(positions, velocities, count, error) || !initialize(error)) return false;
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr || !ensure_particle_buffers(*stream, count, error)) return false;
        context_->UpdateSubresource(stream->position_buffer.Get(), 0, nullptr, positions, 0, 0);
        context_->UpdateSubresource(stream->velocity_buffer.Get(), 0, nullptr, velocities, 0, 0);
        stream->count = count;
        return true;
    }

    bool upload(const float* positions, const float* velocities, std::uint32_t count, std::string& error) {
        return upload_session(0, positions, velocities, count, error);
    }

    bool dispatch_session(
        tc_gpu_session_handle session,
        float ax, float ay, float az, float dt, std::uint32_t substeps,
        float plane_x, float plane_y, float plane_z, float plane_offset,
        float plane_friction, float plane_restitution, bool plane_enabled,
        float sphere_x, float sphere_y, float sphere_z, float sphere_radius,
        float sphere_friction, float sphere_restitution, bool sphere_enabled,
        std::string& error) {
        if (!initialize(error)) return false;
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr) return false;
        return dispatch_unlocked(
            *stream, ax, ay, az, dt, substeps, plane_x, plane_y, plane_z, plane_offset,
            plane_friction, plane_restitution, plane_enabled,
            sphere_x, sphere_y, sphere_z, sphere_radius, sphere_friction, sphere_restitution,
            sphere_enabled, error);
    }

    bool dispatch(
        float ax, float ay, float az, float dt, std::uint32_t substeps,
        float plane_x, float plane_y, float plane_z, float plane_offset,
        float plane_friction, float plane_restitution, bool plane_enabled,
        std::string& error) {
        return dispatch_session(
            0, ax, ay, az, dt, substeps, plane_x, plane_y, plane_z, plane_offset,
            plane_friction, plane_restitution, plane_enabled,
            0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, false, error);
    }

    bool readback_session(
        tc_gpu_session_handle session, float* positions, float* velocities,
        std::uint32_t count, std::string& error) {
        if (!validate_buffers(positions, velocities, count, error) || !initialize(error)) return false;
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr) return false;
        if (stream->count == 0 || count != stream->count) {
            error = "Readback count does not match the resident particle stream.";
            return false;
        }
        return readback_unlocked(*stream, positions, velocities, count, error);
    }

    bool readback(float* positions, float* velocities, std::uint32_t count, std::string& error) {
        return readback_session(0, positions, velocities, count, error);
    }

    bool integrate(
        float* positions, float* velocities, std::uint32_t count,
        float ax, float ay, float az, float dt, std::uint32_t substeps,
        std::string& error) {
        if (!upload(positions, velocities, count, error)) return false;
        if (!dispatch(ax, ay, az, dt, substeps, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, false, error))
            return false;
        return readback(positions, velocities, count, error);
    }

    std::uint32_t session_count(tc_gpu_session_handle session) const {
        std::scoped_lock lock(mutex_);
        if (session == 0) return default_stream_.count;
        const auto found = sessions_.find(session);
        return found == sessions_.end() ? 0 : found->second->count;
    }

    std::uint32_t resident_count() const {
        return session_count(0);
    }

    std::string description() const {
        const unsigned major = (static_cast<unsigned>(feature_level_) >> 12U) & 0xFU;
        const unsigned minor = (static_cast<unsigned>(feature_level_) >> 8U) & 0xFU;
        return "D3D11 hardware compute ready (feature level " + std::to_string(major) + "." + std::to_string(minor) + ").";
    }

private:
    ParticleStream* stream_unlocked(tc_gpu_session_handle session, std::string& error) {
        if (session == 0) return &default_stream_;
        const auto found = sessions_.find(session);
        if (found == sessions_.end()) {
            error = "GPU session handle is invalid or already released.";
            return nullptr;
        }
        return found->second.get();
    }

    static bool validate_buffers(
        const float* positions, const float* velocities, std::uint32_t count, std::string& error) {
        if (positions == nullptr || velocities == nullptr || count == 0 || count > 20'000'000U) {
            error = "Particle buffers or count are invalid.";
            return false;
        }
        return true;
    }

    bool dispatch_unlocked(
        ParticleStream& stream,
        float ax, float ay, float az, float dt, std::uint32_t substeps,
        float plane_x, float plane_y, float plane_z, float plane_offset,
        float plane_friction, float plane_restitution, bool plane_enabled,
        float sphere_x, float sphere_y, float sphere_z, float sphere_radius,
        float sphere_friction, float sphere_restitution, bool sphere_enabled,
        std::string& error) {
        if (stream.count == 0) {
            error = "No resident particle stream has been uploaded.";
            return false;
        }
        ComPtr<ID3D11Buffer> constants;

        struct alignas(16) Parameters {
            float acceleration_dt[4];
            std::uint32_t particle_count;
            std::uint32_t substep_count;
            std::uint32_t padding[2];
            float collision_plane[4];
            float collision_properties[4];
            float collision_sphere[4];
            float sphere_properties[4];
        } parameters{
            {ax, ay, az, dt}, stream.count, std::max(1U, substeps), {0, 0},
            {plane_x, plane_y, plane_z, plane_offset},
            {plane_friction, plane_restitution, 0.0f, plane_enabled ? 1.0f : 0.0f},
            {sphere_x, sphere_y, sphere_z, sphere_radius},
            {sphere_friction, sphere_restitution, sphere_enabled ? 1.0f : 0.0f, 0.0f}
        };
        D3D11_BUFFER_DESC constant_desc{};
        constant_desc.ByteWidth = sizeof(Parameters);
        constant_desc.Usage = D3D11_USAGE_IMMUTABLE;
        constant_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        D3D11_SUBRESOURCE_DATA constant_data{&parameters, 0, 0};
        if (FAILED(device_->CreateBuffer(&constant_desc, &constant_data, &constants))) {
            error = "D3D11 constant buffer allocation failed.";
            return false;
        }
        ID3D11UnorderedAccessView* uavs[] = {stream.position_uav.Get(), stream.velocity_uav.Get()};
        context_->CSSetShader(shader_.Get(), nullptr, 0);
        context_->CSSetUnorderedAccessViews(0, 2, uavs, nullptr);
        context_->CSSetConstantBuffers(0, 1, constants.GetAddressOf());
        context_->Dispatch((stream.count + 255U) / 256U, 1, 1);
        ID3D11UnorderedAccessView* no_uavs[] = {nullptr, nullptr};
        context_->CSSetUnorderedAccessViews(0, 2, no_uavs, nullptr);
        context_->CSSetShader(nullptr, nullptr, 0);

        return true;
    }

    bool readback_unlocked(
        ParticleStream& stream, float* positions, float* velocities,
        std::uint32_t count, std::string& error) {
        const UINT byte_width = count * 4U * sizeof(float);
        context_->CopyResource(stream.position_staging.Get(), stream.position_buffer.Get());
        context_->CopyResource(stream.velocity_staging.Get(), stream.velocity_buffer.Get());
        if (!read_staging(stream.position_staging.Get(), positions, byte_width, error) ||
            !read_staging(stream.velocity_staging.Get(), velocities, byte_width, error)) return false;
        return true;
    }

    bool create_compute_buffer(
        std::uint32_t count, ComPtr<ID3D11Buffer>& buffer,
        ComPtr<ID3D11UnorderedAccessView>& view, std::string& error) {
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = count * 4U * sizeof(float);
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;
        desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
        desc.StructureByteStride = 4U * sizeof(float);
        if (FAILED(device_->CreateBuffer(&desc, nullptr, &buffer))) {
            error = "D3D11 structured particle buffer allocation failed.";
            return false;
        }
        D3D11_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = DXGI_FORMAT_UNKNOWN;
        uav.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
        uav.Buffer.NumElements = count;
        if (FAILED(device_->CreateUnorderedAccessView(buffer.Get(), &uav, &view))) {
            error = "D3D11 particle UAV creation failed.";
            return false;
        }
        return true;
    }

    bool ensure_particle_buffers(ParticleStream& stream, std::uint32_t count, std::string& error) {
        if (stream.capacity == count && stream.position_buffer && stream.velocity_buffer &&
            stream.position_staging && stream.velocity_staging)
            return true;
        stream.position_buffer.Reset(); stream.velocity_buffer.Reset();
        stream.position_uav.Reset(); stream.velocity_uav.Reset();
        stream.position_staging.Reset(); stream.velocity_staging.Reset();
        stream.capacity = 0;
        stream.count = 0;
        const UINT byte_width = count * 4U * sizeof(float);
        if (!create_compute_buffer(count, stream.position_buffer, stream.position_uav, error) ||
            !create_compute_buffer(count, stream.velocity_buffer, stream.velocity_uav, error) ||
            !create_staging(byte_width, stream.position_staging, error) ||
            !create_staging(byte_width, stream.velocity_staging, error)) return false;
        stream.capacity = count;
        return true;
    }

    bool create_staging(UINT byte_width, ComPtr<ID3D11Buffer>& buffer, std::string& error) {
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = byte_width;
        desc.Usage = D3D11_USAGE_STAGING;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        desc.StructureByteStride = 4U * sizeof(float);
        desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
        if (FAILED(device_->CreateBuffer(&desc, nullptr, &buffer))) {
            error = "D3D11 staging buffer allocation failed.";
            return false;
        }
        return true;
    }

    bool read_staging(ID3D11Buffer* buffer, float* output, UINT size, std::string& error) {
        D3D11_MAPPED_SUBRESOURCE mapped{};
        if (FAILED(context_->Map(buffer, 0, D3D11_MAP_READ, 0, &mapped))) {
            error = "D3D11 particle readback failed.";
            return false;
        }
        std::memcpy(output, mapped.pData, size);
        context_->Unmap(buffer, 0);
        return true;
    }

    mutable std::mutex mutex_;
    ComPtr<ID3D11Device> device_;
    ComPtr<ID3D11DeviceContext> context_;
    ComPtr<ID3D11ComputeShader> shader_;
    ParticleStream default_stream_;
    std::unordered_map<tc_gpu_session_handle, std::unique_ptr<ParticleStream>> sessions_;
    tc_gpu_session_handle next_session_{1};
    D3D_FEATURE_LEVEL feature_level_{D3D_FEATURE_LEVEL_10_0};
};

ComputeDevice& compute_device() {
    static ComputeDevice value;
    return value;
}

}
#endif

extern "C" int tc_gpu_compute_available(char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().initialize(error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, compute_device().description());
    return 1;
#else
    if (message && message_size) {
        const char* value = "The native GPU compute backend currently requires Windows/D3D11.";
        const auto count = std::min(message_size - 1, std::strlen(value));
        std::memcpy(message, value, count);
        message[count] = '\0';
    }
    return 0;
#endif
}

extern "C" int tc_gpu_integrate_particles(
    float* positions, float* velocities, std::uint32_t count,
    float ax, float ay, float az, float dt, std::uint32_t substeps,
    char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().integrate(positions, velocities, count, ax, ay, az, dt, substeps, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "D3D11 particle integration dispatched successfully.");
    return 1;
#else
    (void)positions; (void)velocities; (void)count; (void)ax; (void)ay; (void)az; (void)dt; (void)substeps;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_upload_particles(
    const float* positions, const float* velocities, std::uint32_t count,
    char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().upload(positions, velocities, count, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Particle state is resident on the D3D11 device.");
    return 1;
#else
    (void)positions; (void)velocities; (void)count;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_dispatch_particles(
    float ax, float ay, float az, float dt, std::uint32_t substeps,
    float plane_x, float plane_y, float plane_z, float plane_offset,
    float plane_friction, float plane_restitution, std::uint32_t plane_enabled,
    char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().dispatch(
            ax, ay, az, dt, substeps, plane_x, plane_y, plane_z, plane_offset,
            plane_friction, plane_restitution, plane_enabled != 0, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Resident D3D11 particle dispatch completed without CPU readback.");
    return 1;
#else
    (void)ax; (void)ay; (void)az; (void)dt; (void)substeps;
    (void)plane_x; (void)plane_y; (void)plane_z; (void)plane_offset;
    (void)plane_friction; (void)plane_restitution; (void)plane_enabled;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_readback_particles(
    float* positions, float* velocities, std::uint32_t count,
    char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().readback(positions, velocities, count, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Resident D3D11 particle state synchronized to CPU.");
    return 1;
#else
    (void)positions; (void)velocities; (void)count;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" std::uint32_t tc_gpu_resident_particle_count() {
#if defined(_WIN32)
    return compute_device().resident_count();
#else
    return 0;
#endif
}

extern "C" tc_gpu_session_handle tc_gpu_session_create(char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    const auto session = compute_device().create_session(error);
    if (session == 0) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Independent D3D11 particle session created.");
    return session;
#else
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_session_destroy(
    tc_gpu_session_handle session, char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().destroy_session(session, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "D3D11 particle session released.");
    return 1;
#else
    (void)session;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_session_upload_particles(
    tc_gpu_session_handle session, const float* positions, const float* velocities,
    std::uint32_t count, char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().upload_session(session, positions, velocities, count, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Particle state uploaded to its independent D3D11 session.");
    return 1;
#else
    (void)session; (void)positions; (void)velocities; (void)count;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_session_dispatch_particles(
    tc_gpu_session_handle session,
    float ax, float ay, float az, float dt, std::uint32_t substeps,
    float plane_x, float plane_y, float plane_z, float plane_offset,
    float plane_friction, float plane_restitution, std::uint32_t plane_enabled,
    float sphere_x, float sphere_y, float sphere_z, float sphere_radius,
    float sphere_friction, float sphere_restitution, std::uint32_t sphere_enabled,
    char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().dispatch_session(
            session, ax, ay, az, dt, substeps,
            plane_x, plane_y, plane_z, plane_offset, plane_friction, plane_restitution, plane_enabled != 0,
            sphere_x, sphere_y, sphere_z, sphere_radius, sphere_friction, sphere_restitution,
            sphere_enabled != 0, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Independent resident D3D11 particle dispatch completed.");
    return 1;
#else
    (void)session; (void)ax; (void)ay; (void)az; (void)dt; (void)substeps;
    (void)plane_x; (void)plane_y; (void)plane_z; (void)plane_offset;
    (void)plane_friction; (void)plane_restitution; (void)plane_enabled;
    (void)sphere_x; (void)sphere_y; (void)sphere_z; (void)sphere_radius;
    (void)sphere_friction; (void)sphere_restitution; (void)sphere_enabled;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_session_readback_particles(
    tc_gpu_session_handle session, float* positions, float* velocities,
    std::uint32_t count, char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().readback_session(session, positions, velocities, count, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Independent D3D11 particle session synchronized to CPU.");
    return 1;
#else
    (void)session; (void)positions; (void)velocities; (void)count;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" std::uint32_t tc_gpu_session_particle_count(tc_gpu_session_handle session) {
#if defined(_WIN32)
    return compute_device().session_count(session);
#else
    (void)session;
    return 0;
#endif
}
