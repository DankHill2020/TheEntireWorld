"""CMake project discovery, execution, and compiler diagnostic parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import shutil
import subprocess
import time
from typing import Callable, Iterable


_MSVC_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+)(?:,(?P<column>\d+))?\):\s*"
    r"(?P<severity>fatal error|error|warning|note)\s+(?P<code>[A-Za-z]+\d+):\s*(?P<message>.+)$"
)
_CLANG_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s*"
    r"(?P<severity>fatal error|error|warning|note):\s*(?P<message>.+)$"
)
_PYTHON_TRACEBACK = re.compile(r'^\s*File\s+"(?P<file>.+?)",\s+line\s+(?P<line>\d+)')


@dataclass(frozen=True)
class NativeBuildDiagnostic:
    file: str
    line: int
    column: int
    severity: str
    code: str
    message: str

    def display_text(self) -> str:
        location = f"{Path(self.file).name}:{max(1, self.line)}:{max(1, self.column)}"
        return f"{self.severity.upper()} {location} {self.code}: {self.message}"


@dataclass(frozen=True)
class NativeBuildPlan:
    project_root: str
    build_directory: str
    configuration: str
    action: str
    source_file: str
    configure_command: tuple[str, ...]
    build_command: tuple[str, ...]
    test_command: tuple[str, ...]
    clean_command: tuple[str, ...]
    analysis_command: tuple[str, ...]


@dataclass
class NativeBuildReceipt:
    ok: bool
    plan: NativeBuildPlan
    return_code: int
    elapsed_seconds: float
    output: str = ""
    diagnostics: list[NativeBuildDiagnostic] = field(default_factory=list)
    cancelled: bool = False


def find_cmake_project(path: str | Path) -> Path | None:
    current = Path(path).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "CMakeLists.txt").is_file():
            return candidate
    return None


def create_native_build_plan(
    path: str | Path,
    configuration: str = "Debug",
    action: str = "build",
) -> NativeBuildPlan:
    root = find_cmake_project(path)
    if root is None:
        raise ValueError("No CMakeLists.txt was found for the current file or its parents.")
    config = str(configuration or "Debug").strip().title()
    if config not in {"Debug", "Release", "Relwithdebinfo", "Minsizerel"}:
        raise ValueError(f"Unsupported build configuration: {configuration}")
    canonical = {"Relwithdebinfo": "RelWithDebInfo", "Minsizerel": "MinSizeRel"}.get(config, config)
    operation = str(action or "build").strip().lower()
    if operation not in {"build", "build_test", "rebuild", "clean", "analyze"}:
        raise ValueError(f"Unsupported build action: {action}")
    build_dir = root / ".tech_connector" / "cmake" / canonical
    configure = (
        "cmake", "-S", str(root), "-B", str(build_dir),
        f"-DCMAKE_BUILD_TYPE={canonical}", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    )
    build = ("cmake", "--build", str(build_dir), "--config", canonical, "--parallel")
    test = ("ctest", "--test-dir", str(build_dir), "-C", canonical, "--output-on-failure")
    clean = ("cmake", "--build", str(build_dir), "--config", canonical, "--target", "clean")
    source_file = str(Path(path).resolve()) if Path(path).is_file() else ""
    analysis = (
        "clang-tidy", source_file, "-p", str(build_dir), "--quiet",
    ) if source_file else ()
    return NativeBuildPlan(
        str(root), str(build_dir), canonical, operation, source_file,
        configure, build, test, clean, analysis,
    )


def parse_native_build_diagnostics(
    output: str,
    base_directory: str | Path = "",
) -> list[NativeBuildDiagnostic]:
    diagnostics: list[NativeBuildDiagnostic] = []
    seen: set[tuple[str, int, int, str, str]] = set()
    for line in str(output or "").splitlines():
        match = _MSVC_DIAGNOSTIC.match(line.strip()) or _CLANG_DIAGNOSTIC.match(line.strip())
        if not match:
            continue
        values = match.groupdict()
        severity = str(values.get("severity") or "error").replace("fatal ", "")
        source_path = Path(values["file"])
        if not source_path.is_absolute() and base_directory:
            source_path = Path(base_directory) / source_path
        item = NativeBuildDiagnostic(
            file=str(source_path.resolve()),
            line=int(values.get("line") or 1),
            column=int(values.get("column") or 1),
            severity=severity,
            code=str(values.get("code") or "CXX"),
            message=str(values.get("message") or "Compiler diagnostic"),
        )
        key = (item.file, item.line, item.column, item.code, item.message)
        if key not in seen:
            seen.add(key)
            diagnostics.append(item)
    return diagnostics


def source_location_from_output_line(line: str) -> tuple[str, int, int] | None:
    text = str(line or "").strip()
    match = _MSVC_DIAGNOSTIC.match(text) or _CLANG_DIAGNOSTIC.match(text)
    if match:
        values = match.groupdict()
        return str(values["file"]), int(values.get("line") or 1), int(values.get("column") or 1)
    traceback_match = _PYTHON_TRACEBACK.match(text)
    if traceback_match:
        return str(traceback_match.group("file")), int(traceback_match.group("line")), 1
    return None


def reformat_native_source(source: str, path: str | Path) -> tuple[str, list[str]]:
    executable = shutil.which("clang-format")
    if not executable:
        raise RuntimeError("clang-format is not installed or is not available on PATH.")
    completed = subprocess.run(
        [executable, f"--assume-filename={Path(path).name}"], input=source,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "clang-format failed.").strip())
    return completed.stdout, ["Formatted with clang-format using the project's nearest .clang-format file."]


def discover_native_toolchains() -> dict[str, str]:
    """Return concrete executable paths used by the native editor surface."""
    environment = _visual_studio_environment() if os.name == "nt" else dict(os.environ)
    search_path = environment.get("Path") or environment.get("PATH") or ""
    return {
        name: str(shutil.which(name, path=search_path) or "")
        for name in (
            "cmake", "ctest", "ninja", "msbuild", "cl", "clang", "clang++",
            "clang-format", "clang-tidy", "lldb", "gdb",
        )
    }


def run_native_build(
    plan: NativeBuildPlan,
    *,
    emit: Callable[[str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> NativeBuildReceipt:
    environment = _visual_studio_environment() if os.name == "nt" else dict(os.environ)
    search_path = environment.get("Path") or environment.get("PATH") or ""
    if not shutil.which("cmake", path=search_path):
        raise RuntimeError("CMake is not installed or is not available on PATH.")
    started = time.monotonic()
    chunks: list[str] = []
    return_code = 0
    cancelled = False
    commands = {
        "build": (plan.configure_command, plan.build_command),
        "build_test": (plan.configure_command, plan.build_command, plan.test_command),
        "rebuild": (plan.configure_command, plan.clean_command, plan.build_command),
        "clean": (plan.clean_command,),
        "analyze": (plan.configure_command, plan.analysis_command),
    }[plan.action]
    for command in commands:
        if not command:
            raise RuntimeError(f"No command is available for native action '{plan.action}'.")
        if is_cancelled and is_cancelled():
            cancelled = True
            break
        return_code, phase_output, phase_cancelled = _run_phase(
            command, plan.project_root, emit, is_cancelled, environment
        )
        chunks.append(phase_output)
        cancelled = cancelled or phase_cancelled
        if return_code != 0 or cancelled:
            break
    output = "\n".join(chunk for chunk in chunks if chunk)
    return NativeBuildReceipt(
        ok=return_code == 0 and not cancelled,
        plan=plan,
        return_code=return_code,
        elapsed_seconds=time.monotonic() - started,
        output=output,
        diagnostics=parse_native_build_diagnostics(output, plan.project_root),
        cancelled=cancelled,
    )


def _run_phase(
    command: Iterable[str],
    cwd: str,
    emit: Callable[[str], None] | None,
    is_cancelled: Callable[[], bool] | None,
    environment: dict[str, str],
) -> tuple[int, str, bool]:
    process = subprocess.Popen(
        list(command), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        env=environment,
    )
    lines: list[str] = []
    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if line:
            text = line.rstrip("\r\n")
            lines.append(text)
            if emit:
                emit(text)
        if process.poll() is not None:
            remainder = process.stdout.read()
            for trailing in remainder.splitlines():
                lines.append(trailing)
                if emit:
                    emit(trailing)
            break
        if is_cancelled and is_cancelled():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            return int(process.returncode or 1), "\n".join(lines), True
    return int(process.returncode or 0), "\n".join(lines), False


def _visual_studio_environment() -> dict[str, str]:
    base = _dedupe_windows_environment(dict(os.environ))
    script = _find_vsdevcmd()
    if script is None:
        return base
    command = (
        f'cmd.exe /d /c call "{script}" -no_logo '
        "-arch=amd64 -host_arch=amd64 && set"
    )
    completed = subprocess.run(
        command,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        env=base,
    )
    if completed.returncode != 0:
        return base
    generated = dict(base)
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key:
            generated[key] = value
    return _dedupe_windows_environment(generated)


def _find_vsdevcmd() -> Path | None:
    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]
    vswhere = roots[1] / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        completed = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
            capture_output=True, text=True, timeout=8,
        )
        install = completed.stdout.strip()
        candidate = Path(install) / "Common7" / "Tools" / "VsDevCmd.bat"
        if completed.returncode == 0 and candidate.is_file():
            return candidate
    for root in roots:
        candidates = sorted((root / "Microsoft Visual Studio").glob("20*/*/Common7/Tools/VsDevCmd.bat"), reverse=True)
        if candidates:
            return candidates[0]
    return None


def _dedupe_windows_environment(environment: dict[str, str]) -> dict[str, str]:
    deduped: dict[str, str] = {}
    canonical_keys: dict[str, str] = {}
    for key, value in environment.items():
        folded = key.casefold()
        previous = canonical_keys.get(folded)
        if previous is not None:
            deduped.pop(previous, None)
        canonical_keys[folded] = key
        deduped[key] = value
    return deduped


__all__ = [
    "NativeBuildDiagnostic", "NativeBuildPlan", "NativeBuildReceipt",
    "create_native_build_plan", "find_cmake_project",
    "parse_native_build_diagnostics", "run_native_build",
    "reformat_native_source", "discover_native_toolchains", "source_location_from_output_line",
]
