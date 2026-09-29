#include "tc_gpu_compute.h"

#include <algorithm>
#include <cstring>
#include <mutex>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#if defined(_WIN32)
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>

using Microsoft::WRL::ComPtr;

namespace {

constexpr const char* shader_source = R"(
RWStructuredBuffer<float4> positions : register(u0);
RWStructuredBuffer<float4> velocities : register(u1);
StructuredBuffer<float4> physicsFields : register(t0);
cbuffer SimulationParameters : register(b0) {
    float4 accelerationAndDt;
    uint particleCount;
    uint substepCount;
    uint2 padding;
    float4 collisionPlane;
    float4 collisionProperties;
    float4 collisionSphere;
    float4 sphereProperties;
    uint physicsFieldCount;
    float simulationTime;
    float2 fieldPadding;
};
float fieldFalloff(float distance, float radius, float innerRadius, float power) {
    if (radius <= 0.0f) return 1.0f;
    const float inner = clamp(innerRadius, 0.0f, radius);
    if (distance <= inner) return 1.0f;
    return pow(saturate(1.0f - (distance - inner) / max(1.0e-12f, radius - inner)), max(0.01f, power));
}
float3 normalizedOr(float3 value, float3 fallback) {
    const float magnitude = length(value);
    return magnitude > 1.0e-12f ? value / magnitude : fallback;
}
float3 fieldAcceleration(uint particleIndex, float3 position, float3 velocity, float time) {
    float3 result = float3(0.0f, 0.0f, 0.0f);
    for (uint fieldIndex = 0; fieldIndex < physicsFieldCount; ++fieldIndex) {
        const uint base = fieldIndex * 5u;
        const float4 header = physicsFields[base];
        const float4 vectorPower = physicsFields[base + 1u];
        const float4 centerMaximum = physicsFields[base + 2u];
        const float4 dynamics = physicsFields[base + 3u];
        const float4 environment = physicsFields[base + 4u];
        const uint kind = (uint)header.x;
        const float3 fieldVector = vectorPower.xyz;
        const float3 delta = position - centerMaximum.xyz;
        const float distance = length(delta);
        const float falloff = fieldFalloff(distance, header.z, header.w, vectorPower.w);
        float3 value = float3(0.0f, 0.0f, 0.0f);
        if (kind == 0u || kind == 8u) {
            const float gust = 1.0f + environment.x * sin(dynamics.z * time * 6.28318530718f + dynamics.y);
            const float3 target = fieldVector * (header.y * gust);
            value = kind == 8u && dynamics.x > 0.0f
                ? (target - velocity) * (dynamics.x * falloff)
                : target * falloff;
        } else if (kind == 1u) {
            const float softening = max(1.0e-4f, abs(fieldVector.x));
            value = -normalizedOr(delta, float3(0.0f, -1.0f, 0.0f))
                * (header.y / max(softening * softening, distance * distance + softening * softening)) * falloff;
        } else if (kind == 2u || kind == 3u) {
            value = normalizedOr(delta, float3(0.0f, 1.0f, 0.0f))
                * (kind == 3u ? -header.y : header.y) * falloff;
        } else if (kind == 4u) {
            const float3 axis = normalizedOr(fieldVector, float3(0.0f, 1.0f, 0.0f));
            value = normalizedOr(cross(axis, delta), float3(1.0f, 0.0f, 0.0f)) * header.y * falloff;
        } else if (kind == 5u) {
            const float phase = dynamics.y * 17.17f + float(particleIndex) * 0.754877666f;
            const float3 sample = position * max(1.0e-6f, dynamics.w)
                + float3(phase, phase * 1.37f, phase * 2.11f);
            const float timePhase = time * max(0.0f, dynamics.z);
            value = float3(
                sin(sample.y * 1.73f + sample.z * 0.63f + timePhase * 2.03f),
                sin(sample.z * 1.31f + sample.x * 0.79f + timePhase * 1.71f),
                sin(sample.x * 1.57f + sample.y * 0.91f + timePhase * 2.29f)
            ) * header.y * falloff;
        } else if (kind == 6u) {
            value = (fieldVector - velocity) * header.y * falloff;
        } else if (kind == 7u) {
            const float3 relative = velocity - fieldVector;
            value = -relative * (header.y * length(relative) * falloff);
        }
        const float maximum = max(0.0f, centerMaximum.w);
        const float magnitude = length(value);
        if (maximum > 0.0f && magnitude > maximum) value *= maximum / magnitude;
        result += value;
    }
    return result;
}
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
        velocity += (accelerationAndDt.xyz + fieldAcceleration(index, position, velocity, simulationTime + step * stepDt)) * stepDt;
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

constexpr const char* distance_constraint_shader_source = R"(
RWStructuredBuffer<float4> positions : register(u0);
RWStructuredBuffer<float> constraintLambdas : register(u1);
RWStructuredBuffer<float4> velocities : register(u2);
StructuredBuffer<uint2> constraintEndpoints : register(t0);
StructuredBuffer<float4> constraintData : register(t1);
cbuffer ConstraintParameters : register(b0) {
    uint constraintStart;
    uint constraintCount;
    uint particleCount;
    uint resetLambdas;
    float deltaTime;
    float3 constraintPadding;
};
[numthreads(256, 1, 1)]
void main(uint3 dispatchId : SV_DispatchThreadID) {
    const uint localIndex = dispatchId.x;
    if (localIndex >= constraintCount) return;
    const uint constraintIndex = constraintStart + localIndex;
    const uint2 endpoints = constraintEndpoints[constraintIndex];
    if (endpoints.x >= particleCount || endpoints.y >= particleCount) return;
    const float4 data = constraintData[constraintIndex];
    if (resetLambdas != 0u) constraintLambdas[constraintIndex] = 0.0f;
    const float3 delta = positions[endpoints.y].xyz - positions[endpoints.x].xyz;
    const float distance = length(delta);
    const float3 relativeVelocity = velocities[endpoints.y].xyz - velocities[endpoints.x].xyz;
    const float relativeSpeed = length(relativeVelocity);
    const float3 direction = distance > 1.0e-12f ? delta / distance : (
        relativeSpeed > 1.0e-12f ? relativeVelocity / relativeSpeed : float3(1.0f, 0.0f, 0.0f)
    );
    const float firstWeight = max(0.0f, data.z);
    const float secondWeight = max(0.0f, data.w);
    const float alpha = max(0.0f, data.y) / max(1.0e-12f, deltaTime * deltaTime);
    const float denominator = firstWeight + secondWeight + alpha;
    if (denominator <= 1.0e-12f) return;
    const float deltaLambda = (-(distance - data.x) - alpha * constraintLambdas[constraintIndex]) / denominator;
    constraintLambdas[constraintIndex] += deltaLambda;
    const float3 correction = direction * deltaLambda;
    positions[endpoints.x].xyz -= correction * firstWeight;
    positions[endpoints.y].xyz += correction * secondWeight;
    const float inverseDeltaTime = 1.0f / max(1.0e-12f, deltaTime);
    velocities[endpoints.x].xyz -= correction * (firstWeight * inverseDeltaTime);
    velocities[endpoints.y].xyz += correction * (secondWeight * inverseDeltaTime);
}
)";

