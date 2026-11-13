#!/usr/bin/env node
/**
 * TEMPORARY FOR PITCH DEMO — remove after the presentation.
 *
 * Seeds ResolveQA cases on a live/local backend so the production front can
 * poll them via RESOLVEQA_CASE_IDS. The demo backend is ephemeral: cases die
 * on reboot, which is why CI re-seeds on every deploy while this stays in.
 *
 * DELETE checklist (post-pitch):
 * 1. Remove the "Seed backend cases" step from .github/workflows/deploy-aws.yml
 * 2. Delete this file (scripts/seed-backend-cases.mjs)
 * 3. Drop the pitch-seed notes from infra/aws/README.md
 * 4. Clear repository variable RESOLVEQA_CASE_IDS if it only held pitch IDs
 *
 * Usage:
 *   RESOLVEQA_API_URL=https://d2f79ulrlhg51j.cloudfront.net node scripts/seed-backend-cases.mjs
 *
 * Prints CASE_IDS=id1,id2,... (machine-readable) and optionally appends to
 * $GITHUB_ENV when running inside GitHub Actions.
 */
const api = (process.env.RESOLVEQA_API_URL || "").replace(/\/$/, "");
const origin =
  process.env.RESOLVEQA_FRONT_ORIGIN ||
  "https://d10ry6ff7l79jo.cloudfront.net";

if (!api) {
  console.error("RESOLVEQA_API_URL is required");
  process.exit(1);
}

console.log(
  "TEMPORARY pitch seed: creating demo cases on the ephemeral backend.",
);

const reports = [
  ["Acme Commerce", "acme/checkout", "Cupom de 10% não altera o total da compra"],
  ["Acme Commerce", "acme/checkout", "Exportação de CSV gera arquivo vazio"],
  ["Acme Commerce", "acme/profile", "Sessão expira ao atualizar o perfil"],
  ["Acme Commerce", "acme/search", "Busca ignora palavras com acento"],
  ["Acme Commerce", "acme/uploads", "Upload de comprovante retorna erro 500"],
  ["Acme Commerce", "acme/orders", "Data do pedido desconsidera o fuso horário"],
  ["Acme Commerce", "acme/checkout", "Botão salvar não responde no Firefox"],
  ["Acme Commerce", "acme/checkout", "Resumo do checkout diverge do pedido"],
];

const ids = [];
for (const [client_id, repo_ref, report_text] of reports) {
  const res = await fetch(`${api}/api/cases`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      Origin: origin,
    },
    body: JSON.stringify({ client_id, repo_ref, report_text }),
  });
  const text = await res.text();
  if (!res.ok) {
    console.error(`HTTP ${res.status}: ${text}`);
    process.exit(1);
  }
  const payload = JSON.parse(text);
  const id = payload?.case?.case_id;
  if (!id) {
    console.error("Response missing case.case_id:", text);
    process.exit(1);
  }
  ids.push(id);
  console.log(`${id}\t${payload.case.state}\t${report_text}`);
}

const joined = ids.join(",");
console.log(`CASE_IDS=${joined}`);

if (process.env.GITHUB_ENV) {
  const { appendFileSync } = await import("node:fs");
  appendFileSync(
    process.env.GITHUB_ENV,
    `RESOLVEQA_CASE_IDS=${joined}\n`,
    "utf8",
  );
  console.log("Wrote RESOLVEQA_CASE_IDS to GITHUB_ENV for this deploy job.");
}

if (process.env.GITHUB_STEP_SUMMARY) {
  const { appendFileSync } = await import("node:fs");
  appendFileSync(
    process.env.GITHUB_STEP_SUMMARY,
    [
      "## TEMPORARY pitch seed",
      "",
      "Demo cases were created on the ephemeral backend and baked into this front export.",
      "**Remove this seed step after the pitch presentation.**",
      "",
      `\`${ids.length}\` case ids seeded.`,
      "",
    ].join("\n"),
    "utf8",
  );
}
