from __future__ import annotations

import json
from pathlib import Path

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge


def _bridge_with_log(path: Path) -> UnrealBridge:
    bridge = UnrealBridge()
    bridge.LOG_FILE = path
    bridge.MAX_LOG_BYTES = 64
    bridge.MAX_LOG_ARCHIVES = 2
    return bridge


def test_request_log_rotates_and_keeps_bounded_archives(tmp_path: Path) -> None:
    log_path = tmp_path / "unreal_request_log.jsonl"
    bridge = _bridge_with_log(log_path)
    log_path.write_text("oldest\n" * 16, encoding="utf-8")
    Path(f"{log_path}.1").write_text("older\n", encoding="utf-8")
    Path(f"{log_path}.2").write_text("expired\n", encoding="utf-8")

    bridge._log_request({"request_id": "new", "ok": True})

    assert json.loads(log_path.read_text(encoding="utf-8"))["request_id"] == "new"
    assert Path(f"{log_path}.1").read_text(encoding="utf-8").startswith("oldest")
    assert Path(f"{log_path}.2").read_text(encoding="utf-8") == "older\n"
    assert not Path(f"{log_path}.3").exists()


def test_request_log_can_disable_archives(tmp_path: Path) -> None:
    log_path = tmp_path / "unreal_request_log.jsonl"
    bridge = _bridge_with_log(log_path)
    bridge.MAX_LOG_ARCHIVES = 0
    log_path.write_text("old\n" * 32, encoding="utf-8")

    bridge._log_request({"request_id": "replacement"})

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records == [{"request_id": "replacement"}]
    assert not Path(f"{log_path}.1").exists()
