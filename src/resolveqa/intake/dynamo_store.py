"""DynamoDB case store for the cloud spine (optional boto3 dependency)."""

from __future__ import annotations

import json
from typing import Any, Optional

from resolveqa.contracts import ContractValidationError, RunState


class DynamoCaseStore:
    """Case store backed by a DynamoDB table with primary key case_id."""

    def __init__(
        self,
        table_name: str,
        *,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                import boto3
            except ImportError as err:
                raise RuntimeError(
                    "boto3 is required for DynamoCaseStore; install resolveqa[cloud]"
                ) from err
            kwargs: dict[str, Any] = {}
            if region:
                kwargs["region_name"] = region
            resource = boto3.resource("dynamodb", **kwargs)
            self._table = resource.Table(table_name)
        else:
            self._table = client.Table(table_name) if hasattr(client, "Table") else client
        self.table_name = table_name

    def put(self, case: RunState) -> None:
        if not isinstance(case, RunState):
            raise ContractValidationError(
                f"DynamoCaseStore.put expects RunState, got {type(case).__name__}."
            )
        item = {
            "case_id": case.case_id,
            "client_id": case.client_id,
            "updated_at": case.updated_at,
            "created_at": case.created_at,
            "state": case.state.value,
            "payload": json.dumps(case.to_dict(), ensure_ascii=False, sort_keys=True),
        }
        self._table.put_item(Item=item)

    def get(self, case_id: str) -> Optional[RunState]:
        if not isinstance(case_id, str) or not case_id.strip():
            return None
        resp = self._table.get_item(Key={"case_id": case_id.strip()})
        item = resp.get("Item")
        if not item:
            return None
        return RunState.from_dict(json.loads(item["payload"]))

    def list_cases(self) -> list[RunState]:
        cases: list[RunState] = []
        scan_kwargs: dict[str, Any] = {}
        while True:
            resp = self._table.scan(**scan_kwargs)
            for item in resp.get("Items", []):
                try:
                    cases.append(RunState.from_dict(json.loads(item["payload"])))
                except (KeyError, json.JSONDecodeError, ContractValidationError, ValueError):
                    continue
            token = resp.get("LastEvaluatedKey")
            if not token:
                break
            scan_kwargs["ExclusiveStartKey"] = token
        cases.sort(key=lambda c: c.updated_at, reverse=True)
        return cases
