import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const root = new URL("../", import.meta.url).pathname.replace(
  /^\/([A-Z]:)/i,
  "$1",
);
const out = `${root}/.impeccable/review`;
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : { channel: "chrome" }),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1536, height: 1024 },
});
await context.addInitScript(() => {
  if (!localStorage.getItem("env-override-attempt")) {
    localStorage.setItem("env-override-attempt", "1");
    localStorage.setItem(
      "resolveqa.workspace.v2",
      JSON.stringify({
        mode: "production",
        config: { baseUrl: "https://wrong.invalid" },
        playbooks: undefined,
      }),
    );
  }
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const checks = [];
async function check(name, fn) {
  await fn();
  checks.push(name);
  console.log("PASS", name);
}
async function plainLanguage() {
  assert.doesNotMatch(
    await page.locator("body").innerText(),
    /backend|snapshot|\bSSE\b|\bHTTP\b|\bSHA[- ]?256\b|\bLLM\b|\bTraces?\b|\bLogs\b|\bspans?\b|heartbeat|\bRED\b|\bGREEN\b|\bp95\b|\bAPI\b|needs_info/i,
  );
}
const base = process.env.RESOLVEQA_BASE_URL || "http://127.0.0.1:5173";
async function settle() {
  await page.waitForFunction(() => {
    const heading = document.querySelector(".hero-line");
    return !heading || getComputedStyle(heading).display === "block";
  });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() =>
    [...document.querySelectorAll(".mola-sprite")].every(
      (el) => el.getAttribute("data-atlas") === "ready",
    ),
  );
  await page.waitForTimeout(200);
}
await page.goto(base);
await settle();
await check("Landing contém documentação e playbooks", async () => {
  assert.match(await page.locator("h1").innerText(), /Do relato à\s+correção/);
  assert.match(
    await page.locator(".rq-hero-copy").innerText(),
    /documentação atualizada/i,
  );
});
await check(
  "Landing sem seletor de ambiente ou linguagem de configuração",
  async () => {
    assert.equal(await page.locator(".mode-switch").count(), 0);
    const text = await page.locator("body").innerText();
    assert.doesNotMatch(
      text,
      /modo demo|modo produção|backend|snapshot|SSE|HTTP|SHA-?256|\bLLM\b|\bTraces?\b|\bLogs\b/,
    );
  },
);
await page.screenshot({ path: `${out}/desktop.png`, fullPage: true });
await page.screenshot({ path: `${out}/desktop-viewport.png` });
await page.setViewportSize({ width: 390, height: 844 });
await settle();
await page.screenshot({ path: `${out}/mobile.png`, fullPage: true });
await check("Landing mobile sem overflow horizontal", async () =>
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  ),
);
await page.setViewportSize({ width: 1536, height: 1024 });
await page
  .getByRole("link", { name: "Acessar Admin", exact: true })
  .first()
  .click();
await page.getByRole("heading", { name: "Visão geral", exact: true }).waitFor();
await page.getByText("8 casos no período").waitFor();
await settle();
await page.screenshot({ path: `${out}/admin-desktop.png`, fullPage: true });
await check("Admin abre painel com execuções", async () =>
  assert.equal(await page.locator(".metric-strip").count(), 1),
);
await check("Admin preto com contraste legível", async () => {
  const colors = await page.locator(".rq-admin-app").evaluate((el) => ({
    background: getComputedStyle(el).backgroundColor.match(/\d+/g).map(Number),
    foreground: getComputedStyle(el.querySelector("h1"))
      .color.match(/\d+/g)
      .map(Number),
    buttonBackground: getComputedStyle(el.querySelector(".rq-button.primary"))
      .backgroundColor.match(/\d+/g)
      .map(Number),
    buttonForeground: getComputedStyle(el.querySelector(".rq-button.primary"))
      .color.match(/\d+/g)
      .map(Number),
  }));
  assert.ok(Math.max(...colors.background.slice(0, 3)) <= 24);
  assert.equal(colors.background[0], colors.background[1]);
  assert.equal(colors.background[1], colors.background[2]);
  const luminance = (rgb) =>
    rgb
      .slice(0, 3)
      .map((n) => n / 255)
      .map((n) => (n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4))
      .reduce((v, n, i) => v + n * [0.2126, 0.7152, 0.0722][i], 0);
  assert.ok(
    (luminance(colors.foreground) + 0.05) /
      (luminance(colors.background) + 0.05) >=
      7,
  );
  assert.ok(
    (luminance(colors.buttonForeground) + 0.05) /
      (luminance(colors.buttonBackground) + 0.05) >=
      4.5,
  );
});
await page.getByRole("button", { name: "Atividades", exact: true }).click();
await check("Logs estruturados", async () =>
  assert.ok((await page.locator(".log-table tbody tr").count()) >= 8),
);
await page
  .getByRole("button", { name: "Tempo por etapa", exact: true })
  .click();
await check("Trace waterfall", async () =>
  assert.equal(await page.locator(".span-row").count(), 4),
);
await plainLanguage();
await page.getByRole("button", { name: "Procedimentos", exact: true }).click();
await page
  .getByRole("button", { name: "Novo procedimento", exact: true })
  .click();
