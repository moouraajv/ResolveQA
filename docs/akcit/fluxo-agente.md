# Documentação do fluxo do agente — ResolveQA

Material de apoio à banca (Edital AKCIT Camp Multicêntrico 2026, §8 — inputs, lógica, outputs).  
Não substitui a demo ao vivo; serve de consulta no Q&A.

## Problema que o agente resolve

O caminho entre o relato do cliente (“o cupom não aplicou”) e uma correção verificável hoje é manual: suporte interpreta → dev reproduz → alguém corrige → alguém confirma → alguém responde. Cada passagem perde contexto. O ResolveQA coloca **agentes de IA** nesse núcleo: a partir do relato, o sistema raciocina, planeja e executa triagem → reprodução → correção mínima → verificação independente, com evidências e resposta ao cliente — **sem merge automático**.

## Visão geral do pipeline

```
Relato (form / API / chat simulado)
        │
        ▼
   Intake → fila (worker)
        │
        ▼
 Orquestrador (máquina de estados determinística)
        │
        ├─ Triage          (LLM)     → TriageRecord
        ├─ Reproduction    (LLM)     → teste RED no defeito
        ├─ Fix             (LLM + playbook) → patch mínimo
        ├─ Verification    (determinístico) → RED→GREEN + suíte
        ├─ Delivery        → draft PR / pacote local
        └─ Reply           → mensagem ao cliente (só após verified)
```

O **estado do caso nunca é decidido pelo LLM**. Quem promove/reprova é código (orquestrador + verifier) a partir de exit codes e regras.

## Inputs

| Entrada | Origem | Conteúdo |
|---|---|---|
| `client_id` | form / API / chat | Isolamento lógico do cliente |
| `repo_ref` | form / API / chat | Repositório-alvo (ex.: `targets/resolveqa-checkout`) |
| `report_text` | form / API / chat | Relato em linguagem natural |
| `channel` | sistema | `form`, `api` ou `simulated_chat` |
| Playbook | `.resolveqa/playbook.toml` no repo-alvo | Paths permitidos/proibidos, testes protegidos, limites, tom de resposta |
| Snapshot / SSE | Quadro (front Mola) | Operador acompanha progresso real (sem “avançar” fake em produção) |

Relato, logs e saídas de ferramentas são tratados como **dados não confiáveis** (não executam instruções embutidas).

## Lógica (etapas)

1. **Intake** — valida contrato (`ReportInput`), cria caso (`created`), enfileira worker (`202` + `queued: true` quando há fila).
2. **Triage** — LLM estrutura esperado vs observado, suspeitos e confiança; se faltar dado → `needs_info` (sem patch).
3. **Reproduction** — gera/executa teste a partir do relato; deve **falhar** na asserção ligada ao defeito (RED).
4. **Fix** — propõe patch mínimo; em modo `general`, passa por **gates de playbook** (paths, testes protegidos). Fora da política → rejeição / `needs_info`.
5. **Verification** — roda o mesmo teste antes/depois + suíte relevante **sem LLM decidir**. `verified` só se RED→GREEN e suíte verde, com revisões registradas.
6. **Delivery** — draft PR com evidências ou pacote “PR não publicado” se não houver repo autorizado.
7. **Reply** — mensagem clara ao cliente no mesmo canal, **somente** após `verified`.

Modos de agente:

- `RESOLVEQA_AGENT_MODE=dogfood` — caminho determinístico de fix (alvo ResolveQA).
- `RESOLVEQA_AGENT_MODE=general` — triage/repro/fix com LLM + playbook gates (staging atual).

Limites (custo/segurança): tentativas de fix, teto de chamadas LLM, timeout de testes; ao estourar → estado terminal honesto (`blocked` / `infra_error`) com motivo.

## Outputs

| Saída | Para quem | Quando |
|---|---|---|
| Estados do caso + timeline/eventos | Operador (Quadro Mola) | Contínuo via snapshot/SSE |
| Evidências (logs, diffs, exit codes) | Engenharia / auditoria | A cada etapa |
| Draft PR ou pacote local | Revisor humano | Após verificação aprovada |
| Resposta ao cliente | Cliente final | Só em `verified` |
| `needs_info` / `blocked` / `infra_error` | Suporte / operador | Falha honesta, sem fingir progresso |

Estados: `created` → `triaging` → `triaged` → `reproducing` → `reproduced` → `fixing` → `fixed` → `verifying` → `verified` (ou terminais `needs_info`, `blocked`, `infra_error`).

## Demo

- Backend (staging): https://d2a053hki46q2m.cloudfront.net  
- Quadro Mola: https://dsh3ja1i4695p.cloudfront.net/quadro  
- Intake: https://d2a053hki46q2m.cloudfront.net/form  

Detalhes técnicos: [`docs/rfc/0001-arquitetura-e-contratos.md`](../rfc/0001-arquitetura-e-contratos.md), [`docs/cloud-agents.md`](../cloud-agents.md), [`docs/PRD.md`](../PRD.md).
