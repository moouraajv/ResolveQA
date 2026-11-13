"""File-backed case store under runs/_cases/<case_id>.json (local / shared disk)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from resolveqa.contracts import ContractValidationError, RunState
from resolveqa.store.events import validate_case_id


class FileCaseStore:
    """Thread-safe JSON case store for local cloud spine and shared volumes."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve() / "_cases"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, case_id: str) -> Path:
        safe = validate_case_id(case_id)
        return self.root / f"{safe}.json"

    def put(self, case: RunState) -> None:
        if not isinstance(case, RunState):
            raise ContractValidationError(
                f"FileCaseStore.put expects RunState, got {type(case).__name__}."
            )
        path = self._path(case.case_id)
        tmp = path.with_suffix(".tmp")
        payload = json.dumps(case.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        with self._lock:
            tmp.write_text(payload + "\n", encoding="utf-8")
            tmp.replace(path)

    def get(self, case_id: str) -> Optional[RunState]:
        path = self._path(case_id)
        with self._lock:
            if not path.is_file():
                return None
            raw = path.read_text(encoding="utf-8")
        return RunState.from_dict(json.loads(raw))

    def list_cases(self) -> list[RunState]:
        with self._lock:
            paths = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            cases: list[RunState] = []
            for path in paths:
                try:
                    cases.append(RunState.from_dict(json.loads(path.read_text(encoding="utf-8"))))
                except (OSError, json.JSONDecodeError, ContractValidationError, ValueError):
                    continue
            return cases
