"""Data contracts for the code-agent comparison benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    """Describe one isolated coding task and its hidden evaluator.

    :param case_id: Stable case identifier.
    :param title: Human-readable case title.
    :param category: Product area represented by the case.
    :param prompt: Exact task text sent to every agent.
    :param seed_files: Relative source paths and initial contents.
    :param allowed_paths: Paths the agent may change.
    :param evaluator_source: Hidden Python evaluator created after the run.
    :param assertion_count: Number of behavioral assertions in the evaluator.
    :return: Benchmark case definition.
    """

    case_id: str
    title: str
    category: str
    prompt: str
    seed_files: dict[str, str]
    allowed_paths: tuple[str, ...]
    evaluator_source: str
    assertion_count: int


@dataclass
class AgentRun:
    """Capture one agent attempt before deterministic grading.

    :param agent: Stable agent adapter name.
    :param model: Requested or reported model identifier.
    :param case_id: Benchmark case identifier.
    :param repetition: One-based repetition number.
    :param status: Adapter completion status.
    :param wall_seconds: Total wall-clock duration.
    :return: Agent run record.
    """

    agent: str
    model: str
    case_id: str
    repetition: int
    status: str
    wall_seconds: float
    exit_code: int | None = None
    timed_out: bool = False
    eligible: bool = True
    ineligibility_reason: str = ""
    error: str = ""
    final_message: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    time_to_first_output_seconds: float | None = None
    tool_calls: int = 0
    command_calls: int = 0
    file_change_events: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        :return: Run data as a dictionary.
        """

        return asdict(self)


@dataclass
class Score:
    """Store deterministic quality and patch-efficiency measurements."""

    behavior_points: float = 0.0
    quality_points: float = 0.0
    syntax_points: float = 0.0
    scope_points: float = 0.0
    completion_points: float = 0.0
    total_points: float = 0.0
    assertions_passed: int = 0
    assertions_total: int = 0
    syntax_ok: bool = False
    changed_files: list[str] = field(default_factory=list)
    out_of_scope_files: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    evaluator_seconds: float = 0.0
    evaluator_output: str = ""
    quality_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        :return: Score data as a dictionary.
        """

        return asdict(self)


@dataclass
class BenchmarkReport:
    """Combine environment facts and all scored benchmark attempts."""

    benchmark_version: str
    started_at: str
    finished_at: str
    environment: dict[str, Any]
    runs: list[dict[str, Any]]
    summary: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        :return: Complete report dictionary.
        """

        return asdict(self)
