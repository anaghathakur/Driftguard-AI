"""Bounded, opt-in validation execution in a disposable repository copy.

The process-local runner is intentionally limited to development/test deployments. A
production deployment must use a stronger external sandbox; until one is configured the
capability truthfully reports NOT_CONFIGURED and static validation remains available.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from apps.api.app.domain.repository import RepositoryScan
from apps.api.app.schemas.validation import (
    ValidationCommandResult,
    ValidationExecution,
    ValidationExecutionStatus,
)

_PYTHON_CONFIGS = {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"}
_NODE_SCRIPTS = ("typecheck", "lint", "test", "build")
_MAX_COMMANDS = 8


@dataclass(frozen=True, slots=True)
class DiscoveredCommand:
    category: str
    display_name: str
    argv: tuple[str, ...]
    working_directory: str


class ValidationExecutionEngine:
    def __init__(
        self,
        *,
        provider: str,
        deployment_environment: str,
        timeout_seconds: float,
        output_max_bytes: int,
    ) -> None:
        self.provider = provider
        self.deployment_environment = deployment_environment
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.output_max_bytes = max(1_000, int(output_max_bytes))

    @property
    def available(self) -> bool:
        return self.provider == "local" and self.deployment_environment in {
            "development",
            "test",
        }

    def execute(
        self,
        scan: RepositoryScan,
        modified_sources: dict[str, str],
    ) -> ValidationExecution:
        if not self.available:
            return ValidationExecution(
                status=ValidationExecutionStatus.NOT_CONFIGURED,
                message=(
                    "Test execution is not configured. Static validation and test discovery "
                    "were completed; configure an isolated runner to execute repository code."
                ),
            )

        started = time.monotonic()
        source_by_path = {item.path: item.content for item in scan.files}
        if any(path not in source_by_path for path in modified_sources):
            return _blocked(started, "The validated patch references a file outside the snapshot.")

        with TemporaryDirectory(prefix="driftguard-validation-") as temp_name:
            root = Path(temp_name).resolve()
            try:
                for relative, original in source_by_path.items():
                    destination = _safe_destination(root, relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(
                        modified_sources.get(relative, original), encoding="utf-8", newline=""
                    )
            except (OSError, ValueError):
                return _blocked(started, "The temporary validation copy could not be prepared.")

            commands, ecosystem, discovery_checks = discover_commands(root)
            if not commands:
                return ValidationExecution(
                    status=ValidationExecutionStatus.NOT_CONFIGURED,
                    ecosystem=ecosystem,
                    checks=discovery_checks,
                    duration_ms=_elapsed_ms(started),
                    isolated_temporary_copy=True,
                    message=(
                        "No executable allowlisted test, lint, typecheck, or build command was "
                        "discovered from the repository configuration."
                    ),
                )

            results = [self._run(root, command) for command in commands[:_MAX_COMMANDS]]

        failed = any(item.timed_out or item.exit_code not in {0, None} for item in results)
        partial = any(item.output_truncated for item in results)
        status = (
            ValidationExecutionStatus.FAILED
            if failed
            else ValidationExecutionStatus.PARTIAL
            if partial
            else ValidationExecutionStatus.PASSED
        )
        return ValidationExecution(
            status=status,
            ecosystem=ecosystem,
            commands=results,
            checks=discovery_checks,
            duration_ms=_elapsed_ms(started),
            isolated_temporary_copy=True,
            message=(
                "One or more allowlisted validation commands failed or timed out."
                if failed
                else "Allowlisted validation commands completed in a disposable repository copy."
            ),
        )

    def _run(self, root: Path, command: DiscoveredCommand) -> ValidationCommandResult:
        validate_discovered_command(command)
        cwd = _safe_destination(root, command.working_directory or ".")
        started = time.monotonic()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        }
        environment.update(
            {
                "CI": "1",
                "NO_COLOR": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        try:
            completed = subprocess.run(
                list(command.argv),
                cwd=cwd,
                env=environment,
                capture_output=True,
                check=False,
                shell=False,
                timeout=self.timeout_seconds,
            )
            stdout, stdout_truncated = _bounded_output(
                completed.stdout, self.output_max_bytes
            )
            stderr, stderr_truncated = _bounded_output(
                completed.stderr, self.output_max_bytes
            )
            return ValidationCommandResult(
                category=command.category,
                display_name=command.display_name,
                argv=list(command.argv),
                exit_code=completed.returncode,
                duration_ms=_elapsed_ms(started),
                stdout_summary=stdout,
                stderr_summary=stderr,
                output_truncated=stdout_truncated or stderr_truncated,
            )
        except subprocess.TimeoutExpired as exc:
            stdout, stdout_truncated = _bounded_output(exc.stdout or b"", self.output_max_bytes)
            stderr, stderr_truncated = _bounded_output(exc.stderr or b"", self.output_max_bytes)
            return ValidationCommandResult(
                category=command.category,
                display_name=command.display_name,
                argv=list(command.argv),
                timed_out=True,
                duration_ms=_elapsed_ms(started),
                stdout_summary=stdout,
                stderr_summary=stderr,
                output_truncated=stdout_truncated or stderr_truncated,
            )


def discover_commands(root: Path) -> tuple[list[DiscoveredCommand], str | None, list[str]]:
    commands: list[DiscoveredCommand] = []
    checks: list[str] = []
    python_roots = sorted(
        {path.parent for path in root.rglob("*") if path.name.casefold() in _PYTHON_CONFIGS}
    )
    if not python_roots and any(path.name.startswith("test_") for path in root.rglob("*.py")):
        python_roots = [root]
    if python_roots:
        checks.append("Python project configuration or pytest tests discovered.")
        if importlib.util.find_spec("pytest") is not None:
            project = python_roots[0]
            commands.append(
                DiscoveredCommand(
                    category="test",
                    display_name="Python tests (pytest)",
                    argv=(sys.executable, "-m", "pytest", "-q"),
                    working_directory=project.relative_to(root).as_posix() or ".",
                )
            )
        else:
            checks.append("pytest is not installed in the validation runner environment.")

    package_files = sorted(root.rglob("package.json"))
    if package_files:
        package = package_files[0]
        scripts = _package_scripts(package)
        manager = _node_manager(package.parent)
        checks.append("Node package.json configuration discovered.")
        if manager is None:
            checks.append("No npm, pnpm, or yarn executable is available to the runner.")
        else:
            for script in _NODE_SCRIPTS:
                if script not in scripts:
                    continue
                argv = (manager, "run", script)
                commands.append(
                    DiscoveredCommand(
                        category=script,
                        display_name=f"Node {script}",
                        argv=argv,
                        working_directory=package.parent.relative_to(root).as_posix() or ".",
                    )
                )

    if python_roots and package_files:
        ecosystem = "python+node"
    elif python_roots:
        ecosystem = "python"
    elif package_files:
        ecosystem = "node"
    else:
        ecosystem = None
    return commands[:_MAX_COMMANDS], ecosystem, checks


def validate_discovered_command(command: DiscoveredCommand) -> None:
    argv = command.argv
    is_pytest = len(argv) == 4 and argv[0] == sys.executable and argv[1:] == (
        "-m",
        "pytest",
        "-q",
    )
    executable = Path(argv[0]).name.casefold()
    is_node = (
        len(argv) == 3
        and executable in {"npm", "npm.cmd", "pnpm", "pnpm.cmd", "yarn", "yarn.cmd"}
        and argv[1] == "run"
        and argv[2] in _NODE_SCRIPTS
    )
    if not (is_pytest or is_node):
        raise ValueError("Validation command is outside the fixed allowlist.")


def _package_scripts(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    scripts = value.get("scripts") if isinstance(value, dict) else None
    return scripts if isinstance(scripts, dict) else {}


def _node_manager(directory: Path) -> str | None:
    candidates = (
        ("pnpm", "pnpm-lock.yaml"),
        ("yarn", "yarn.lock"),
        ("npm", "package-lock.json"),
    )
    for command, marker in candidates:
        executable = shutil.which(command)
        if executable and (directory / marker).exists():
            return executable
    return shutil.which("npm")


def _safe_destination(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    destination = (root / normalized).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path escapes the temporary validation root.") from exc
    return destination


def _bounded_output(value: bytes | str, maximum: int) -> tuple[str, bool]:
    raw = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
    truncated = len(raw) > maximum
    return raw[:maximum].decode("utf-8", errors="replace"), truncated


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _blocked(started: float, message: str) -> ValidationExecution:
    return ValidationExecution(
        status=ValidationExecutionStatus.BLOCKED,
        duration_ms=_elapsed_ms(started),
        message=message,
    )
