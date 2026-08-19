#include "tc_runtime_core.h"
#include "tc_force_tree.h"
#include "tc_spatial_index.h"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <unordered_set>

namespace tc::runtime {
namespace {

Matrix4 identity_matrix() {
    return {1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
}

Matrix4 multiply_matrix(const Matrix4& left,const Matrix4& right){
    Matrix4 result{};for(int row=0;row<4;++row)for(int column=0;column<4;++column)for(int inner=0;inner<4;++inner)result[row*4+column]+=left[row*4+inner]*right[inner*4+column];return result;
}

double sample_animation_curve(const AnimationCurve& curve,double frame){
    if(curve.keys.empty())return 0.0;if(frame<=curve.keys.front().frame)return curve.keys.front().value;if(frame>=curve.keys.back().frame)return curve.keys.back().value;
    for(std::size_t index=1;index<curve.keys.size();++index){const auto& first=curve.keys[index-1];const auto& second=curve.keys[index];if(frame>second.frame)continue;if(first.interpolation=="constant"||first.interpolation=="stepped")return first.value;const double alpha=(frame-first.frame)/std::max(1.0e-12,second.frame-first.frame);return first.value*(1.0-alpha)+second.value*alpha;}return curve.keys.back().value;
}

std::string normalized_attribute(std::string value){value.erase(std::remove_if(value.begin(),value.end(),[](unsigned char character){return character=='_'||character=='.'||character==' ';}),value.end());std::transform(value.begin(),value.end(),value.begin(),[](unsigned char character){return static_cast<char>(std::tolower(character));});return value;}

Matrix4 rotation_matrix(double x_degrees,double y_degrees,double z_degrees){
    constexpr double radians=3.14159265358979323846/180.0;const double x=x_degrees*radians,y=y_degrees*radians,z=z_degrees*radians;const double cx=std::cos(x),sx=std::sin(x),cy=std::cos(y),sy=std::sin(y),cz=std::cos(z),sz=std::sin(z);
    const Matrix4 rx{1,0,0,0,0,cx,sx,0,0,-sx,cx,0,0,0,0,1};const Matrix4 ry{cy,0,-sy,0,0,1,0,0,sy,0,cy,0,0,0,0,1};const Matrix4 rz{cz,sz,0,0,-sz,cz,0,0,0,0,1,0,0,0,0,1};return multiply_matrix(multiply_matrix(rx,ry),rz);
}

using Clock = std::chrono::steady_clock;

std::vector<std::string> fields(const std::string& line) {
    std::vector<std::string> result;
    std::size_t start = 0;
    while (start <= line.size()) {
        const auto end = line.find('\t', start);
        result.push_back(line.substr(start, end == std::string::npos ? end : end - start));
        if (end == std::string::npos) {
            break;
        }
        start = end + 1;
    }
    return result;
}

std::string decode(const std::string& value) {
    std::string result;
    result.reserve(value.size());
    for (std::size_t index = 0; index < value.size(); ++index) {
        if (value[index] == '%' && index + 2 < value.size()) {
            const auto hex = value.substr(index + 1, 2);
            unsigned int code = 0;
            std::istringstream(hex) >> std::hex >> code;
            result.push_back(static_cast<char>(code));
            index += 2;
        } else {
            result.push_back(value[index]);
        }
    }
    return result;
}

std::string encode(const std::string& value) {
    std::ostringstream result;
    result << std::uppercase << std::hex;
    for (const unsigned char character : value) {
        if (character == '%' || character == '\t' || character == '\n' || character == '\r') {
            result << '%' << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(character);
        } else {
            result << static_cast<char>(character);
        }
    }
    return result.str();
}

float number(const std::vector<std::string>& row, std::size_t index, float fallback = 0.0F) {
    if (index >= row.size()) {
        return fallback;
    }
    const float value = std::stof(row[index]);
    if (!std::isfinite(value)) {
        throw std::runtime_error("Runtime manifest contains a non-finite number");
    }
    return value;
}

double real_number(const std::vector<std::string>& row, std::size_t index, double fallback = 0.0) {
    if (index >= row.size()) return fallback;
    const double value = std::stod(row[index]);
    if (!std::isfinite(value)) throw std::runtime_error("Runtime manifest contains a non-finite number");
    return value;
}

bool flag(const std::vector<std::string>& row, std::size_t index, bool fallback = false) {
    return index < row.size() ? row[index] == "1" || row[index] == "true" : fallback;
}

float argument_number(const GraphInstruction& instruction, std::size_t index, float fallback = 0.0F) {
    if (index >= instruction.arguments.size()) {
        return fallback;
    }
    return std::stof(instruction.arguments[index]);
}

double argument_real(const GraphInstruction& instruction, std::size_t index, double fallback = 0.0) {
    if (index >= instruction.arguments.size()) return fallback;
    return std::stod(instruction.arguments[index]);
}

double milliseconds(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

std::uint64_t mixed_bits(std::uint64_t value) {
    value += 0x9E3779B97F4A7C15ULL;
    value = (value ^ (value >> 30U)) * 0xBF58476D1CE4E5B9ULL;
    value = (value ^ (value >> 27U)) * 0x94D049BB133111EBULL;
    return value ^ (value >> 31U);
}

double unit_random(std::uint64_t value) {
    return (static_cast<double>(mixed_bits(value) >> 11U) + 0.5) / 9007199254740992.0;
}

double normal_random(std::uint64_t first, std::uint64_t second) {
    const double u1 = std::max(1.0e-15, unit_random(first));
    const double u2 = unit_random(second);
    return std::sqrt(-2.0 * std::log(u1)) * std::cos(6.283185307179586 * u2);
}

std::shared_ptr<CookedCollisionAsset> load_cooked_collision_asset(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("Could not open cooked collision asset: " + path.string());
    std::array<char, 8> magic{};
    std::uint32_t version = 0, kind = 0, vertex_count = 0, triangle_count = 0, child_count = 0;
    std::array<float, 6> bounds{};
    stream.read(magic.data(), static_cast<std::streamsize>(magic.size()));
    stream.read(reinterpret_cast<char*>(&version), sizeof(version));
    stream.read(reinterpret_cast<char*>(&kind), sizeof(kind));
    stream.read(reinterpret_cast<char*>(&vertex_count), sizeof(vertex_count));
    stream.read(reinterpret_cast<char*>(&triangle_count), sizeof(triangle_count));
    stream.read(reinterpret_cast<char*>(&child_count), sizeof(child_count));
    stream.read(reinterpret_cast<char*>(bounds.data()), static_cast<std::streamsize>(bounds.size() * sizeof(float)));
    const std::array<char, 8> expected{'T','C','C','O','L','0','1','\0'};
    if (!stream || magic != expected || version != 1U || kind < 1U || kind > 3U ||
        vertex_count > 10000000U || triangle_count > 20000000U || child_count > 65535U)
        throw std::runtime_error("Unsupported or corrupt cooked collision asset: " + path.string());
    auto result = std::make_shared<CookedCollisionAsset>();
    result->shape = kind == 1U ? ColliderShape::convex_hull : kind == 2U ? ColliderShape::triangle_mesh : ColliderShape::compound;
    result->bounds_min = {bounds[0], bounds[1], bounds[2]};
    result->bounds_max = {bounds[3], bounds[4], bounds[5]};
    result->vertices.resize(vertex_count);
    for (auto& vertex : result->vertices) {
        std::array<float, 3> value{};
        stream.read(reinterpret_cast<char*>(value.data()), static_cast<std::streamsize>(sizeof(value)));
        vertex = {value[0], value[1], value[2]};
    }
    result->triangles.resize(triangle_count);
    for (auto& triangle : result->triangles)
        stream.read(reinterpret_cast<char*>(triangle.data()), static_cast<std::streamsize>(sizeof(triangle)));
    result->children.resize(child_count);
    for (auto& child : result->children) {
        std::uint32_t shape = 0;
        std::array<float, 12> values{};
        stream.read(reinterpret_cast<char*>(&shape), sizeof(shape));
        stream.read(reinterpret_cast<char*>(values.data()), static_cast<std::streamsize>(sizeof(values)));
        if (shape < 1U || shape > 3U) throw std::runtime_error("Cooked collision asset has an invalid compound child.");
        child.shape = shape == 1U ? ColliderShape::box : shape == 2U ? ColliderShape::sphere : ColliderShape::capsule;
        child.translation = {values[0], values[1], values[2]};
        child.rotation = {values[3], values[4], values[5], values[6]};
        child.half_extents = {values[7], values[8], values[9]};
        child.radius = values[10]; child.half_height = values[11];
    }
    if (!stream) throw std::runtime_error("Cooked collision asset is truncated: " + path.string());
    return result;
}

struct ContactManifold {
    WorldVector3 normal{};
    WorldVector3 point{};
    double penetration{0.0};
    bool hit{false};
};

double dot(const WorldVector3& first, const WorldVector3& second) {
    return first.x * second.x + first.y * second.y + first.z * second.z;
}

WorldVector3 subtract(const WorldVector3& first, const WorldVector3& second) {
    return {first.x - second.x, first.y - second.y, first.z - second.z};
}

WorldVector3 add(const WorldVector3& first, const WorldVector3& second) {
    return {first.x + second.x, first.y + second.y, first.z + second.z};
}

WorldVector3 scale(const WorldVector3& value, double amount) {
    return {value.x * amount, value.y * amount, value.z * amount};
}

double vector_length(const WorldVector3& value) { return std::sqrt(dot(value, value)); }

WorldVector3 normalize(const WorldVector3& value, WorldVector3 fallback = {0.0, 1.0, 0.0}) {
    const double length = vector_length(value);
    return length > 1.0e-12 ? scale(value, 1.0 / length) : fallback;
}

WorldVector3 rotate_local_vector(WorldVector3 value, const TcGraphVector3& rotation_degrees) {
    constexpr double radians = 3.14159265358979323846 / 180.0;
    const double x = static_cast<double>(rotation_degrees.x) * radians;
    const double y = static_cast<double>(rotation_degrees.y) * radians;
    const double z = static_cast<double>(rotation_degrees.z) * radians;
    const double cx = std::cos(x), sx = std::sin(x);
    const double cy = std::cos(y), sy = std::sin(y);
    const double cz = std::cos(z), sz = std::sin(z);
    value = {value.x, value.y * cx - value.z * sx, value.y * sx + value.z * cx};
    value = {value.x * cy + value.z * sy, value.y, -value.x * sy + value.z * cy};
    return {value.x * cz - value.y * sz, value.x * sz + value.y * cz, value.z};
}

struct Quaternion { double x{0.0}; double y{0.0}; double z{0.0}; double w{1.0}; };

Quaternion normalized_quaternion(Quaternion value) {
    const double length = std::sqrt(value.x * value.x + value.y * value.y + value.z * value.z + value.w * value.w);
    if (length <= 1.0e-12) return {};
    return {value.x / length, value.y / length, value.z / length, value.w / length};
}

Quaternion multiply_quaternion(const Quaternion& first, const Quaternion& second) {
    return {
        first.w * second.x + first.x * second.w + first.y * second.z - first.z * second.y,
        first.w * second.y - first.x * second.z + first.y * second.w + first.z * second.x,
        first.w * second.z + first.x * second.y - first.y * second.x + first.z * second.w,
        first.w * second.w - first.x * second.x - first.y * second.y - first.z * second.z,
    };
}

Quaternion conjugate_quaternion(const Quaternion& value) { return {-value.x, -value.y, -value.z, value.w}; }

WorldVector3 rotate_quaternion_vector(const WorldVector3& value, const Quaternion& orientation) {
    const WorldVector3 twice_cross{
        2.0 * (orientation.y * value.z - orientation.z * value.y),
        2.0 * (orientation.z * value.x - orientation.x * value.z),
        2.0 * (orientation.x * value.y - orientation.y * value.x),
    };
    return {
        value.x + orientation.w * twice_cross.x + orientation.y * twice_cross.z - orientation.z * twice_cross.y,
        value.y + orientation.w * twice_cross.y + orientation.z * twice_cross.x - orientation.x * twice_cross.z,
        value.z + orientation.w * twice_cross.z + orientation.x * twice_cross.y - orientation.y * twice_cross.x,
    };
}

Quaternion euler_quaternion(const TcGraphVector3& degrees) {
    constexpr double radians = 3.14159265358979323846 / 360.0;
    const double cx = std::cos(degrees.x * radians), sx = std::sin(degrees.x * radians);
    const double cy = std::cos(degrees.y * radians), sy = std::sin(degrees.y * radians);
    const double cz = std::cos(degrees.z * radians), sz = std::sin(degrees.z * radians);
    return normalized_quaternion({
        sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz, cx * cy * cz + sx * sy * sz,
    });
}

TcGraphVector3 quaternion_euler(Quaternion value) {
    value = normalized_quaternion(value);
    constexpr double degrees = 57.29577951308232;
    const double sin_x = 2.0 * (value.w * value.x + value.y * value.z);
    const double cos_x = 1.0 - 2.0 * (value.x * value.x + value.y * value.y);
    const double sin_y = std::clamp(2.0 * (value.w * value.y - value.z * value.x), -1.0, 1.0);
    const double sin_z = 2.0 * (value.w * value.z + value.x * value.y);
    const double cos_z = 1.0 - 2.0 * (value.y * value.y + value.z * value.z);
    return {static_cast<float>(std::atan2(sin_x, cos_x) * degrees),
            static_cast<float>(std::asin(sin_y) * degrees),
            static_cast<float>(std::atan2(sin_z, cos_z) * degrees)};
}

Quaternion rotation_vector_quaternion(const WorldVector3& degrees) {
    const double angle_degrees = vector_length(degrees);
    if (angle_degrees <= 1.0e-12) return {};
    constexpr double half_radians = 3.14159265358979323846 / 360.0;
    const WorldVector3 axis = scale(degrees, 1.0 / angle_degrees);
    const double half_angle = angle_degrees * half_radians;
    if (angle_degrees <= 0.5) {
        const double squared = half_angle * half_angle;
        const double sine = half_angle * (1.0 - squared / 6.0);
        return normalized_quaternion({
            axis.x * sine, axis.y * sine, axis.z * sine, 1.0 - squared * 0.5,
        });
    }
    const double sine = std::sin(half_angle);
    return {axis.x * sine, axis.y * sine, axis.z * sine, std::cos(half_angle)};
}

WorldVector3 quaternion_rotation_error(Quaternion current, Quaternion rest) {
    Quaternion error = normalized_quaternion(multiply_quaternion(current, conjugate_quaternion(rest)));
    if (error.w < 0.0) error = {-error.x, -error.y, -error.z, -error.w};
    constexpr double degrees = 57.29577951308232;
    const double sine_squared = error.x * error.x + error.y * error.y + error.z * error.z;
    if (sine_squared <= 1.0e-16) return {};
    if (error.w >= 0.9995) {
        constexpr double small_angle_scale = 2.0 * degrees;
        return {error.x * small_angle_scale, error.y * small_angle_scale, error.z * small_angle_scale};
    }
    const double sine = std::sqrt(sine_squared);
    const double angle = 2.0 * std::atan2(sine, std::clamp(error.w, -1.0, 1.0));
    const double error_scale = angle * degrees / sine;
    return {error.x * error_scale, error.y * error_scale, error.z * error_scale};
}

WorldVector3 cross(const WorldVector3& first, const WorldVector3& second) {
    return {first.y * second.z - first.z * second.y, first.z * second.x - first.x * second.z,
            first.x * second.y - first.y * second.x};
}

std::array<WorldVector3, 3> box_basis(const Transform& transform) {
    return {normalize(rotate_local_vector({1.0, 0.0, 0.0}, transform.rotation), {1.0, 0.0, 0.0}),
            normalize(rotate_local_vector({0.0, 1.0, 0.0}, transform.rotation), {0.0, 1.0, 0.0}),
            normalize(rotate_local_vector({0.0, 0.0, 1.0}, transform.rotation), {0.0, 0.0, 1.0})};
}

double projected_box_radius(const Collider& box, const std::array<WorldVector3, 3>& basis, const WorldVector3& axis) {
    return box.half_extents.x * std::fabs(dot(basis[0], axis)) +
           box.half_extents.y * std::fabs(dot(basis[1], axis)) +
           box.half_extents.z * std::fabs(dot(basis[2], axis));
}

ContactManifold box_manifold_with_basis(
    const Transform& first_transform, const Collider& first, const std::array<WorldVector3, 3>& first_basis,
    const Transform& second_transform, const Collider& second, const std::array<WorldVector3, 3>& second_basis) {
    const WorldVector3 delta = subtract(second_transform.position, first_transform.position);
    std::array<WorldVector3, 15> axes{};
    std::size_t axis_count = 0;
    for (const WorldVector3 axis : first_basis) axes[axis_count++] = axis;
    for (const WorldVector3 axis : second_basis) axes[axis_count++] = axis;
    for (const auto& first_axis : first_basis) for (const auto& second_axis : second_basis) {
        const WorldVector3 candidate = cross(first_axis, second_axis);
        const double length_squared = dot(candidate, candidate);
        if (length_squared > 1.0e-16) axes[axis_count++] = scale(candidate, 1.0 / std::sqrt(length_squared));
    }
    double minimum_overlap = std::numeric_limits<double>::max();
    WorldVector3 minimum_axis{1.0, 0.0, 0.0};
    for (std::size_t index = 0; index < axis_count; ++index) {
        const WorldVector3 axis = axes[index];
        const double overlap = projected_box_radius(first, first_basis, axis) + projected_box_radius(second, second_basis, axis) -
                               std::fabs(dot(delta, axis));
        if (overlap <= 0.0) return {};
        if (overlap < minimum_overlap) {
            minimum_overlap = overlap;
            minimum_axis = dot(delta, axis) < 0.0 ? scale(axis, -1.0) : axis;
        }
    }
    return {minimum_axis, scale(add(first_transform.position, second_transform.position), 0.5), minimum_overlap, true};
}

ContactManifold box_manifold(const Transform& first_transform, const Collider& first,
                             const Transform& second_transform, const Collider& second) {
    return box_manifold_with_basis(
        first_transform, first, box_basis(first_transform),
        second_transform, second, box_basis(second_transform));
}

ContactManifold sphere_manifold(const WorldVector3& first_position, const Collider& first,
                                const WorldVector3& second_position, const Collider& second) {
    const WorldVector3 delta = subtract(second_position, first_position);
    const double distance = vector_length(delta);
    const double radius = first.radius + second.radius;
    if (distance >= radius) return {};
    const WorldVector3 normal = normalize(delta, {1.0, 0.0, 0.0});
    return {normal, add(first_position, scale(normal, first.radius)), radius - distance, true};
}

WorldVector3 closest_point_on_box(const WorldVector3& point, const Transform& box_transform, const Collider& box) {
    const auto basis = box_basis(box_transform);
    const WorldVector3 delta = subtract(point, box_transform.position);
    WorldVector3 closest = box_transform.position;
    const double extents[3] = {box.half_extents.x, box.half_extents.y, box.half_extents.z};
    for (int axis = 0; axis < 3; ++axis)
        closest = add(closest, scale(basis[axis], std::clamp(dot(delta, basis[axis]), -extents[axis], extents[axis])));
    return closest;
}

ContactManifold sphere_box_manifold(const Transform& sphere_transform, const Collider& sphere,
                                    const Transform& box_transform, const Collider& box) {
    const WorldVector3 closest = closest_point_on_box(sphere_transform.position, box_transform, box);
    const WorldVector3 sphere_position = sphere_transform.position;
    const WorldVector3 sphere_to_box = subtract(closest, sphere_position);
    const double distance = vector_length(sphere_to_box);
    if (distance >= sphere.radius) return {};
    const WorldVector3 normal = normalize(sphere_to_box, normalize(subtract(box_transform.position, sphere_position), {1.0, 0.0, 0.0}));
    return {normal, closest, sphere.radius - distance, true};
}

std::pair<WorldVector3, WorldVector3> capsule_segment(const Transform& transform, const Collider& capsule) {
    const WorldVector3 axis = normalize(rotate_local_vector({0.0, 1.0, 0.0}, transform.rotation));
    return {subtract(transform.position, scale(axis, capsule.half_height)), add(transform.position, scale(axis, capsule.half_height))};
}

WorldVector3 closest_point_on_segment(const WorldVector3& point, const WorldVector3& start, const WorldVector3& end) {
    const WorldVector3 direction = subtract(end, start);
    const double denominator = dot(direction, direction);
    return add(start, scale(direction, denominator > 1.0e-12 ? std::clamp(dot(subtract(point, start), direction) / denominator, 0.0, 1.0) : 0.0));
}

ContactManifold sphere_capsule_manifold(const Transform& sphere_transform, const Collider& sphere,
                                        const Transform& capsule_transform, const Collider& capsule) {
    const auto [start, end] = capsule_segment(capsule_transform, capsule);
    const WorldVector3 closest = closest_point_on_segment(sphere_transform.position, start, end);
    const WorldVector3 delta = subtract(closest, sphere_transform.position);
    const double distance = vector_length(delta), radius = sphere.radius + capsule.radius;
    if (distance >= radius) return {};
    const WorldVector3 normal = normalize(delta, normalize(subtract(capsule_transform.position, sphere_transform.position), {1.0, 0.0, 0.0}));
    return {normal, add(sphere_transform.position, scale(normal, sphere.radius)), radius - distance, true};
}

ContactManifold capsule_capsule_manifold(const Transform& first_transform, const Collider& first,
                                         const Transform& second_transform, const Collider& second) {
    const auto [first_start, first_end] = capsule_segment(first_transform, first);
    const auto [second_start, second_end] = capsule_segment(second_transform, second);
    const WorldVector3 first_direction = subtract(first_end, first_start), second_direction = subtract(second_end, second_start);
    const WorldVector3 offset = subtract(first_start, second_start);
    const double a = dot(first_direction, first_direction), e = dot(second_direction, second_direction);
    const double b = dot(first_direction, second_direction), c = dot(first_direction, offset), f = dot(second_direction, offset);
    const double denominator = a * e - b * b;
    double first_t = denominator > 1.0e-12 ? std::clamp((b * f - c * e) / denominator, 0.0, 1.0) : 0.0;
    double second_t = e > 1.0e-12 ? std::clamp((b * first_t + f) / e, 0.0, 1.0) : 0.0;
    first_t = a > 1.0e-12 ? std::clamp((b * second_t - c) / a, 0.0, 1.0) : 0.0;
    const WorldVector3 first_point = add(first_start, scale(first_direction, first_t));
    const WorldVector3 second_point = add(second_start, scale(second_direction, second_t));
    const WorldVector3 delta = subtract(second_point, first_point);
    const double distance = vector_length(delta), radius = first.radius + second.radius;
    if (distance >= radius) return {};
    const WorldVector3 normal = normalize(delta, normalize(subtract(second_transform.position, first_transform.position), {1.0, 0.0, 0.0}));
    return {normal, add(first_point, scale(normal, first.radius)), radius - distance, true};
}

ContactManifold capsule_box_manifold(const Transform& capsule_transform, const Collider& capsule,
                                     const Transform& box_transform, const Collider& box) {
    const auto [start, end] = capsule_segment(capsule_transform, capsule);
    const WorldVector3 direction = subtract(end, start);
    const auto basis = box_basis(box_transform);
    const double extents[3] = {box.half_extents.x, box.half_extents.y, box.half_extents.z};
    const auto closest_on_box = [&](const WorldVector3& point) {
        const WorldVector3 delta = subtract(point, box_transform.position);
        WorldVector3 closest = box_transform.position;
        for (int axis = 0; axis < 3; ++axis) {
            closest = add(closest, scale(
                basis[axis], std::clamp(dot(delta, basis[axis]), -extents[axis], extents[axis])));
        }
        return closest;
    };
    double low = 0.0, high = 1.0;
    const auto distance_squared = [&](double value) {
        const WorldVector3 point = add(start, scale(direction, value));
        const WorldVector3 closest = closest_on_box(point);
        return dot(subtract(closest, point), subtract(closest, point));
    };
    for (int iteration = 0; iteration < 10; ++iteration) {
        const double first = (2.0 * low + high) / 3.0, second = (low + 2.0 * high) / 3.0;
        if (distance_squared(first) < distance_squared(second)) high = second; else low = first;
    }
    const WorldVector3 capsule_point = add(start, scale(direction, 0.5 * (low + high)));
    const WorldVector3 box_point = closest_on_box(capsule_point);
    const WorldVector3 delta = subtract(box_point, capsule_point);
    const double distance = vector_length(delta);
    if (distance >= capsule.radius) return {};
    const WorldVector3 normal = normalize(delta, normalize(subtract(box_transform.position, capsule_transform.position), {1.0, 0.0, 0.0}));
    return {normal, box_point, capsule.radius - distance, true};
}

WorldVector3 cooked_world_vertex(const Transform& transform, const WorldVector3& vertex) {
    const WorldVector3 scaled{vertex.x * transform.scale.x, vertex.y * transform.scale.y, vertex.z * transform.scale.z};
    return add(transform.position, rotate_local_vector(scaled, transform.rotation));
}

WorldVector3 closest_point_on_triangle(const WorldVector3& point, const WorldVector3& a,
                                       const WorldVector3& b, const WorldVector3& c) {
    const WorldVector3 ab = subtract(b, a), ac = subtract(c, a), ap = subtract(point, a);
    const double d1 = dot(ab, ap), d2 = dot(ac, ap);
    if (d1 <= 0.0 && d2 <= 0.0) return a;
    const WorldVector3 bp = subtract(point, b);
    const double d3 = dot(ab, bp), d4 = dot(ac, bp);
    if (d3 >= 0.0 && d4 <= d3) return b;
    const double vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0) return add(a, scale(ab, d1 / (d1 - d3)));
    const WorldVector3 cp = subtract(point, c);
    const double d5 = dot(ab, cp), d6 = dot(ac, cp);
    if (d6 >= 0.0 && d5 <= d6) return c;
    const double vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0) return add(a, scale(ac, d2 / (d2 - d6)));
    const double va = d3 * d6 - d5 * d4;
    if (va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0)
        return add(b, scale(subtract(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6))));
    const double inverse = 1.0 / (va + vb + vc);
    return add(a, add(scale(ab, vb * inverse), scale(ac, vc * inverse)));
}

ContactManifold sphere_cooked_manifold(const Transform& sphere_transform, const Collider& sphere,
                                       const Transform& cooked_transform, const Collider& cooked) {
    if (!cooked.cooked || cooked.cooked->triangles.empty()) return sphere_box_manifold(sphere_transform, sphere, cooked_transform, cooked);
    double best_squared = std::numeric_limits<double>::max();
    WorldVector3 best{};
    for (const auto& triangle : cooked.cooked->triangles) {
        const WorldVector3 a = cooked_world_vertex(cooked_transform, cooked.cooked->vertices[triangle[0]]);
        const WorldVector3 b = cooked_world_vertex(cooked_transform, cooked.cooked->vertices[triangle[1]]);
        const WorldVector3 c = cooked_world_vertex(cooked_transform, cooked.cooked->vertices[triangle[2]]);
        const WorldVector3 closest = closest_point_on_triangle(sphere_transform.position, a, b, c);
        const double distance_squared = dot(subtract(closest, sphere_transform.position), subtract(closest, sphere_transform.position));
        if (distance_squared < best_squared) { best_squared = distance_squared; best = closest; }
    }
    if (best_squared >= sphere.radius * sphere.radius) return {};
    const double distance = std::sqrt(std::max(0.0, best_squared));
    return {normalize(subtract(best, sphere_transform.position), {0.0, 1.0, 0.0}), best, sphere.radius - distance, true};
}

ContactManifold collider_manifold(const Transform& first_transform, const Collider& first,
                                  const Transform& second_transform, const Collider& second) {
    if (first.shape == ColliderShape::compound && first.cooked) {
        ContactManifold best{};
        for (const auto& source : first.cooked->children) {
            Transform child_transform = first_transform;
            child_transform.position = add(first_transform.position, rotate_local_vector(source.translation, first_transform.rotation));
            const Quaternion parent_rotation = euler_quaternion(first_transform.rotation);
            const Quaternion child_rotation{source.rotation[0], source.rotation[1], source.rotation[2], source.rotation[3]};
            child_transform.rotation = quaternion_euler(multiply_quaternion(parent_rotation, child_rotation));
            Collider child;
            child.shape = source.shape; child.half_extents = source.half_extents;
            child.radius = source.radius; child.half_height = source.half_height;
            const ContactManifold candidate = collider_manifold(child_transform, child, second_transform, second);
            if (candidate.hit && (!best.hit || candidate.penetration > best.penetration)) best = candidate;
        }
        return best;
    }
    if (second.shape == ColliderShape::compound && second.cooked) {
        ContactManifold result = collider_manifold(second_transform, second, first_transform, first);
        result.normal = scale(result.normal, -1.0);
        return result;
    }
    const auto cooked_shape = [](ColliderShape shape) {
        return shape == ColliderShape::convex_hull || shape == ColliderShape::triangle_mesh;
    };
    if (first.shape == ColliderShape::sphere && cooked_shape(second.shape))
        return sphere_cooked_manifold(first_transform, first, second_transform, second);
    if (cooked_shape(first.shape) && second.shape == ColliderShape::sphere) {
        ContactManifold result = sphere_cooked_manifold(second_transform, second, first_transform, first);
        result.normal = scale(result.normal, -1.0);
        return result;
    }
    if (first.shape == ColliderShape::sphere && second.shape == ColliderShape::sphere)
        return sphere_manifold(first_transform.position, first, second_transform.position, second);
    if (first.shape == ColliderShape::capsule && second.shape == ColliderShape::capsule)
        return capsule_capsule_manifold(first_transform, first, second_transform, second);
    if (first.shape == ColliderShape::sphere && second.shape == ColliderShape::capsule)
        return sphere_capsule_manifold(first_transform, first, second_transform, second);
    if (first.shape == ColliderShape::capsule && second.shape == ColliderShape::sphere) {
        ContactManifold result = sphere_capsule_manifold(second_transform, second, first_transform, first);
        result.normal = scale(result.normal, -1.0);
        return result;
    }
    if (first.shape == ColliderShape::capsule && second.shape == ColliderShape::box)
        return capsule_box_manifold(first_transform, first, second_transform, second);
    if (first.shape == ColliderShape::box && second.shape == ColliderShape::capsule) {
        ContactManifold result = capsule_box_manifold(second_transform, second, first_transform, first);
        result.normal = scale(result.normal, -1.0);
        return result;
    }
    if (first.shape == ColliderShape::sphere && second.shape == ColliderShape::box)
        return sphere_box_manifold(first_transform, first, second_transform, second);
    if (first.shape == ColliderShape::box && second.shape == ColliderShape::sphere) {
        ContactManifold result = sphere_box_manifold(second_transform, second, first_transform, first);
        result.normal = scale(result.normal, -1.0);
        return result;
    }
    return box_manifold(first_transform, first, second_transform, second);
}

WorldVector3 collider_world_half_extents(const Transform& transform, const Collider& collider) {
    if (collider.shape == ColliderShape::sphere) return {collider.radius, collider.radius, collider.radius};
    if (collider.shape == ColliderShape::capsule) {
        const WorldVector3 axis = normalize(rotate_local_vector({0.0, 1.0, 0.0}, transform.rotation));
        return {collider.radius + std::fabs(axis.x) * collider.half_height,
                collider.radius + std::fabs(axis.y) * collider.half_height,
                collider.radius + std::fabs(axis.z) * collider.half_height};
    }
    const auto basis = box_basis(transform);
    return {projected_box_radius(collider, basis, {1.0, 0.0, 0.0}),
            projected_box_radius(collider, basis, {0.0, 1.0, 0.0}),
            projected_box_radius(collider, basis, {0.0, 0.0, 1.0})};
}

PhysicsJointType physics_joint_type(const std::string& value) {
    if (value == "ball") return PhysicsJointType::ball;
    if (value == "hinge") return PhysicsJointType::hinge;
    if (value == "slider") return PhysicsJointType::slider;
    if (value == "distance") return PhysicsJointType::distance;
    if (value == "spring") return PhysicsJointType::spring;
    if (value == "cone_twist") return PhysicsJointType::cone_twist;
    if (value == "six_dof") return PhysicsJointType::six_dof;
    return PhysicsJointType::fixed;
}

}  // namespace

