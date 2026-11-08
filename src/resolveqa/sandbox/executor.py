"""Isolated local process Sandbox implementation (RFC-0001 §3.3, §6.1, §9 D2).

ISOLATION BOUNDARIES AND KNOWN MVP LIMITATIONS (D2-a):
- Process & Working Directory Isolation: Commands run in a temporary directory copy
  restricted to paths inside `base_root` (rejecting absolute paths, `..`, symlinks with
  absolute targets, and external symlinks), in a dedicated process session
  (`start_new_session=True`) whose full process group (`os.killpg`) is unconditionally
  terminated both on timeout and on normal leader exit before temporary directory cleanup,
  with a sanitized environment free of host Git tokens, cloud credentials, or LLM API keys,
  and bounded in-memory stdout/stderr capture (zero unbounded disk temp files).
- Non-Goals / Roadmap Boundaries (D2-b, PRD §7): `LocalSandbox` runs under the same OS
  user (`uid`/`gid`), without Linux network namespace isolation (`unshare -n`), and
  without filesystem chroot/mount namespace isolation (so subprocesses still share OS-level
  access to private files of the same user — e.g. mode `0600` — as well as world-readable
  absolute paths on the host). Dedicated OS users, containers, and network namespace
  isolation (`unshare -n`) belong to the roadmap.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import IO, Iterator

from resolveqa.contracts import ExecResult

DEFAULT_MAX_OUTPUT_BYTES = 65536
TRUNCATION_SUFFIX = "\n...[truncated: output exceeded max_output_bytes]"


def _discover_default_base_root() -> Path:
    """Locate repository root by searching upwards for pyproject.toml or falling back safely."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() or (parent / ".git").exists():
            return parent
    return here.parents[3]


def _load_max_output_bytes(base_root: Path) -> int:
    limits_file = base_root / "config" / "limits.json"
    if limits_file.is_file():
        with contextlib.suppress(Exception):
            data = json.loads(limits_file.read_text(encoding="utf-8"))
            return int(data.get("max_output_bytes", DEFAULT_MAX_OUTPUT_BYTES))
    return DEFAULT_MAX_OUTPUT_BYTES


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


