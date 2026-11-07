"""Isolated local process Sandbox implementation (RFC-0001 §3.3, §6.1, §9 D2)."""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator

from resolveqa.contracts import ExecResult


def _discover_default_base_root() -> Path:
    """Locate repository root by searching upwards for pyproject.toml or falling back safely."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() or (parent / ".git").exists():
            return parent
    return here.parents[3]


_SECRET_PATTERNS = [
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{8,})\b"),
    re.compile(r"\b(github_pat_[A-Za-z0-9_]{8,})\b"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"\b(AIza[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
]


def redact_secrets(text: str) -> str:
    """Scrub recognizable token patterns from captured output (RNF-01)."""
    if not text:
        return ""
    scrubbed = text
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED_SECRET]", scrubbed)
    return scrubbed


def _terminate_process_group(proc: subprocess.Popen[bytes], grace_s: float = 0.2) -> None:
    """Terminate an entire process group started with start_new_session=True (SIGTERM then SIGKILL)."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        pgid = proc.pid

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.02)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    with contextlib.suppress(Exception):
        proc.wait(timeout=1.0)


class LocalSandbox:
    """Execute target repository commands in an isolated temporary copy with a clean environment."""

    def __init__(self, base_root: Path | str | None = None, default_timeout_s: float = 600.0) -> None:
        self.base_root = Path(base_root).resolve() if base_root is not None else _discover_default_base_root()
        self.default_timeout_s = float(default_timeout_s)

    def resolve_workdir(self, workdir_ref: str | Path) -> Path:
        """Resolve a relative repository reference strictly inside `base_root`, rejecting '..', absolutes, and external symlinks."""
        raw_str = str(workdir_ref).strip()
        if not raw_str:
            raise ValueError("workdir_ref must be a non-empty relative path inside base_root")

        raw_path = Path(raw_str)
        if raw_path.is_absolute() or raw_str.startswith(("/", "\\")):
            raise ValueError(f"Absolute paths are not allowed for workdir_ref: {workdir_ref!r}")

        if ".." in raw_path.parts or raw_path.parts == (".",):
            raise ValueError(f"Parent traversal ('..') or current root ('.') is not allowed in workdir_ref: {workdir_ref!r}")

        current = self.base_root
        for part in raw_path.parts:
            current = current / part
            if current.is_symlink():
                resolved_target = current.resolve()
                if not resolved_target.is_relative_to(self.base_root):
                    raise ValueError(
                        f"Symlink in workdir_ref points outside base_root: {workdir_ref!r} -> {resolved_target}"
                    )

        resolved = (self.base_root / raw_path).resolve()
        if not resolved.is_relative_to(self.base_root) or resolved == self.base_root:
            raise ValueError(f"workdir_ref resolves outside base_root: {workdir_ref!r}")

        if not resolved.is_dir():
            raise FileNotFoundError(f"Sandbox workdir_ref does not exist or is not a directory: {workdir_ref!r}")

        return resolved

    @staticmethod
    def _validate_no_external_symlinks(source_dir: Path) -> None:
        """Ensure no symlink inside `source_dir` resolves outside `source_dir`."""
        resolved_root = source_dir.resolve()
        for entry in source_dir.rglob("*"):
            if entry.is_symlink():
                target = entry.resolve()
                if not target.is_relative_to(resolved_root):
                    raise ValueError(
                        f"Symlink inside workdir points outside repository tree: {entry.relative_to(source_dir)} -> {target}"
                    )

    @contextlib.contextmanager
    def isolated_copy(self, workdir_ref: str | Path) -> Iterator[Path]:
        """Yield a temporary isolated copy of `workdir_ref` (preserving only internal symlinks)."""
        source_dir = self.resolve_workdir(workdir_ref)
        self._validate_no_external_symlinks(source_dir)
        with tempfile.TemporaryDirectory(prefix="resolveqa_sandbox_") as tmp_root:
            dest_dir = Path(tmp_root) / "workspace"
            shutil.copytree(
                source_dir,
                dest_dir,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "*.pyc"),
            )
            yield dest_dir

    @staticmethod
    def build_clean_env(workspace_dir: Path) -> dict[str, str]:
        """Construct a minimal environment free of Git tokens, cloud credentials, or LLM keys."""
        python_bin_dir = str(Path(sys.executable).resolve().parent)
        safe_path = f"{python_bin_dir}:/usr/local/bin:/usr/bin:/bin"
        return {
            "PATH": safe_path,
            "HOME": str(workspace_dir),
            "TMPDIR": str(workspace_dir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(workspace_dir),
        }

    def exec(
        self,
        workdir_ref: str,
        command: str,
        timeout_s: float | None = None,
    ) -> ExecResult:
        """Execute `command` inside an isolated temporary copy of `workdir_ref` in a new process session."""
        effective_timeout = float(timeout_s if timeout_s is not None else self.default_timeout_s)
        if effective_timeout <= 0:
            raise ValueError("timeout_s must be positive")

        if not isinstance(command, str) or not command.strip():
            return ExecResult(exit_code=2, stdout_ref="", stderr_ref="Invalid empty command", timed_out=False)

        try:
            argv = shlex.split(command)
        except ValueError as err:
            return ExecResult(
                exit_code=2,
                stdout_ref="",
                stderr_ref=redact_secrets(f"Invalid command syntax: {err}"),
                timed_out=False,
            )

        if not argv:
            return ExecResult(exit_code=2, stdout_ref="", stderr_ref="Empty command argument list", timed_out=False)

        if argv[0] in {"python", "python3"}:
            argv[0] = sys.executable

        try:
            with self.isolated_copy(workdir_ref) as workspace_dir:
                clean_env = self.build_clean_env(workspace_dir)
                with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
                    try:
                        proc = subprocess.Popen(
                            argv,
                            cwd=str(workspace_dir),
                            env=clean_env,
                            shell=False,
                            stdin=subprocess.DEVNULL,
                            stdout=out_f,
                            stderr=err_f,
                            start_new_session=True,
                        )
                    except OSError as exc:
                        return ExecResult(
                            exit_code=127,
                            stdout_ref="",
                            stderr_ref=redact_secrets(str(exc)),
                            timed_out=False,
                        )

                    timed_out = False
                    try:
                        proc.wait(timeout=effective_timeout)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        _terminate_process_group(proc)
                    finally:
                        if proc.poll() is None:
                            _terminate_process_group(proc)

                    out_f.seek(0)
                    err_f.seek(0)
                    raw_out = out_f.read().decode("utf-8", errors="replace")
                    raw_err = err_f.read().decode("utf-8", errors="replace")

                    if timed_out:
                        return ExecResult(
                            exit_code=124,
                            stdout_ref=redact_secrets(raw_out),
                            stderr_ref=redact_secrets(raw_err or f"Command timed out after {effective_timeout}s"),
                            timed_out=True,
                        )
                    return ExecResult(
                        exit_code=int(proc.returncode if proc.returncode is not None else 1),
                        stdout_ref=redact_secrets(raw_out),
                        stderr_ref=redact_secrets(raw_err),
                        timed_out=False,
                    )
        except Exception as err:
            return ExecResult(
                exit_code=2,
                stdout_ref="",
                stderr_ref=redact_secrets(str(err)),
                timed_out=False,
            )


Sandbox = LocalSandbox