EntityId World::create_entity(std::string stable_name) {
    if (stable_name.empty()) {
        stable_name = "Entity" + std::to_string(next_entity_);
    }
    if (const auto found = ids_by_name_.find(stable_name); found != ids_by_name_.end()) {
        return found->second;
    }
    const EntityId entity = next_entity_++;
    entities_.push_back(entity);
    names_[entity] = stable_name;
    ids_by_name_[stable_name] = entity;
    transforms.emplace(entity, Transform{});
    return entity;
}

bool World::destroy_entity(EntityId entity) {
    const auto found = names_.find(entity);
    if (found == names_.end()) {
        return false;
    }
    ids_by_name_.erase(found->second);
    names_.erase(found);
    std::erase(entities_, entity);
    transforms.erase(entity);
    renderables.erase(entity);
    rigid_bodies.erase(entity);
    colliders.erase(entity);
    particles.erase(entity);
    cameras.erase(entity);
    lights.erase(entity);
    reflection_probes.erase(entity);
    std::erase_if(physics_joints, [entity](const auto& item) {
        return item.second.first == entity || item.second.second == entity;
    });
    return true;
}

EntityId World::find_entity(const std::string& stable_name) const {
    const auto found = ids_by_name_.find(stable_name);
    return found == ids_by_name_.end() ? 0U : found->second;
}

