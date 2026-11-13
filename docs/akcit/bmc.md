# Business Model Canvas — ResolveQA

BMC atualizado — Edital AKCIT Camp Multicêntrico 2026, entregável obrigatório §8.  
Formato clássico (Osterwalder) + notas de early-stage.

---

## Canvas (9 blocos)

```text
┌─────────────────────┬──────────────────────────────┬─────────────────────┐
│ 8. Parceiros-chave  │ 5. Atividades-chave          │ 1. Proposta de valor│
│                     │                              │                     │
│ • AWS / AKCIT       │ • Orquestrar agentes         │ Relato → correção   │
│ • Software houses   │   (triage→repro→fix→verify) │ verificada com      │
│   piloto            │ • Guardrails / playbooks     │ evidências, sem     │
│ • Open source       │ • Observabilidade (Quadro)   │ merge automático e  │
│                     │ • Empacotar PR + reply       │ sem progresso falso │
│                     ├──────────────────────────────┤                     │
│                     │ 6. Recursos-chave            │ Diferencial:        │
│                     │                              │ verifier determi-   │
│                     │ • Pipeline + orquestrador    │ nístico; playbooks  │
│                     │ • LLM + sandbox de testes    │ da empresa; Quadro  │
│                     │ • Infra AWS staging          │ com worker real     │
│                     │ • UI Mola                    │                     │
├─────────────────────┼──────────────────────────────┼─────────────────────┤
│ 4. Relacionamento   │ 2. Segmentos                 │ 3. Canais           │
│                     │                              │                     │
│ • Demo pública      │ • Software houses multi-     │ • Form / API / chat │
│ • Sucesso assistido │   cliente                    │   simulado          │
│   (humano no merge) │ • Produto / engenharia       │ • Quadro Mola       │
│ • Playbooks por     │ • Suporte / CS               │ • Admin / playbooks │
│   repositório       │                              │ • Draft PR GitHub   │
├─────────────────────┴──────────────────────────────┴─────────────────────┤
│ 9. Estrutura de custos              │ 7. Fontes de receita               │
│                                     │                                    │
│ • Inferência LLM / caso             │ • SaaS B2B: seat / repo / caso     │
│ • Compute worker + testes           │ • Enterprise: isolamento, auditoria│
│ • CloudFront / EC2 / artefatos      │ • Setup + tuning de playbooks      │
│ • Revisão humana (custo intencional)│ (hipótese early-stage)             │
└─────────────────────────────────────┴────────────────────────────────────┘
```

---

## Proposta de valor (expandida)

Transformar um relato de bug em **reprodução automática → correção mínima → verificação independente → evidências → resposta ao cliente**.

Se o agente de IA fosse removido, o valor principal desapareceria (§9.4 — centralidade da IA).

## Segmentos e personas

| Segmento | Dor | O que compra |
|---|---|---|
| Software house | Muitos clientes, filas de bugs, pouco contexto | Isolamento + playbooks + evidências |
| Time de produto | Ciclo lento relato→fix | Tempo até `verified` com prova |
| Suporte / CS | Depende de engenharia para status | Quadro com estados honestos |

## Unit economics (hipótese — validar na final)

| Item | Hipótese early-stage |
|---|---|
| Custo variável / caso | LLM (triage+repro+fix) + minutos de sandbox |
| Preço alvo | Faixa SaaS por repositório conectado + overage por caso |
| Margem | Sobe com cache de playbooks, limites de tentativas e dogfood |
| Payback | Redução de horas-engenheiro por incidente reproduzível |

*Números definitivos entram no pitch de 5 min da final (§8.6 / §9.2 Potencial de Investimento).*

## Tração / validação atual

- Protótipo **staging** público (API + worker + Quadro).
- Caso dogfood (cupom) e caso negativo (`needs_info`).
- Monorepo open source: `moouraajv/ResolveQA`.

## Referências

- Fluxo do agente: [`fluxo-agente.md`](fluxo-agente.md)
- Pitch: [`../../pitch/`](../../pitch/)
- Roteiro 3 min: [`pitch-roteiro-3min.md`](pitch-roteiro-3min.md)
- PRD: [`../PRD.md`](../PRD.md)