constexpr const char* mesh_collision_shader_source = R"(
RWStructuredBuffer<float4> positions : register(u0);
RWStructuredBuffer<float4> velocities : register(u1);
StructuredBuffer<float4> nodeBounds : register(t0);
StructuredBuffer<uint4> nodeMetadata : register(t1);
StructuredBuffer<float4> triangleVertices : register(t2);
cbuffer MeshCollisionParameters : register(b0) {
    uint particleCount;
    uint nodeCount;
    uint triangleCount;
    float deltaTime;
    float friction;
    float restitution;
    float2 meshPadding;
    float4 surfaceVelocity;
};
bool sphereOverlapsBounds(float3 center, float radius, float3 minimumValue, float3 maximumValue) {
    const float3 closest = clamp(center, minimumValue, maximumValue);
    const float3 delta = center - closest;
    return dot(delta, delta) <= radius * radius;
}
float3 closestPointTriangle(float3 queryPoint, float3 a, float3 b, float3 c) {
    const float3 ab = b - a; const float3 ac = c - a; const float3 ap = queryPoint - a;
    const float d1 = dot(ab, ap); const float d2 = dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) return a;
    const float3 bp = queryPoint - b; const float d3 = dot(ab, bp); const float d4 = dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) return b;
    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) return a + ab * (d1 / max(1.0e-12f, d1 - d3));
    const float3 cp = queryPoint - c; const float d5 = dot(ab, cp); const float d6 = dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) return c;
    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) return a + ac * (d2 / max(1.0e-12f, d2 - d6));
    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f)
        return b + (c - b) * ((d4 - d3) / max(1.0e-12f, (d4 - d3) + (d5 - d6)));
    const float denominator = max(1.0e-12f, va + vb + vc);
    return a + ab * (vb / denominator) + ac * (vc / denominator);
}
[numthreads(256, 1, 1)]
void main(uint3 dispatchId : SV_DispatchThreadID) {
    const uint index = dispatchId.x;
    if (index >= particleCount || positions[index].w <= 0.0f || nodeCount == 0u) return;
    const float3 position = positions[index].xyz;
    const float radius = positions[index].w;
    float closestDistance = radius;
    float3 closestPoint = position;
    float3 closestNormal = float3(0.0f, 1.0f, 0.0f);
    bool hit = false;
    uint stack[64]; uint stackSize = 1u; stack[0] = 0u;
    while (stackSize > 0u) {
        const uint nodeIndex = stack[--stackSize];
        if (nodeIndex >= nodeCount) continue;
        if (!sphereOverlapsBounds(position, radius, nodeBounds[nodeIndex * 2u].xyz,
                                  nodeBounds[nodeIndex * 2u + 1u].xyz)) continue;
        const uint4 metadata = nodeMetadata[nodeIndex];
        if (metadata.w > 0u) {
            for (uint local = 0u; local < metadata.w; ++local) {
                const uint triangleIndex = metadata.z + local;
                if (triangleIndex >= triangleCount) continue;
                const float3 a = triangleVertices[triangleIndex * 3u].xyz;
                const float3 b = triangleVertices[triangleIndex * 3u + 1u].xyz;
                const float3 c = triangleVertices[triangleIndex * 3u + 2u].xyz;
                const float3 candidate = closestPointTriangle(position, a, b, c);
                const float distance = length(position - candidate);
                if (distance >= closestDistance) continue;
                float3 normal = normalize(cross(b - a, c - a));
                if (dot(position - candidate, normal) < 0.0f) normal *= -1.0f;
                closestDistance = distance; closestPoint = candidate; closestNormal = normal; hit = true;
            }
        } else {
            if (metadata.x != 0xffffffffu && stackSize < 64u) stack[stackSize++] = metadata.x;
            if (metadata.y != 0xffffffffu && stackSize < 64u) stack[stackSize++] = metadata.y;
        }
    }
    if (!hit) return;
    const float3 correctedPosition = closestPoint + closestNormal * radius;
    const float3 previousPosition = position - velocities[index].xyz * deltaTime;
    positions[index].xyz = correctedPosition;
    float3 relative = (correctedPosition - previousPosition) / max(1.0e-12f, deltaTime) - surfaceVelocity.xyz;
    const float normalSpeed = dot(relative, closestNormal);
    const float3 normalVelocity = closestNormal * normalSpeed;
    const float3 tangentVelocity = relative - normalVelocity;
    const float3 reflected = normalSpeed < 0.0f ? normalVelocity * -max(0.0f, restitution) : normalVelocity;
    velocities[index].xyz = surfaceVelocity.xyz + reflected + tangentVelocity * max(0.0f, 1.0f - friction);
}
)";

constexpr const char* grid_clear_shader_source = R"(
RWStructuredBuffer<uint> gridHeads : register(u0);
cbuffer GridClearParameters : register(b0) { uint bucketCount; uint3 padding; };
[numthreads(256, 1, 1)] void main(uint3 id : SV_DispatchThreadID) {
    if (id.x < bucketCount) gridHeads[id.x] = 0xffffffffu;
}
)";

