import { test } from "node:test";
import assert from "node:assert/strict";
import { readRuntimeSettings } from "../lib/resolveqa/environment.ts";
import {
  explainText,
  friendlyError,
  sourceLabel,
  agentLabel,
} from "../lib/resolveqa/copy.ts";

test("ambiente sem configuração usa produção, nunca exemplos por acidente", () => {
  assert.equal(readRuntimeSettings({}).mode, "production");
});
test("ambiente de exemplos precisa ser habilitado explicitamente", () => {
  assert.equal(readRuntimeSettings({ RESOLVEQA_MODE: "demo" }).mode, "demo");
  assert.throws(() => readRuntimeSettings({ RESOLVEQA_MODE: "produciton" }));
});
test("configuração pública permite somente os campos de conexão previstos", () => {
  const settings = readRuntimeSettings({
    RESOLVEQA_MODE: "production",
    RESOLVEQA_API_URL: "https://example.test/",
    RESOLVEQA_CASE_IDS: "case-1, case-1\ncase-2",
    RESOLVEQA_EVENTS_PATH: "/events",
    INTERNAL_SECRET: "never-send-this",
  });
  assert.equal(settings.connection.baseUrl, "https://example.test");
  assert.deepEqual(settings.connection.caseIds, ["case-1", "case-2"]);
  assert.equal(settings.connection.streamPath, "/events");
  assert.ok(!JSON.stringify(settings).includes("never-send-this"));
});
test("identificadores e rótulos internos ganham explicações compreensíveis", () => {
  assert.equal(sourceLabel("verification"), "Verificação");
  assert.equal(agentLabel("Reproducer"), "Reprodução");
  const original =
    "SHA256 a81c04f0000000000000000000000000000000000000000000000000000000000";
  const text = explainText(original);
  assert.match(text, /integridade do arquivo/);
  assert.doesNotMatch(text, /SHA256|a81c04f/);
  assert.match(original, /SHA256/); // Presentation never rewrites the stored evidence.
});
test("falhas de serviço oferecem recuperação sem códigos de programação", () => {
  const text = friendlyError(new Error("Backend respondeu HTTP 503"));
  assert.match(text, /Tente novamente/);
  assert.doesNotMatch(text, /Backend|HTTP|503/);
});
