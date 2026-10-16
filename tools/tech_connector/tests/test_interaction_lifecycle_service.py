from tech_connector.services.interaction_lifecycle_service import InteractionLifecycleManager


def test_completed_operation_is_not_reported_as_cancelled() -> None:
    lifecycle = InteractionLifecycleManager()
    operation = lifecycle.start_operation(origin_message_id="demo_pipeline")

    assert lifecycle.complete_current() is True
    assert lifecycle.current_operation() is None
    assert lifecycle.get_operation(operation.operation_id).status == "completed"
    assert lifecycle.get_operation(operation.operation_id).cancellation_reason == ""


def test_completing_operation_finishes_outstanding_provider_requests() -> None:
    lifecycle = InteractionLifecycleManager()
    operation = lifecycle.start_operation(continuation_id="demo")
    request = lifecycle.start_provider_request(
        operation_id=operation.operation_id,
        continuation_id="demo",
        slot_name="asset",
    )

    assert lifecycle.complete_operation(operation.operation_id) is True
    stored = lifecycle.get_operation(operation.operation_id)
    assert stored.provider_requests[request.request_id].status == "completed"
