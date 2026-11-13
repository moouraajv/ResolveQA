# Demo ao vivo / gravada — protótipo funcional

Entregável §8: **protótipo funcional do agente de IA** (demo ao vivo ou gravado).

## URLs (staging)

| Superfície | URL |
|---|---|
| Intake | https://dec5ise4h3d48.cloudfront.net/form |
| Chat simulado | https://dec5ise4h3d48.cloudfront.net/chat |
| Health | https://dec5ise4h3d48.cloudfront.net/health |
| Quadro Mola | https://dsh3ja1i4695p.cloudfront.net/quadro |
| Admin | https://dsh3ja1i4695p.cloudfront.net/admin |

Confirme antes da banca: `GET /health` → `"environment":"staging"`, `"queue":true`, `"operator_advance":false`.

## Roteiro de demonstração (~2–3 min na tela)

### A — Caminho feliz (cupom)

1. Abrir **form** e **Quadro** lado a lado.
2. No form, preencher:
   - `client_id`: `resolveqa`
   - `repo_ref`: `targets/resolveqa-checkout`
   - `report_text`: `Comprei R$ 200,00 no site, apliquei o cupom DESC10 de 10% e o total continuou R$ 200,00. Deveria ser R$ 180,00.`
3. Enviar → API responde **202** (`queued: true`).
4. No Quadro, apontar o card avançando pelos estados reais (triage → repro → fix → verify).
5. Narrar: “Aqui o worker puxou a fila; não clicamos em Avançar.”
6. Se chegar em `verified`, abrir evidências / mencionar draft PR ou pacote local.

### B — Caminho honesto (relato vago) — 30s

1. Novo caso com relato: `O site está estranho.`
2. Esperar `needs_info` (sem patch).
3. Narrar: “Agente não inventa correção sem dado.”

### C — Chat simulado (opcional)

1. https://dec5ise4h3d48.cloudfront.net/chat  
2. Mostrar o rótulo permanente **Canal simulado**.  
3. Enviar o mesmo relato do cupom.

## Como gravar (plano B do edital)

1. Resolução 1920×1080; microfone; cronômetro 3 min.
2. Gravar tela + voz seguindo o roteiro A (+ fechamento do pitch).
3. Salvar em `docs/akcit/assets/` como `demo-resolveqa-YYYYMMDD.mp4` (ou link no README se o arquivo for grande demais para o Git).
4. No README, acrescentar a linha do vídeo na tabela de entregáveis.

```bash
# Exemplo local (PipeWire / wf-recorder em Omarchy)
wf-recorder -g "$(slurp)" -f docs/akcit/assets/demo-resolveqa.mp4
```

## Smoke rápido (CI / pré-banca)

```bash
python3 scripts/smoke_test.py --base-url https://dec5ise4h3d48.cloudfront.net
curl -sS https://dec5ise4h3d48.cloudfront.net/health
```
