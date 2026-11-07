# PRD — ResolveQA

> **Versão base — aguardando revisão da equipe**
> Nada neste documento foi implementado ou testado.

**Legenda**
- **[FATO]** é uma informação já estabelecida.
- **[HIPÓTESE]** é uma suposição a validar.
- **[DECISÃO PENDENTE]** cabe à equipe decidir.

---

## 1. Visão e problema

**Visão.** O cliente descreve o problema pelo canal que já usa, como uma conversa estilo WhatsApp. O ResolveQA transforma o relato num teste que reproduz o bug, produz uma correção mínima e a submete a um verificador independente. Depois gera um PR com evidências e responde a quem reclamou.

**Problema.** Hoje, o caminho entre o relato do cliente e a correção é manual e fragmentado:
1. O suporte interpreta o relato.
2. Um dev coleta contexto e tenta reproduzir.
3. Alguém corrige.
4. Alguém confirma.
5. Por fim, alguém responde ao cliente.

Cada passagem de mão perde contexto e tempo. [HIPÓTESE: o tamanho dessa dor ainda não foi medido]

**Exemplo de relato** (só para a demo): "Apliquei um cupom de 10% em uma compra de R$ 200, mas o total continuou em R$ 200." Não é o único caso possível; veja a decisão pendente na seção 10.

## 2. Personas

| Persona | Papel | O que precisa |
|---|---|---|
| **Cliente final** | Relata o problema | Ser ouvido no próprio canal e receber resposta quando o problema for corrigido |
| **Suporte/CS** | Recebe o relato e responde ao cliente | Ver o estado do caso sem depender da engenharia e responder com prova |
| **Dev/revisor** | Aceita a entrega com merge humano | PR pequeno, com reprodução e evidências fáceis de conferir |
| **Software house** | Mantém sistemas de vários clientes | Isolamento entre clientes e repositórios, com histórico de cada caso |

As necessidades das personas são [HIPÓTESE] até que haja entrevistas.

## 3. Objetivos e métricas de sucesso

**Demo do MVP** (são metas, não resultados medidos):
- O-1. Fluxo ponta a ponta em até 2 minutos: relato → teste que reproduz → correção → verificação → PR ou pacote de evidências → resposta ao cliente.
- O-2. Zero `verified` falsos. Nenhum caso aparece como corrigido sem aprovação do Verifier.
- O-3. Um caso negativo, com relato insuficiente, termina em `needs_info` sem gerar patch.
- O-4. A demo é ensaiada duas vezes, com uma gravação identificada como plano B.

**Métricas de produto** [HIPÓTESE; ainda não há base de comparação]:
- Tempo do relato à resposta ao cliente, em mediana e com o tamanho da amostra.
- Taxa de casos reabertos pelo mesmo problema.
- Fração dos relatos que viram uma reprodução válida.

## 4. Escopo: MVP x Roadmap

| Item | MVP | Roadmap |
|---|---|---|
| Entrada por formulário ou API | Sim | Webhooks de helpdesks |
| Canal estilo WhatsApp | **Simulado e identificado na demo** | Integração com a API oficial |
| Triagem, reprodução por linguagem natural, correção | Sim, num repositório controlado com um defeito de exemplo | Várias linguagens |
| Verificação independente | Sim, de forma determinística, rodando testes numa cópia isolada | Ambiente parecido com produção |
| PR com evidências | Draft PR se houver repositório autorizado; caso contrário, pacote local identificado | Pacote de evidências para auditoria |
| Resposta ao cliente | Mensagem simulada no mesmo canal | Envio real e confirmação de leitura |
| Vários clientes e repositórios | **Roadmap.** No MVP, o caso tem o campo `client_id`, mas a demo usa um só cliente | Isolamento real, credenciais por cliente, visão por cliente |
| Aprendizado entre casos | Não | Depois de definir a política de privacidade de dados |

## 5. Requisitos funcionais

Cada requisito tem critério de aceite verificável. "MVP" indica o que entra na demo.

- **RF-01 — Entrada do relato (MVP).** O sistema recebe o relato por formulário ou API: texto livre, repositório e `client_id`.
  *Aceite:* um relato enviado cria um caso com `case_id` único, estado `created` e consulta por ID.
- **RF-02 — Canal estilo WhatsApp, simulado (MVP).** Uma interface de conversa permite enviar o relato.
  *Aceite:* a tela mostra o rótulo visível "Canal simulado", e a mensagem enviada gera um caso igual ao do RF-01.
- **RF-03 — Triagem (MVP).** O relato vira um registro estruturado: entrada, valor esperado, valor observado, arquivos suspeitos e confiança.
  *Aceite:* no caso de exemplo, esperado e observado estão preenchidos e coerentes com o relato. Se faltar dado, o caso vai para RF-07.
- **RF-04 — Reprodução a partir de linguagem natural (MVP).** O sistema gera um teste novo a partir do relato, sem depender de um teste prévio do defeito.
  *Aceite:* o teste gerado falha na versão com defeito, na asserção ligada ao relato, e não por erro de ambiente. Log e exit code ficam guardados.
- **RF-05 — Correção mínima (MVP).** O sistema propõe um patch limitado à causa identificada, numa branch ou cópia isolada.
  *Aceite:* o diff não altera o teste de reprodução, os demais testes nem a configuração de CI. O número de arquivos alterados respeita o limite configurado.
- **RF-06 — Verificação independente (MVP).** Um Verifier separado do Fixer roda o mesmo teste antes e depois da correção e também a suíte relevante.
  *Aceite:* `verified` só aparece quando o teste falha antes, passa depois, a suíte relevante está verde e o identificador de cada revisão foi registrado. O LLM não define o estado.
