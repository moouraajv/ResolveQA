import {
  type Run,
  type Snapshot,
  type RunEvent,
  type Playbook,
  type CaseState,
  terminal,
} from "./domain";

export const demoTitles = [
  "Cupom de 10% não altera o total da compra",
  "Exportação de CSV gera arquivo vazio",
  "Sessão expira ao atualizar o perfil",
  "Busca ignora palavras com acento",
  "Upload de comprovante retorna erro 500",
  "Data do pedido desconsidera o fuso horário",
  "Botão salvar não responde no Firefox",
  "Resumo do checkout diverge do pedido",
];
export function makeRun(
  id: string,
  text: string,
  state: CaseState = "created",
  now = Date.now(),
): Run {
  return {
    case_id: id,
    client_id: "Acme Commerce",
    repo_ref: "acme/checkout",
    report_text: text,
    channel: "api",
    state,
    created_at: new Date(now - 95000).toISOString(),
    updated_at: new Date(now).toISOString(),
    attempts: { fix: 1, llm_calls: 4 },
    evidence_ids: terminal(state) ? [`evidence-${id}`] : [],
    terminal_reason:
      state === "needs_info"
        ? "Informe o navegador e os passos para reproduzir."
        : state === "infra_error"
          ? "Sandbox indisponível. A execução precisa ser repetida."
          : null,
    base_revision: "a81c04f",
    fix_revision: state === "verified" ? "c72b91e" : null,
  };
}
export function makeDemo(now = Date.now()): Snapshot {
  const statuses: CaseState[] = [
    "created",
    "created",
    "fixing",
    "reproducing",
    "verifying",
    "verified",
    "verified",
    "needs_info",
  ];
  const cases = demoTitles
    .map((t, i) => makeRun(`RQA-${1048 - i}`, t, statuses[i], now - i * 23000))
    .map((c, i) => ({
      ...c,
      created_at: new Date(
        Date.parse(c.updated_at) - (39000 + i * 13500),
      ).toISOString(),
    }));
  const events: RunEvent[] = cases.map((c, i) => ({
    event_id: `seed-${c.case_id}`,
    case_id: c.case_id,
    seq: 1,
    ts: c.updated_at,
    source: i < 2 ? "intake" : i < 4 ? "fix" : "verification",
    type: "CaseCreated",
    reason:
      i < 2
        ? "Relato recebido pelo agente de triagem."
        : "Contexto de demonstração carregado.",
    evidence_refs: c.evidence_ids,
  }));
  return {
    cases,
    events,
    spans: cases
      .filter((c) => terminal(c.state))
      .flatMap((c) => [
        {
          id: `${c.case_id}-t`,
          case_id: c.case_id,
          name: "Triage · classificar relato",
          start_ms: 0,
          duration_ms: 8200,
          status: "ok" as const,
        },
        {
          id: `${c.case_id}-r`,
          case_id: c.case_id,
          name: "Reproducer · confirmar teste RED",
          start_ms: 8200,
          duration_ms: 24900,
          status: "ok" as const,
        },
        {
          id: `${c.case_id}-f`,
          case_id: c.case_id,
          name: "Fixer · propor patch mínimo",
          start_ms: 33100,
          duration_ms: 38700,
          status: "ok" as const,
        },
        {
          id: `${c.case_id}-v`,
          case_id: c.case_id,
          name: "Verifier · comparar RED / GREEN",
          start_ms: 71800,
          duration_ms: 23200,
          status: c.state === "verified" ? ("ok" as const) : ("error" as const),
        },
      ]),
    documents: [
      {
        id: "doc-checkout",
        case_id: cases[5].case_id,
        title: "Regra de desconto no checkout",
        path: "docs/checkout.md",
        summary:
          "Documentação atualizada com o comportamento esperado e o teste de regressão. Exemplo simulado.",
        updated_at: cases[5].updated_at,
      },
    ],
  };
}
export const demoPlaybooks: Playbook[] = [
  {
    id: "pb-checkout",
    name: "Correções no checkout",
    company: "Acme Commerce",
    repository: "acme/checkout",
    instructions:
      "1. Reproduzir o relato com um teste novo.\n2. Limitar o patch à causa identificada.\n3. Verificar RED antes e GREEN depois.\n4. Atualizar docs/checkout.md.\n5. Entregar evidências para revisão humana.",
    enabled: true,
    updated_at: "2026-11-07T18:00:00Z",
  },
  {
    id: "pb-support",
    name: "Triagem com contexto insuficiente",
    company: "Acme Commerce",
    repository: "acme/support",
    instructions:
      "Solicitar passos, comportamento esperado e observado. Encerrar em needs_info quando faltar contexto. Nunca gerar patch sem reprodução.",
    enabled: true,
    updated_at: "2026-11-07T17:30:00Z",
  },
];
export function nextDemoEvent(snapshot: Snapshot): {
  run?: Run;
  event: RunEvent;
} {
  const flow: Partial<Record<CaseState, CaseState>> = {
    created: "triaging",
    triaging: "triaged",
    triaged: "reproducing",
    reproducing: "reproduced",
    reproduced: "fixing",
    fixing: "fixed",
    fixed: "verifying",
    verifying: "verified",
  };
  const run = snapshot.cases.find((c) => !terminal(c.state));
  const ts = new Date().toISOString();
  if (!run || snapshot.events.length % 12 === 0) {
    const c = makeRun(
      `RQA-${crypto.randomUUID().slice(0, 7)}`,
      demoTitles[snapshot.cases.length % demoTitles.length],
    );
    c.created_at = ts;
    c.updated_at = ts;
    return {
      run: c,
      event: {
        event_id: crypto.randomUUID(),
        case_id: c.case_id,
        seq: 1,
        ts,
        source: "intake",
        type: "CaseCreated",
        reason:
          "Agente criou um novo caso a partir de um relato. Demonstração.",
        evidence_refs: [],
      },
    };
  }
  const next = flow[run.state]!;
  return {
    event: {
      event_id: crypto.randomUUID(),
      case_id: run.case_id,
      seq:
        Math.max(
          0,
          ...snapshot.events
            .filter((e) => e.case_id === run.case_id)
            .map((e) => e.seq),
        ) + 1,
      ts,
      source:
        next === "verified" || next === "verifying"
          ? "verification"
          : next === "fixing" || next === "fixed"
            ? "fix"
            : next.startsWith("repro")
              ? "reproduction"
              : "triage",
      type: "StateChanged",
      from_state: run.state,
      to_state: next,
      reason:
        next === "verified"
          ? "Teste RED antes, GREEN depois e suíte aprovada. Demonstração."
          : "Agente avançou a etapa. Demonstração.",
      evidence_refs: next === "verified" ? [`verdict-${run.case_id}`] : [],
    },
  };
}
