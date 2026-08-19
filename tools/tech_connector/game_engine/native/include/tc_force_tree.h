#ifndef TC_FORCE_TREE_H
#define TC_FORCE_TREE_H

#include "tc_spatial_index.h"

#include <array>
#include <cstdint>
#include <vector>

namespace tc::runtime {

struct MassPoint {
    std::uint32_t id{0};
    SpatialPoint position_meters{};
    double mass_kilograms{0.0};
};

class BarnesHutMassTree {
public:
    explicit BarnesHutMassTree(std::vector<MassPoint> bodies);
    [[nodiscard]] SpatialPoint acceleration_at(std::uint32_t target_id, const SpatialPoint& position_meters,
                                               double gravitational_constant, double softening_meters,
                                               double theta) const;

private:
    struct Node {
        SpatialPoint center{};
        double half_extent{0.0};
        double mass{0.0};
        SpatialPoint center_of_mass{};
        std::array<int, 8> children{-1, -1, -1, -1, -1, -1, -1, -1};
        std::vector<std::size_t> body_indices;
    };

    int build_node(const std::vector<std::size_t>& indices, const SpatialPoint& center, double half_extent, int depth);
    void accumulate(int node_index, std::uint32_t target_id, const SpatialPoint& position, double constant,
                    double softening_squared, double theta, SpatialPoint& acceleration) const;

    std::vector<MassPoint> bodies_;
    std::vector<Node> nodes_;
    int root_{-1};
};

}  // namespace tc::runtime

#endif
