# ResolveQA

**AKCIT Camp Multicêntrico 2026** — Open Innovation em Agentes de Inteligência Artificial  
Repositório de submissão (Edital §8): protótipo · BMC · pitch · fluxo do agente.

> Demo pública: branch **`staging`**. Produção (`main`) só após aprovação explícita.

Checklist de congelamento: [`docs/akcit/checklist-entrega.md`](docs/akcit/checklist-entrega.md)

---

## 1. Problema e solução (Agentes de IA)

**Dor.** Relato do cliente vira telefone sem fio (suporte → dev → QA → resposta); o contexto se perde.

**Solução.** Pipeline de **agentes de IA** que, a partir do relato:

1. faz triagem;
2. gera teste que **reproduz** o defeito;
3. propõe **correção mínima** (com playbook);
4. **verifica de forma independente** (RED→GREEN — o LLM não decide o estado);
5. empacota evidências / draft PR e **responde ao cliente** só após `verified`.

Sem o agente, o valor principal some (§9.4 — centralidade da IA).

---

## 2. Entregáveis obrigatórios (Edital §8)

| Entregável | Artefato no GitHub |
|---|---|
| **Protótipo funcional** (ao vivo / gravado) | URLs abaixo + [`docs/akcit/demo-ao-vivo.md`](docs/akcit/demo-ao-vivo.md) |
| **BMC** | [`docs/akcit/bmc.md`](docs/akcit/bmc.md) |
| **Pitch** (3 min regional) | [`pitch/`](pitch/) + roteiro [`docs/akcit/pitch-roteiro-3min.md`](docs/akcit/pitch-roteiro-3min.md) |
| **Fluxo do agente** (inputs, lógica, outputs) | [`docs/akcit/fluxo-agente.md`](docs/akcit/fluxo-agente.md) |

Apoio: [`docs/akcit/equipe.md`](docs/akcit/equipe.md) · [`docs/akcit/evolucao-regional.md`](docs/akcit/evolucao-regional.md) · [`docs/PRD.md`](docs/PRD.md) · [`docs/rfc/0001-arquitetura-e-contratos.md`](docs/rfc/0001-arquitetura-e-contratos.md)

---

## 3. Demo pública (staging)

| Superfície | URL |
|---|---|
| Backend | https://dec5ise4h3d48.cloudfront.net |
| Health | https://dec5ise4h3d48.cloudfront.net/health |
| Intake (form) | https://dec5ise4h3d48.cloudfront.net/form |
| Chat simulado | https://dec5ise4h3d48.cloudfront.net/chat |
| Front Mola (Quadro) | https://dsh3ja1i4695p.cloudfront.net/quadro |
| Admin | https://dsh3ja1i4695p.cloudfront.net/admin |

Stacks: `resolveqa-staging-backend` / `resolveqa-staging-frontend`.  
Quadro reflete o **worker real** (`create → fila → orquestrador`) — sem “play” inventado.

### Como ver o agente em ~2 minutos

1. Abra o [form](https://dec5ise4h3d48.cloudfront.net/form) e o [Quadro](https://dsh3ja1i4695p.cloudfront.net/quadro).
2. Envie: `client_id=resolveqa`, `repo_ref=targets/resolveqa-checkout`, relato do cupom DESC10 (total deveria ser R$ 180).
3. Acompanhe os estados até `verified` ou um terminal honesto (`needs_info`, etc.).

Detalhes: [`docs/akcit/demo-ao-vivo.md`](docs/akcit/demo-ao-vivo.md).

---

## 4. Pitch (arquivos)

| Arquivo | Uso |
|---|---|
| [`pitch/ResolveQA-Pitch-Deck-Converge-2026.pdf`](pitch/ResolveQA-Pitch-Deck-Converge-2026.pdf) | Deck principal (Converge / AKCIT) |
| [`pitch/ResolveQA-pitch-deck.pdf`](pitch/ResolveQA-pitch-deck.pdf) | Versão anterior |
| [`docs/akcit/pitch-roteiro-3min.md`](docs/akcit/pitch-roteiro-3min.md) | Fala cronometrada + Q&A |

---

## 5. Monorepo

| Parte | Caminho |
|---|---|
| Backend / agentes / worker | `src/resolveqa/`, `scripts/`, `infra/aws/` |
| Frontend Mola | `front/` |
| Alvo dogfood | `targets/resolveqa-checkout/` |
| Entregáveis AKCIT | `docs/akcit/` |
| Pitch | `pitch/` |

Repo: **`moouraajv/ResolveQA`**. Legado `ThiagoVenturaV/ResolveQA-front` = espelho histórico (deploys desligados).

---

## 6. Critérios do edital — mapa rápido

| Critério | Onde evidenciar |
|---|---|
| Problema e validação (§9.1) | §1 + PRD |
| Solução e uso de IA (§9.4) | [`fluxo-agente.md`](docs/akcit/fluxo-agente.md) + demo |
| Diferencial e viabilidade | [`bmc.md`](docs/akcit/bmc.md) |
| Equipe | [`equipe.md`](docs/akcit/equipe.md) + histórico Git |
| Qualidade do pitch | Deck + roteiro + demo do fluxo |
| Evolução → final (§9.2) | [`evolucao-regional.md`](docs/akcit/evolucao-regional.md) |

---

## 7. Open innovation

Autoria da equipe; organização AKCIT autorizada a divulgar (edital §12). Código e documentação públicos neste repositório.
