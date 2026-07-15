from __future__ import annotations

"""Atomic multi-file project edit transactions with scope and validation gates."""

from dataclasses import asdict, dataclass, field
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable

from services.execution_contract_service import ExecutionContract, ScopeObservation, check_scope


@dataclass
class PendingFileChange:
    path: str
    action: str
    before: str = ""
    after: str = ""
    symbols: list[str] = field(default_factory=list)
    preview_hash: str = ""

    def normalize(self) -> None:
        if not self.preview_hash and self.action == "modify":
            self.preview_hash = _hash_text(self.before)

    def to_dict(self) -> dict[str, Any]:
        self.normalize()
        return asdict(self)


@dataclass
class TransactionResult:
    ok: bool
    status: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    validation: list[dict[str, Any]] = field(default_factory=list)
    rolled_back: bool = False
    errors: list[str] = field(default_factory=list)
    scope_check: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_project_edit_transaction(
    changes: Iterable[PendingFileChange | dict[str, Any]],
    *,
    contract: ExecutionContract | dict[str, Any],
    validator: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    rollback_on_validation_failure: bool = True,
) -> TransactionResult:
    pending = [item if isinstance(item, PendingFileChange) else PendingFileChange(**dict(item)) for item in changes]
    for item in pending:
        item.normalize()
    observation = ScopeObservation(
        files_touched=[item.path for item in pending],
        symbols_touched=[symbol for item in pending for symbol in item.symbols],
        edit_count=len(pending),
        new_files=[item.path for item in pending if item.action == "create"],
        operation="project_edit",
    )
    scope = check_scope(contract, observation)
    if not scope.ok:
        return TransactionResult(False, "scope_rejected", scope_check=scope.to_dict(), errors=list(scope.violations))

    errors = _preflight(pending)
    if errors:
        return TransactionResult(False, "preflight_failed", scope_check=scope.to_dict(), errors=errors)

    backups: dict[str, tuple[bool, str]] = {}
    written: list[PendingFileChange] = []
    try:
        for item in pending:
            path = Path(item.path)
            existed = path.exists()
            backups[item.path] = (existed, path.read_text(encoding="utf-8", errors="replace") if existed else "")
            _atomic_write(path, item.after)
            written.append(item)
    except Exception as exc:
        rollback_errors = _rollback(backups)
        return TransactionResult(
            False,
            "write_failed_rolled_back" if not rollback_errors else "write_failed_rollback_incomplete",
            changes=[item.to_dict() for item in written],
            rolled_back=True,
            scope_check=scope.to_dict(),
            errors=[str(exc), *rollback_errors],
        )

    validation = validator([item.path for item in written]) if validator else []
    required_failures = [item for item in validation if item.get("required", True) and not item.get("ok")]
    if required_failures and rollback_on_validation_failure:
        rollback_errors = _rollback(backups)
        return TransactionResult(
            False,
            "validation_failed_rolled_back" if not rollback_errors else "validation_failed_rollback_incomplete",
            changes=[item.to_dict() for item in written],
            validation=validation,
            rolled_back=True,
            scope_check=scope.to_dict(),
            errors=[str(item.get("message") or item.get("key") or "Validation failed") for item in required_failures] + rollback_errors,
        )
    return TransactionResult(
        not required_failures,
        "applied" if not required_failures else "applied_with_validation_errors",
        changes=[item.to_dict() for item in written],
        validation=validation,
        scope_check=scope.to_dict(),
        errors=[str(item.get("message") or "Validation failed") for item in required_failures],
    )


def _preflight(changes: list[PendingFileChange]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for item in changes:
        path = Path(item.path)
        key = str(path.resolve()) if path.exists() else str(path.absolute())
        if key in seen:
            errors.append(f"Duplicate change target: {item.path}")
        seen.add(key)
        if item.action not in {"modify", "create"}:
            errors.append(f"Unsupported action for {item.path}: {item.action}")
            continue
        if item.action == "modify":
            if not path.exists():
                errors.append(f"Cannot modify missing file: {item.path}")
                continue
            current = path.read_text(encoding="utf-8", errors="replace")
            if item.preview_hash and _hash_text(current) != item.preview_hash:
                errors.append(f"File changed after preview: {item.path}")
        elif path.exists():
            errors.append(f"Cannot create existing file without explicit replace semantics: {item.path}")
    return errors


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except Exception:
            pass
        raise


def _rollback(backups: dict[str, tuple[bool, str]]) -> list[str]:
    errors: list[str] = []
    for raw_path, (existed, content) in reversed(list(backups.items())):
        path = Path(raw_path)
        try:
            if existed:
                _atomic_write(path, content)
            elif path.exists():
                path.unlink()
        except Exception as exc:
            errors.append(f"Rollback failed for {raw_path}: {exc}")
    return errors


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()
