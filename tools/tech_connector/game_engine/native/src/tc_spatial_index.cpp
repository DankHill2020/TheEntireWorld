#include "tc_spatial_index.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tc::runtime {
namespace {

std::int64_t cell_coordinate(double value, double cell_size) {
    const double coordinate = std::floor(value / cell_size);
    constexpr double minimum = static_cast<double>(std::numeric_limits<std::int64_t>::min() + 1);
    constexpr double maximum = static_cast<double>(std::numeric_limits<std::int64_t>::max() - 1);
    return static_cast<std::int64_t>(std::clamp(coordinate, minimum, maximum));
}

std::size_t mix(std::uint64_t value) noexcept {
    value ^= value >> 30U;
    value *= 0xBF58476D1CE4E5B9ULL;
    value ^= value >> 27U;
    value *= 0x94D049BB133111EBULL;
    value ^= value >> 31U;
    return static_cast<std::size_t>(value);
}

}  // namespace

SpatialNeighborhoodIndex::SpatialNeighborhoodIndex(double cell_size) : cell_size_(cell_size) {
    if (!std::isfinite(cell_size_) || cell_size_ <= 0.0) throw std::invalid_argument("Spatial cell size must be finite and positive");
}

void SpatialNeighborhoodIndex::rebuild(const std::vector<SpatialEntry>& entries) {
    cells_.clear();
    for (const auto& entry : entries) cells_[cell_for(entry.position)].push_back(entry);
    for (auto& [unused, bucket] : cells_) {
        static_cast<void>(unused);
        std::sort(bucket.begin(), bucket.end(), [](const SpatialEntry& left, const SpatialEntry& right) { return left.id < right.id; });
    }
}

std::vector<std::uint32_t> SpatialNeighborhoodIndex::query_radius(const SpatialPoint& center, double radius) const {
    if (!std::isfinite(radius) || radius < 0.0) throw std::invalid_argument("Spatial query radius must be finite and non-negative");
    if (!std::isfinite(center.x) || !std::isfinite(center.y) || !std::isfinite(center.z)) {
        throw std::invalid_argument("Spatial query center must be finite");
    }
    const Cell minimum = cell_for({center.x - radius, center.y - radius, center.z - radius});
    const Cell maximum = cell_for({center.x + radius, center.y + radius, center.z + radius});
    const auto cell_span = [](std::int64_t low, std::int64_t high) {
        return static_cast<std::uint64_t>(high) - static_cast<std::uint64_t>(low);
    };
    if (cell_span(minimum.x, maximum.x) > 256U || cell_span(minimum.y, maximum.y) > 256U ||
        cell_span(minimum.z, maximum.z) > 256U) {
        throw std::invalid_argument("Spatial query spans too many cells; increase the index cell size");
    }
    const double radius_squared = radius * radius;
    std::vector<std::uint32_t> result;
    for (std::int64_t x = minimum.x; x <= maximum.x; ++x) {
        for (std::int64_t y = minimum.y; y <= maximum.y; ++y) {
            for (std::int64_t z = minimum.z; z <= maximum.z; ++z) {
                const auto found = cells_.find({x, y, z});
                if (found == cells_.end()) continue;
                for (const auto& entry : found->second) {
                    const double dx = entry.position.x - center.x;
                    const double dy = entry.position.y - center.y;
                    const double dz = entry.position.z - center.z;
                    if (dx * dx + dy * dy + dz * dz <= radius_squared) result.push_back(entry.id);
                }
            }
        }
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());
    return result;
}

double SpatialNeighborhoodIndex::cell_size() const noexcept { return cell_size_; }

std::size_t SpatialNeighborhoodIndex::CellHash::operator()(const Cell& cell) const noexcept {
    const auto x = mix(static_cast<std::uint64_t>(cell.x));
    const auto y = mix(static_cast<std::uint64_t>(cell.y) ^ 0x9E3779B97F4A7C15ULL);
    const auto z = mix(static_cast<std::uint64_t>(cell.z) ^ 0xD1B54A32D192ED03ULL);
    return x ^ (y << 1U) ^ (z << 7U);
}

SpatialNeighborhoodIndex::Cell SpatialNeighborhoodIndex::cell_for(const SpatialPoint& point) const {
    return {cell_coordinate(point.x, cell_size_), cell_coordinate(point.y, cell_size_), cell_coordinate(point.z, cell_size_)};
}

}  // namespace tc::runtime
