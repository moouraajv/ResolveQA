import { startProductionPreview } from "./preview-helper.mjs";
import { chromium } from "playwright-core";
import { createServer } from "node:http";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
const ts = () => new Date().toISOString();
const run = (id, title) => ({
  case_id: id,
  client_id: "Test enterprise",
  repo_ref: "test/repo",
  channel: "api",
  report_text: title,
  state: "created",
  created_at: ts(),
  updated_at: ts(),
  attempts: { fix: 0, llm_calls: 0 },
  evidence_ids: [],
});
const cases = [run("SSE-1", "Caso controlado recebido pelo stream")];
const events = [
  {
    event_id: "created-1",
    case_id: "SSE-1",
    seq: 1,
    ts: ts(),
    source: "intake",
    type: "CaseCreated",
    evidence_refs: [],
  },
];
const streams = new Set();
let unavailable = false;
const server = createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") {
    res.writeHead(204).end();
    return;
  }
  if (unavailable) {
    res.writeHead(503).end();
    return;
  }
  if (req.url === "/stream") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    res.write(": connected\n\n");
    streams.add(res);
    req.on("close", () => streams.delete(res));
    return;
  }
  res.setHeader("Content-Type", "application/json");
  if (req.url === "/health") return res.end(JSON.stringify({ ok: true }));
  if (req.url === "/snapshot")
    return res.end(JSON.stringify({ cases, events, spans: [], documents: [] }));
  const found = cases.find((c) => req.url === `/api/cases/${c.case_id}`);
  if (found) return res.end(JSON.stringify({ case: found }));
  res.writeHead(404).end(JSON.stringify({ error: "not found" }));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
const backend = `http://127.0.0.1:${address.port}`;
const preview = await startProductionPreview(backend);
const browser = await chromium.launch({
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : { channel: "chrome" }),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1536, height: 1024 },
});
await context.addInitScript(
  ({ backend }) =>
    localStorage.setItem(
      "resolveqa.workspace.v2",
      JSON.stringify({
        mode: "demo",
        config: {
          baseUrl: backend,
          caseIds: ["SSE-1"],
          snapshotPath: "/snapshot",
          streamPath: "/stream",
          playbooksPath: "",
        },
      }),
    ),
  { backend },
);
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const checks = [];
const check = (name) => {
  checks.push(name);
  console.log("PASS", name);
};
function emit(event) {
  events.unshift(event);
  for (const res of streams)
    res.write(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`);
}
try {
  await page.goto(`${preview.url}/quadro`);
  await page.locator('[data-run-id="SSE-1"]').waitFor();
  await page.waitForFunction(() =>
    document
      .querySelector(".connection-label")
      ?.textContent.includes("Informações atualizadas"),
  );
  check("SSE conecta e hidrata snapshot");
  cases[0] = { ...cases[0], state: "fixing", updated_at: ts() };
  const moved = {
    event_id: "moved-2",
    case_id: "SSE-1",
    seq: 2,
    ts: cases[0].updated_at,
    source: "fix",
    type: "StateChanged",
    from_state: "created",
    to_state: "fixing",
    reason: "Patch em andamento",
    evidence_refs: [],
  };
  emit(moved);
  await page.waitForSelector(".transport:not([hidden])", { state: "attached" });
  for (const res of streams) res.write(`data: ${JSON.stringify(moved)}\n\n`);
  await page.waitForFunction(
    () => document.querySelector(".transport")?.hidden,
  );
  assert.equal(
    await page.locator('[data-lane="active"] [data-run-id="SSE-1"]').count(),
    1,
  );
  check(
    "Evento SSE transporta o card e reconexão duplicada não repete a transição",
  );
  const second = run("SSE-2", "Caso criado pelo agente remoto");
  cases.push(second);
  emit({
    event_id: "created-2",
    case_id: "SSE-2",
    seq: 1,
    ts: second.created_at,
    source: "intake",
    type: "CaseCreated",
    evidence_refs: [],
  });
  await page.locator('[data-lane="intake"] [data-run-id="SSE-2"]').waitFor();
  await page.waitForFunction(() =>
    Object.values(
      JSON.parse(localStorage.getItem("resolveqa.workspace.v2")).watchedCases ||
        {},
    ).some((ids) => ids.includes("SSE-2")),
  );
  check("CaseCreated descobre e consulta caso criado por agente remoto");
  emit({
    event_id: "proof-1",
    case_id: "SSE-1",
    seq: 3,
    ts: ts(),
    source: "verification",
    type: "EvidenceAdded",
    evidence_refs: ["real-test-log"],
  });
  cases[0].evidence_ids = ["real-test-log"];
  await page.getByRole("button", { name: "Abrir SSE-1", exact: true }).click();
  await page.locator('[data-evidence-id="real-test-log"]').waitFor();
  check("EvidenceAdded atualiza as evidências do caso");
  await page
    .getByRole("button", { name: "Fechar detalhes", exact: true })
    .click();
  unavailable = true;
  await page
    .getByRole("button", { name: "Atualizar dados", exact: true })
    .click();
  await page
    .getByRole("alert")
    .filter({ hasText: "Não foi possível confirmar esta atualização" })
    .waitFor();
  assert.equal(await page.locator(".live-card").count(), 2);
  check(
    "Falha de backend mostra erro e identifica o último snapshot sem inventar dados",
  );
  assert.equal(await page.locator(".mode-switch").count(), 0);
  assert.equal(await page.locator('[data-run-id="SSE-1"]').count(), 1);
  check(
    "Produção vem do env e ignora preferência de exemplos salva no navegador",
  );
  assert.deepEqual(errors, []);
  await fs.mkdir(new URL("../.impeccable/review/", import.meta.url), {
    recursive: true,
  });
  await fs.writeFile(
    new URL("../.impeccable/review/stream-checks.json", import.meta.url),
    JSON.stringify(
      {
        checks,
        errors,
        backend:
          "local controlled HTTP/SSE service; not a remote production activation",
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ passed: checks.length, errors }));
} finally {
  await browser.close();
  preview.close();
  for (const res of streams) res.end();
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
}