- **RF-07 — Estados terminais honestos (MVP).** Os estados `needs_info`, `blocked` e `infra_error` sempre trazem o motivo.
  *Aceite:* um relato sem dados suficientes termina em `needs_info`, com uma pergunta ao suporte e sem patch. Uma falha de ambiente aparece como `infra_error`, nunca como bug reproduzido.
- **RF-08 — PR com evidências (MVP).** O sistema gera um draft PR com relato, causa, diff, teste antes e depois e limites. Sem repositório autorizado, gera um pacote local.
  *Aceite:* links e anexos do PR ou do pacote existem de fato. O pacote local vem identificado como "PR não publicado". Não há merge automático.
- **RF-09 — Resposta ao cliente (MVP).** Depois de `verified`, o sistema envia ao cliente, no mesmo canal, uma resposta em linguagem simples.
  *Aceite:* a mensagem cita o comportamento corrigido (no exemplo: "total agora R$ 180,00") e só sai após `verified`. Nos estados `needs_info` e `blocked`, sai uma mensagem honesta de andamento.
- **RF-10 — Linha do tempo do caso (MVP).** O suporte vê a sequência real de estados, com horário e evidências.
  *Aceite:* cada transição tem horário e origem. Nenhum progresso é simulado, e um replay aparece rotulado com o horário do run original.
- **RF-11 — Vários clientes e repositórios (Roadmap; o modelo de dados entra no MVP).** Casos, repositórios e credenciais ficam isolados por cliente.
  *Aceite no MVP:* todo caso tem `client_id`. *Aceite no roadmap:* um caso do cliente A não lê o repositório, os segredos nem as evidências do cliente B, e um teste negativo comprova isso.
- **RF-12 — Pacote de evidências para auditoria (Roadmap).** O sistema exporta a cadeia relato → teste → aprovação → commit → deploy.
  *Aceite:* o pacote liga o SHA aprovado ao SHA implantado e registra quem aprovou e quando.

## 6. Requisitos não funcionais

- **RNF-01 Segurança e segredos.** O worker que executa código do repositório não recebe tokens de Git nem chaves de LLM. Logs, prompts e PRs não contêm segredos. *Aceite:* uma varredura de segredos nos artefatos da demo não encontra nada.
- **RNF-02 Conteúdo não confiável.** Relato, README, logs e saídas de ferramentas são tratados como dados. Instruções contidas neles não disparam ação. *Aceite:* um relato com instrução maliciosa não executa a ação pedida.
- **RNF-03 Limites de custo e tentativas.** No máximo 2 tentativas de correção, 12 chamadas de LLM por caso e 10 minutos por execução de teste. Ao atingir um limite, o caso termina com o motivo registrado. Os valores são limites propostos, não custos medidos.
- **RNF-04 Auditoria.** Todo caso tem uma trilha de eventos imutável, com `case_id`, horário, estado e referência de evidência.
- **RNF-05 Merge humano.** Nunca há merge ou deploy automático.
- **RNF-06 Dados.** A demo usa só dados sintéticos, sem dados pessoais reais.
- **RNF-07 Honestidade da demo.** Canal simulado, PR local ou replay aparecem rotulados como tal.

## 7. Fora de escopo (MVP)

- API real do WhatsApp, integrações com helpdesks e webhooks.
- Isolamento real entre vários clientes (RF-11 completo), aprendizado entre casos e ambiente parecido com produção.
- API Gateway, telemetria completa, dashboards de métricas, infraestrutura como código e um segundo provedor de LLM.
- Mais de um defeito, mais de uma linguagem e repositórios arbitrários.
- Autenticação de usuários e deploy público.

## 8. Riscos técnicos

| # | Risco | Mitigação |
|---|---|---|
| RT-1 | O LLM pode não gerar, a partir do relato, um teste que reproduza o defeito de forma confiável [HIPÓTESE] | Validar o RF-04 primeiro, antes de integrar o resto |
| RT-2 | Teste verde não basta para provar que a correção é boa | O teste nasce do relato; a revisão humana é obrigatória |
| RT-3 | Provedor de LLM, chaves e créditos não estão confirmados | Adaptador de provedor com mock; confirmar o acesso cedo |
| RT-4 | Uma falha de ambiente pode ser confundida com o bug | Classificação explícita `infra_error` (RF-07) |
| RT-5 | Um relato ou o repositório pode conter instruções maliciosas | RNF-02 e lista de ferramentas permitidas controlada pelo código |

## 9. Prazo

A submissão do MVP é no domingo, 08/11/2026, às 13h, no horário de Brasília (UTC−3). O alvo interno sugerido é 12h30.

## 10. Questões técnicas em aberto

1. **[DECISÃO PENDENTE] Defeito da demo.** Escolher entre "cupom aplicado duas vezes" e "cupom não aplicado: esperado R$ 180,00, observado R$ 200,00".
2. **[DECISÃO PENDENTE]** Onde a verificação roda: serviço de build na nuvem ou processo local isolado.
3. **[DECISÃO PENDENTE]** Provedor de LLM e confirmação de acesso.
4. **[DECISÃO PENDENTE]** Repositório-alvo da demo e autorização para abrir um draft PR real.
5. **[DECISÃO PENDENTE]** Se o RF-11 entra no MVP só com o `client_id` ou também com uma segunda demo de cliente.

## 11. Referências técnicas

- SWT-Bench, sobre geração de testes de reprodução a partir de issues: https://arxiv.org/abs/2406.12952 (acesso em 07/11/2026)
- Evidência de mudança: a cadeia PR → SHA → deploy: https://oneuptime.com/blog/post/2026-08-04-github-pull-requests-change-management-evidence/view (acesso em 07/11/2026)
