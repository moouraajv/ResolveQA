# Evolução desde a etapa regional → Final

Edital §7 (continuidade) e §8.6 / critério **Evolução desde a Etapa Regional** (§9.2, 10%).

> Documento vivo: atualizar após mentorias e antes da final (28/11/2026).

## O que já amadureceu no protótipo atual (staging)

| Eixo | Regional / base | Estado atual no monorepo |
|---|---|---|
| Agente | Ideia do pipeline relato→fix | Spine real: create → fila → worker → orquestrador |
| Verificação | Conceito RED→GREEN | Verifier determinístico; LLM não decide estado |
| Guardrails | — | Playbooks + modos dogfood/general |
| UX | Mock / demo | Quadro Mola em produção mode (sem advance fake) |
| Infra | Local / demo | AWS staging (API + worker + CloudFront) |
| Entregáveis §8 | Parciais | BMC, fluxo, pitch e demo indexados no README |

## Aprendizados de mentoria (preencher)

| Data | Mentoria / tema | O que mudou no produto |
|---|---|---|
| _a preencher_ | | |

## Próximos saltos até a final

1. Unit economics e pricing no pitch de 5 min.
2. Tração: N casos dogfood / piloto com playbook real.
3. Overlay cloud (SQS/Dynamo) se mentorias priorizarem escala.
4. Gravação polida da demo como backup.

## Não faremos

- Trocar de tema ou de problema (vedado pelo §7).
- Prometer merge automático ou progresso inventado no Quadro.
