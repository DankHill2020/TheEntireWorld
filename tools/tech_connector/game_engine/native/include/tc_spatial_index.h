#ifndef TC_SPATIAL_INDEX_H
#define TC_SPATIAL_INDEX_H

#include <cstdint>
#include <unordered_map>
#include <vector>

namespace tc::runtime {

struct SpatialPoint {
    double x{0.0};
    double y{0.0};
    double z{0.0};
};

struct SpatialEntry {
    std::uint32_t id{0};
    SpatialPoint position{};
};

class SpatialNeighborhoodIndex {
public:
    explicit SpatialNeighborhoodIndex(double cell_size);
    void rebuild(const std::vector<SpatialEntry>& entries);
    [[nodiscard]] std::vector<std::uint32_t> query_radius(const SpatialPoint& center, double radius) const;
    [[nodiscard]] double cell_size() const noexcept;

private:
    struct Cell {
        std::int64_t x{0};
        std::int64_t y{0};
        std::int64_t z{0};
        bool operator==(const Cell&) const = default;
    };
    struct CellHash {
        std::size_t operator()(const Cell& cell) const noexcept;
    };
    [[nodiscard]] Cell cell_for(const SpatialPoint& point) const;

    double cell_size_{1.0};
    std::unordered_map<Cell, std::vector<SpatialEntry>, CellHash> cells_;
};

}  // namespace tc::runtime

#endif