constexpr const char* grid_build_shader_source = R"(
StructuredBuffer<float4> positions : register(t0);
RWStructuredBuffer<uint> gridHeads : register(u0);
RWStructuredBuffer<uint> gridNext : register(u1);
RWStructuredBuffer<int4> gridCells : register(u2);
cbuffer GridBuildParameters : register(b0) {
    uint particleCount; uint bucketMask; float cellSize; float padding;
};
uint hashCell(int3 cell) {
    return (asuint(cell.x) * 73856093u ^ asuint(cell.y) * 19349663u ^ asuint(cell.z) * 83492791u) & bucketMask;
}
[numthreads(256, 1, 1)] void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= particleCount) return;
    const int3 cell = (int3)floor(positions[id.x].xyz / cellSize);
    gridCells[id.x] = int4(cell, 0);
    uint previous; InterlockedExchange(gridHeads[hashCell(cell)], id.x, previous);
    gridNext[id.x] = previous;
}
)";

constexpr const char* self_collision_shader_source = R"(
StructuredBuffer<float4> positions : register(t0);
StructuredBuffer<uint> gridHeads : register(t1);
StructuredBuffer<uint> gridNext : register(t2);
StructuredBuffer<int4> gridCells : register(t3);
RWStructuredBuffer<float4> outputPositions : register(u0);
RWStructuredBuffer<float4> velocities : register(u1);
cbuffer SelfCollisionParameters : register(b0) {
    uint particleCount; uint bucketMask; uint maximumBucketVisits; float cellSize;
    float deltaTime; float correctionLimit; float2 padding;
};
uint hashCell(int3 cell) {
    return (asuint(cell.x) * 73856093u ^ asuint(cell.y) * 19349663u ^ asuint(cell.z) * 83492791u) & bucketMask;
}
[numthreads(256, 1, 1)] void main(uint3 id : SV_DispatchThreadID) {
    const uint index = id.x;
    if (index >= particleCount) return;
    const float4 source = positions[index];
    if (source.w <= 0.0f) { outputPositions[index] = source; return; }
    const int3 cell = gridCells[index].xyz;
    float3 correction = 0.0f; uint visits = 0u;
    [loop] for (int x = -1; x <= 1; ++x) [loop] for (int y = -1; y <= 1; ++y)
    [loop] for (int z = -1; z <= 1; ++z) {
        const int3 target = cell + int3(x, y, z);
        uint other = gridHeads[hashCell(target)];
        [loop] while (other != 0xffffffffu && visits < maximumBucketVisits) {
            ++visits;
            if (other != index && all(gridCells[other].xyz == target) && positions[other].w > 0.0f) {
                const float3 delta = source.xyz - positions[other].xyz;
                const float distance = length(delta);
                const float minimumDistance = source.w + positions[other].w;
                if (distance > 1.0e-12f && distance < minimumDistance)
                    correction += delta / distance * ((minimumDistance - distance) * 0.5f);
            }
            other = gridNext[other];
        }
    }
    const float magnitude = length(correction);
    if (magnitude > correctionLimit) correction *= correctionLimit / magnitude;
    outputPositions[index] = float4(source.xyz + correction, source.w);
    velocities[index].xyz += correction / max(1.0e-12f, deltaTime);
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
    ComPtr<ID3D11Buffer> constraint_endpoints, constraint_data, constraint_lambdas;
    ComPtr<ID3D11ShaderResourceView> constraint_endpoints_srv, constraint_data_srv;
    ComPtr<ID3D11UnorderedAccessView> constraint_lambdas_uav;
    ComPtr<ID3D11Buffer> physics_fields;
    ComPtr<ID3D11ShaderResourceView> physics_fields_srv;
    ComPtr<ID3D11Buffer> mesh_node_bounds, mesh_node_metadata, mesh_triangle_vertices;
    ComPtr<ID3D11ShaderResourceView> mesh_node_bounds_srv, mesh_node_metadata_srv, mesh_triangle_vertices_srv;
    ComPtr<ID3D11Buffer> grid_heads, grid_next, grid_cells, self_collision_scratch;
    ComPtr<ID3D11ShaderResourceView> grid_heads_srv, grid_next_srv, grid_cells_srv, position_srv;
    ComPtr<ID3D11UnorderedAccessView> grid_heads_uav, grid_next_uav, grid_cells_uav, self_collision_scratch_uav;
    std::vector<std::uint32_t> constraint_color_offsets;
    std::uint32_t capacity{0};
    std::uint32_t count{0};
    std::uint32_t constraint_capacity{0};
    std::uint32_t constraint_count{0};
    std::uint32_t physics_field_capacity{0};
    std::uint32_t physics_field_count{0};
    float simulation_time{0.0f};
    std::uint32_t mesh_node_count{0};
    std::uint32_t mesh_triangle_count{0};
    float mesh_friction{0.0f}, mesh_restitution{0.0f}, mesh_surface_velocity[3]{0.0f, 0.0f, 0.0f};
    std::uint32_t grid_bucket_count{0};
};

