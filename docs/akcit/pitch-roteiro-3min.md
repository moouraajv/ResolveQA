# Roteiro de pitch — 3 minutos (Hackathon Regional / Online)

Edital §8 + critério **Qualidade do Pitch** (§9.1, 15%): clareza, objetividade e explicação do **fluxo do agente** na demo.

Deck: [`pitch/ResolveQA-Pitch-Deck-Converge-2026.pdf`](../../pitch/ResolveQA-Pitch-Deck-Converge-2026.pdf)  
Fluxo (apoio Q&A): [`fluxo-agente.md`](fluxo-agente.md)  
Demo ao vivo: [`demo-ao-vivo.md`](demo-ao-vivo.md)

---

## Timing

| Min | Bloco | O que dizer / mostrar |
|---|---|---|
| 0:00–0:25 | **Gancho + problema** | “Um cliente relata: o cupom de 10% não baixou o total. Hoje isso vira telefone sem fio — suporte, dev, QA, resposta — e o contexto se perde.” |
| 0:25–0:55 | **Solução em uma frase** | “ResolveQA é um pipeline de **agentes de IA** que transforma o relato em teste que reproduz o bug, correção mínima, verificação independente e resposta ao cliente — **sem merge automático**.” |
| 0:55–1:50 | **Fluxo do agente (inputs → lógica → outputs)** | Abrir Quadro/form (ver demo). Narrar: **entrada** = relato + repo + client_id → **triage** → **reprodução RED** → **fix + playbook** → **verifier determinístico RED→GREEN** → **PR/evidências + reply**. Frase-chave: “O LLM não decide `verified`; o código decide.” |
| 1:50–2:25 | **Diferencial + IA no núcleo (§9.4)** | Centralidade: sem o agente, some o valor. Profundidade: orquestrador, guardrails, limites, estados honestos (`needs_info`). Ativo: playbooks da empresa + evidências por caso. |
| 2:25–2:50 | **Negócio (BMC em 20s)** | B2B para software houses / produto: menos tempo relato→correção verificada; receita SaaS por repo/caso; humano no merge. |
| 2:50–3:00 | **Pedido / fechamento** | “Demo pública no staging; pedimos a chance de evoluir até a final com foco em escala e unit economics.” |

---

## Frases prontas (não improvisar)

1. “Inputs: relato em linguagem natural. Lógica: multi-etapa com verifier fora do LLM. Outputs: evidências + draft PR + resposta só após `verified`.”
2. “Se removêssemos a IA, o ResolveQA deixaria de existir — ela não é um chatbot acessório.”
3. “Progresso no Quadro é real: worker na fila, sem botão que finge avanço.”

## Q&A — respostas curtas

| Pergunta | Resposta |
|---|---|
| E se o relato for vago? | Vai para `needs_info`, sem patch inventado. |
| O agente faz merge? | Não. Só draft PR / pacote; merge humano. |
| Como evita alucinação de “corrigido”? | Verifier determinístico: teste RED antes, GREEN depois + suíte. |
| Onde roda? | Staging AWS: API + worker + CloudFront (URLs no README). |

## Checklist antes de subir ao palco

- [ ] Quadro e form abertos em abas (staging)
- [ ] Relato do cupom colado na área de transferência
- [ ] Deck PDF aberto na slide 1
- [ ] Cronômetro / pessoa com sinal em 2:30