await page.getByLabel("Nome", { exact: true }).fill("QA smoke playbook");
await page.getByLabel("Empresa", { exact: true }).fill("Smoke empresa");
await page.getByLabel("Projeto", { exact: true }).fill("smoke/repo");
await page
  .getByLabel("Instruções", { exact: true })
  .fill("Reproduzir, verificar e atualizar a documentação.");
await page
  .getByRole("button", { name: "Salvar procedimento", exact: true })
  .click();
await check(
  "Cadastro de playbook",
  async () =>
    await page
      .getByRole("heading", { name: "QA smoke playbook", exact: true })
      .waitFor(),
);
await page.reload();
await page.getByRole("button", { name: "Procedimentos", exact: true }).click();
await check(
  "Playbook persiste após reload",
  async () =>
    await page
      .getByRole("heading", { name: "QA smoke playbook", exact: true })
      .waitFor(),
);
await page
  .getByRole("button", { name: "Excluir QA smoke playbook", exact: true })
  .click();
await page
  .getByRole("button", { name: "Confirmar exclusão", exact: true })
  .click();
await check("Exclusão de playbook", async () =>
  assert.equal(
    await page
      .getByRole("heading", { name: "QA smoke playbook", exact: true })
      .count(),
    0,
  ),
);
await page.getByRole("button", { name: "Documentação", exact: true }).click();
await check(
  "Referências de documentação",
  async () =>
    await page
      .getByRole("heading", {
        name: "Regra de desconto no checkout",
        exact: true,
      })
      .waitFor(),
);
await page.getByRole("button", { name: "Visão geral", exact: true }).click();
await page.setViewportSize({ width: 390, height: 844 });
await settle();
await page.screenshot({ path: `${out}/admin-mobile.png`, fullPage: true });
await check("Admin mobile sem overflow horizontal", async () =>
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  ),
);
await page.setViewportSize({ width: 1536, height: 1024 });
await page.getByRole("link", { name: "Mola", exact: true }).click();
await page
  .getByRole("heading", { name: "O trabalho em movimento.", exact: true })
  .waitFor();
await settle();
await page.getByRole("button", { name: "Reiniciar exemplos" }).click();
await page.screenshot({ path: `${out}/board-desktop.png`, fullPage: true });
await page
  .getByRole("button", { name: "Próxima atividade", exact: true })
  .click();
await page.waitForSelector(".transport:not([hidden])", { state: "attached" });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${out}/board-motion.png` });
await page.waitForFunction(() => document.querySelector(".transport")?.hidden);
await check("Mola transporta card após evento", async () =>
  assert.equal(
    await page.locator('[data-lane="active"] [data-run-id="RQA-1048"]').count(),
    1,
  ),
);
await page.getByRole("button", { name: "Novo relato", exact: true }).click();
await page
  .getByLabel("Relato", { exact: true })
  .fill("Relato smoke: cupom não atualiza o total da compra.");
await page.getByRole("button", { name: "Criar caso", exact: true }).click();
await check(
  "Criação de caso no quadro",
  async () =>
    await page
      .getByRole("button", {
        name: "Relato smoke: cupom não atualiza o total da compra.",
        exact: true,
      })
      .waitFor(),
);
await page
  .getByRole("button", {
    name: "Relato smoke: cupom não atualiza o total da compra.",
    exact: true,
  })
  .click();
await page.getByRole("button", { name: "Fechar detalhes" }).waitFor();
await page.keyboard.press("Escape");
await check("Detalhes fecham com Escape", async () =>
  assert.equal(await page.locator(".case-drawer").count(), 0),
);
await page.getByRole("button", { name: "Reiniciar exemplos" }).click();
await page.setViewportSize({ width: 390, height: 844 });
await settle();
await page.screenshot({ path: `${out}/board-mobile.png`, fullPage: true });
await check("Quadro mobile rola dentro do Kanban", async () => {
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  assert.ok(
    await page
      .locator(".live-board")
      .evaluate((el) => el.scrollWidth > el.clientWidth),
  );
});
await page.setViewportSize({ width: 1536, height: 1024 });
await page.evaluate(() =>
  localStorage.setItem("resolveqa.workspace.v2", "null"),
);
await page.reload();
await page.waitForFunction(
  () => document.querySelectorAll(".live-card").length === 8,
);
await check("Armazenamento inválido recupera a demonstração", async () =>
  assert.equal(await page.locator(".live-card").count(), 8),
);
await check("Preferência antiga não sobrepõe o env", async () => {
  const saved = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("resolveqa.workspace.v2")),
  );
  assert.ok(!("mode" in saved));
  assert.ok(!("config" in saved));
  assert.equal(await page.locator(".live-card").count(), 8);
});
await plainLanguage();
assert.deepEqual(errors, []);
await fs.writeFile(
  `${out}/functional-checks.json`,
  JSON.stringify(
    {
      checks,
      errors,
      viewports: ["1536x1024", "390x844"],
      configuration:
        "Demo from env; stored mode/config cannot override it. Production validated separately by test:stream.",
    },
    null,
    2,
  ),
);
await browser.close();
console.log(JSON.stringify({ passed: checks.length, errors }));