const std::vector<EntityId>& World::entities() const noexcept { return entities_; }

const std::string& World::name(EntityId entity) const {
    static const std::string empty;
    const auto found = names_.find(entity);
    return found == names_.end() ? empty : found->second;
}

std::string stable_asset_id(const std::string& type, const std::string& canonical_path) {
    std::uint64_t hash = 1469598103934665603ULL;
    std::string normalized_type = type;
    std::transform(normalized_type.begin(), normalized_type.end(), normalized_type.begin(),
                   [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
    std::string normalized_path = canonical_path;
    std::replace(normalized_path.begin(), normalized_path.end(), '\\', '/');
    if (normalized_path.size() > 1 && normalized_path[1] == ':') {
        std::transform(normalized_path.begin(), normalized_path.end(), normalized_path.begin(),
                       [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
    }
    const std::string key = normalized_type + '\0' + normalized_path;
    for (const unsigned char byte : key) {
        hash ^= byte;
        hash *= 1099511628211ULL;
    }
    std::ostringstream stream;
    stream << "tc.asset." << std::hex << std::setfill('0') << std::setw(16) << hash;
    return stream.str();
}

bool Runtime::load_manifest(const std::filesystem::path& path, std::string& error) {
    try {
        std::ifstream stream(path, std::ios::binary);
        if (!stream) {
            error = "Could not open runtime manifest: " + path.string();
            return false;
        }
        world_ = World{};
        active_animation_id_.clear();animation_time_seconds_=0.0;animation_playback_speed_=1.0;animation_playing_=true;
        std::string line;
        if (!std::getline(stream, line)) {
            error = "TC runtime manifest is empty";
            return false;
        }
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line != "TCRUNTIME\t1") {
            error = "Unsupported or invalid TC runtime manifest";
            return false;
        }
        std::size_t line_number = 1;
        while (std::getline(stream, line)) {
            ++line_number;
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty() || line[0] == '#') {
                continue;
            }
            const auto row = fields(line);
            if (row.empty()) {
                continue;
            }
            const std::string& type = row[0];
            if (type == "ASSET" && row.size() >= 5) {
                std::filesystem::path source=decode(row[3]);if(source.is_relative())source=path.parent_path()/source;
                world_.assets[row[1]] = AssetRecord{row[1], row[2],std::move(source), row[4]};
            } else if (type == "ENTITY" && row.size() >= 2) {
                world_.create_entity(decode(row[1]));
            } else if (type == "TRANSFORM" && row.size() >= 11) {
                const auto id = world_.create_entity(decode(row[1]));
                world_.transforms[id] = Transform{
                    {real_number(row, 2), real_number(row, 3), real_number(row, 4)},
                    {number(row, 5), number(row, 6), number(row, 7)},
                    {number(row, 8, 1.0F), number(row, 9, 1.0F), number(row, 10, 1.0F)},
                };
            } else if (type == "RENDER" && row.size() >= 10) {
                const auto id = world_.create_entity(decode(row[1]));
                world_.renderables[id] = Renderable{
                    row[2], row[3], "", "", "", "", "", "",
                    {number(row, 4), number(row, 5), number(row, 6)},
                    number(row, 7), number(row, 8, 0.45F), flag(row, 9, true),
                };
                if (row.size() >= 15) {
                    auto& renderable = world_.renderables[id];
                    renderable.base_color_texture = row[10];
                    renderable.normal_texture = row[11];
                    renderable.roughness_texture = row[12];
                    renderable.metallic_texture = row[13];
                    renderable.emission_texture = row[14];
                }
                if(row.size()>=16)world_.renderables[id].skin_binding=decode(row[15]);
            } else if (type == "RIGID" && row.size() >= 8) {
                const auto id = world_.create_entity(decode(row[1]));
                RigidBody body;
                body.velocity = {real_number(row, 2), real_number(row, 3), real_number(row, 4)};
                body.mass = real_number(row, 5, 1.0);
                body.restitution = number(row, 6, 0.2F);
                body.dynamic = flag(row, 7, true);
                world_.rigid_bodies[id] = body;
                if (row.size() >= 16) {
                    auto& extended_body = world_.rigid_bodies[id];
                    extended_body.angular_velocity = {real_number(row, 8), real_number(row, 9), real_number(row, 10)};
                    extended_body.linear_damping = number(row, 11, 0.01F);
                    extended_body.angular_damping = number(row, 12, 0.05F);
                    extended_body.gravity_scale = number(row, 13, 1.0F);
                    extended_body.kinematic = flag(row, 14);
                    extended_body.continuous_collision = flag(row, 15);
                }
                if (row.size() >= 21) {
                    auto& extended_body = world_.rigid_bodies[id];
                    extended_body.inertia_diagonal = {
                        std::max(1.0e-9, real_number(row, 16, 1.0)),
                        std::max(1.0e-9, real_number(row, 17, 1.0)),
                        std::max(1.0e-9, real_number(row, 18, 1.0)),
                    };
                    extended_body.allow_sleep = flag(row, 19, true);
                    extended_body.sleeping = flag(row, 20);
                }
            } else if (type == "COLLIDER" && row.size() >= 6) {
                const auto id = world_.create_entity(decode(row[1]));
                world_.colliders[id] = Collider{
                    {real_number(row, 2, 0.5), real_number(row, 3, 0.5), real_number(row, 4, 0.5)}, flag(row, 5),
                };
                if (row.size() >= 13) {
                    auto& collider = world_.colliders[id];
                    const auto shape = decode(row[6]);
                    collider.shape = shape == "sphere" ? ColliderShape::sphere : shape == "capsule" ? ColliderShape::capsule :
                        shape == "convex_hull" ? ColliderShape::convex_hull : shape == "triangle_mesh" ? ColliderShape::triangle_mesh :
                        shape == "compound" ? ColliderShape::compound : ColliderShape::box;
                    collider.radius = std::max(0.0, real_number(row, 7, 0.5));
                    collider.half_height = std::max(0.0, real_number(row, 8, 0.5));
                    collider.layer = static_cast<std::uint32_t>(std::stoull(row[9]));
                    collider.mask = static_cast<std::uint32_t>(std::stoull(row[10]));
                    collider.friction = std::clamp(number(row, 11, 0.5F), 0.0F, 1.0F);
                    collider.restitution = std::clamp(number(row, 12, 0.2F), 0.0F, 1.0F);
                    if (collider.shape == ColliderShape::sphere) collider.half_extents = {collider.radius, collider.radius, collider.radius};
                    if (collider.shape == ColliderShape::capsule) collider.half_extents = {collider.radius, collider.radius + collider.half_height, collider.radius};
                    if (row.size() >= 14 && !row[13].empty()) {
                        collider.collision_asset = row[13];
                        const auto asset = world_.assets.find(collider.collision_asset);
                        if (asset == world_.assets.end()) {
                            std::string available;
                            for (const auto& [asset_id, unused] : world_.assets) {
                                static_cast<void>(unused);
                                available += (available.empty() ? "" : ", ") + asset_id;
                            }
                            throw std::runtime_error("collider references an unknown collision asset: " + collider.collision_asset + "; available: " + available);
                        }
                        if (asset->second.type != "collision")
                            throw std::runtime_error("collider asset is not collision data: " + collider.collision_asset + " (" + asset->second.type + ")");
                        collider.cooked = load_cooked_collision_asset(asset->second.source);
                        collider.shape = collider.cooked->shape;
                        collider.half_extents = {
                            (collider.cooked->bounds_max.x - collider.cooked->bounds_min.x) * 0.5,
                            (collider.cooked->bounds_max.y - collider.cooked->bounds_min.y) * 0.5,
                            (collider.cooked->bounds_max.z - collider.cooked->bounds_min.z) * 0.5,
                        };
                    }
                }
            } else if (type == "PHYSICSJOINT" && row.size() >= 26) {
                PhysicsJoint joint;
                joint.id = decode(row[1]);
                joint.type = physics_joint_type(row[2]);
                joint.first = world_.find_entity(decode(row[3]));
                joint.second = world_.find_entity(decode(row[4]));
                if (joint.id.empty() || joint.first == 0U || joint.second == 0U || joint.first == joint.second)
                    throw std::runtime_error("physics joint references invalid entities: " + joint.id);
                joint.first_anchor = {real_number(row, 5), real_number(row, 6), real_number(row, 7)};
                joint.second_anchor = {real_number(row, 8), real_number(row, 9), real_number(row, 10)};
                joint.axis = normalize({real_number(row, 11, 1.0), real_number(row, 12), real_number(row, 13)}, {1.0, 0.0, 0.0});
                joint.minimum_limit = real_number(row, 14);
                joint.maximum_limit = real_number(row, 15);
                joint.stiffness = std::clamp(real_number(row, 16, 1.0), 0.0, 1.0);
                joint.damping = std::max(0.0, real_number(row, 17, 0.1));
                joint.motor_target_velocity = real_number(row, 18);
                joint.motor_maximum_force = std::max(0.0, real_number(row, 19));
                joint.break_force = std::max(0.0, real_number(row, 20));
                joint.break_torque = std::max(0.0, real_number(row, 21));
                joint.limits_enabled = flag(row, 22);
                joint.motor_enabled = flag(row, 23);
                joint.collision_enabled = flag(row, 24);
                joint.enabled = flag(row, 25, true);
                const auto& first_transform = world_.transforms.at(joint.first);
                const auto& second_transform = world_.transforms.at(joint.second);
                joint.rest_distance = vector_length(subtract(
                    add(second_transform.position, rotate_local_vector(joint.second_anchor, second_transform.rotation)),
                    add(first_transform.position, rotate_local_vector(joint.first_anchor, first_transform.rotation))));
                joint.rest_rotation = {
                    static_cast<double>(second_transform.rotation.x - first_transform.rotation.x),
                    static_cast<double>(second_transform.rotation.y - first_transform.rotation.y),
                    static_cast<double>(second_transform.rotation.z - first_transform.rotation.z),
                };
                const Quaternion first_orientation = euler_quaternion(first_transform.rotation);
                const Quaternion second_orientation = euler_quaternion(second_transform.rotation);
                const Quaternion rest_orientation = normalized_quaternion(
                    multiply_quaternion(conjugate_quaternion(first_orientation), second_orientation));
                joint.rest_orientation = {rest_orientation.x, rest_orientation.y, rest_orientation.z, rest_orientation.w};
                if (world_.physics_joints.contains(joint.id)) throw std::runtime_error("duplicate physics joint: " + joint.id);
                world_.physics_joints[joint.id] = std::move(joint);
            } else if (type == "JOINT6DOF" && row.size() >= 38) {
                const std::string joint_id = decode(row[1]);
                auto found = world_.physics_joints.find(joint_id);
                if (found == world_.physics_joints.end() || found->second.type != PhysicsJointType::six_dof)
                    throw std::runtime_error("six-DOF settings reference an unknown six-DOF joint: " + joint_id);
                const auto vector_at = [&row](std::size_t index) {
                    return WorldVector3{real_number(row, index), real_number(row, index + 1), real_number(row, index + 2)};
                };
                auto& joint = found->second;
                joint.linear_lower_limit = vector_at(2); joint.linear_upper_limit = vector_at(5);
                joint.angular_lower_limit = vector_at(8); joint.angular_upper_limit = vector_at(11);
                joint.linear_spring_stiffness = vector_at(14); joint.linear_spring_damping = vector_at(17);
                joint.angular_spring_stiffness = vector_at(20); joint.angular_spring_damping = vector_at(23);
                joint.linear_drive_velocity = vector_at(26); joint.angular_drive_velocity = vector_at(29);
                joint.linear_drive_maximum_force = vector_at(32); joint.angular_drive_maximum_force = vector_at(35);
                joint.extended_six_dof = true;
            } else if (type == "PARTICLE" && row.size() >= 10) {
                const auto id = world_.create_entity(decode(row[1]));
                world_.particles[id] = ParticlePhysics{
                    real_number(row, 2, 1.0e-9), real_number(row, 3), real_number(row, 4),
                    real_number(row, 5, 1.0e-9), real_number(row, 6, 1000.0),
                    real_number(row, 7, 0.001), real_number(row, 8, 2000.0), flag(row, 9, true),
                };
            } else if (type == "CAMERA" && row.size() >= 6) {
                const auto id = world_.create_entity(decode(row[1]));
                world_.cameras[id] = Camera{number(row, 2, 55.0F), number(row, 3, 0.05F), number(row, 4, 5000.0F), flag(row, 5, true)};
                if (row.size() >= 9) world_.cameras[id].look_at = {real_number(row, 6), real_number(row, 7, 1.0), real_number(row, 8)};
            } else if (type == "LIGHT" && row.size() >= 10) {
                const auto id = world_.create_entity(decode(row[1]));
                world_.lights[id] = DirectionalLight{
                    {number(row, 2), number(row, 3), number(row, 4)},
                    {number(row, 5, 1.0F), number(row, 6, 1.0F), number(row, 7, 1.0F)},
                    number(row, 8, 4.0F), flag(row, 9, true), number(row, 10, 0.266F),
                };
            } else if (type == "PROBE" && row.size() >= 8) {
                const auto id = world_.create_entity(decode(row[1]));
                world_.reflection_probes[id] = ReflectionProbe{
                    row[2],
                    {number(row, 3, 5.0F), number(row, 4, 5.0F), number(row, 5, 5.0F)},
                    number(row, 6, 1.0F), static_cast<int>(number(row, 7)),
                };
            } else if (type == "HUD" && row.size() >= 2) {
                world_.hud_text = decode(row[1]);
            } else if (type == "SAVE" && row.size() >= 2) {
                world_.save_slot = decode(row[1]);
            } else if (type == "RENDERSETTINGS" && row.size() >= 6) {
                world_.render_settings = RenderSettings{
                    decode(row[1]), decode(row[2]), number(row, 3, 1.0F), number(row, 4, 1.0F), number(row, 5, 0.2F),
                    row.size() > 6 ? row[6] : "", number(row, 7, 1.0F), flag(row, 8),
                    number(row, 9, 0.5F), number(row, 10, 1.0F), number(row, 11, 16.6667F),
                    row.size() > 12 ? decode(row[12]) : "physically_based",
                    row.size() > 13 ? decode(row[13]) : "probe",
                    {number(row, 14, 0.08F), number(row, 15, 0.18F), number(row, 16, 0.42F)},
                    {number(row, 17, 0.025F), number(row, 18, 0.035F), number(row, 19, 0.045F)},
                    number(row, 20, 1.0F), number(row, 21, 4.0F), number(row, 22, 0.15F),
                    flag(row, 23), number(row, 24, 0.35F), number(row, 25, 12.0F),
                    static_cast<int>(number(row, 26, 8.0F)),
                    flag(row, 27, true), number(row, 28, 1.0F), number(row, 29, 1.0F),
                    number(row, 30, 4.0F),
                };
            } else if (type == "SIMULATION" && row.size() >= 12) {
                world_.simulation_settings = SimulationSettings{
                    decode(row[1]), real_number(row, 2, 1.0), real_number(row, 3, 1.0),
                    {real_number(row, 4), real_number(row, 5, -9.80665), real_number(row, 6)},
                    real_number(row, 7, 1.0 / 120.0), static_cast<int>(real_number(row, 8, 8.0)),
                    real_number(row, 9, 10000.0), real_number(row, 10, 1.0), flag(row, 11, true),
                    real_number(row, 12, 293.15), real_number(row, 13, 0.001),
                    real_number(row, 14, 1.0), static_cast<std::uint64_t>(real_number(row, 15, 1.0)),
                    real_number(row, 16, 0.6),
                };
                if (row.size() >= 18) world_.simulation_settings.joint_solver_iterations =
                    std::clamp(static_cast<int>(real_number(row, 17, 12.0)), 1, 64);
                if (row.size() >= 21) {
                    world_.simulation_settings.sleep_linear_threshold = std::max(0.0, real_number(row, 18, 0.05));
                    world_.simulation_settings.sleep_angular_threshold = std::max(0.0, real_number(row, 19, 0.05));
                    world_.simulation_settings.sleep_delay_seconds = std::max(0.0, real_number(row, 20, 0.5));
                }
                if (row.size() >= 23) {
                    world_.simulation_settings.contact_solver_iterations =
                        std::clamp(static_cast<int>(real_number(row, 21, 4.0)), 1, 16);
                    world_.simulation_settings.shock_propagation_factor =
                        std::clamp(real_number(row, 22, 0.35), 0.0, 1.0);
                }
            } else if (type == "GRAPH" && row.size() >= 7) {
                GraphInstruction instruction;
                instruction.node_id = decode(row[2]);
                instruction.operation = row[3];
                instruction.source_file = decode(row[4]);
                instruction.source_line = std::stoi(row[5]);
                for (std::size_t index = 6; index < row.size(); ++index) {
                    instruction.arguments.push_back(decode(row[index]));
                }
                (row[1] == "begin" ? world_.begin_play : world_.tick).push_back(std::move(instruction));
            } else if(type=="SKELETON"&&row.size()>=3){Skeleton skeleton;skeleton.id=decode(row[1]);skeleton.declared_joint_count=static_cast<std::size_t>(std::stoull(row[2]));world_.skeletons[skeleton.id]=std::move(skeleton);
            } else if(type=="JOINT"&&row.size()>=21){const std::string skeleton_id=decode(row[1]);auto found=world_.skeletons.find(skeleton_id);if(found==world_.skeletons.end())throw std::runtime_error("joint references unknown skeleton: "+skeleton_id);SkeletonJoint joint;joint.id=decode(row[2]);const std::string parent_id=decode(row[3]);joint.name=decode(row[4]);for(std::size_t index=0;index<16;++index)joint.rest_local[index]=real_number(row,5+index);joint.local=joint.rest_local;joint.world=joint.rest_local;if(!parent_id.empty()){const auto parent=found->second.joint_indices.find(parent_id);if(parent==found->second.joint_indices.end())throw std::runtime_error("joint parent must precede child: "+parent_id);joint.parent_index=static_cast<int>(parent->second);}found->second.joint_indices[joint.id]=found->second.joints.size();found->second.joints.push_back(std::move(joint));
            } else if(type=="ANIMATION"&&row.size()>=8){AnimationClip clip;clip.id=decode(row[1]);clip.name=decode(row[2]);clip.skeleton_id=decode(row[3]);clip.start_frame=real_number(row,4,1.0);clip.end_frame=real_number(row,5,clip.start_frame);clip.frame_rate=real_number(row,6,24.0);clip.looping=flag(row,7,true);if(!world_.skeletons.contains(clip.skeleton_id))throw std::runtime_error("animation references unknown skeleton: "+clip.skeleton_id);if(active_animation_id_.empty())active_animation_id_=clip.id;world_.animation_clips[clip.id]=std::move(clip);
            } else if(type=="ANIMCURVE"&&row.size()>=10){const std::string clip_id=decode(row[1]);auto found=world_.animation_clips.find(clip_id);if(found==world_.animation_clips.end())throw std::runtime_error("curve references unknown animation: "+clip_id);AnimationCurve curve;curve.joint_id=decode(row[2]);curve.attribute=decode(row[3]);curve.layer_weight=real_number(row,4,1.0);curve.additive=flag(row,5);const std::size_t count=static_cast<std::size_t>(std::stoull(row[6]));if(count>1000000U||row.size()<7+count*3)throw std::runtime_error("invalid animation key count");for(std::size_t index=0;index<count;++index)curve.keys.push_back({real_number(row,7+index*3),real_number(row,8+index*3),decode(row[9+index*3])});found->second.curves.push_back(std::move(curve));
            } else if(type=="SKIN"&&row.size()>=13){SkinBinding skin;skin.id=decode(row[1]);skin.mesh_id=decode(row[2]);skin.skeleton_id=decode(row[3]);skin.deformation_mode=decode(row[4]);skin.vertex_count=static_cast<std::size_t>(std::stoull(row[5]));skin.maximum_influences=static_cast<std::size_t>(std::stoull(row[6]));const std::size_t joint_count=static_cast<std::size_t>(std::stoull(row[7]));if(joint_count==0||joint_count>65535U||row.size()<8+joint_count+5)throw std::runtime_error("invalid skin joint map: "+skin.id);for(std::size_t index=0;index<joint_count;++index)skin.joint_ids.push_back(decode(row[8+index]));const std::size_t asset_start=8+joint_count;skin.inverse_bind_asset=row[asset_start];skin.rest_positions_asset=row[asset_start+1];skin.influence_offsets_asset=row[asset_start+2];skin.joint_indices_asset=row[asset_start+3];skin.weights_asset=row[asset_start+4];if(skin.vertex_count==0||skin.maximum_influences>32U)throw std::runtime_error("invalid skin binding dimensions: "+skin.id);world_.skin_bindings[skin.id]=std::move(skin);
            } else if(type=="PHYSANIM"&&row.size()>=9){PhysicalAnimationBinding binding;binding.skeleton_id=decode(row[1]);binding.joint_id=decode(row[2]);binding.body=world_.find_entity(decode(row[3]));binding.pose_drive_strength=std::clamp(real_number(row,4,0.8),0.0,1.0);binding.damping=std::max(0.0,real_number(row,5,0.5));binding.maximum_force=std::max(0.0,real_number(row,6,10000.0));binding.physics_blend=std::clamp(real_number(row,7,1.0),0.0,1.0);binding.muscle_strength=std::clamp(real_number(row,8,1.0),0.0,1.0);if(binding.body==0U||!world_.rigid_bodies.contains(binding.body))throw std::runtime_error("physical animation references invalid rigid body");const auto skeleton=world_.skeletons.find(binding.skeleton_id);if(skeleton==world_.skeletons.end()||!skeleton->second.joint_indices.contains(binding.joint_id))throw std::runtime_error("physical animation references invalid skeleton joint: "+binding.joint_id);world_.physical_animation_bindings.push_back(std::move(binding));
            } else {
                error = "Invalid runtime record at line " + std::to_string(line_number) + ": " + type;
                return false;
            }
        }
        for(const auto& [id,skeleton]:world_.skeletons)if(skeleton.joints.size()!=skeleton.declared_joint_count)throw std::runtime_error("skeleton joint count mismatch: "+id);
        for(const auto& [id,skin]:world_.skin_bindings){const auto skeleton=world_.skeletons.find(skin.skeleton_id);if(skeleton==world_.skeletons.end())throw std::runtime_error("skin references unknown skeleton: "+id);for(const auto& joint_id:skin.joint_ids)if(!skeleton->second.joint_indices.contains(joint_id))throw std::runtime_error("skin references unknown joint: "+joint_id);for(const auto* asset:{&skin.inverse_bind_asset,&skin.rest_positions_asset,&skin.influence_offsets_asset,&skin.joint_indices_asset,&skin.weights_asset})if(!world_.assets.contains(*asset))throw std::runtime_error("skin references unknown asset: "+*asset);}
        error.clear();
        return true;
    } catch (const std::exception& exception) {
        error = exception.what();
        return false;
    }
}

void Runtime::begin_play() { animation_time_seconds_=0.0;evaluate_animation(0.0);execute(world_.begin_play, 0.0F); }

void Runtime::set_input_axis(float x, float y) noexcept {
    input_axis_.x = std::clamp(x, -1.0F, 1.0F);
    input_axis_.y = std::clamp(y, -1.0F, 1.0F);
}

void Runtime::tick(float delta_seconds) {
    const auto frame_start = Clock::now();
    const auto graph_start = Clock::now();
    execute(world_.tick, delta_seconds);
    evaluate_animation(delta_seconds);
    apply_physical_animation_drives(delta_seconds);
    const auto graph_end = Clock::now();
    simulate(static_cast<double>(delta_seconds) * std::max(0.0, world_.simulation_settings.time_scale));
    blend_physical_animation_pose();
    const auto physics_end = Clock::now();
    profile_.frame_ms = milliseconds(frame_start, physics_end);
    profile_.graph_ms = milliseconds(graph_start, graph_end);
    profile_.physics_ms = milliseconds(graph_end, physics_end);
    profile_.physics_integration_ms = std::max(
        0.0, profile_.physics_ms - profile_.physics_joint_ms - profile_.physics_collision_ms);
    profile_.maximum_joint_position_error = 0.0;
    for (const auto& diagnostic : physics_joint_diagnostics_) {
        profile_.maximum_joint_position_error = std::max(
            profile_.maximum_joint_position_error, diagnostic.position_error);
    }
    profile_.entities = world_.entities().size();
    profile_.draw_calls = world_.renderables.size();
    profile_.broadphase_pairs = broadphase_pairs_;
    profile_.collision_contacts = collision_contacts_;
    profile_.solver_islands = solver_islands_;
    profile_.sleeping_bodies = static_cast<std::size_t>(std::count_if(
        world_.rigid_bodies.begin(), world_.rigid_bodies.end(),
        [](const auto& item) { return item.second.sleeping; }));
}

void Runtime::evaluate_animation(double delta_seconds){
    if(active_animation_id_.empty())return;const auto clip_found=world_.animation_clips.find(active_animation_id_);if(clip_found==world_.animation_clips.end())return;const auto& clip=clip_found->second;auto skeleton_found=world_.skeletons.find(clip.skeleton_id);if(skeleton_found==world_.skeletons.end())return;auto& skeleton=skeleton_found->second;
    if(animation_playing_)animation_time_seconds_+=delta_seconds*animation_playback_speed_;const double duration_frames=std::max(0.0,clip.end_frame-clip.start_frame);double frame=clip.start_frame+animation_time_seconds_*std::max(1.0e-6,clip.frame_rate);if(clip.looping&&duration_frames>0.0){double wrapped=std::fmod(frame-clip.start_frame,duration_frames);if(wrapped<0.0)wrapped+=duration_frames;frame=clip.start_frame+wrapped;}else frame=std::clamp(frame,clip.start_frame,clip.end_frame);
    struct Channels{bool initialized[9]{};double values[9]{};};std::unordered_map<std::string,Channels> channels;
    auto channel_index=[](const std::string& attribute){const auto key=normalized_attribute(attribute);if(key=="translatex"||key=="tx")return 0;if(key=="translatey"||key=="ty")return 1;if(key=="translatez"||key=="tz")return 2;if(key=="rotatex"||key=="rotationx"||key=="rx")return 3;if(key=="rotatey"||key=="rotationy"||key=="ry")return 4;if(key=="rotatez"||key=="rotationz"||key=="rz")return 5;if(key=="scalex"||key=="sx")return 6;if(key=="scaley"||key=="sy")return 7;if(key=="scalez"||key=="sz")return 8;return -1;};
    for(const auto& curve:clip.curves){const int index=channel_index(curve.attribute);if(index<0||!skeleton.joint_indices.contains(curve.joint_id))continue;const double sample=sample_animation_curve(curve,frame);auto& target=channels[curve.joint_id];if(!target.initialized[index]){target.values[index]=sample;target.initialized[index]=true;}else if(curve.additive)target.values[index]+=sample*curve.layer_weight;else target.values[index]=target.values[index]*(1.0-curve.layer_weight)+sample*curve.layer_weight;}
    for(auto& joint:skeleton.joints){joint.local=joint.rest_local;const auto values=channels.find(joint.id);if(values!=channels.end()){const auto& channel=values->second;if(channel.initialized[0])joint.local[12]=channel.values[0];if(channel.initialized[1])joint.local[13]=channel.values[1];if(channel.initialized[2])joint.local[14]=channel.values[2];if(channel.initialized[3]||channel.initialized[4]||channel.initialized[5]){Matrix4 rest=joint.rest_local;rest[12]=rest[13]=rest[14]=0.0;const auto rotation=rotation_matrix(channel.initialized[3]?channel.values[3]:0.0,channel.initialized[4]?channel.values[4]:0.0,channel.initialized[5]?channel.values[5]:0.0);const double tx=joint.local[12],ty=joint.local[13],tz=joint.local[14];joint.local=multiply_matrix(rotation,rest);joint.local[12]=tx;joint.local[13]=ty;joint.local[14]=tz;}for(int axis=0;axis<3;++axis)if(channel.initialized[6+axis]){const double length=std::sqrt(joint.local[axis*4]*joint.local[axis*4]+joint.local[axis*4+1]*joint.local[axis*4+1]+joint.local[axis*4+2]*joint.local[axis*4+2]);const double factor=channel.values[6+axis]/std::max(1.0e-12,length);joint.local[axis*4]*=factor;joint.local[axis*4+1]*=factor;joint.local[axis*4+2]*=factor;}}
        joint.world=joint.parent_index>=0?multiply_matrix(joint.local,skeleton.joints[static_cast<std::size_t>(joint.parent_index)].world):joint.local;
    }
}

void Runtime::apply_physical_animation_drives(double step_seconds) {
    if (step_seconds <= 0.0) return;
    constexpr double radians_per_degree = 0.017453292519943295;
    for (const auto& binding : world_.physical_animation_bindings) {
        auto skeleton = world_.skeletons.find(binding.skeleton_id);
        auto body = world_.rigid_bodies.find(binding.body);
        auto transform = world_.transforms.find(binding.body);
        if (skeleton == world_.skeletons.end() || body == world_.rigid_bodies.end() ||
            transform == world_.transforms.end() || !body->second.dynamic || body->second.kinematic) continue;
        const auto joint_index = skeleton->second.joint_indices.find(binding.joint_id);
        if (joint_index == skeleton->second.joint_indices.end()) continue;
        const Matrix4& target = skeleton->second.joints[joint_index->second].world;
        const WorldVector3 target_position{target[12], target[13], target[14]};
        const WorldVector3 position_error = subtract(target_position, transform->second.position);
        const double strength = binding.pose_drive_strength * binding.muscle_strength;
        const double spring = 120.0 * strength;
        WorldVector3 force = subtract(scale(position_error, spring), scale(body->second.velocity, binding.damping * 12.0));
        const double force_length = vector_length(force);
        if (force_length > binding.maximum_force && force_length > 1.0e-12)
            force = scale(force, binding.maximum_force / force_length);
        body->second.velocity = add(body->second.velocity, scale(force, step_seconds / std::max(1.0e-9, body->second.mass)));

        const double target_y = std::asin(std::clamp(-target[2], -1.0, 1.0));
        const double target_x = std::atan2(target[6], target[10]);
        const double target_z = std::atan2(target[1], target[0]);
        const WorldVector3 rotation_error{
            target_x - transform->second.rotation.x * radians_per_degree,
            target_y - transform->second.rotation.y * radians_per_degree,
            target_z - transform->second.rotation.z * radians_per_degree,
        };
        WorldVector3 torque = subtract(scale(rotation_error, spring * 0.5), scale(body->second.angular_velocity, binding.damping * 8.0));
        const double torque_length = vector_length(torque);
        if (torque_length > binding.maximum_force && torque_length > 1.0e-12)
            torque = scale(torque, binding.maximum_force / torque_length);
        body->second.angular_velocity = add(body->second.angular_velocity, {
            torque.x * step_seconds / std::max(1.0e-9, body->second.inertia_diagonal.x),
            torque.y * step_seconds / std::max(1.0e-9, body->second.inertia_diagonal.y),
            torque.z * step_seconds / std::max(1.0e-9, body->second.inertia_diagonal.z),
        });
        body->second.sleeping = false;
    }
}

void Runtime::blend_physical_animation_pose() {
    for (const auto& binding : world_.physical_animation_bindings) {
        auto skeleton = world_.skeletons.find(binding.skeleton_id);
        const auto transform = world_.transforms.find(binding.body);
        if (skeleton == world_.skeletons.end() || transform == world_.transforms.end()) continue;
        const auto joint_index = skeleton->second.joint_indices.find(binding.joint_id);
        if (joint_index == skeleton->second.joint_indices.end()) continue;
        Matrix4& pose = skeleton->second.joints[joint_index->second].world;
        const double blend = binding.physics_blend * binding.muscle_strength;
        const Matrix4 body_rotation = rotation_matrix(
            transform->second.rotation.x, transform->second.rotation.y, transform->second.rotation.z);
        for (std::size_t index = 0; index < 12; ++index)
            pose[index] = pose[index] * (1.0 - blend) + body_rotation[index] * blend;
        pose[12] = pose[12] * (1.0 - blend) + transform->second.position.x * blend;
        pose[13] = pose[13] * (1.0 - blend) + transform->second.position.y * blend;
        pose[14] = pose[14] * (1.0 - blend) + transform->second.position.z * blend;
    }
}

void Runtime::execute(const std::vector<GraphInstruction>& instructions, float delta_seconds) {
    const auto graph_value_key = [](const GraphInstruction& instruction, const std::string& output) {
        return "@graph:" + instruction.node_id + ":" + output;
    };
    const auto resolve_entity = [this](const std::string& target) {
        if (target != "Self") return world_.find_entity(target);
        for (const auto entity : world_.entities()) {
            const auto body = world_.rigid_bodies.find(entity);
            if (body != world_.rigid_bodies.end() && body->second.dynamic) return entity;
        }
        for (const auto entity : world_.entities()) {
            if (world_.rigid_bodies.contains(entity)) return entity;
        }
        return EntityId{0};
    };
    const auto linked_vector = [this](const std::string& key) {
        const auto component = [this, &key](const char* suffix) {
            const auto found = world_.variables.find(key + suffix);
            return found == world_.variables.end() ? 0.0 : found->second;
        };
        return WorldVector3{component(".x"), component(".y"), component(".z")};
    };
    const auto store_vector = [this](const std::string& key, const WorldVector3& value) {
        world_.variables[key + ".x"] = value.x;
        world_.variables[key + ".y"] = value.y;
        world_.variables[key + ".z"] = value.z;
    };
    for (const auto& item : instructions) {
        try {
            const auto& args = item.arguments;
            if (item.operation == "variable.set" && args.size() >= 2) {
                world_.variables[args[0]] = argument_number(item, 1);
            } else if (item.operation == "variable.add" && args.size() >= 2) {
                world_.variables[args[0]] += argument_number(item, 1);
            } else if (item.operation == "branch.greater" && args.size() >= 3) {
                if (world_.variables[args[0]] > argument_number(item, 1)) {
                    world_.events.push_back(args[2]);
                }
            } else if (item.operation == "event.emit" && !args.empty()) {
                world_.events.push_back(args[0]);
            } else if (item.operation == "entity.spawn" && args.size() >= 4) {
                const auto id = world_.create_entity(args[0]);
                world_.transforms[id].position = {argument_real(item, 1), argument_real(item, 2), argument_real(item, 3)};
            } else if (item.operation == "component.set_position" && args.size() >= 4) {
                const auto id = world_.find_entity(args[0]);
                if (id == 0U) throw std::runtime_error("entity not found: " + args[0]);
                world_.transforms[id].position = {argument_real(item, 1), argument_real(item, 2), argument_real(item, 3)};
            } else if (item.operation == "component.get_position" && args.size() >= 2) {
                const auto id = world_.find_entity(args[0]);
                if (id == 0U) throw std::runtime_error("entity not found: " + args[0]);
                const auto position = world_.transforms.at(id).position;
                world_.variables[args[1] + ".x"] = position.x;
                world_.variables[args[1] + ".y"] = position.y;
                world_.variables[args[1] + ".z"] = position.z;
            } else if (item.operation == "input.move" && args.size() >= 2) {
                const auto id = world_.find_entity(args[0]);
                if (id == 0U) throw std::runtime_error("entity not found: " + args[0]);
                const float speed = argument_number(item, 1, 6.0F);
                auto& body = world_.rigid_bodies[id];
                body.velocity.x = input_axis_.x * speed;
                body.velocity.z = input_axis_.y * speed;
            } else if (item.operation == "input.read_axis" && !args.empty()) {
                store_vector(graph_value_key(item, "value"), {input_axis_.x, input_axis_.y, 0.0});
            } else if (item.operation == "movement.calculate_velocity" && args.size() >= 4) {
                WorldVector3 direction = linked_vector(args[0]);
                const double direction_length = std::sqrt(direction.x * direction.x + direction.y * direction.y);
                if (direction_length > 1.0) {
                    direction.x /= direction_length;
                    direction.y /= direction_length;
                }
                const double speed = argument_real(item, 1, 6.0);
                const double acceleration = std::max(0.0, argument_real(item, 2, 30.0));
                const auto id = resolve_entity(args[3]);
                if (id == 0U || !world_.rigid_bodies.contains(id))
                    throw std::runtime_error("rigid body not found: " + args[3]);
                const WorldVector3 current = world_.rigid_bodies.at(id).velocity;
                const WorldVector3 desired{direction.x * speed, 0.0, direction.y * speed};
                const double maximum_change = acceleration * std::max(0.0F, delta_seconds);
                const auto approach = [maximum_change](double value, double target) {
                    return value + std::clamp(target - value, -maximum_change, maximum_change);
                };
                store_vector(graph_value_key(item, "velocity"), {
                    approach(current.x, desired.x), approach(current.y, desired.y), approach(current.z, desired.z),
                });
            } else if (item.operation == "actor.set_velocity" && args.size() >= 2) {
                const auto id = resolve_entity(args[0]);
                if (id == 0U || !world_.rigid_bodies.contains(id))
                    throw std::runtime_error("rigid body not found: " + args[0]);
                auto& body = world_.rigid_bodies.at(id);
                body.velocity = linked_vector(args[1]);
                body.sleeping = false;
            } else if (item.operation == "time.accumulate" && !args.empty()) {
                world_.variables[args[0]] += delta_seconds;
            } else if (item.operation == "ui.set_text" && !args.empty()) {
                world_.hud_text = args[0];
            } else if (item.operation == "audio.play" && !args.empty()) {
                world_.events.push_back("Audio:" + args[0]);
            } else if (item.operation == "save.write") {
                world_.events.push_back("SaveRequested");
            } else if(item.operation=="animation.play"&&!args.empty()){
                if(!world_.animation_clips.contains(args[0]))throw std::runtime_error("animation clip not found: "+args[0]);
                if(active_animation_id_!=args[0])animation_time_seconds_=0.0;active_animation_id_=args[0];animation_playing_=true;
                if(args.size()>=2&&args[1]=="restart")animation_time_seconds_=0.0;
            } else if(item.operation=="animation.stop"){
                animation_playing_=false;
            } else if(item.operation=="animation.set_speed"&&!args.empty()){
                animation_playback_speed_=std::clamp(argument_real(item,0,1.0),-8.0,8.0);
            } else {
                throw std::runtime_error("unsupported operation: " + item.operation);
            }
            debug_trace_.push_back("OK " + item.node_id + " " + item.operation);
        } catch (const std::exception& exception) {
            std::ostringstream message;
            message << item.source_file << ':' << item.source_line << ":1: error: [TC1001] " << exception.what()
                    << " [node " << item.node_id << ']';
            debug_trace_.push_back(message.str());
        }
    }
    if (debug_trace_.size() > 2048) {
        debug_trace_.erase(debug_trace_.begin(), debug_trace_.begin() + 1024);
    }
}

bool build_skin_matrix_palette(const World& world,const std::string& skin_id,std::vector<Matrix4>& palette,std::string& error){
    palette.clear();const auto skin_found=world.skin_bindings.find(skin_id);if(skin_found==world.skin_bindings.end()){error="Unknown skin binding: "+skin_id;return false;}const auto& skin=skin_found->second;
    const auto skeleton_found=world.skeletons.find(skin.skeleton_id);if(skeleton_found==world.skeletons.end()){error="Skin skeleton is unavailable: "+skin.skeleton_id;return false;}const auto asset_found=world.assets.find(skin.inverse_bind_asset);if(asset_found==world.assets.end()){error="Inverse-bind asset is unavailable: "+skin.inverse_bind_asset;return false;}
    const std::size_t float_count=skin.joint_ids.size()*16U;if(float_count>65535U*16U){error="Skin palette exceeds the native joint limit.";return false;}std::ifstream stream(asset_found->second.source,std::ios::binary|std::ios::ate);if(!stream){error="Could not open inverse-bind asset: "+asset_found->second.source.string();return false;}const auto byte_count=stream.tellg();if(byte_count<0||static_cast<std::uint64_t>(byte_count)<float_count*sizeof(float)){error="Inverse-bind asset is truncated.";return false;}stream.seekg(0);std::vector<float> values(float_count);stream.read(reinterpret_cast<char*>(values.data()),static_cast<std::streamsize>(float_count*sizeof(float)));if(!stream){error="Could not read inverse-bind matrices.";return false;}
    palette.reserve(skin.joint_ids.size());for(std::size_t index=0;index<skin.joint_ids.size();++index){Matrix4 inverse{};for(std::size_t component_index=0;component_index<16;++component_index)inverse[component_index]=values[index*16+component_index];const auto joint_index=skeleton_found->second.joint_indices.find(skin.joint_ids[index]);if(joint_index==skeleton_found->second.joint_indices.end()){error="Skin joint is unavailable: "+skin.joint_ids[index];palette.clear();return false;}palette.push_back(multiply_matrix(inverse,skeleton_found->second.joints[joint_index->second].world));}error.clear();return true;
}

void Runtime::simulate(double delta_seconds) {
    const double bounded = std::clamp(delta_seconds, 0.0, 1.0);
    const double fixed = std::max(1.0e-9, world_.simulation_settings.fixed_timestep_seconds);
    const int steps = std::clamp(static_cast<int>(std::ceil(bounded / fixed)), 1,
                                 std::max(1, world_.simulation_settings.maximum_substeps));
    const double step = bounded / static_cast<double>(steps);
    broadphase_pairs_ = 0;
    collision_contacts_ = 0;
    profile_.physics_joint_ms = 0.0;
    profile_.physics_collision_ms = 0.0;
    profile_.physics_joint_iterations = 0;
    physics_contacts_.clear();
    physics_joint_diagnostics_.clear();
    for (int index = 0; index < steps; ++index) simulate_step(step);
}

void Runtime::solve_physics_joints(double step) {
    const int requested_iterations = std::clamp(world_.simulation_settings.joint_solver_iterations, 1, 64);
    const double inverse_step_squared = 1.0 / std::max(1.0e-12, step * step);
    struct JointSolveReference {
        PhysicsJoint* joint;
        Transform* first_transform;
        Transform* second_transform;
        Quaternion* first_orientation;
        Quaternion* second_orientation;
        RigidBody* first_body;
        RigidBody* second_body;
        bool first_dynamic;
        bool second_dynamic;
        double first_inverse_mass;
        double second_inverse_mass;
    };
    std::vector<JointSolveReference> joints;
    joints.reserve(world_.physics_joints.size());
    std::unordered_map<EntityId, Quaternion> orientations;
    orientations.reserve(world_.physics_joints.size() * 2U);
    for (auto& [unused_joint_id, joint] : world_.physics_joints) {
        static_cast<void>(unused_joint_id);
        auto first_transform = world_.transforms.find(joint.first);
        auto second_transform = world_.transforms.find(joint.second);
        if (first_transform == world_.transforms.end() || second_transform == world_.transforms.end()) continue;
        auto first_body = world_.rigid_bodies.find(joint.first);
        auto second_body = world_.rigid_bodies.find(joint.second);
        RigidBody* first_body_pointer = first_body == world_.rigid_bodies.end() ? nullptr : &first_body->second;
        RigidBody* second_body_pointer = second_body == world_.rigid_bodies.end() ? nullptr : &second_body->second;
        const bool first_dynamic = first_body_pointer != nullptr && first_body_pointer->dynamic && !first_body_pointer->kinematic;
        const bool second_dynamic = second_body_pointer != nullptr && second_body_pointer->dynamic && !second_body_pointer->kinematic;
        auto [first_orientation, first_inserted] = orientations.try_emplace(
            joint.first, euler_quaternion(first_transform->second.rotation));
        static_cast<void>(first_inserted);
        auto [second_orientation, second_inserted] = orientations.try_emplace(
            joint.second, euler_quaternion(second_transform->second.rotation));
        static_cast<void>(second_inserted);
        joints.push_back({
            &joint, &first_transform->second, &second_transform->second,
            &first_orientation->second, &second_orientation->second,
            first_body_pointer, second_body_pointer, first_dynamic, second_dynamic,
            first_dynamic ? 1.0 / std::max(1.0e-12, first_body_pointer->mass) : 0.0,
            second_dynamic ? 1.0 / std::max(1.0e-12, second_body_pointer->mass) : 0.0,
        });
    }
    // Preserve authored quality for ordinary scenes while bounding deterministic large-island work.
    constexpr std::size_t constraint_rows_per_substep = 5000U;
    const int workload_iterations = joints.empty() ? requested_iterations : std::max(
        5, static_cast<int>(constraint_rows_per_substep / joints.size()));
    const int iterations = std::min(requested_iterations, workload_iterations);
    profile_.physics_joint_iterations = std::max(profile_.physics_joint_iterations, iterations);
    std::unordered_map<EntityId, EntityId> island_parent;
    island_parent.reserve(joints.size() * 2U);
    for (const JointSolveReference& reference : joints) {
        const auto& joint = *reference.joint;
        if (!joint.enabled || joint.broken) continue;
        island_parent.emplace(joint.first, joint.first);
        island_parent.emplace(joint.second, joint.second);
    }
    const auto island_root = [&island_parent](EntityId entity) {
        EntityId root = entity;
        while (island_parent.contains(root) && island_parent.at(root) != root) root = island_parent.at(root);
        EntityId current = entity;
        while (island_parent.contains(current) && island_parent.at(current) != current) {
            const EntityId next = island_parent.at(current);
            island_parent[current] = root;
            current = next;
        }
        return root;
    };
    for (const JointSolveReference& reference : joints) {
        const auto& joint = *reference.joint;
        if (!joint.enabled || joint.broken) continue;
        const EntityId first_root = island_root(joint.first), second_root = island_root(joint.second);
        if (first_root != second_root) island_parent[std::max(first_root, second_root)] = std::min(first_root, second_root);
    }
    std::sort(joints.begin(), joints.end(), [&island_root](const JointSolveReference& first, const JointSolveReference& second) {
        const EntityId first_root = island_root(first.joint->first);
        const EntityId second_root = island_root(second.joint->first);
        return first_root != second_root ? first_root < second_root : first.joint->id < second.joint->id;
    });
    std::unordered_set<EntityId> island_roots;
    for (const auto& [entity, unused_parent] : island_parent) {
        static_cast<void>(unused_parent);
        island_roots.insert(island_root(entity));
    }
    solver_islands_ = island_roots.size();
    std::unordered_map<std::string, std::size_t> diagnostic_indices;
    diagnostic_indices.reserve(physics_joint_diagnostics_.size() + joints.size());
    for (std::size_t index = 0; index < physics_joint_diagnostics_.size(); ++index)
        diagnostic_indices.emplace(physics_joint_diagnostics_[index].joint_id, index);
    for (int iteration = 0; iteration < iterations; ++iteration) {
        for (JointSolveReference& reference : joints) {
            auto& joint = *reference.joint;
            const std::string& joint_id = joint.id;
            if (!joint.enabled || joint.broken) continue;
            RigidBody* first_body = reference.first_body;
            RigidBody* second_body = reference.second_body;
            const bool first_dynamic = reference.first_dynamic;
            const bool second_dynamic = reference.second_dynamic;
            const double first_inverse_mass = reference.first_inverse_mass;
            const double second_inverse_mass = reference.second_inverse_mass;
            const double inverse_mass_sum = first_inverse_mass + second_inverse_mass;
            if (inverse_mass_sum <= 0.0) continue;

            if (iteration == 0) {
                const WorldVector3 warm_linear = scale(joint.accumulated_linear_impulse, 0.8);
                const WorldVector3 warm_angular = scale(joint.accumulated_angular_impulse, 0.8);
                if (first_dynamic) {
                    first_body->velocity = add(first_body->velocity, scale(warm_linear, first_inverse_mass));
                    first_body->angular_velocity = subtract(first_body->angular_velocity, scale(warm_angular, first_inverse_mass));
                }
                if (second_dynamic) {
                    second_body->velocity = subtract(second_body->velocity, scale(warm_linear, second_inverse_mass));
                    second_body->angular_velocity = add(second_body->angular_velocity, scale(warm_angular, second_inverse_mass));
                }
            }

            auto& first_transform = *reference.first_transform;
            auto& second_transform = *reference.second_transform;
            const WorldVector3 first_anchor = add(first_transform.position, rotate_quaternion_vector(joint.first_anchor, *reference.first_orientation));
            const WorldVector3 second_anchor = add(second_transform.position, rotate_quaternion_vector(joint.second_anchor, *reference.second_orientation));
            const WorldVector3 joint_axis = normalize(rotate_quaternion_vector(joint.axis, *reference.first_orientation), {1.0, 0.0, 0.0});
            std::array<WorldVector3, 3> joint_basis{
                WorldVector3{1.0, 0.0, 0.0}, WorldVector3{0.0, 1.0, 0.0}, WorldVector3{0.0, 0.0, 1.0},
            };
            if (joint.type == PhysicsJointType::six_dof) {
                joint_basis = {
                    normalize(rotate_quaternion_vector({1.0, 0.0, 0.0}, *reference.first_orientation), {1.0, 0.0, 0.0}),
                    normalize(rotate_quaternion_vector({0.0, 1.0, 0.0}, *reference.first_orientation), {0.0, 1.0, 0.0}),
                    normalize(rotate_quaternion_vector({0.0, 0.0, 1.0}, *reference.first_orientation), {0.0, 0.0, 1.0}),
                };
            }
            const WorldVector3 anchor_delta = subtract(second_anchor, first_anchor);
            const double distance = vector_length(anchor_delta);
            WorldVector3 position_error{};
            if (joint.type == PhysicsJointType::distance || joint.type == PhysicsJointType::spring) {
                double target = joint.rest_distance;
                if (joint.limits_enabled) target = std::clamp(distance, std::min(joint.minimum_limit, joint.maximum_limit),
                                                               std::max(joint.minimum_limit, joint.maximum_limit));
                position_error = scale(normalize(anchor_delta, joint_axis), distance - target);
            } else if (joint.type == PhysicsJointType::slider) {
                const double along_axis = dot(anchor_delta, joint_axis);
                position_error = subtract(anchor_delta, scale(joint_axis, along_axis));
                if (joint.limits_enabled) {
                    const double limited = std::clamp(along_axis, std::min(joint.minimum_limit, joint.maximum_limit),
                                                       std::max(joint.minimum_limit, joint.maximum_limit));
                    position_error = add(position_error, scale(joint_axis, along_axis - limited));
                }
            } else if (joint.type == PhysicsJointType::six_dof && joint.extended_six_dof) {
                const double lower[3] = {joint.linear_lower_limit.x, joint.linear_lower_limit.y, joint.linear_lower_limit.z};
                const double upper[3] = {joint.linear_upper_limit.x, joint.linear_upper_limit.y, joint.linear_upper_limit.z};
                const double springs[3] = {joint.linear_spring_stiffness.x, joint.linear_spring_stiffness.y, joint.linear_spring_stiffness.z};
                for (int axis_index = 0; axis_index < 3; ++axis_index) {
                    const double value = dot(anchor_delta, joint_basis[axis_index]);
                    const double limited = std::clamp(value, lower[axis_index], upper[axis_index]);
                    const double spring_error = value * std::clamp(springs[axis_index] * step * step, 0.0, 1.0);
                    position_error = add(position_error, scale(joint_basis[axis_index], value - limited + spring_error));
                }
            } else {
                position_error = anchor_delta;
            }
            const double position_error_length = vector_length(position_error);
            const bool simple_angular_free =
                joint.type == PhysicsJointType::ball || joint.type == PhysicsJointType::distance ||
                joint.type == PhysicsJointType::spring;
            if (position_error_length <= 1.0e-6 && simple_angular_free && !joint.motor_enabled) {
                if (iteration + 1 == iterations) {
                    const PhysicsJointDiagnostic diagnostic{joint_id, first_anchor, second_anchor, 0.0, 0.0, false};
                    const auto existing = diagnostic_indices.find(joint_id);
                    if (existing == diagnostic_indices.end()) {
                        diagnostic_indices.emplace(joint_id, physics_joint_diagnostics_.size());
                        physics_joint_diagnostics_.push_back(diagnostic);
                    } else {
                        physics_joint_diagnostics_[existing->second] = diagnostic;
                    }
                }
                continue;
            }
            if (position_error_length > 1.0e-6 || joint.motor_enabled) {
                if (first_body != nullptr) { first_body->sleeping = false; first_body->sleep_timer = 0.0; }
                if (second_body != nullptr) { second_body->sleeping = false; second_body->sleep_timer = 0.0; }
            }

            double strength = joint.stiffness;
            if (joint.type == PhysicsJointType::spring) strength = std::clamp(joint.stiffness * step * 12.0, 0.0, 1.0);
            const WorldVector3 correction = scale(position_error, strength);
            if (first_dynamic) first_transform.position = add(first_transform.position, scale(correction, first_inverse_mass / inverse_mass_sum));
            if (second_dynamic) second_transform.position = subtract(second_transform.position, scale(correction, second_inverse_mass / inverse_mass_sum));

            const WorldVector3 direction = normalize(position_error, joint_axis);
            const WorldVector3 first_velocity = first_dynamic ? first_body->velocity : WorldVector3{};
            const WorldVector3 second_velocity = second_dynamic ? second_body->velocity : WorldVector3{};
            const double separating_speed = dot(subtract(second_velocity, first_velocity), direction);
            const double damping_impulse = separating_speed * joint.damping / inverse_mass_sum / static_cast<double>(iterations);
            if (first_dynamic) first_body->velocity = add(first_body->velocity, scale(direction, damping_impulse * first_inverse_mass));
            if (second_dynamic) second_body->velocity = subtract(second_body->velocity, scale(direction, damping_impulse * second_inverse_mass));
            if (iteration + 1 == iterations) joint.accumulated_linear_impulse = scale(direction, damping_impulse);
            if (joint.type == PhysicsJointType::six_dof && joint.extended_six_dof) {
                const double linear_damping[3] = {joint.linear_spring_damping.x, joint.linear_spring_damping.y, joint.linear_spring_damping.z};
                const double angular_damping[3] = {joint.angular_spring_damping.x, joint.angular_spring_damping.y, joint.angular_spring_damping.z};
                for (int axis_index = 0; axis_index < 3; ++axis_index) {
                    const double linear_speed = dot(subtract(second_velocity, first_velocity), joint_basis[axis_index]);
                    const double linear_impulse = linear_speed * std::clamp(linear_damping[axis_index] * step, 0.0, 1.0) /
                                                  inverse_mass_sum / static_cast<double>(iterations);
                    if (first_dynamic) first_body->velocity = add(first_body->velocity, scale(joint_basis[axis_index], linear_impulse * first_inverse_mass));
                    if (second_dynamic) second_body->velocity = subtract(second_body->velocity, scale(joint_basis[axis_index], linear_impulse * second_inverse_mass));
                    const WorldVector3 first_angular = first_dynamic ? first_body->angular_velocity : WorldVector3{};
                    const WorldVector3 second_angular = second_dynamic ? second_body->angular_velocity : WorldVector3{};
                    const double angular_speed = dot(subtract(second_angular, first_angular), joint_basis[axis_index]);
                    const double angular_impulse = angular_speed * std::clamp(angular_damping[axis_index] * step, 0.0, 1.0) /
                                                   inverse_mass_sum / static_cast<double>(iterations);
                    if (first_dynamic) first_body->angular_velocity = add(first_body->angular_velocity, scale(joint_basis[axis_index], angular_impulse * first_inverse_mass));
                    if (second_dynamic) second_body->angular_velocity = subtract(second_body->angular_velocity, scale(joint_basis[axis_index], angular_impulse * second_inverse_mass));
                }
            }

            WorldVector3 angular_error{};
            const bool angular_constrained =
                joint.type != PhysicsJointType::ball && joint.type != PhysicsJointType::distance &&
                joint.type != PhysicsJointType::spring;
            if (angular_constrained) {
            const Quaternion relative_orientation = normalized_quaternion(
                multiply_quaternion(conjugate_quaternion(*reference.first_orientation), *reference.second_orientation));
            const Quaternion rest_orientation{
                joint.rest_orientation[0], joint.rest_orientation[1], joint.rest_orientation[2], joint.rest_orientation[3]};
            const WorldVector3 relative_rotation = quaternion_rotation_error(relative_orientation, rest_orientation);
            if (joint.type == PhysicsJointType::six_dof && joint.extended_six_dof) {
                const double values[3] = {relative_rotation.x, relative_rotation.y, relative_rotation.z};
                const double lower[3] = {joint.angular_lower_limit.x, joint.angular_lower_limit.y, joint.angular_lower_limit.z};
                const double upper[3] = {joint.angular_upper_limit.x, joint.angular_upper_limit.y, joint.angular_upper_limit.z};
                const double springs[3] = {joint.angular_spring_stiffness.x, joint.angular_spring_stiffness.y, joint.angular_spring_stiffness.z};
                double errors[3]{};
                for (int axis_index = 0; axis_index < 3; ++axis_index) {
                    const double limited = std::clamp(values[axis_index], lower[axis_index], upper[axis_index]);
                    errors[axis_index] = values[axis_index] - limited +
                        values[axis_index] * std::clamp(springs[axis_index] * step * step, 0.0, 1.0);
                }
                angular_error = {errors[0], errors[1], errors[2]};
            } else if (joint.type == PhysicsJointType::fixed || joint.type == PhysicsJointType::six_dof || joint.type == PhysicsJointType::slider) {
                angular_error = relative_rotation;
            } else if (joint.type == PhysicsJointType::hinge) {
                const double angle = dot(relative_rotation, joint_axis);
                angular_error = subtract(relative_rotation, scale(joint_axis, angle));
                if (joint.limits_enabled) {
                    const double limited = std::clamp(angle, std::min(joint.minimum_limit, joint.maximum_limit),
                                                       std::max(joint.minimum_limit, joint.maximum_limit));
                    angular_error = add(angular_error, scale(joint_axis, angle - limited));
                }
            } else if (joint.type == PhysicsJointType::cone_twist && joint.limits_enabled) {
                const double angle = vector_length(relative_rotation);
                const double maximum = std::max(std::fabs(joint.minimum_limit), std::fabs(joint.maximum_limit));
                if (angle > maximum) angular_error = scale(normalize(relative_rotation, joint_axis), angle - maximum);
            }
            const double angular_amount = strength;
            const WorldVector3 angular_axis = normalize(angular_error, joint.axis);
            const auto projected_inverse_inertia = [&angular_axis](const RigidBody& body) {
                return angular_axis.x * angular_axis.x / std::max(1.0e-9, body.inertia_diagonal.x) +
                       angular_axis.y * angular_axis.y / std::max(1.0e-9, body.inertia_diagonal.y) +
                       angular_axis.z * angular_axis.z / std::max(1.0e-9, body.inertia_diagonal.z);
            };
            const double first_angular_weight = first_dynamic ? projected_inverse_inertia(*first_body) : 0.0;
            const double second_angular_weight = second_dynamic ? projected_inverse_inertia(*second_body) : 0.0;
            const double angular_weight_sum = first_angular_weight + second_angular_weight;
            if (angular_weight_sum > 0.0 && vector_length(angular_error) > 1.0e-9) {
                if (first_dynamic) *reference.first_orientation = normalized_quaternion(multiply_quaternion(
                    *reference.first_orientation, rotation_vector_quaternion(scale(angular_error, angular_amount * first_angular_weight / angular_weight_sum))));
                if (second_dynamic) *reference.second_orientation = normalized_quaternion(multiply_quaternion(
                    *reference.second_orientation, rotation_vector_quaternion(scale(angular_error, -angular_amount * second_angular_weight / angular_weight_sum))));
            }
            }

            if (joint.motor_enabled && joint.motor_maximum_force > 0.0) {
                const double maximum_delta = joint.motor_maximum_force * step / std::max(1.0e-12, 1.0 / inverse_mass_sum);
                if (joint.type == PhysicsJointType::slider) {
                    const double current = dot(subtract(second_velocity, first_velocity), joint_axis);
                    const double delta = std::clamp(joint.motor_target_velocity - current, -maximum_delta, maximum_delta);
                    if (first_dynamic) first_body->velocity = subtract(first_body->velocity, scale(joint_axis, delta * first_inverse_mass / inverse_mass_sum));
                    if (second_dynamic) second_body->velocity = add(second_body->velocity, scale(joint_axis, delta * second_inverse_mass / inverse_mass_sum));
                    if (iteration + 1 == iterations) joint.accumulated_linear_impulse = scale(joint_axis, -delta / inverse_mass_sum);
                } else {
                    const WorldVector3 first_angular = first_dynamic ? first_body->angular_velocity : WorldVector3{};
                    const WorldVector3 second_angular = second_dynamic ? second_body->angular_velocity : WorldVector3{};
                    const double current = dot(subtract(second_angular, first_angular), joint_axis);
                    const double delta = std::clamp(joint.motor_target_velocity - current, -maximum_delta, maximum_delta);
                    if (first_dynamic) first_body->angular_velocity = subtract(first_body->angular_velocity, scale(joint_axis, delta * first_inverse_mass / inverse_mass_sum));
                    if (second_dynamic) second_body->angular_velocity = add(second_body->angular_velocity, scale(joint_axis, delta * second_inverse_mass / inverse_mass_sum));
                    if (iteration + 1 == iterations) joint.accumulated_angular_impulse = scale(joint_axis, delta / inverse_mass_sum);
                }
            }
            if (joint.type == PhysicsJointType::six_dof && joint.extended_six_dof) {
                const double linear_targets[3] = {joint.linear_drive_velocity.x, joint.linear_drive_velocity.y, joint.linear_drive_velocity.z};
                const double linear_forces[3] = {joint.linear_drive_maximum_force.x, joint.linear_drive_maximum_force.y, joint.linear_drive_maximum_force.z};
                const double angular_targets[3] = {joint.angular_drive_velocity.x, joint.angular_drive_velocity.y, joint.angular_drive_velocity.z};
                const double angular_forces[3] = {joint.angular_drive_maximum_force.x, joint.angular_drive_maximum_force.y, joint.angular_drive_maximum_force.z};
                for (int axis_index = 0; axis_index < 3; ++axis_index) {
                    if (linear_forces[axis_index] > 0.0) {
                        const double current = dot(subtract(second_body != nullptr ? second_body->velocity : WorldVector3{},
                                                            first_body != nullptr ? first_body->velocity : WorldVector3{}), joint_basis[axis_index]);
                        const double delta = std::clamp(linear_targets[axis_index] - current, -linear_forces[axis_index] * step, linear_forces[axis_index] * step);
                        if (first_dynamic) first_body->velocity = subtract(first_body->velocity, scale(joint_basis[axis_index], delta * first_inverse_mass / inverse_mass_sum));
                        if (second_dynamic) second_body->velocity = add(second_body->velocity, scale(joint_basis[axis_index], delta * second_inverse_mass / inverse_mass_sum));
                    }
                    if (angular_forces[axis_index] > 0.0) {
                        const double current = dot(subtract(second_body != nullptr ? second_body->angular_velocity : WorldVector3{},
                                                            first_body != nullptr ? first_body->angular_velocity : WorldVector3{}), joint_basis[axis_index]);
                        const double delta = std::clamp(angular_targets[axis_index] - current, -angular_forces[axis_index] * step, angular_forces[axis_index] * step);
                        if (first_dynamic) first_body->angular_velocity = subtract(first_body->angular_velocity, scale(joint_basis[axis_index], delta * first_inverse_mass / inverse_mass_sum));
                        if (second_dynamic) second_body->angular_velocity = add(second_body->angular_velocity, scale(joint_basis[axis_index], delta * second_inverse_mass / inverse_mass_sum));
                    }
                }
            }

            const double applied_force = vector_length(position_error) * inverse_step_squared / inverse_mass_sum;
            const double applied_torque = vector_length(angular_error) * inverse_step_squared / inverse_mass_sum;
            if ((joint.break_force > 0.0 && applied_force > joint.break_force) ||
                (joint.break_torque > 0.0 && applied_torque > joint.break_torque)) joint.broken = true;
            if (joint.broken || iteration + 1 == iterations) {
                const PhysicsJointDiagnostic diagnostic{
                    joint_id, first_anchor, second_anchor, vector_length(position_error), applied_force, joint.broken,
                };
                const auto existing = diagnostic_indices.find(joint_id);
                if (existing == diagnostic_indices.end()) {
                    diagnostic_indices.emplace(joint_id, physics_joint_diagnostics_.size());
                    physics_joint_diagnostics_.push_back(diagnostic);
                } else {
                    physics_joint_diagnostics_[existing->second] = diagnostic;
                }
            }
        }
    }
    for (const auto& [entity, orientation] : orientations) {
        world_.transforms.at(entity).rotation = quaternion_euler(orientation);
    }
}

void Runtime::simulate_microscopic_forces(double step, bool molecular) {
    constexpr double coulomb_constant = 8.9875517923e9;
    const auto& settings = world_.simulation_settings;
    const double meters_per_unit = std::max(1.0e-30, settings.meters_per_world_unit);
    const double permittivity = std::max(1.0e-12, settings.relative_permittivity);
    std::vector<EntityId> particles;
    for (const auto& [entity, material] : world_.particles) {
        static_cast<void>(material);
        if (world_.transforms.contains(entity) && world_.rigid_bodies.contains(entity)) particles.push_back(entity);
    }
    for (std::size_t left = 0; left < particles.size(); ++left) for (std::size_t right = left + 1; right < particles.size(); ++right) {
        const EntityId first_id = particles[left], second_id = particles[right];
        auto& first_body = world_.rigid_bodies[first_id];auto& second_body = world_.rigid_bodies[second_id];
        if (!first_body.dynamic && !second_body.dynamic) continue;
        const auto& first_material = world_.particles.at(first_id);const auto& second_material = world_.particles.at(second_id);
        const auto& first = world_.transforms.at(first_id).position;const auto& second = world_.transforms.at(second_id).position;
        const WorldVector3 delta_units{second.x-first.x,second.y-first.y,second.z-first.z};
        const double distance_units_squared=delta_units.x*delta_units.x+delta_units.y*delta_units.y+delta_units.z*delta_units.z;
        const double softening=std::max(1.0e-15,0.05*std::min(first_material.radius_meters,second_material.radius_meters));
        const double distance_squared=distance_units_squared*meters_per_unit*meters_per_unit+softening*softening;
        const double distance=std::sqrt(distance_squared);if(distance<=1.0e-30)continue;
        double force_per_delta_meter=-coulomb_constant*first_material.charge_coulombs*second_material.charge_coulombs/
                                      (permittivity*distance_squared*distance);
        if(molecular&&first_material.lennard_jones_epsilon_joules>0&&second_material.lennard_jones_epsilon_joules>0){
            const double epsilon=std::sqrt(first_material.lennard_jones_epsilon_joules*second_material.lennard_jones_epsilon_joules);
            const double sigma=0.5*(first_material.lennard_jones_sigma_meters+second_material.lennard_jones_sigma_meters);
            const double ratio=std::min(10.0,sigma/distance),ratio2=ratio*ratio,ratio6=ratio2*ratio2*ratio2,ratio12=ratio6*ratio6;
            force_per_delta_meter+=-24.0*epsilon*(2.0*ratio12-ratio6)/distance_squared;
        }
        if(!std::isfinite(force_per_delta_meter))continue;
        const double first_factor=force_per_delta_meter*step/std::max(1.0e-40,first_body.mass);
        const double second_factor=force_per_delta_meter*step/std::max(1.0e-40,second_body.mass);
        if(first_body.dynamic){first_body.velocity.x+=delta_units.x*first_factor;first_body.velocity.y+=delta_units.y*first_factor;first_body.velocity.z+=delta_units.z*first_factor;}
        if(second_body.dynamic){second_body.velocity.x-=delta_units.x*second_factor;second_body.velocity.y-=delta_units.y*second_factor;second_body.velocity.z-=delta_units.z*second_factor;}
    }
}

void Runtime::apply_thermal_motion(double step) {
    constexpr double boltzmann_constant = 1.380649e-23;
    const auto& settings = world_.simulation_settings;
    const double meters_per_unit=std::max(1.0e-30,settings.meters_per_world_unit);
    for(const auto& [entity,material]:world_.particles){
        if(!material.thermal_motion||!world_.transforms.contains(entity)||!world_.rigid_bodies.contains(entity))continue;
        auto& body=world_.rigid_bodies[entity];if(!body.dynamic)continue;
        const double viscosity=material.viscosity_pascal_seconds>0?material.viscosity_pascal_seconds:settings.medium_viscosity_pascal_seconds;
        const double drag=6.0*3.141592653589793*std::max(1.0e-15,viscosity)*std::max(1.0e-15,material.radius_meters);
        const double damping=std::exp(-drag/std::max(1.0e-40,body.mass)*step);
        body.velocity.x*=damping;body.velocity.y*=damping;body.velocity.z*=damping;
        const double diffusion=boltzmann_constant*std::max(0.0,settings.temperature_kelvin)/drag;
        const double deviation=std::sqrt(std::max(0.0,2.0*diffusion*step))/meters_per_unit;
        auto& position=world_.transforms[entity].position;
        const std::uint64_t base=settings.random_seed^(simulation_step_index_*0x9E3779B97F4A7C15ULL)^(static_cast<std::uint64_t>(entity)<<24U);
        position.x+=deviation*normal_random(base+1,base+2);position.y+=deviation*normal_random(base+3,base+4);position.z+=deviation*normal_random(base+5,base+6);
    }
}

void Runtime::simulate_fluid_forces(double step) {
    const double meters_per_unit=std::max(1.0e-30,world_.simulation_settings.meters_per_world_unit);
    std::vector<EntityId> ids;
    double smoothing_radius=0.0;
    for(const auto& [entity,particle]:world_.particles)if(world_.transforms.contains(entity)&&world_.rigid_bodies.contains(entity)){
        ids.push_back(entity);smoothing_radius=std::max(smoothing_radius,particle.radius_meters*4.0);
    }
    if(ids.empty()||smoothing_radius<=0)return;
    const double smoothing_radius_units=smoothing_radius/meters_per_unit;
    SpatialNeighborhoodIndex neighborhoods(smoothing_radius_units);
    std::vector<SpatialEntry> entries;entries.reserve(ids.size());
    std::unordered_map<EntityId,std::size_t> particle_index;particle_index.reserve(ids.size());
    for(std::size_t index=0;index<ids.size();++index){
        const auto& position=world_.transforms.at(ids[index]).position;
        entries.push_back({ids[index],{position.x,position.y,position.z}});particle_index.emplace(ids[index],index);
    }
    neighborhoods.rebuild(entries);
    const double h2=smoothing_radius*smoothing_radius;
    const double poly6=315.0/(64.0*3.141592653589793*std::pow(smoothing_radius,9));
    std::vector<double> density(ids.size(),0.0),pressure(ids.size(),0.0);
    for(std::size_t i=0;i<ids.size();++i){
        const auto& a=world_.transforms.at(ids[i]).position;
        for(const EntityId neighbor:neighborhoods.query_radius({a.x,a.y,a.z},smoothing_radius_units)){
        const auto j=particle_index.at(neighbor);const auto& b=world_.transforms.at(neighbor).position;
        const double dx=(b.x-a.x)*meters_per_unit,dy=(b.y-a.y)*meters_per_unit,dz=(b.z-a.z)*meters_per_unit;
        const double r2=dx*dx+dy*dy+dz*dz;if(r2<h2)density[i]+=world_.rigid_bodies.at(ids[j]).mass*poly6*std::pow(h2-r2,3);
        }
    }
    for(std::size_t i=0;i<ids.size();++i){const auto& particle=world_.particles.at(ids[i]);density[i]=std::max(1.0e-12,density[i]);pressure[i]=particle.pressure_stiffness*(density[i]-particle.rest_density_kg_per_m3);}
    const double spiky=45.0/(3.141592653589793*std::pow(smoothing_radius,6));
    for(std::size_t i=0;i<ids.size();++i){
        const auto& a=world_.transforms.at(ids[i]).position;
        for(const EntityId neighbor:neighborhoods.query_radius({a.x,a.y,a.z},smoothing_radius_units)){
        const auto j=particle_index.at(neighbor);if(j<=i)continue;const auto& b=world_.transforms.at(ids[j]).position;
        const double dx=(b.x-a.x)*meters_per_unit,dy=(b.y-a.y)*meters_per_unit,dz=(b.z-a.z)*meters_per_unit;
        const double distance=std::sqrt(dx*dx+dy*dy+dz*dz);if(distance<=1.0e-15||distance>=smoothing_radius)continue;
        const double nx=dx/distance,ny=dy/distance,nz=dz/distance;
        const double gradient=spiky*std::pow(smoothing_radius-distance,2);
        auto& first=world_.rigid_bodies[ids[i]];auto& second=world_.rigid_bodies[ids[j]];
        const double first_pressure=-second.mass*(pressure[i]/(density[i]*density[i])+pressure[j]/(density[j]*density[j]))*gradient;
        const double second_pressure=-first.mass*(pressure[i]/(density[i]*density[i])+pressure[j]/(density[j]*density[j]))*gradient;
        if(first.dynamic){first.velocity.x+=nx*first_pressure/meters_per_unit*step;first.velocity.y+=ny*first_pressure/meters_per_unit*step;first.velocity.z+=nz*first_pressure/meters_per_unit*step;}
        if(second.dynamic){second.velocity.x-=nx*second_pressure/meters_per_unit*step;second.velocity.y-=ny*second_pressure/meters_per_unit*step;second.velocity.z-=nz*second_pressure/meters_per_unit*step;}
        const double laplacian=spiky*(smoothing_radius-distance);
        const double viscosity=0.5*(world_.particles.at(ids[i]).viscosity_pascal_seconds+world_.particles.at(ids[j]).viscosity_pascal_seconds);
        const WorldVector3 velocity_delta{second.velocity.x-first.velocity.x,second.velocity.y-first.velocity.y,second.velocity.z-first.velocity.z};
        const double viscous=viscosity*laplacian*step/std::max(1.0e-12,0.5*(density[i]+density[j]));
        if(first.dynamic){first.velocity.x+=velocity_delta.x*viscous;first.velocity.y+=velocity_delta.y*viscous;first.velocity.z+=velocity_delta.z*viscous;}
        if(second.dynamic){second.velocity.x-=velocity_delta.x*viscous;second.velocity.y-=velocity_delta.y*viscous;second.velocity.z-=velocity_delta.z*viscous;}
        }
    }
}

void Runtime::simulate_step(double step) {
    const auto& simulation = world_.simulation_settings;
    const std::string domain = simulation.domain;
    const bool orbital = domain == "galactic" || domain == "astronomical";
    std::unordered_map<EntityId, WorldVector3> previous_positions;
    if (domain == "microscopic" || domain == "molecular") simulate_microscopic_forces(step, domain == "molecular");
    if (domain == "fluid" || domain == "sph") simulate_fluid_forces(step);
    if (orbital) {
        constexpr double gravitational_constant = 6.67430e-11;
        std::vector<EntityId> bodies;
        for (const auto& [entity, body] : world_.rigid_bodies) if (world_.transforms.contains(entity)) bodies.push_back(entity);
        const double meters_per_unit = std::max(1.0e-30, simulation.meters_per_world_unit);
        const double softening_squared = simulation.gravity_softening_meters * simulation.gravity_softening_meters;
        if(bodies.size()>64U){
            std::vector<MassPoint> mass_points;mass_points.reserve(bodies.size());
            for(const EntityId entity:bodies){const auto& position=world_.transforms.at(entity).position;mass_points.push_back({entity,{position.x*meters_per_unit,position.y*meters_per_unit,position.z*meters_per_unit},world_.rigid_bodies.at(entity).mass});}
            const BarnesHutMassTree force_tree(std::move(mass_points));
            for(const EntityId entity:bodies){auto& body=world_.rigid_bodies[entity];if(!body.dynamic)continue;const auto& position=world_.transforms.at(entity).position;const auto acceleration=force_tree.acceleration_at(entity,{position.x*meters_per_unit,position.y*meters_per_unit,position.z*meters_per_unit},gravitational_constant,simulation.gravity_softening_meters,std::clamp(simulation.long_range_approximation_theta,0.1,1.5));body.velocity.x+=acceleration.x/meters_per_unit*step;body.velocity.y+=acceleration.y/meters_per_unit*step;body.velocity.z+=acceleration.z/meters_per_unit*step;}
        }else{
        for (std::size_t left = 0; left < bodies.size(); ++left) for (std::size_t right = left + 1; right < bodies.size(); ++right) {
            auto& first_body = world_.rigid_bodies[bodies[left]];auto& second_body = world_.rigid_bodies[bodies[right]];
            if(!first_body.dynamic&&!second_body.dynamic)continue;
            const auto& first = world_.transforms.at(bodies[left]).position;const auto& second = world_.transforms.at(bodies[right]).position;
            const WorldVector3 delta{second.x-first.x,second.y-first.y,second.z-first.z};
            const double distance_squared=(delta.x*delta.x+delta.y*delta.y+delta.z*delta.z)*meters_per_unit*meters_per_unit+softening_squared;
            const double inverse_distance_cubed=1.0/(distance_squared*std::sqrt(distance_squared));
            const double first_factor=gravitational_constant*second_body.mass*meters_per_unit*inverse_distance_cubed*step;
            const double second_factor=gravitational_constant*first_body.mass*meters_per_unit*inverse_distance_cubed*step;
            if(first_body.dynamic){first_body.velocity.x+=delta.x*first_factor;first_body.velocity.y+=delta.y*first_factor;first_body.velocity.z+=delta.z*first_factor;}
            if(second_body.dynamic){second_body.velocity.x-=delta.x*second_factor;second_body.velocity.y-=delta.y*second_factor;second_body.velocity.z-=delta.z*second_factor;}
        }
        }
    }
    for (auto& [entity, body] : world_.rigid_bodies) {
        if (!body.dynamic || body.kinematic || body.sleeping || !world_.transforms.contains(entity)) {
            continue;
        }
        const double meters_per_unit = std::max(1.0e-30, simulation.meters_per_world_unit);
        if (body.continuous_collision) previous_positions[entity] = world_.transforms.at(entity).position;
        if (!orbital) {
            body.velocity.x += simulation.gravity_meters_per_second_squared.x / meters_per_unit * step * body.gravity_scale;
            body.velocity.y += simulation.gravity_meters_per_second_squared.y / meters_per_unit * step * body.gravity_scale;
            body.velocity.z += simulation.gravity_meters_per_second_squared.z / meters_per_unit * step * body.gravity_scale;
        }
        const double linear_damping = std::exp(-std::max(0.0F, body.linear_damping) * step);
        const double angular_damping = std::exp(-std::max(0.0F, body.angular_damping) * step);
        body.velocity = scale(body.velocity, linear_damping);
        body.angular_velocity = scale(body.angular_velocity, angular_damping);
        auto& transform = world_.transforms[entity];
        transform.position.x += body.velocity.x * step;
        transform.position.y += body.velocity.y * step;
        transform.position.z += body.velocity.z * step;
        constexpr double degrees_per_radian = 57.29577951308232;
        transform.rotation.x += static_cast<float>(body.angular_velocity.x * step * degrees_per_radian);
        transform.rotation.y += static_cast<float>(body.angular_velocity.y * step * degrees_per_radian);
        transform.rotation.z += static_cast<float>(body.angular_velocity.z * step * degrees_per_radian);
        const auto collider = world_.colliders.find(entity);
        const double floor_offset = collider == world_.colliders.end() ? 0.5 : collider->second.half_extents.y;
        if (simulation.floor_enabled && !orbital && transform.position.y < floor_offset) {
            transform.position.y = floor_offset;
            if (body.velocity.y < 0.0F) {
                const float collider_restitution = collider == world_.colliders.end() ? body.restitution : collider->second.restitution;
                const float friction = collider == world_.colliders.end() ? 0.5F : collider->second.friction;
                body.velocity.y = -body.velocity.y * std::clamp(std::max(body.restitution, collider_restitution), 0.0F, 1.0F);
                const double floor_friction = std::max(0.0, 1.0 - static_cast<double>(friction) * step * 8.0);
                body.velocity.x *= floor_friction;
                body.velocity.z *= floor_friction;
                if (std::fabs(body.velocity.y) < 0.05F) body.velocity.y = 0.0F;
            }
        }
    }
    if (domain == "microscopic" || domain == "molecular") apply_thermal_motion(step);
    const auto joint_start = Clock::now();
    solve_physics_joints(step);
    profile_.physics_joint_ms += milliseconds(joint_start, Clock::now());
    ++simulation_step_index_;
    if (orbital) return;

    const auto collision_start = Clock::now();

    std::unordered_map<EntityId, WorldVector3> collider_extents;
    collider_extents.reserve(world_.colliders.size());
    std::unordered_map<EntityId, std::array<WorldVector3, 3>> box_bases;
    box_bases.reserve(world_.colliders.size());
    for (const auto& [entity, collider] : world_.colliders) {
        const auto transform = world_.transforms.find(entity);
        if (transform == world_.transforms.end()) continue;
        WorldVector3 extents{};
        if (collider.shape == ColliderShape::box) {
            const auto basis = box_basis(transform->second);
            box_bases.emplace(entity, basis);
            extents = {
                projected_box_radius(collider, basis, {1.0, 0.0, 0.0}),
                projected_box_radius(collider, basis, {0.0, 1.0, 0.0}),
                projected_box_radius(collider, basis, {0.0, 0.0, 1.0}),
            };
        } else {
            extents = collider_world_half_extents(transform->second, collider);
        }
        collider_extents.emplace(entity, extents);
    }
    struct BroadphaseProxy {
        EntityId entity;
        WorldVector3 minimum;
        WorldVector3 maximum;
    };
    std::vector<BroadphaseProxy> proxies;
    proxies.reserve(collider_extents.size());
    for (const auto& [entity, extents] : collider_extents) {
        const WorldVector3 position = world_.transforms.at(entity).position;
        const WorldVector3 previous = previous_positions.contains(entity) ? previous_positions.at(entity) : position;
        proxies.push_back({
            entity,
            {std::min(position.x, previous.x) - extents.x, std::min(position.y, previous.y) - extents.y,
             std::min(position.z, previous.z) - extents.z},
            {std::max(position.x, previous.x) + extents.x, std::max(position.y, previous.y) + extents.y,
             std::max(position.z, previous.z) + extents.z},
        });
    }
    std::sort(proxies.begin(), proxies.end(), [](const BroadphaseProxy& first, const BroadphaseProxy& second) {
        return first.minimum.x != second.minimum.x ? first.minimum.x < second.minimum.x : first.entity < second.entity;
    });
    std::vector<std::uint64_t> candidates;
    candidates.reserve(collider_extents.size() * 8U);
    for (std::size_t left = 0; left < proxies.size(); ++left) {
        const auto& first = proxies[left];
        for (std::size_t right = left + 1; right < proxies.size(); ++right) {
            const auto& second = proxies[right];
            if (second.minimum.x > first.maximum.x) break;
            if (second.minimum.y > first.maximum.y || second.maximum.y < first.minimum.y ||
                second.minimum.z > first.maximum.z || second.maximum.z < first.minimum.z) continue;
            const EntityId minimum = std::min(first.entity, second.entity);
            const EntityId maximum = std::max(first.entity, second.entity);
            candidates.push_back((static_cast<std::uint64_t>(minimum) << 32U) | maximum);
        }
    }
    std::unordered_set<std::uint64_t> disabled_collision_pairs;
    disabled_collision_pairs.reserve(world_.physics_joints.size());
    for (const auto& [unused_joint_id, joint] : world_.physics_joints) {
        static_cast<void>(unused_joint_id);
        if (!joint.enabled || joint.broken || joint.collision_enabled) continue;
        const EntityId minimum = std::min(joint.first, joint.second);
        const EntityId maximum = std::max(joint.first, joint.second);
        disabled_collision_pairs.insert((static_cast<std::uint64_t>(minimum) << 32U) | maximum);
    }
    broadphase_pairs_ = std::max(broadphase_pairs_, candidates.size());
    for (const std::uint64_t encoded : candidates) {
        const EntityId first = static_cast<EntityId>(encoded >> 32U);
        const EntityId second = static_cast<EntityId>(encoded & 0xFFFFFFFFULL);
        auto first_body = world_.rigid_bodies.find(first);
        auto second_body = world_.rigid_bodies.find(second);
        const bool first_dynamic = first_body != world_.rigid_bodies.end() && first_body->second.dynamic && !first_body->second.kinematic;
        const bool second_dynamic = second_body != world_.rigid_bodies.end() && second_body->second.dynamic && !second_body->second.kinematic;
        if (!first_dynamic && !second_dynamic) continue;
        auto& first_transform = world_.transforms[first];
        auto& second_transform = world_.transforms[second];
        const auto& first_collider = world_.colliders.at(first);
        const auto& second_collider = world_.colliders.at(second);
        if (disabled_collision_pairs.contains(encoded)) continue;
        if ((first_collider.mask & second_collider.layer) == 0U || (second_collider.mask & first_collider.layer) == 0U) continue;
        const bool continuous_pair = previous_positions.contains(first) || previous_positions.contains(second);
        if (!continuous_pair) {
            const WorldVector3 delta = subtract(second_transform.position, first_transform.position);
            const WorldVector3 first_extents = collider_extents.at(first);
            const WorldVector3 second_extents = collider_extents.at(second);
            if (std::fabs(delta.x) > first_extents.x + second_extents.x ||
                std::fabs(delta.y) > first_extents.y + second_extents.y ||
                std::fabs(delta.z) > first_extents.z + second_extents.z) continue;
        }
        ContactManifold contact =
            first_collider.shape == ColliderShape::box && second_collider.shape == ColliderShape::box
            ? box_manifold_with_basis(
                first_transform, first_collider, box_bases.at(first),
                second_transform, second_collider, box_bases.at(second))
            : collider_manifold(first_transform, first_collider, second_transform, second_collider);
        if (!contact.hit && continuous_pair) {
            const WorldVector3 first_previous = previous_positions.contains(first) ? previous_positions.at(first) : first_transform.position;
            const WorldVector3 second_previous = previous_positions.contains(second) ? previous_positions.at(second) : second_transform.position;
            const WorldVector3 relative_start = subtract(second_previous, first_previous);
            const WorldVector3 relative_end = subtract(second_transform.position, first_transform.position);
            const WorldVector3 motion = subtract(relative_end, relative_start);
            const double radius = vector_length(collider_extents.at(first)) + vector_length(collider_extents.at(second));
            const double a = dot(motion, motion), b = 2.0 * dot(relative_start, motion);
            const double c = dot(relative_start, relative_start) - radius * radius;
            const double discriminant = b * b - 4.0 * a * c;
            if (a > 1.0e-12 && discriminant >= 0.0) {
                const double time = (-b - std::sqrt(discriminant)) / (2.0 * a);
                if (time >= 0.0 && time <= 1.0) {
                    if (first_dynamic) first_transform.position = add(first_previous, scale(subtract(first_transform.position, first_previous), time));
                    if (second_dynamic) second_transform.position = add(second_previous, scale(subtract(second_transform.position, second_previous), time));
                    contact.normal = normalize(add(relative_start, scale(motion, time)), {1.0, 0.0, 0.0});
                    contact.point = scale(add(first_transform.position, second_transform.position), 0.5);
                    contact.penetration = 1.0e-6;
                    contact.hit = true;
                }
            }
        }
        if (!contact.hit) continue;
        ++collision_contacts_;
        const bool trigger = first_collider.trigger || second_collider.trigger;
        physics_contacts_.push_back({first, second, contact.point, contact.normal, contact.penetration, trigger});
        if (trigger) continue;
        if (first_body != world_.rigid_bodies.end()) { first_body->second.sleeping = false; first_body->second.sleep_timer = 0.0; }
        if (second_body != world_.rigid_bodies.end()) { second_body->second.sleeping = false; second_body->second.sleep_timer = 0.0; }
        double first_inverse_mass = first_dynamic ? 1.0 / std::max(1.0e-12, first_body->second.mass) : 0.0;
        double second_inverse_mass = second_dynamic ? 1.0 / std::max(1.0e-12, second_body->second.mass) : 0.0;
        const double shock = simulation.shock_propagation_factor;
        if (first_dynamic && second_dynamic && std::fabs(contact.normal.y) > 0.45) {
            if (first_transform.position.y < second_transform.position.y) first_inverse_mass *= 1.0 - shock;
            else second_inverse_mass *= 1.0 - shock;
        }
        const double inverse_mass_sum = first_inverse_mass + second_inverse_mass;
        if (inverse_mass_sum <= 0.0) continue;
        const int contact_iterations = std::max(1, simulation.contact_solver_iterations);
        const double correction_fraction = 1.0 - std::pow(0.2, 1.0 / static_cast<double>(contact_iterations));
        const double resolved_fraction = 1.0 - std::pow(1.0 - correction_fraction, contact_iterations);
        const WorldVector3 correction = scale(contact.normal, contact.penetration / inverse_mass_sum * resolved_fraction);
        if (first_dynamic) first_transform.position = subtract(first_transform.position, scale(correction, first_inverse_mass));
        if (second_dynamic) second_transform.position = add(second_transform.position, scale(correction, second_inverse_mass));
        const WorldVector3 first_velocity = first_dynamic ? first_body->second.velocity : WorldVector3{};
        const WorldVector3 second_velocity = second_dynamic ? second_body->second.velocity : WorldVector3{};
        WorldVector3 relative_velocity = subtract(second_velocity, first_velocity);
        const double velocity_along_normal = dot(relative_velocity, contact.normal);
        if (velocity_along_normal >= 0.0) continue;
        const float restitution = std::clamp(std::max(first_collider.restitution, second_collider.restitution), 0.0F, 1.0F);
        const double impulse_amount = -(1.0 + restitution) * velocity_along_normal / inverse_mass_sum;
        const WorldVector3 impulse = scale(contact.normal, impulse_amount);
        if (first_dynamic) first_body->second.velocity = subtract(first_body->second.velocity, scale(impulse, first_inverse_mass));
        if (second_dynamic) second_body->second.velocity = add(second_body->second.velocity, scale(impulse, second_inverse_mass));
        relative_velocity = subtract(second_dynamic ? second_body->second.velocity : WorldVector3{}, first_dynamic ? first_body->second.velocity : WorldVector3{});
        const WorldVector3 tangent_unscaled = subtract(relative_velocity, scale(contact.normal, dot(relative_velocity, contact.normal)));
        const WorldVector3 tangent = normalize(tangent_unscaled, {});
        double friction_impulse = -dot(relative_velocity, tangent) / inverse_mass_sum;
        const double friction = std::sqrt(static_cast<double>(first_collider.friction) * second_collider.friction);
        friction_impulse = std::clamp(friction_impulse, -impulse_amount * friction, impulse_amount * friction);
        const WorldVector3 tangent_impulse = scale(tangent, friction_impulse);
        if (first_dynamic) first_body->second.velocity = subtract(first_body->second.velocity, scale(tangent_impulse, first_inverse_mass));
        if (second_dynamic) second_body->second.velocity = add(second_body->second.velocity, scale(tangent_impulse, second_inverse_mass));
    }
    for (auto& [unused_entity, body] : world_.rigid_bodies) {
        static_cast<void>(unused_entity);
        if (!body.dynamic || body.kinematic || !body.allow_sleep) {
            body.sleep_timer = 0.0;
            body.sleeping = false;
            continue;
        }
        if (vector_length(body.velocity) <= simulation.sleep_linear_threshold &&
            vector_length(body.angular_velocity) <= simulation.sleep_angular_threshold) {
            body.sleep_timer += step;
            if (body.sleep_timer >= simulation.sleep_delay_seconds) {
                body.sleeping = true;
                body.velocity = {};
                body.angular_velocity = {};
            }
        } else {
            body.sleep_timer = 0.0;
            body.sleeping = false;
        }
    }
    profile_.physics_collision_ms += milliseconds(collision_start, Clock::now());
}

const std::vector<PhysicsContact>& Runtime::physics_contacts() const noexcept { return physics_contacts_; }

const std::vector<PhysicsJointDiagnostic>& Runtime::physics_joint_diagnostics() const noexcept {
    return physics_joint_diagnostics_;
}

bool Runtime::raycast(const WorldVector3& origin, const WorldVector3& direction, double maximum_distance,
                      PhysicsRayHit& hit, std::uint32_t layer_mask) const {
    const WorldVector3 ray = normalize(direction, {});
    if (vector_length(ray) <= 1.0e-12 || maximum_distance < 0.0) return false;
    bool found = false;
    double closest = maximum_distance;
    for (const auto& [entity, collider] : world_.colliders) {
        if ((collider.layer & layer_mask) == 0U || !world_.transforms.contains(entity)) continue;
        const auto& center = world_.transforms.at(entity).position;
        double near_distance = 0.0;
        double far_distance = closest;
        WorldVector3 normal{};
        const double origins[3] = {origin.x, origin.y, origin.z};
        const double directions[3] = {ray.x, ray.y, ray.z};
        const double centers[3] = {center.x, center.y, center.z};
        const double extents[3] = {collider.half_extents.x, collider.half_extents.y, collider.half_extents.z};
        bool intersects = true;
        int near_axis = -1;
        double near_sign = 0.0;
        for (int axis = 0; axis < 3; ++axis) {
            if (std::fabs(directions[axis]) <= 1.0e-12) {
                if (origins[axis] < centers[axis] - extents[axis] || origins[axis] > centers[axis] + extents[axis]) intersects = false;
                continue;
            }
            double first = (centers[axis] - extents[axis] - origins[axis]) / directions[axis];
            double second = (centers[axis] + extents[axis] - origins[axis]) / directions[axis];
            double sign = -1.0;
            if (first > second) { std::swap(first, second); sign = 1.0; }
            if (first > near_distance) { near_distance = first; near_axis = axis; near_sign = sign; }
            far_distance = std::min(far_distance, second);
            if (near_distance > far_distance) intersects = false;
        }
        if (!intersects || near_distance < 0.0 || near_distance > closest) continue;
        closest = near_distance;
        if (near_axis == 0) normal.x = near_sign;
        else if (near_axis == 1) normal.y = near_sign;
        else if (near_axis == 2) normal.z = near_sign;
        hit = {entity, add(origin, scale(ray, closest)), normal, closest};
        found = true;
    }
    return found;
}

bool Runtime::save(const std::filesystem::path& path, std::string& error) const {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    if (!stream) {
        error = "Could not write save game: " + path.string();
        return false;
    }
    stream << std::setprecision(17);
    stream << "TCSAVE\t2\n";
    for (const auto& [name, value] : world_.variables) stream << "VAR\t" << encode(name) << '\t' << value << '\n';
    for (const auto entity : world_.entities()) {
        const auto found = world_.transforms.find(entity);
        if (found != world_.transforms.end()) {
            const auto& transform = found->second;
            const auto body = world_.rigid_bodies.find(entity);
            const WorldVector3 velocity = body == world_.rigid_bodies.end() ? WorldVector3{} : body->second.velocity;
            const WorldVector3 angular_velocity = body == world_.rigid_bodies.end() ? WorldVector3{} : body->second.angular_velocity;
            stream << "BODY\t" << encode(world_.name(entity))
                   << '\t' << transform.position.x << '\t' << transform.position.y << '\t' << transform.position.z
                   << '\t' << transform.rotation.x << '\t' << transform.rotation.y << '\t' << transform.rotation.z
                   << '\t' << transform.scale.x << '\t' << transform.scale.y << '\t' << transform.scale.z
                   << '\t' << velocity.x << '\t' << velocity.y << '\t' << velocity.z
                   << '\t' << angular_velocity.x << '\t' << angular_velocity.y << '\t' << angular_velocity.z;
            if (body != world_.rigid_bodies.end()) {
                stream << '\t' << body->second.inertia_diagonal.x << '\t' << body->second.inertia_diagonal.y << '\t' << body->second.inertia_diagonal.z
                       << '\t' << (body->second.allow_sleep ? 1 : 0) << '\t' << (body->second.sleeping ? 1 : 0)
                       << '\t' << body->second.sleep_timer;
            }
            stream << '\n';
        }
    }
    std::vector<std::string> joint_ids;
    joint_ids.reserve(world_.physics_joints.size());
    for (const auto& [joint_id, unused_joint] : world_.physics_joints) {
        static_cast<void>(unused_joint);
        joint_ids.push_back(joint_id);
    }
    std::sort(joint_ids.begin(), joint_ids.end());
    for (const auto& joint_id : joint_ids) {
        const auto& joint = world_.physics_joints.at(joint_id);
        stream << "JOINTSTATE\t" << encode(joint_id) << '\t' << (joint.enabled ? 1 : 0) << '\t' << (joint.broken ? 1 : 0)
               << '\t' << joint.accumulated_linear_impulse.x << '\t' << joint.accumulated_linear_impulse.y << '\t' << joint.accumulated_linear_impulse.z
               << '\t' << joint.accumulated_angular_impulse.x << '\t' << joint.accumulated_angular_impulse.y << '\t' << joint.accumulated_angular_impulse.z << '\n';
    }
    error.clear();
    return true;
}

bool Runtime::load_save(const std::filesystem::path& path, std::string& error) {
    std::ifstream stream(path, std::ios::binary);
    std::string line;
    if (!stream || !std::getline(stream, line)) {
        error = "Unsupported or missing TC save game";
        return false;
    }
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line != "TCSAVE\t1" && line != "TCSAVE\t2") {
        error = "Unsupported or missing TC save game";
        return false;
    }
    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        const auto row = fields(line);
        if (row.size() >= 3 && row[0] == "VAR") world_.variables[decode(row[1])] = real_number(row, 2);
        if (row.size() >= 5 && row[0] == "POS") {
            const auto id = world_.find_entity(decode(row[1]));
            if (id != 0U) world_.transforms[id].position = {real_number(row, 2), real_number(row, 3), real_number(row, 4)};
        }
        if (row.size() >= 17 && row[0] == "BODY") {
            const auto id = world_.find_entity(decode(row[1]));
            if (id != 0U) {
                auto& transform = world_.transforms[id];
                transform.position = {real_number(row, 2), real_number(row, 3), real_number(row, 4)};
                transform.rotation = {number(row, 5), number(row, 6), number(row, 7)};
                transform.scale = {number(row, 8, 1.0F), number(row, 9, 1.0F), number(row, 10, 1.0F)};
                const auto body = world_.rigid_bodies.find(id);
                if (body != world_.rigid_bodies.end()) {
                    body->second.velocity = {real_number(row, 11), real_number(row, 12), real_number(row, 13)};
                    body->second.angular_velocity = {real_number(row, 14), real_number(row, 15), real_number(row, 16)};
                    if (row.size() >= 23) {
                        body->second.inertia_diagonal = {real_number(row, 17, 1.0), real_number(row, 18, 1.0), real_number(row, 19, 1.0)};
                        body->second.allow_sleep = flag(row, 20, true);
                        body->second.sleeping = flag(row, 21);
                        body->second.sleep_timer = std::max(0.0, real_number(row, 22));
                    }
                }
            }
        }
        if (row.size() >= 4 && row[0] == "JOINTSTATE") {
            const auto joint = world_.physics_joints.find(decode(row[1]));
            if (joint != world_.physics_joints.end()) {
                joint->second.enabled = flag(row, 2, true);
                joint->second.broken = flag(row, 3);
                if (row.size() >= 10) {
                    joint->second.accumulated_linear_impulse = {real_number(row, 4), real_number(row, 5), real_number(row, 6)};
                    joint->second.accumulated_angular_impulse = {real_number(row, 7), real_number(row, 8), real_number(row, 9)};
                }
            }
        }
    }
    error.clear();
    return true;
}

World& Runtime::world() noexcept { return world_; }
const World& Runtime::world() const noexcept { return world_; }
const RuntimeProfile& Runtime::profile() const noexcept { return profile_; }
const std::vector<std::string>& Runtime::debug_trace() const noexcept { return debug_trace_; }

}  // namespace tc::runtime