class ComputeDevice {
public:
    bool initialize(std::string& error) {
        std::scoped_lock lock(mutex_);
        if (device_ && context_ && shader_ && distance_constraint_shader_ && mesh_collision_shader_
            && grid_clear_shader_ && grid_build_shader_ && self_collision_shader_) return true;
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
        bytecode.Reset();
        errors.Reset();
        result = D3DCompile(
            distance_constraint_shader_source, std::strlen(distance_constraint_shader_source),
            "tc_distance_constraints", nullptr, nullptr, "main", "cs_5_0",
            D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &bytecode, &errors);
        if (FAILED(result)) {
            error = errors ? std::string(static_cast<const char*>(errors->GetBufferPointer()), errors->GetBufferSize())
                           : "D3D11 distance-constraint shader compilation failed.";
            return false;
        }
        if (FAILED(device_->CreateComputeShader(
                bytecode->GetBufferPointer(), bytecode->GetBufferSize(), nullptr, &distance_constraint_shader_))) {
            error = "D3D11 distance-constraint shader creation failed.";
            return false;
        }
        bytecode.Reset();
        errors.Reset();
        result = D3DCompile(
            mesh_collision_shader_source, std::strlen(mesh_collision_shader_source),
            "tc_mesh_collision", nullptr, nullptr, "main", "cs_5_0",
            D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &bytecode, &errors);
        if (FAILED(result)) {
            error = errors ? std::string(static_cast<const char*>(errors->GetBufferPointer()), errors->GetBufferSize())
                           : "D3D11 mesh-collision shader compilation failed.";
            return false;
        }
        if (FAILED(device_->CreateComputeShader(
                bytecode->GetBufferPointer(), bytecode->GetBufferSize(), nullptr, &mesh_collision_shader_))) {
            error = "D3D11 mesh-collision shader creation failed.";
            return false;
        }
        const auto compile_shader = [&](const char* source, const char* name,
                                        ComPtr<ID3D11ComputeShader>& output) -> bool {
            ComPtr<ID3DBlob> code, compile_errors;
            const auto status = D3DCompile(source, std::strlen(source), name, nullptr, nullptr, "main", "cs_5_0",
                                           D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &code, &compile_errors);
            if (FAILED(status)) {
                error = compile_errors ? std::string(static_cast<const char*>(compile_errors->GetBufferPointer()),
                                                     compile_errors->GetBufferSize())
                                       : std::string("D3D11 shader compilation failed: ") + name;
                return false;
            }
            if (FAILED(device_->CreateComputeShader(code->GetBufferPointer(), code->GetBufferSize(), nullptr, &output))) {
                error = std::string("D3D11 shader creation failed: ") + name;
                return false;
            }
            return true;
        };
        if (!compile_shader(grid_clear_shader_source, "tc_grid_clear", grid_clear_shader_) ||
            !compile_shader(grid_build_shader_source, "tc_grid_build", grid_build_shader_) ||
            !compile_shader(self_collision_shader_source, "tc_self_collision", self_collision_shader_)) return false;
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

    bool upload_distance_constraints_session(
        tc_gpu_session_handle session, const std::uint32_t* endpoints, const float* data,
        std::uint32_t count, const std::uint32_t* color_offsets, std::uint32_t color_count,
        std::string& error) {
        if (!initialize(error)) return false;
        if (endpoints == nullptr || data == nullptr || color_offsets == nullptr || count == 0 || color_count == 0) {
            error = "Distance-constraint buffers or counts are invalid.";
            return false;
        }
        if (color_offsets[0] != 0 || color_offsets[color_count] != count) {
            error = "Distance-constraint color offsets must span the full constraint buffer.";
            return false;
        }
        for (std::uint32_t index = 0; index < color_count; ++index) {
            if (color_offsets[index] > color_offsets[index + 1]) {
                error = "Distance-constraint color offsets must be monotonic.";
                return false;
            }
        }
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr || stream->count == 0 || !ensure_constraint_buffers(*stream, count, error)) return false;
        context_->UpdateSubresource(stream->constraint_endpoints.Get(), 0, nullptr, endpoints, 0, 0);
        context_->UpdateSubresource(stream->constraint_data.Get(), 0, nullptr, data, 0, 0);
        stream->constraint_color_offsets.assign(color_offsets, color_offsets + color_count + 1U);
        stream->constraint_count = count;
        return true;
    }

