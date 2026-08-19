"""Compatibility entry point for the code-agent comparison benchmark."""

from pathlib import Path
import sys


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tech_connector.benchmarks.code_agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
