import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyEvent,
  caseSchema,
  eventSchema,
  laneOf,
  percentile,
} from "../lib/resolveqa/domain.ts";
const time = "2026-11-08T03:00:00Z";
const run = {
  case_id: "case-1",
  client_id: "client-1",
  repo_ref: "acme/repo",
  channel: "api",
  report_text: "Cupom não altera total",
  state: "created",
  attempts: { fix: 0, llm_calls: 0 },
  created_at: time,
  updated_at: time,
  evidence_ids: [],
};
const snapshot = () => ({
  cases: [structuredClone(run)],
  events: [],
  spans: [],
  documents: [],
});
const event = (overrides = {}) =>
  eventSchema.parse({
    event_id: "event-1",
    case_id: "case-1",
    seq: 1,
    ts: "2026-11-08T03:00:05Z",
    source: "orchestrator",
    type: "StateChanged",
    from_state: "created",
    to_state: "fixing",
    evidence_refs: [],
    ...overrides,
  });
test("somente verified ocupa a coluna Concluído", () => {
  assert.equal(laneOf("verified"), "done");
  for (const state of ["blocked", "needs_info", "infra_error"])
    assert.equal(laneOf(state), "attention");
  for (const state of ["fixed", "verifying"])
    assert.equal(laneOf(state), "review");
});
test("transição recebida atualiza estado sem alterar o snapshot original", () => {
  const original = snapshot();
  const next = applyEvent(original, event());
  assert.equal(original.cases[0].state, "created");
  assert.equal(next.cases[0].state, "fixing");
});
test("reconexão SSE não aplica o mesmo event_id duas vezes", () => {
  const next = applyEvent(snapshot(), event());
  assert.equal(applyEvent(next, event()), next);
});
test("sequência atrasada não regride o caso", () => {
  const next = applyEvent(snapshot(), event({ seq: 3 }));
  assert.equal(
    applyEvent(next, event({ event_id: "old", seq: 2, to_state: "triaging" })),
    next,
  );
});
test("evento anterior ao snapshot não regride estado hidratado", () => {
  const original = snapshot();
  original.cases[0].state = "verified";
  original.cases[0].updated_at = "2026-11-08T04:00:00Z";
  assert.equal(applyEvent(original, event()).cases[0].state, "verified");
});
test("EvidenceAdded conserva o estado e incorpora evidências", () => {
  const ev = eventSchema.parse({
    event_id: "proof",
    case_id: "case-1",
    seq: 1,
    ts: time,
    type: "EvidenceAdded",
    source: "verification",
    evidence_refs: ["before-log", "after-log"],
  });
  const next = applyEvent(snapshot(), ev);
  assert.equal(next.cases[0].state, "created");
  assert.deepEqual(next.cases[0].evidence_ids, ["before-log", "after-log"]);
});
test("contratos recusam estados desconhecidos e transições malformadas", () => {
  assert.equal(
    caseSchema.safeParse({ ...run, state: "success" }).success,
    false,
  );
  assert.throws(() => event({ from_state: "fixing" }));
  assert.throws(() => event({ type: "EvidenceAdded" }));
  assert.throws(() => event({ seq: -1 }));
});
test("replay exige referência à execução de origem", () => {
  assert.equal(
    eventSchema.safeParse({
      event_id: "r",
      case_id: "case-1",
      seq: 1,
      ts: time,
      source: "orchestrator",
      type: "ReplayStarted",
    }).success,
    false,
  );
});
test("falhas terminais conservam o motivo recebido", () => {
  const next = applyEvent(
    snapshot(),
    event({ to_state: "infra_error", reason: "Sandbox indisponível" }),
  );
  assert.equal(next.cases[0].terminal_reason, "Sandbox indisponível");
});
test("percentis usam as amostras disponíveis", () => {
  assert.equal(percentile([10, 100, 30], 0.95), 100);
  assert.equal(percentile([], 0.95), 0);
});
