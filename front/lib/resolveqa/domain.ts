import { z } from "zod";

export const states = [
  "created",
  "triaging",
  "triaged",
  "reproducing",
  "reproduced",
  "fixing",
  "fixed",
  "verifying",
  "verified",
  "needs_info",
  "blocked",
  "infra_error",
] as const;
export type CaseState = (typeof states)[number];
export const caseSchema = z.object({
  case_id: z.string().min(1),
  client_id: z.string().min(1),
  repo_ref: z.string().min(1),
  report_text: z.string().min(1),
  state: z.enum(states),
  channel: z.enum(["api", "form", "simulated_chat"]),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  attempts: z.object({
    fix: z.number().int().nonnegative(),
    llm_calls: z.number().int().nonnegative(),
  }),
  evidence_ids: z.array(z.string()),
  terminal_reason: z
    .union([z.string(), z.record(z.unknown())])
    .nullable()
    .optional(),
  base_revision: z.string().nullable().optional(),
  fix_revision: z.string().nullable().optional(),
});
export type Run = z.infer<typeof caseSchema>;
export const eventSchema = z
  .object({
    event_id: z.string().min(1),
    case_id: z.string().min(1),
    seq: z.number().int().positive(),
    ts: z.string().datetime({ offset: true }),
    source: z.enum([
      "intake",
      "orchestrator",
      "triage",
      "reproduction",
      "fix",
      "verification",
      "delivery",
      "reply",
    ]),
    type: z.enum([
      "CaseCreated",
      "StateChanged",
      "EvidenceAdded",
      "LimitReached",
      "MessageSent",
      "ReplayStarted",
    ]),
    from_state: z.enum(states).nullable().optional(),
    to_state: z.enum(states).nullable().optional(),
    reason: z.string().nullable().optional(),
    evidence_refs: z.array(z.string()).default([]),
    replay_of: z
      .object({ case_id: z.string(), original_ts: z.string() })
      .nullable()
      .optional(),
  })
  .superRefine((e, ctx) => {
    if (
      e.type === "StateChanged" &&
      (!e.from_state || !e.to_state || e.from_state === e.to_state)
    )
      ctx.addIssue({ code: "custom", message: "Transição inválida" });
    if (e.type !== "StateChanged" && (e.from_state || e.to_state))
      ctx.addIssue({
        code: "custom",
        message: "Somente StateChanged pode alterar o estado",
      });
    if (e.type === "ReplayStarted" && !e.replay_of)
      ctx.addIssue({ code: "custom", message: "Replay sem origem" });
  });
export type RunEvent = z.infer<typeof eventSchema>;
export const playbookSchema = z.object({
  id: z.string(),
  name: z.string().min(1).max(120),
  company: z.string().min(1),
  repository: z.string().min(1),
  instructions: z.string().min(1).max(20000),
  enabled: z.boolean(),
  updated_at: z.string(),
});
export type Playbook = z.infer<typeof playbookSchema>;
export const spanSchema = z.object({
  id: z.string(),
  case_id: z.string(),
  name: z.string(),
  start_ms: z.number().nonnegative(),
  duration_ms: z.number().nonnegative(),
  status: z.enum(["ok", "error", "running"]),
});
export type Span = z.infer<typeof spanSchema>;
export const documentSchema = z.object({
  id: z.string(),
  title: z.string(),
  case_id: z.string(),
  path: z.string(),
  summary: z.string(),
  updated_at: z.string(),
});
export type ProjectDocument = z.infer<typeof documentSchema>;
export const snapshotSchema = z.object({
  cases: z.array(caseSchema),
  events: z.array(eventSchema),
  spans: z.array(spanSchema).default([]),
  documents: z.array(documentSchema).default([]),
});
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Lane = "intake" | "active" | "review" | "done" | "attention";
export const lanes: { id: Lane; title: string; description: string }[] = [
  { id: "intake", title: "Entrada", description: "Relatos recebidos" },
  { id: "active", title: "Em execução", description: "Agentes trabalhando" },
  { id: "review", title: "Verificação", description: "Validação independente" },
  { id: "done", title: "Concluído", description: "Correções verificadas" },
  { id: "attention", title: "Atenção", description: "Intervenção necessária" },
];
export const labels: Record<CaseState, string> = {
  created: "Recebido",
  triaging: "Em triagem",
  triaged: "Triado",
  reproducing: "Reproduzindo",
  reproduced: "Reproduzido",
  fixing: "Corrigindo",
  fixed: "Correção pronta",
  verifying: "Verificando",
  verified: "Verificado",
  needs_info: "Precisa de informação",
  blocked: "Bloqueado",
  infra_error: "Serviço indisponível",
};
export const terminal = (s: CaseState) =>
  ["verified", "needs_info", "blocked", "infra_error"].includes(s);
export function laneOf(state: CaseState): Lane {
  return state === "created"
    ? "intake"
    : state === "verified"
      ? "done"
      : ["fixed", "verifying"].includes(state)
        ? "review"
        : terminal(state)
          ? "attention"
          : "active";
}
export function agentOf(s: CaseState) {
  return ["created", "triaging", "triaged", "needs_info"].includes(s)
    ? "Triage"
    : ["reproducing", "reproduced"].includes(s)
      ? "Reproducer"
      : ["fixing", "fixed"].includes(s)
        ? "Fixer"
        : "Verifier";
}
export function duration(run: Run) {
  return Math.max(0, Date.parse(run.updated_at) - Date.parse(run.created_at));
}
export function elapsed(ms: number) {
  return ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${Math.floor(ms / 60000)} min ${Math.floor((ms % 60000) / 1000)} s`;
}
export function reasonText(run: Run) {
  return typeof run.terminal_reason === "string"
    ? run.terminal_reason
    : run.terminal_reason
      ? Object.entries(run.terminal_reason)
          .map(
            ([k, v]) =>
              `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`,
          )
          .join(" · ")
      : "";
}
export function percentile(values: number[], p: number) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length
    ? sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)]
    : 0;
}

/** Immutable domain update. Old, duplicate and out-of-order transitions cannot roll a case back. */
export function applyEvent(snapshot: Snapshot, event: RunEvent): Snapshot {
  if (snapshot.events.some((e) => e.event_id === event.event_id))
    return snapshot;
  const seq = Math.max(
    0,
    ...snapshot.events
      .filter((e) => e.case_id === event.case_id)
      .map((e) => e.seq),
  );
  if (event.seq <= seq) return snapshot;
  return {
    ...snapshot,
    events: [event, ...snapshot.events].slice(0, 1000),
    cases: snapshot.cases.map((c) => {
      if (
        c.case_id !== event.case_id ||
        Date.parse(event.ts) < Date.parse(c.updated_at)
      )
        return c;
      const updated = {
        ...c,
        evidence_ids: [...new Set([...c.evidence_ids, ...event.evidence_refs])],
      };
      return event.type === "StateChanged" && event.to_state
        ? {
            ...updated,
            state: event.to_state,
            updated_at: event.ts,
            terminal_reason:
              terminal(event.to_state) && event.to_state !== "verified"
                ? event.reason || "Consulte as evidências do caso."
                : null,
          }
        : updated;
    }),
  };
}
