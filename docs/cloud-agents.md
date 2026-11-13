# Cloud agents spine

Production path: **create → SQS → worker → Orchestrator → snapshot/SSE**.

## Local two-process smoke

```bash
export RESOLVEQA_ROOT=$PWD
export RESOLVEQA_CASE_STORE=file
export RESOLVEQA_QUEUE=file
export RESOLVEQA_ALLOW_OPERATOR_ADVANCE=0
export RESOLVEQA_AGENT_MODE=general   # or dogfood for deterministic Fix only
export PYTHONPATH=src

# Terminal A — API
python scripts/run_server.py --host 127.0.0.1 --port 8080

# Terminal B — worker (mock LLM unless RESOLVEQA_LIVE=1)
python -m resolveqa.worker --store file --queue file --root "$PWD"
```

Create a dogfood case:

```bash
curl -s -X POST http://127.0.0.1:8080/api/cases \
  -H 'content-type: application/json' \
  -d '{
    "client_id":"resolveqa",
    "repo_ref":"targets/resolveqa-checkout",
    "report_text":"Comprei R$ 200,00 no site, apliquei o cupom DESC10 de 10% e o total continuou R$ 200,00. Deveria ser R$ 180,00."
  }'
```

Expect **202** with `queued: true`. Poll `/api/snapshot` until `state=verified`.

## AWS

See [`infra/aws/cloud-agents-overlay.yaml`](../infra/aws/cloud-agents-overlay.yaml):

- DynamoDB `cases`
- SQS + DLQ
- S3 evidence bucket
- EFS shared `runs/`
- Dedicated worker EC2 (`python -m resolveqa.worker`)
- Managed policy for the API role (`sqs:SendMessage` + DDB)

API env on the existing CloudFront EC2:

```
RESOLVEQA_CASE_STORE=file   # on EFS
RESOLVEQA_QUEUE=sqs
RESOLVEQA_SQS_URL=...
RESOLVEQA_ALLOW_OPERATOR_ADVANCE=0
```

## Front

`RESOLVEQA_MODE=production` with:

```
RESOLVEQA_SNAPSHOT_PATH=/api/snapshot
RESOLVEQA_EVENTS_PATH=/api/events
```

No Avançar/Reproduzir/drag in production — only real worker progress.
