# ResolveQA

**AKCIT Camp Multicêntrico 2026** — Programa Nacional de Open Innovation em Agentes de Inteligência Artificial  
Repositório de submissão (Edital §8): protótipo, BMC, pitch e documentação do fluxo do agente.

> Ambiente público atual: branch **`staging`**. Promoção para `main`/produção só com aprovação explícita da equipe.

---

## 1. Problema e solução (tema: Agentes de IA)

**Dor.** Entre o relato do cliente e a correção há uma corrente manual (suporte → dev → QA → resposta). Cada passagem perde contexto e tempo.

**Solução.** O ResolveQA é um **pipeline de agentes de IA** que, a partir do relato em linguagem natural:

1. faz triagem estruturada;
2. gera um teste que **reproduz** o defeito;
3. propõe uma **correção mínima** (com playbook da empresa);
4. **verifica de forma independente** (RED→GREEN; o LLM não decide o estado);
5. empacota evidências / draft PR e **responde ao cliente** só após `verified`.

Se o agente fosse removido, o valor principal (reprodução → correção verificada a partir do relato) deixaria de existir — a IA está no núcleo do problema (critério técnico §9.4, centralidade da IA).

---

## 2. Entregáveis obrigatórios (Edital §8)

| Entregável | Onde está neste GitHub |
|---|---|
| **Protótipo funcional** (demo ao vivo) | URLs de staging abaixo |
| **BMC** (negócio / impacto) | [`docs/akcit/bmc.md`](docs/akcit/bmc.md) |
| **Pitch** | [`pitch/`](pitch/) — PDF/PPTX do deck |
| **Fluxo do agente** (inputs, lógica, outputs) | [`docs/akcit/fluxo-agente.md`](docs/akcit/fluxo-agente.md) |

Documentação técnica de apoio (não substitui os quatro itens acima): [`docs/PRD.md`](docs/PRD.md), [`docs/rfc/0001-arquitetura-e-contratos.md`](docs/rfc/0001-arquitetura-e-contratos.md), [`docs/cloud-agents.md`](docs/cloud-agents.md).

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

Stacks AWS: `resolveqa-staging-backend` / `resolveqa-staging-frontend`.  
Em produção/staging o avanço do quadro reflete o **worker real** (`create → fila → orquestrador`); não há “play” inventado.

### Como ver o agente em ~2 minutos

1. Abra o [form](https://dec5ise4h3d48.cloudfront.net/form) ou o [Quadro](https://dsh3ja1i4695p.cloudfront.net/quadro).
2. Envie um relato com `client_id` + `repo_ref` (ex. dogfood: `resolveqa` / `targets/resolveqa-checkout`) e um texto como: *“Comprei R$ 200, apliquei cupom DESC10 de 10% e o total continuou R$ 200.”*
3. Acompanhe os estados no Quadro até `verified` ou um terminal honesto (`needs_info`, etc.).

---

## 4. Monorepo

Repositório principal: **`moouraajv/ResolveQA`**.

| Parte | Caminho |
|---|---|
| Backend / agentes / worker | `src/resolveqa/`, `scripts/`, `infra/aws/` |
| Frontend Mola | `front/` |
| Alvo dogfood | `targets/resolveqa-checkout/` |
| Pitch | `pitch/` |
| Entregáveis AKCIT | `docs/akcit/` |

O repo legado `ThiagoVenturaV/ResolveQA-front` é espelho histórico (deploys AWS desligados).

---

## 5. Critérios do edital — onde evidenciar

| Critério (regional §9.1) | Evidência neste repo / demo |
|---|---|
| Problema e validação | Seção 1 + PRD (personas e relato concreto) |
| Solução e uso de IA (§9.4) | [`docs/akcit/fluxo-agente.md`](docs/akcit/fluxo-agente.md) + demo staging |
| Diferencial e viabilidade | [`docs/akcit/bmc.md`](docs/akcit/bmc.md) + playbooks / verifier |
| Equipe / execução | Histórico Git + deploys em `staging` |
| Qualidade do pitch | [`pitch/`](pitch/) + explicação do fluxo na demo |

Parâmetros técnicos (§9.4): centralidade da IA no pipeline; profundidade (orquestrador, guardrails, verifier); ativo próprio (playbooks + evidências por caso).

---

## 6. Licença e open innovation

Projeto em modelo de inovação aberta conforme o edital AKCIT (autoria da equipe; organização autorizada a divulgar). Componentes e documentação versionados publicamente neste repositório.
