"""Isolated local process Sandbox implementation (RFC-0001 §3.3, §6.1, §9 D2)."""

from __future__ import annotations

import contextlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

from resolveqa.contracts import ExecResult

REPO_ROOT = Path(__file__).resolve().parents[3]

_SECRET_PATTERNS = [
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{8,})\b"),
    re.compile(r"\b(github_pat_[A-Za-z0-9_]{8,})\b"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"\b(AIza[A-Za-z0-9_-]{8,})\b"),
]


def redact_secrets(text: str) -> str:
    """Scrub recognizable token patterns from captured output (RNF-01)."""
    if not text:
        return ""
    scrubbed = text
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED_SECRET]", scrubbed)
    return scrubbed


class LocalSandbox:
    """Execute target repository commands in an isolated temporary copy with a clean environment."""

    def __init__(self, base_root: Path | str | None = None, default_timeout_s: float = 600.0) -> None:
        self.base_root = Path(base_root).resolve() if base_root is not None else REPO_ROOT
        self.default_timeout_s = float(default_timeout_s)

    def resolve_workdir(self, workdir_ref: str | Path) -> Path:
        """Resolve a repository reference or path to an existing directory."""
        candidate = Path(workdir_ref)
        if not candidate.is_absolute():
            candidate = (self.base_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.is_dir():
            raise FileNotFoundError(f"Sandbox workdir_ref does not exist or is not a directory: {workdir_ref}")
        return candidate

    @contextlib.contextmanager
    def isolated_copy(self, workdir_ref: str | Path) -> Iterator[Path]:
        """Yield a temporary isolated copy of `workdir_ref` that is cleaned up on exit."""
        source_dir = self.resolve_workdir(workdir_ref)
        with tempfile.TemporaryDirectory(prefix="resolveqa_sandbox_") as tmp_root:
            dest_dir = Path(tmp_root) / "workspace"
            shutil.copytree(
                source_dir,
                dest_dir,
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
        """Execute `command` inside an isolated temporary copy of `workdir_ref` without shell."""
        effective_timeout = float(timeout_s if timeout_s is not None else self.default_timeout_s)
        if effective_timeout <= 0:
            raise ValueError("timeout_s must be positive")

        if not isinstance(command, str) or not command.strip():
            return ExecResult(
                exit_code=2,
                stdout_ref="",
                stderr_ref="Invalid empty command",
                timed_out=False,
            )

        try:
            source_dir = self.resolve_workdir(workdir_ref)
        except Exception as err:
            return ExecResult(
                exit_code=2,
                stdout_ref="",
                stderr_ref=redact_secrets(str(err)),
                timed_out=False,
            )

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
            return ExecResult(
                exit_code=2,
                stdout_ref="",
                stderr_ref="Empty command argument list",
                timed_out=False,
            )

        if argv[0] in {"python", "python3"}:
            argv[0] = sys.executable

        with self.isolated_copy(source_dir) as workspace_dir:
            clean_env = self.build_clean_env(workspace_dir)
            try:
                completed = subprocess.run(
                    argv,
                    cwd=str(workspace_dir),
                    env=clean_env,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                    check=False,
                )
                return ExecResult(
                    exit_code=int(completed.returncode),
                    stdout_ref=redact_secrets(completed.stdout or ""),
                    stderr_ref=redact_secrets(completed.stderr or ""),
                    timed_out=False,
                )
            except subprocess.TimeoutExpired as exc:
                raw_out = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                raw_err = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                return ExecResult(
                    exit_code=124,
                    stdout_ref=redact_secrets(raw_out),
                    stderr_ref=redact_secrets(raw_err or f"Command timed out after {effective_timeout}s"),
                    timed_out=True,
                )
            except OSError as exc:
                return ExecResult(
                    exit_code=127,
                    stdout_ref="",
                    stderr_ref=redact_secrets(str(exc)),
                    timed_out=False,
                )


Sandbox = LocalSandbox
