from __future__ import annotations

import math
import random

import pytest

from tech_connector.game_engine.runtime.graph_execution_service import (
    GraphExecutionContext,
    create_default_graph_operation_registry,
)
from tech_connector.game_engine.runtime.native_graph_backend import (
    NativeGraphBackend,
    NativeGraphBackendError,
    discover_native_graph_library,
    native_graph_backend_status,
)


def _backend() -> NativeGraphBackend:
    path = discover_native_graph_library()
    if path is None:
        pytest.skip("Native graph runtime has not been built for this test run.")
    return NativeGraphBackend(path)


def test_native_backend_loads_with_the_expected_abi() -> None:
    backend = _backend()
    status = native_graph_backend_status()

    assert backend.abi_version == 1
    assert status.available
    assert status.library_path.endswith("tc_graph_runtime.dll")


def test_native_input_and_movement_match_reference_runtime_randomized() -> None:
    backend = _backend()
    registry = create_default_graph_operation_registry()
    read_input = registry.resolve("input.read_axis")
    calculate = registry.resolve("movement.calculate_velocity")
    assert read_input is not None and calculate is not None
    randomizer = random.Random(73021)

    for _ in range(250):
        direction = (
            randomizer.uniform(-2.0, 2.0),
            randomizer.uniform(-2.0, 2.0),
        )
        current = tuple(randomizer.uniform(-12.0, 12.0) for _ in range(3))
        speed = randomizer.uniform(0.0, 30.0)
        acceleration = randomizer.uniform(0.0, 80.0)
        delta_seconds = randomizer.uniform(0.0, 0.1)
        context = GraphExecutionContext(
            delta_seconds=delta_seconds,
            input_actions={"Move": direction},
            actors={"Self": {"velocity": current}},
        )
        reference_direction = read_input(context=context, axis="Move")
        reference_velocity = calculate(
            context=context,
            direction=reference_direction,
            speed=speed,
            acceleration=acceleration,
            target="Self",
        )
        native_direction = backend.clamp_input_axis(direction)
        native_velocity = backend.calculate_movement_velocity(
            direction=native_direction,
            current_velocity=current,
            maximum_speed=speed,
            acceleration=acceleration,
            delta_seconds=delta_seconds,
        )

        assert native_direction == pytest.approx(reference_direction, abs=1.0e-6)
        assert native_velocity == pytest.approx(reference_velocity, abs=2.0e-5)


def test_native_backend_rejects_non_finite_and_out_of_range_values() -> None:
    backend = _backend()

    with pytest.raises(NativeGraphBackendError, match="NaN or infinity"):
        backend.calculate_movement_velocity(
            direction=(math.nan, 0.0),
            current_velocity=(0.0, 0.0, 0.0),
            maximum_speed=6.0,
            acceleration=4.0,
            delta_seconds=0.1,
        )
    with pytest.raises(NativeGraphBackendError, match="valid range"):
        backend.calculate_movement_velocity(
            direction=(1.0, 0.0),
            current_velocity=(0.0, 0.0, 0.0),
            maximum_speed=-1.0,
            acceleration=4.0,
            delta_seconds=0.1,
        )