class _BoundedPipeReader:
    """Read from a pipe stream into memory up to `max_bytes`, discarding any excess bytes without disk usage."""

    def __init__(self, stream: IO[bytes] | None, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._chunks: list[bytes] = []
        self._collected = 0
        self.truncated = False
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        if self._stream is None:
            return
        try:
            while True:
                chunk = self._stream.read(4096)
                if not chunk:
                    break
                if self._collected <= self._max_bytes:
                    remaining = (self._max_bytes + 1) - self._collected
                    take = chunk[:remaining]
                    self._chunks.append(take)
                    self._collected += len(take)
                    if self._collected > self._max_bytes:
                        self.truncated = True
                else:
                    self.truncated = True
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                self._stream.close()

    def finish(self, timeout_s: float = 0.5) -> tuple[str, bool]:
        self._thread.join(timeout=timeout_s)
        raw = b"".join(self._chunks)
        if len(raw) > self._max_bytes or self.truncated:
            clipped = raw[: self._max_bytes].decode("utf-8", errors="replace") + TRUNCATION_SUFFIX
            return clipped, True
        return raw.decode("utf-8", errors="replace"), False


def _make_exec_result(
    exit_code: int,
    stdout_ref: str,
    stderr_ref: str,
    timed_out: bool,
) -> ExecResult:
    """Create the immutable contract result; truncation stays on LocalSandbox.last_output_truncated."""
    return ExecResult(
        exit_code=exit_code,
        stdout_ref=stdout_ref,
        stderr_ref=stderr_ref,
        timed_out=timed_out,
    )


def _pgid_has_live_processes(pgid: int) -> bool:
    """Return True if any non-zombie process still exists in process group `pgid`."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    proc_root = Path("/proc")
    if proc_root.is_dir():
        found_live = False
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            stat_path = entry / "stat"
            with contextlib.suppress(Exception):
                stat_text = stat_path.read_text(encoding="utf-8")
                rparen = stat_text.rfind(")")
                if rparen != -1:
                    fields = stat_text[rparen + 2 :].split()
                    # fields[0] is state ('Z' = zombie), fields[2] is pgrp
                    if len(fields) >= 3 and int(fields[2]) == pgid and fields[0] != "Z":
                        found_live = True
                        break
        return found_live
    return True


def _terminate_process_group(proc: subprocess.Popen[bytes], pgid: int, grace_s: float = 0.2) -> None:
    """Unconditionally terminate an entire process group started with start_new_session=True."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        with contextlib.suppress(Exception):
            proc.wait(timeout=0.2)
        return

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if not _pgid_has_live_processes(pgid):
            break
        time.sleep(0.02)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    kill_deadline = time.monotonic() + 0.5
    while time.monotonic() < kill_deadline:
        if not _pgid_has_live_processes(pgid):
            break
        time.sleep(0.02)

    with contextlib.suppress(Exception):
        proc.wait(timeout=0.5)


class LocalSandbox:
    """Execute target repository commands in an isolated temporary copy with a clean environment."""

    def __init__(
        self,
        base_root: Path | str | None = None,
        default_timeout_s: float = 600.0,
        max_output_bytes: int | None = None,
    ) -> None:
        self.base_root = Path(base_root).resolve() if base_root is not None else _discover_default_base_root()
        self.default_timeout_s = float(default_timeout_s)
        self.max_output_bytes = (
            int(max_output_bytes) if max_output_bytes is not None else _load_max_output_bytes(self.base_root)
        )
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.last_output_truncated: bool = False

    def resolve_workdir(self, workdir_ref: str | Path) -> Path:
        """Resolve a relative repository reference strictly inside `base_root`, rejecting '..', absolutes, and external/absolute symlinks."""
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
                raw_link = Path(os.readlink(current))
                if raw_link.is_absolute() or str(raw_link).startswith(("/", "\\")):
                    raise ValueError(
                        f"Symlink with absolute target is not allowed in workdir_ref: {workdir_ref!r} -> {raw_link}"
                    )
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
        """Ensure no symlink inside `source_dir` has an absolute target or resolves outside `source_dir`."""
        resolved_root = source_dir.resolve()
        for entry in source_dir.rglob("*"):
            if entry.is_symlink():
                raw_target = Path(os.readlink(entry))
                if raw_target.is_absolute() or str(raw_target).startswith(("/", "\\")):
                    raise ValueError(
                        f"Symlink with absolute target is not allowed inside workdir: {entry.relative_to(source_dir)} -> {raw_target}"
                    )
                target = entry.resolve()
                if not target.is_relative_to(resolved_root):
                    raise ValueError(
                        f"Symlink inside workdir points outside repository tree: {entry.relative_to(source_dir)} -> {target}"
                    )

    @contextlib.contextmanager
    def isolated_copy(self, workdir_ref: str | Path) -> Iterator[Path]:
        """Yield a temporary isolated copy of `workdir_ref` (preserving only validated relative internal symlinks)."""
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
        """Execute `command` inside an isolated temporary copy of `workdir_ref` with bounded output."""
        self.last_output_truncated = False
        effective_timeout = float(timeout_s if timeout_s is not None else self.default_timeout_s)
        if effective_timeout <= 0:
            raise ValueError("timeout_s must be positive")

        if not isinstance(command, str) or not command.strip():
            return _make_exec_result(2, "", "Invalid empty command", False)

        try:
            argv = shlex.split(command)
        except ValueError as err:
            return _make_exec_result(2, "", redact_secrets(f"Invalid command syntax: {err}"), False)

        if not argv:
            return _make_exec_result(2, "", "Empty command argument list", False)

        if argv[0] in {"python", "python3"}:
            argv[0] = sys.executable

        try:
            with self.isolated_copy(workdir_ref) as workspace_dir:
                clean_env = self.build_clean_env(workspace_dir)
                try:
                    proc = subprocess.Popen(
                        argv,
                        cwd=str(workspace_dir),
                        env=clean_env,
                        shell=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        start_new_session=True,
                    )
                except OSError as exc:
                    return _make_exec_result(127, "", redact_secrets(str(exc)), False)

                pgid = proc.pid
                out_reader = _BoundedPipeReader(proc.stdout, self.max_output_bytes)
                err_reader = _BoundedPipeReader(proc.stderr, self.max_output_bytes)

                timed_out = False
                try:
                    proc.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                finally:
                    # Unconditionally terminate the entire process group (both on timeout
                    # and when the group leader exits normally leaving background children)
                    # BEFORE the temporary workspace directory is removed.
                    _terminate_process_group(proc, pgid=pgid)

                raw_out, out_trunc = out_reader.finish()
                raw_err, err_trunc = err_reader.finish()
                self.last_output_truncated = out_trunc or err_trunc

                if timed_out:
                    return _make_exec_result(
                        exit_code=124,
                        stdout_ref=redact_secrets(raw_out),
                        stderr_ref=redact_secrets(raw_err or f"Command timed out after {effective_timeout}s"),
                        timed_out=True,
                    )
                return _make_exec_result(
                    exit_code=int(proc.returncode if proc.returncode is not None else 1),
                    stdout_ref=redact_secrets(raw_out),
                    stderr_ref=redact_secrets(raw_err),
                    timed_out=False,
                )
        except Exception as err:
            return _make_exec_result(2, "", redact_secrets(str(err)), False)


Sandbox = LocalSandbox
