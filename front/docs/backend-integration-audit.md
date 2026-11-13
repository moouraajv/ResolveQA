# Backend integration audit — 07/11/2026

Source confirmed by user: https://github.com/moouraajv/ResolveQA.git
Clone: ../work/ResolveQA-backend (read only inspection).

## Observed transport
- integration/backend-pipeline at f2abd1e: src/resolveqa/web/server.py exposes GET /health, POST /api/cases, GET /api/cases/<case_id> and simulated chat.
- POST body: {client_id, repo_ref, report_text}; response {case: RunState, storage: ephemeral-in-memory}.
- GET by id returns {case, storage}. There is no list route in the observed server.
- feat/backend-aws-runtime at 86dfcd1 packages the intake/chat surface; not an implementation of full agents or observability.
- main contains contracts and sandbox/LLM work but not the integrated HTTP entry.

## Existing domain contracts
RunState: case_id, client_id, repo_ref, channel, report_text, state, attempts, evidence_ids, base_revision, fix_revision, created_at, updated_at, terminal_reason.
Events: event_id, case_id, seq, ts, source, type, from_state, to_state, reason, evidence_refs, replay_of.
Types: CaseCreated, StateChanged, EvidenceAdded, LimitReached, MessageSent, ReplayStarted.
States: created, triaging, triaged, reproducing, reproduced, fixing, fixed, verifying, verified, needs_info, blocked, infra_error.

## Required integration work
No endpoints for metrics, spans, log querying, playbooks CRUD, case listing or event streaming were found in the inspected branches. A backend gateway must expose these before real production operation can be claimed.
The frontend should implement explicit demo and production adapters behind the same domain interface. Production must display empty, unsupported, disconnected and retry states; it must never substitute demo data silently.
Existing create/get case APIs can be connected directly through a server-side gateway or configured CORS. Do not expose origin verification secrets in the browser.
Production board should hydrate a snapshot, deduplicate event_id, enforce per-case seq, recover gaps with snapshot refresh, serialize animations and cancel on mode switch. Domain state follows backend events; animation only visualizes it. Terminal failure states belong in an attention lane, never in verified.
Demo should drive the identical event ingestion and animation queue with explicitly synthetic data, including agent-created cards, verification failure and information-needed cases.
Playbooks should persist locally only in demo; production mutations require actual endpoint confirmation. Observability metrics must use real durations/counts in production; missing spans are not invented.

## Current step
User requested image approval before UI implementation. Visual references are pending approval. Existing app routes have not been modified in this step.