    bool dispatch_distance_constraints_session(
        tc_gpu_session_handle session, float dt, std::uint32_t iterations, std::string& error) {
        if (!initialize(error)) return false;
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr) return false;
        return dispatch_constraints_unlocked(*stream, dt, iterations, error);
    }

    std::uint32_t session_constraint_count(tc_gpu_session_handle session) const {
        std::scoped_lock lock(mutex_);
        if (session == 0) return default_stream_.constraint_count;
        const auto found = sessions_.find(session);
        return found == sessions_.end() ? 0 : found->second->constraint_count;
    }

    bool upload_physics_fields_session(
        tc_gpu_session_handle session, const float* records, std::uint32_t count,
        float simulation_time, std::string& error) {
        if (!initialize(error)) return false;
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr) return false;
        stream->simulation_time = simulation_time;
        if (count == 0) {
            stream->physics_field_count = 0;
            return true;
        }
        if (records == nullptr || count > 4096U || !ensure_physics_field_buffer(*stream, count, error)) {
            if (error.empty()) error = "Physics-field buffer or count is invalid.";
            return false;
        }
        context_->UpdateSubresource(stream->physics_fields.Get(), 0, nullptr, records, 0, 0);
        stream->physics_field_count = count;
        return true;
    }

    std::uint32_t session_physics_field_count(tc_gpu_session_handle session) const {
        std::scoped_lock lock(mutex_);
        if (session == 0) return default_stream_.physics_field_count;
        const auto found = sessions_.find(session);
        return found == sessions_.end() ? 0 : found->second->physics_field_count;
    }

    bool upload_mesh_bvh_session(
        tc_gpu_session_handle session, const float* node_bounds, const std::uint32_t* node_metadata,
        std::uint32_t node_count, const float* triangle_vertices, std::uint32_t triangle_count,
        float friction, float restitution, float velocity_x, float velocity_y, float velocity_z,
        std::string& error) {
        if (!initialize(error)) return false;
        if (node_bounds == nullptr || node_metadata == nullptr || triangle_vertices == nullptr ||
            node_count == 0 || triangle_count == 0) {
            error = "Mesh BVH buffers or counts are invalid.";
            return false;
        }
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr) return false;
        stream->mesh_node_bounds.Reset(); stream->mesh_node_metadata.Reset();
        stream->mesh_triangle_vertices.Reset(); stream->mesh_node_bounds_srv.Reset();
        stream->mesh_node_metadata_srv.Reset(); stream->mesh_triangle_vertices_srv.Reset();
        if (!create_structured_srv(node_count * 2U, 4U * sizeof(float), stream->mesh_node_bounds,
                                   stream->mesh_node_bounds_srv, error) ||
            !create_structured_srv(node_count, 4U * sizeof(std::uint32_t), stream->mesh_node_metadata,
                                   stream->mesh_node_metadata_srv, error) ||
            !create_structured_srv(triangle_count * 3U, 4U * sizeof(float), stream->mesh_triangle_vertices,
                                   stream->mesh_triangle_vertices_srv, error)) return false;
        context_->UpdateSubresource(stream->mesh_node_bounds.Get(), 0, nullptr, node_bounds, 0, 0);
        context_->UpdateSubresource(stream->mesh_node_metadata.Get(), 0, nullptr, node_metadata, 0, 0);
        context_->UpdateSubresource(stream->mesh_triangle_vertices.Get(), 0, nullptr, triangle_vertices, 0, 0);
        stream->mesh_node_count = node_count; stream->mesh_triangle_count = triangle_count;
        stream->mesh_friction = std::max(0.0f, friction);
        stream->mesh_restitution = std::max(0.0f, restitution);
        stream->mesh_surface_velocity[0] = velocity_x;
        stream->mesh_surface_velocity[1] = velocity_y;
        stream->mesh_surface_velocity[2] = velocity_z;
        return true;
    }

    bool dispatch_mesh_bvh_session(tc_gpu_session_handle session, float dt, std::string& error) {
        if (!initialize(error)) return false;
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr) return false;
        return dispatch_mesh_unlocked(*stream, dt, error);
    }

    std::uint32_t session_mesh_triangle_count(tc_gpu_session_handle session) const {
        std::scoped_lock lock(mutex_);
        if (session == 0) return default_stream_.mesh_triangle_count;
        const auto found = sessions_.find(session);
        return found == sessions_.end() ? 0 : found->second->mesh_triangle_count;
    }

    bool dispatch_self_collision_session(
        tc_gpu_session_handle session, float cell_size, float dt, std::uint32_t iterations,
        std::uint32_t maximum_visits, std::string& error) {
        if (!initialize(error)) return false;
        std::scoped_lock lock(mutex_);
        auto* stream = stream_unlocked(session, error);
        if (stream == nullptr || !ensure_grid_buffers(*stream, error)) return false;
        return dispatch_self_collision_unlocked(
            *stream, std::max(1.0e-6f, cell_size), dt, std::max(1U, iterations),
            std::max(32U, maximum_visits), error);
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
            std::uint32_t physics_field_count;
            float simulation_time;
            float field_padding[2];
        } parameters{
            {ax, ay, az, dt}, stream.count, std::max(1U, substeps), {0, 0},
            {plane_x, plane_y, plane_z, plane_offset},
            {plane_friction, plane_restitution, 0.0f, plane_enabled ? 1.0f : 0.0f},
            {sphere_x, sphere_y, sphere_z, sphere_radius},
            {sphere_friction, sphere_restitution, sphere_enabled ? 1.0f : 0.0f, 0.0f},
            stream.physics_field_count, stream.simulation_time, {0.0f, 0.0f}
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
        ID3D11ShaderResourceView* field_srvs[] = {stream.physics_fields_srv.Get()};
        context_->CSSetShaderResources(0, 1, field_srvs);
        context_->CSSetConstantBuffers(0, 1, constants.GetAddressOf());
        context_->Dispatch((stream.count + 255U) / 256U, 1, 1);
        ID3D11UnorderedAccessView* no_uavs[] = {nullptr, nullptr};
        ID3D11ShaderResourceView* no_field_srvs[] = {nullptr};
        context_->CSSetUnorderedAccessViews(0, 2, no_uavs, nullptr);
        context_->CSSetShaderResources(0, 1, no_field_srvs);
        context_->CSSetShader(nullptr, nullptr, 0);
        stream.simulation_time += dt;

        return true;
    }

    bool dispatch_constraints_unlocked(
        ParticleStream& stream, float dt, std::uint32_t iterations, std::string& error) {
        if (stream.count == 0 || stream.constraint_count == 0 || stream.constraint_color_offsets.size() < 2U) {
            error = "No resident particle/constraint stream has been uploaded.";
            return false;
        }
        struct alignas(16) ConstraintParameters {
            std::uint32_t constraint_start;
            std::uint32_t constraint_count;
            std::uint32_t particle_count;
            std::uint32_t reset_lambdas;
            float delta_time;
            float padding[3];
        };
        ID3D11UnorderedAccessView* uavs[] = {
            stream.position_uav.Get(), stream.constraint_lambdas_uav.Get(), stream.velocity_uav.Get()
        };
        ID3D11ShaderResourceView* srvs[] = {
            stream.constraint_endpoints_srv.Get(), stream.constraint_data_srv.Get()
        };
        context_->CSSetShader(distance_constraint_shader_.Get(), nullptr, 0);
        context_->CSSetUnorderedAccessViews(0, 3, uavs, nullptr);
        context_->CSSetShaderResources(0, 2, srvs);
        const auto iteration_count = std::max(1U, iterations);
        for (std::uint32_t iteration = 0; iteration < iteration_count; ++iteration) {
            for (std::size_t color = 0; color + 1U < stream.constraint_color_offsets.size(); ++color) {
                const auto start = stream.constraint_color_offsets[color];
                const auto count = stream.constraint_color_offsets[color + 1U] - start;
                if (count == 0) continue;
                const ConstraintParameters parameters{
                    start, count, stream.count, iteration == 0U ? 1U : 0U,
                    dt, {0.0f, 0.0f, 0.0f}
                };
                ComPtr<ID3D11Buffer> constants;
                D3D11_BUFFER_DESC constant_desc{};
                constant_desc.ByteWidth = sizeof(ConstraintParameters);
                constant_desc.Usage = D3D11_USAGE_IMMUTABLE;
                constant_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
                D3D11_SUBRESOURCE_DATA constant_data{&parameters, 0, 0};
                if (FAILED(device_->CreateBuffer(&constant_desc, &constant_data, &constants))) {
                    error = "D3D11 constraint constant buffer allocation failed.";
                    return false;
                }
                context_->CSSetConstantBuffers(0, 1, constants.GetAddressOf());
                context_->Dispatch((count + 255U) / 256U, 1, 1);
            }
        }
        ID3D11UnorderedAccessView* no_uavs[] = {nullptr, nullptr, nullptr};
        ID3D11ShaderResourceView* no_srvs[] = {nullptr, nullptr};
        context_->CSSetUnorderedAccessViews(0, 3, no_uavs, nullptr);
        context_->CSSetShaderResources(0, 2, no_srvs);
        context_->CSSetShader(nullptr, nullptr, 0);
        return true;
    }

    bool dispatch_mesh_unlocked(ParticleStream& stream, float dt, std::string& error) {
        if (stream.count == 0 || stream.mesh_node_count == 0 || stream.mesh_triangle_count == 0) {
            error = "No resident particle/mesh BVH stream has been uploaded.";
            return false;
        }
        struct alignas(16) MeshParameters {
            std::uint32_t particle_count, node_count, triangle_count;
            float delta_time;
            float friction, restitution, padding[2];
            float surface_velocity[4];
        } parameters{
            stream.count, stream.mesh_node_count, stream.mesh_triangle_count, dt,
            stream.mesh_friction, stream.mesh_restitution, {0.0f, 0.0f},
            {stream.mesh_surface_velocity[0], stream.mesh_surface_velocity[1],
             stream.mesh_surface_velocity[2], 0.0f}
        };
        ComPtr<ID3D11Buffer> constants;
        D3D11_BUFFER_DESC constant_desc{};
        constant_desc.ByteWidth = sizeof(MeshParameters);
        constant_desc.Usage = D3D11_USAGE_IMMUTABLE;
        constant_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        D3D11_SUBRESOURCE_DATA constant_data{&parameters, 0, 0};
        if (FAILED(device_->CreateBuffer(&constant_desc, &constant_data, &constants))) {
            error = "D3D11 mesh collision constant buffer allocation failed.";
            return false;
        }
        ID3D11UnorderedAccessView* uavs[] = {stream.position_uav.Get(), stream.velocity_uav.Get()};
        ID3D11ShaderResourceView* srvs[] = {
            stream.mesh_node_bounds_srv.Get(), stream.mesh_node_metadata_srv.Get(),
            stream.mesh_triangle_vertices_srv.Get()
        };
        context_->CSSetShader(mesh_collision_shader_.Get(), nullptr, 0);
        context_->CSSetUnorderedAccessViews(0, 2, uavs, nullptr);
        context_->CSSetShaderResources(0, 3, srvs);
        context_->CSSetConstantBuffers(0, 1, constants.GetAddressOf());
        context_->Dispatch((stream.count + 255U) / 256U, 1, 1);
        ID3D11UnorderedAccessView* no_uavs[] = {nullptr, nullptr};
        ID3D11ShaderResourceView* no_srvs[] = {nullptr, nullptr, nullptr};
        context_->CSSetUnorderedAccessViews(0, 2, no_uavs, nullptr);
        context_->CSSetShaderResources(0, 3, no_srvs);
        context_->CSSetShader(nullptr, nullptr, 0);
        return true;
    }

    bool dispatch_self_collision_unlocked(
        ParticleStream& stream, float cell_size, float dt, std::uint32_t iterations,
        std::uint32_t maximum_visits, std::string& error) {
        struct alignas(16) ClearParameters { std::uint32_t count, padding[3]; } clear{stream.grid_bucket_count,{0,0,0}};
        struct alignas(16) BuildParameters { std::uint32_t count, mask; float cell_size, padding; }
            build{stream.count,stream.grid_bucket_count-1U,cell_size,0.0f};
        struct alignas(16) SolveParameters {
            std::uint32_t count, mask, visits; float cell_size;
            float dt, limit, padding[2];
        } solve{stream.count,stream.grid_bucket_count-1U,maximum_visits,cell_size,dt,cell_size,{0,0}};
        const auto constant = [&](const void* data, UINT size, ComPtr<ID3D11Buffer>& output) {
            D3D11_BUFFER_DESC desc{}; desc.ByteWidth=size; desc.Usage=D3D11_USAGE_IMMUTABLE;
            desc.BindFlags=D3D11_BIND_CONSTANT_BUFFER; D3D11_SUBRESOURCE_DATA initial{data,0,0};
            return SUCCEEDED(device_->CreateBuffer(&desc,&initial,&output));
        };
        ComPtr<ID3D11Buffer> clear_cb, build_cb, solve_cb;
        if (!constant(&clear,sizeof(clear),clear_cb)||!constant(&build,sizeof(build),build_cb)||
            !constant(&solve,sizeof(solve),solve_cb)) { error="D3D11 self-collision constants failed."; return false; }
        for (std::uint32_t iteration=0; iteration<iterations; ++iteration) {
            ID3D11UnorderedAccessView* clear_uav[]={stream.grid_heads_uav.Get()};
            context_->CSSetShader(grid_clear_shader_.Get(),nullptr,0); context_->CSSetUnorderedAccessViews(0,1,clear_uav,nullptr);
            context_->CSSetConstantBuffers(0,1,clear_cb.GetAddressOf()); context_->Dispatch((stream.grid_bucket_count+255U)/256U,1,1);
            ID3D11UnorderedAccessView* none3[]={nullptr,nullptr,nullptr}; context_->CSSetUnorderedAccessViews(0,1,none3,nullptr);
            ID3D11UnorderedAccessView* build_uav[]={stream.grid_heads_uav.Get(),stream.grid_next_uav.Get(),stream.grid_cells_uav.Get()};
            ID3D11ShaderResourceView* position[]={stream.position_srv.Get()};
            context_->CSSetShader(grid_build_shader_.Get(),nullptr,0); context_->CSSetShaderResources(0,1,position);
            context_->CSSetUnorderedAccessViews(0,3,build_uav,nullptr); context_->CSSetConstantBuffers(0,1,build_cb.GetAddressOf());
            context_->Dispatch((stream.count+255U)/256U,1,1); context_->CSSetUnorderedAccessViews(0,3,none3,nullptr);
            ID3D11ShaderResourceView* no1[]={nullptr}; context_->CSSetShaderResources(0,1,no1);
            ID3D11UnorderedAccessView* solve_uav[]={stream.self_collision_scratch_uav.Get(),stream.velocity_uav.Get()};
            ID3D11ShaderResourceView* solve_srv[]={stream.position_srv.Get(),stream.grid_heads_srv.Get(),stream.grid_next_srv.Get(),stream.grid_cells_srv.Get()};
            context_->CSSetShader(self_collision_shader_.Get(),nullptr,0); context_->CSSetShaderResources(0,4,solve_srv);
            context_->CSSetUnorderedAccessViews(0,2,solve_uav,nullptr); context_->CSSetConstantBuffers(0,1,solve_cb.GetAddressOf());
            context_->Dispatch((stream.count+255U)/256U,1,1); context_->CSSetUnorderedAccessViews(0,2,none3,nullptr);
            ID3D11ShaderResourceView* none4[]={nullptr,nullptr,nullptr,nullptr}; context_->CSSetShaderResources(0,4,none4);
            context_->CopyResource(stream.position_buffer.Get(),stream.self_collision_scratch.Get());
        }
        context_->CSSetShader(nullptr,nullptr,0); return true;
    }

    bool create_grid_resource(std::uint32_t count, UINT stride, ComPtr<ID3D11Buffer>& buffer,
        ComPtr<ID3D11ShaderResourceView>& srv, ComPtr<ID3D11UnorderedAccessView>& uav, std::string& error) {
        D3D11_BUFFER_DESC desc{}; desc.ByteWidth=count*stride; desc.Usage=D3D11_USAGE_DEFAULT;
        desc.BindFlags=D3D11_BIND_SHADER_RESOURCE|D3D11_BIND_UNORDERED_ACCESS;
        desc.MiscFlags=D3D11_RESOURCE_MISC_BUFFER_STRUCTURED; desc.StructureByteStride=stride;
        if(FAILED(device_->CreateBuffer(&desc,nullptr,&buffer))){error="D3D11 grid buffer failed.";return false;}
        D3D11_SHADER_RESOURCE_VIEW_DESC sd{}; sd.Format=DXGI_FORMAT_UNKNOWN; sd.ViewDimension=D3D11_SRV_DIMENSION_BUFFER; sd.Buffer.NumElements=count;
        D3D11_UNORDERED_ACCESS_VIEW_DESC ud{}; ud.Format=DXGI_FORMAT_UNKNOWN; ud.ViewDimension=D3D11_UAV_DIMENSION_BUFFER; ud.Buffer.NumElements=count;
        if(FAILED(device_->CreateShaderResourceView(buffer.Get(),&sd,&srv))||FAILED(device_->CreateUnorderedAccessView(buffer.Get(),&ud,&uav))){error="D3D11 grid views failed.";return false;}
        return true;
    }

    bool ensure_grid_buffers(ParticleStream& stream, std::string& error) {
        std::uint32_t buckets=1U; while(buckets<std::max(2U,stream.count*2U)) buckets<<=1U;
        if(stream.grid_bucket_count==buckets&&stream.grid_next&&stream.self_collision_scratch) return true;
        stream.grid_bucket_count=buckets;
        if(!create_grid_resource(buckets,sizeof(std::uint32_t),stream.grid_heads,stream.grid_heads_srv,stream.grid_heads_uav,error)||
           !create_grid_resource(stream.count,sizeof(std::uint32_t),stream.grid_next,stream.grid_next_srv,stream.grid_next_uav,error)||
           !create_grid_resource(stream.count,4U*sizeof(std::int32_t),stream.grid_cells,stream.grid_cells_srv,stream.grid_cells_uav,error)) return false;
        ComPtr<ID3D11ShaderResourceView> unused;
        return create_grid_resource(stream.count,4U*sizeof(float),stream.self_collision_scratch,unused,stream.self_collision_scratch_uav,error);
    }

    bool create_structured_srv(
        std::uint32_t count, UINT stride, ComPtr<ID3D11Buffer>& buffer,
        ComPtr<ID3D11ShaderResourceView>& view, std::string& error) {
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = count * stride;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
        desc.StructureByteStride = stride;
        if (FAILED(device_->CreateBuffer(&desc, nullptr, &buffer))) {
            error = "D3D11 constraint SRV buffer allocation failed.";
            return false;
        }
        D3D11_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_UNKNOWN;
        srv.ViewDimension = D3D11_SRV_DIMENSION_BUFFER;
        srv.Buffer.NumElements = count;
        if (FAILED(device_->CreateShaderResourceView(buffer.Get(), &srv, &view))) {
            error = "D3D11 constraint SRV creation failed.";
            return false;
        }
        return true;
    }

    bool create_scalar_uav(
        std::uint32_t count, ComPtr<ID3D11Buffer>& buffer,
        ComPtr<ID3D11UnorderedAccessView>& view, std::string& error) {
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = count * sizeof(float);
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_UNORDERED_ACCESS;
        desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
        desc.StructureByteStride = sizeof(float);
        if (FAILED(device_->CreateBuffer(&desc, nullptr, &buffer))) {
            error = "D3D11 constraint lambda buffer allocation failed.";
            return false;
        }
        D3D11_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = DXGI_FORMAT_UNKNOWN;
        uav.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
        uav.Buffer.NumElements = count;
        if (FAILED(device_->CreateUnorderedAccessView(buffer.Get(), &uav, &view))) {
            error = "D3D11 constraint lambda UAV creation failed.";
            return false;
        }
        return true;
    }

    bool ensure_constraint_buffers(ParticleStream& stream, std::uint32_t count, std::string& error) {
        if (stream.constraint_capacity == count && stream.constraint_endpoints &&
            stream.constraint_data && stream.constraint_lambdas) return true;
        stream.constraint_endpoints.Reset(); stream.constraint_data.Reset(); stream.constraint_lambdas.Reset();
        stream.constraint_endpoints_srv.Reset(); stream.constraint_data_srv.Reset();
        stream.constraint_lambdas_uav.Reset();
        stream.constraint_capacity = 0;
        stream.constraint_count = 0;
        stream.constraint_color_offsets.clear();
        if (!create_structured_srv(count, 2U * sizeof(std::uint32_t), stream.constraint_endpoints,
                                   stream.constraint_endpoints_srv, error) ||
            !create_structured_srv(count, 4U * sizeof(float), stream.constraint_data,
                                   stream.constraint_data_srv, error) ||
            !create_scalar_uav(count, stream.constraint_lambdas, stream.constraint_lambdas_uav, error))
            return false;
        stream.constraint_capacity = count;
        return true;
    }

    bool ensure_physics_field_buffer(ParticleStream& stream, std::uint32_t count, std::string& error) {
        if (stream.physics_field_capacity == count && stream.physics_fields && stream.physics_fields_srv)
            return true;
        stream.physics_fields.Reset();
        stream.physics_fields_srv.Reset();
        stream.physics_field_capacity = 0;
        stream.physics_field_count = 0;
        if (!create_structured_srv(
                count * 5U, 4U * sizeof(float), stream.physics_fields,
                stream.physics_fields_srv, error)) return false;
        stream.physics_field_capacity = count;
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
        stream.position_srv.Reset();
        stream.position_staging.Reset(); stream.velocity_staging.Reset();
        stream.capacity = 0;
        stream.count = 0;
        const UINT byte_width = count * 4U * sizeof(float);
        if (!create_compute_buffer(count, stream.position_buffer, stream.position_uav, error) ||
            !create_compute_buffer(count, stream.velocity_buffer, stream.velocity_uav, error) ||
            !create_staging(byte_width, stream.position_staging, error) ||
            !create_staging(byte_width, stream.velocity_staging, error)) return false;
        D3D11_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_UNKNOWN; srv.ViewDimension = D3D11_SRV_DIMENSION_BUFFER;
        srv.Buffer.NumElements = count;
        if (FAILED(device_->CreateShaderResourceView(stream.position_buffer.Get(), &srv, &stream.position_srv))) {
            error = "D3D11 particle position SRV creation failed."; return false;
        }
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
    ComPtr<ID3D11ComputeShader> distance_constraint_shader_;
    ComPtr<ID3D11ComputeShader> mesh_collision_shader_;
    ComPtr<ID3D11ComputeShader> grid_clear_shader_, grid_build_shader_, self_collision_shader_;
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

extern "C" int tc_gpu_session_upload_physics_fields(
    tc_gpu_session_handle session, const float* records, std::uint32_t field_count,
    float simulation_time, char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().upload_physics_fields_session(
            session, records, field_count, simulation_time, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Composable physics fields uploaded to D3D11.");
    return 1;
#else
    (void)session; (void)records; (void)field_count; (void)simulation_time;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" std::uint32_t tc_gpu_session_physics_field_count(tc_gpu_session_handle session) {
#if defined(_WIN32)
    return compute_device().session_physics_field_count(session);
#else
    (void)session;
    return 0;
#endif
}

extern "C" int tc_gpu_session_upload_mesh_bvh(
    tc_gpu_session_handle session, const float* node_bounds, const std::uint32_t* node_metadata,
    std::uint32_t node_count, const float* triangle_vertices, std::uint32_t triangle_count,
    float friction, float restitution, float velocity_x, float velocity_y, float velocity_z,
    char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().upload_mesh_bvh_session(
            session, node_bounds, node_metadata, node_count, triangle_vertices, triangle_count,
            friction, restitution, velocity_x, velocity_y, velocity_z, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Refittable mesh BVH uploaded to D3D11.");
    return 1;
#else
    (void)session; (void)node_bounds; (void)node_metadata; (void)node_count;
    (void)triangle_vertices; (void)triangle_count; (void)friction; (void)restitution;
    (void)velocity_x; (void)velocity_y; (void)velocity_z;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_session_dispatch_mesh_bvh(
    tc_gpu_session_handle session, float dt, char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().dispatch_mesh_bvh_session(session, dt, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "D3D11 particle-to-BVH traversal completed.");
    return 1;
#else
    (void)session; (void)dt;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" std::uint32_t tc_gpu_session_mesh_triangle_count(tc_gpu_session_handle session) {
#if defined(_WIN32)
    return compute_device().session_mesh_triangle_count(session);
#else
    (void)session;
    return 0;
#endif
}

extern "C" int tc_gpu_session_dispatch_self_collision(
    tc_gpu_session_handle session, float cell_size, float dt, std::uint32_t iterations,
    std::uint32_t maximum_visits, char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().dispatch_self_collision_session(
            session, cell_size, dt, iterations, maximum_visits, error)) {
        write_message(message, message_size, error); return 0;
    }
    write_message(message, message_size, "D3D11 spatial-hash self-collision completed."); return 1;
#else
    (void)session;(void)cell_size;(void)dt;(void)iterations;(void)maximum_visits;
    if(message&&message_size)message[0]='\0'; return 0;
#endif
}

extern "C" int tc_gpu_session_upload_distance_constraints(
    tc_gpu_session_handle session, const std::uint32_t* endpoints, const float* data,
    std::uint32_t constraint_count, const std::uint32_t* color_offsets,
    std::uint32_t color_count, char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().upload_distance_constraints_session(
            session, endpoints, data, constraint_count, color_offsets, color_count, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Graph-colored distance constraints uploaded to D3D11.");
    return 1;
#else
    (void)session; (void)endpoints; (void)data; (void)constraint_count;
    (void)color_offsets; (void)color_count;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" int tc_gpu_session_dispatch_distance_constraints(
    tc_gpu_session_handle session, float dt, std::uint32_t iterations,
    char* message, std::size_t message_size) {
#if defined(_WIN32)
    std::string error;
    if (!compute_device().dispatch_distance_constraints_session(session, dt, iterations, error)) {
        write_message(message, message_size, error);
        return 0;
    }
    write_message(message, message_size, "Graph-colored D3D11 XPBD distance dispatch completed.");
    return 1;
#else
    (void)session; (void)dt; (void)iterations;
    if (message && message_size) message[0] = '\0';
    return 0;
#endif
}

extern "C" std::uint32_t tc_gpu_session_distance_constraint_count(tc_gpu_session_handle session) {
#if defined(_WIN32)
    return compute_device().session_constraint_count(session);
#else
    (void)session;
    return 0;
#endif
}
