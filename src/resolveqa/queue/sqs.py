"""SQS-backed case queue for the cloud worker."""

from __future__ import annotations

import json
from typing import Any, Optional

from .protocol import CaseJob


class SqsCaseQueue:
    """Case queue using an SQS queue URL (DLQ configured in CloudFormation)."""

    def __init__(
        self,
        queue_url: str,
        *,
        region: str | None = None,
        client: Any | None = None,
        visibility_timeout: int = 900,
    ) -> None:
        if client is None:
            try:
                import boto3
            except ImportError as err:
                raise RuntimeError(
                    "boto3 is required for SqsCaseQueue; install resolveqa[cloud]"
                ) from err
            kwargs: dict[str, Any] = {}
            if region:
                kwargs["region_name"] = region
            client = boto3.client("sqs", **kwargs)
        self._client = client
        self.queue_url = queue_url
        self.visibility_timeout = visibility_timeout

    def enqueue(self, case_id: str, *, attempt: int = 1) -> None:
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        body = json.dumps({"case_id": case_id.strip(), "attempt": int(attempt)}, sort_keys=True)
        self._client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=body,
            MessageAttributes={
                "case_id": {"DataType": "String", "StringValue": case_id.strip()},
            },
        )

    def dequeue(self, *, wait_seconds: int = 5) -> Optional[CaseJob]:
        resp = self._client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=max(0, min(20, int(wait_seconds))),
            VisibilityTimeout=self.visibility_timeout,
            MessageAttributeNames=["All"],
        )
        messages = resp.get("Messages") or []
        if not messages:
            return None
        msg = messages[0]
        try:
            payload = json.loads(msg["Body"])
            case_id = str(payload["case_id"]).strip()
            attempt = int(payload.get("attempt", 1))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
            # Poison message: delete so it does not loop forever without DLQ attributes.
            self._client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=msg["ReceiptHandle"],
            )
            raise ValueError(f"invalid SQS case job body: {err}") from err
        return CaseJob(
            case_id=case_id,
            attempt=attempt,
            receipt_handle=msg["ReceiptHandle"],
        )

    def ack(self, job: CaseJob) -> None:
        if not job.receipt_handle:
            return
        self._client.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=job.receipt_handle,
        )

    def nack(self, job: CaseJob, *, requeue: bool = True) -> None:
        if not job.receipt_handle:
            return
        if requeue:
            # Make visible immediately for another attempt.
            self._client.change_message_visibility(
                QueueUrl=self.queue_url,
                ReceiptHandle=job.receipt_handle,
                VisibilityTimeout=0,
            )
            return
        self.ack(job)
