#include "tc_graph_runtime.h"

#include <algorithm>
#include <cmath>

namespace {

bool finite(float value) noexcept {
    return std::isfinite(value);
}

bool finite(TcGraphVector2 value) noexcept {
    return finite(value.x) && finite(value.y);
}

bool finite(TcGraphVector3 value) noexcept {
    return finite(value.x) && finite(value.y) && finite(value.z);
}

TcGraphVector3 move_toward(
    TcGraphVector3 current,
    TcGraphVector3 target,
    float maximum_change
) noexcept {
    const TcGraphVector3 delta{
        target.x - current.x,
        target.y - current.y,
        target.z - current.z,
    };
    const float distance = std::sqrt(
        delta.x * delta.x + delta.y * delta.y + delta.z * delta.z
    );
    if (distance <= maximum_change || distance <= 1.0e-9F) {
        return target;
    }
    const float scale = maximum_change / distance;
    return TcGraphVector3{
        current.x + delta.x * scale,
        current.y + delta.y * scale,
        current.z + delta.z * scale,
    };
}

}  // namespace

uint32_t tc_graph_abi_version(void) {
    return TC_GRAPH_ABI_VERSION;
}

const char* tc_graph_status_message(TcGraphStatus status) {
    switch (status) {
        case TC_GRAPH_STATUS_OK:
            return "Success";
        case TC_GRAPH_STATUS_NULL_POINTER:
            return "A required pointer was null";
        case TC_GRAPH_STATUS_NON_FINITE_VALUE:
            return "An input contained NaN or infinity";
        case TC_GRAPH_STATUS_OUT_OF_RANGE:
            return "An input was outside its valid range";
        default:
            return "Unknown graph runtime status";
    }
}

TcGraphStatus tc_graph_clamp_input_axis(
    const TcGraphVector2* input,
    TcGraphVector2* output
) {
    if (input == nullptr || output == nullptr) {
        return TC_GRAPH_STATUS_NULL_POINTER;
    }
    if (!finite(*input)) {
        return TC_GRAPH_STATUS_NON_FINITE_VALUE;
    }
    output->x = std::clamp(input->x, -1.0F, 1.0F);
    output->y = std::clamp(input->y, -1.0F, 1.0F);
    return TC_GRAPH_STATUS_OK;
}

TcGraphStatus tc_graph_calculate_movement_velocity(
    const TcGraphMovementInput* input,
    TcGraphVector3* output
) {
    if (input == nullptr || output == nullptr) {
        return TC_GRAPH_STATUS_NULL_POINTER;
    }
    if (
        !finite(input->direction)
        || !finite(input->current_velocity)
        || !finite(input->maximum_speed)
        || !finite(input->acceleration)
        || !finite(input->delta_seconds)
    ) {
        return TC_GRAPH_STATUS_NON_FINITE_VALUE;
    }
    if (
        input->maximum_speed < 0.0F
        || input->acceleration < 0.0F
        || input->delta_seconds < 0.0F
    ) {
        return TC_GRAPH_STATUS_OUT_OF_RANGE;
    }

    TcGraphVector2 direction = input->direction;
    const float magnitude = std::hypot(direction.x, direction.y);
    if (magnitude > 1.0F) {
        direction.x /= magnitude;
        direction.y /= magnitude;
    }
    const TcGraphVector3 desired{
        direction.x * input->maximum_speed,
        0.0F,
        direction.y * input->maximum_speed,
    };
    *output = move_toward(
        input->current_velocity,
        desired,
        input->acceleration * input->delta_seconds
    );
    return TC_GRAPH_STATUS_OK;
}
