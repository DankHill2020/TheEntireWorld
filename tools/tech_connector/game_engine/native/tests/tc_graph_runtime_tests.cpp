#include "tc_graph_runtime.h"

#include <cassert>
#include <cmath>
#include <limits>

namespace {

bool close(float left, float right) {
    return std::fabs(left - right) <= 1.0e-5F;
}

}  // namespace

int main() {
    assert(tc_graph_abi_version() == TC_GRAPH_ABI_VERSION);

    const TcGraphVector2 raw_axis{2.0F, -3.0F};
    TcGraphVector2 clamped{};
    assert(tc_graph_clamp_input_axis(&raw_axis, &clamped) == TC_GRAPH_STATUS_OK);
    assert(close(clamped.x, 1.0F));
    assert(close(clamped.y, -1.0F));

    const TcGraphMovementInput movement{
        TcGraphVector2{1.0F, 0.0F},
        TcGraphVector3{0.0F, 0.0F, 0.0F},
        6.0F,
        4.0F,
        0.25F,
    };
    TcGraphVector3 velocity{};
    assert(
        tc_graph_calculate_movement_velocity(&movement, &velocity)
        == TC_GRAPH_STATUS_OK
    );
    assert(close(velocity.x, 1.0F));
    assert(close(velocity.y, 0.0F));
    assert(close(velocity.z, 0.0F));

    TcGraphMovementInput invalid = movement;
    invalid.maximum_speed = std::numeric_limits<float>::quiet_NaN();
    assert(
        tc_graph_calculate_movement_velocity(&invalid, &velocity)
        == TC_GRAPH_STATUS_NON_FINITE_VALUE
    );
    assert(
        tc_graph_calculate_movement_velocity(nullptr, &velocity)
        == TC_GRAPH_STATUS_NULL_POINTER
    );
    return 0;
}
