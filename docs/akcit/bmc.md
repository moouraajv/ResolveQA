# Business Model Canvas — ResolveQA

BMC atualizado para o AKCIT Camp Multicêntrico 2026 (entregável obrigatório §8).  
Foco: solução early-stage baseada em **agentes de IA** para o ciclo relato → correção verificada.

## 1. Proposta de valor

Transformar um relato de bug (texto livre) em **reprodução automática, correção mínima e verificação independente**, com evidências e resposta ao cliente — sem merge automático e sem progresso inventado.

Diferencial: o agente não “chuta” que está corrigido; o **Verifier determinístico** só promove `verified` com RED→GREEN + suíte verde, e playbooks da empresa limitam o que o agente pode alterar.

## 2. Segmentos de clientes

- Software houses e times de produto que mantêm vários clientes/repositórios.
- Times de suporte/CS que precisam de status auditável sem depender só da engenharia.
- Engenharias que querem PRs pequenos, com prova de reprodução e verificação.

## 3. Personas / canais

| Persona | Canal ResolveQA |
|---|---|
| Cliente final | Form, API ou chat simulado (estilo WhatsApp na demo) |
| Suporte / CS | Quadro Mola (`/quadro`) — timeline real |
| Dev / revisor | Draft PR + pacote de evidências |
| Admin | `/admin` — operação e playbooks |

## 4. Relacionamento

- Demo pública (staging) para validação com banca e usuários.
- Operação assistida: humano aprova merge; agente prepara o pacote.
- Playbooks por repositório (política da casa do cliente).

## 5. Atividades-chave

- Orquestração multi-etapa do agente (triage → repro → fix → verify → reply).
- Guardrails (playbook, limites de custo, estados terminais honestos).
- Observabilidade do caso (snapshot/SSE) no front Mola.
- Empacotamento de evidências e resposta ao cliente.

## 6. Recursos-chave

- Pipeline de agentes + orquestrador determinístico.
- Alvo dogfood (`targets/resolveqa-checkout`) e modo general com LLM.
- Infra AWS (API + worker + CloudFront) no monorepo `moouraajv/ResolveQA`.
- Interface Mola (Kanban operacional).

## 7. Parcerias-chave

- AWS (infra / workshops do programa AKCIT).
- Ecossistema open source (código e artefatos no GitHub).
- Clientes piloto (software houses) para validação de playbooks reais.

## 8. Estrutura de custos (early stage)

- Inferência LLM por caso (triage/repro/fix).
- Compute de sandbox/testes e worker.
- Hospedagem staging/produção (EC2, CloudFront, artefatos).
- Tempo de revisão humana no merge (intencional — não automatizado).

## 9. Fontes de receita (hipótese de modelo)

- SaaS B2B por seat / por caso resolvido / por repositório conectado.
- Camada enterprise: playbooks, isolamento multi-cliente, auditoria.
- Serviços de implantação e tuning de playbooks em contas piloto.

*Unit economics e pricing ainda em validação (etapa early stage do programa).*

## 10. Métricas de tração (demo / MVP)

- Relato → `verified` com evidências, sem falso positivo.
- Caso vago → `needs_info` (sem patch inventado).
- Operador vê só progresso real no Quadro (advance demo-only).

## Referências no repositório

- Pitch: [`pitch/`](../../pitch/)
- Fluxo do agente: [`fluxo-agente.md`](fluxo-agente.md)
- PRD: [`../PRD.md`](../PRD.md)
