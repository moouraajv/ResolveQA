# Executor da demo (#19)

Na raiz do clone, com pytest instalado no ambiente:

```sh
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo --scenario coupon
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo --scenario vague
.venv/bin/python -B -m pytest tests/e2e/test_demo_executor.py
```

O padrão é **modo mock**, sem rede nem chave. O comando cria casos novos usando
Intake, Orchestrator, TriageEngine, ReproductionEngine, FixStage e Verification.
O mock substitui somente o LLM; execução de testes, correção isolada, decisão do
verificador, eventos, DeliveryBuilder e ReplyComposer são reais. O caso positivo
usa o cupom DESC10 e termina em verified com RED/GREEN/suíte verde. O relato vago
termina em needs_info sem patch nem pacote. O canal e a resposta são simulados.

Os arquivos ficam em `runs/<case_id>/`: eventos append-only, evidências,
`evidence-manifest.json` com SHA-256 e caminhos, `demo-result.json` com o estado,
e `delivery/pr-nao-publicado/` quando verified. A saída informa a linha do tempo,
os ids das evidências, os exit codes e o caminho do pacote. Delivery recebe cópias
dos logs e diff efetivamente produzidos, nos nomes exigidos por sua API atual.
O FixStage atual é determinístico para o defeito controlado do cupom.

## Dependências ainda fora da main na criação desta branch

- PR #47: `resolveqa.store.evidence_store.EvidenceStore`
- PR #49: `resolveqa.triage.engine.TriageEngine`
- PR #50: `resolveqa.reproduction.engine.ReproductionEngine`
- PR #52: `resolveqa.fix.engine.FixStage`
- PR #53: `resolveqa.verification.verifier.Verification`

Sem essas APIs, o comando informa todas as dependências ausentes e sai com 2
antes de criar casos ou artefatos. Não substitui etapas por resultados fabricados.
Os dois testes E2E exigem as etapas reais: falham explicitamente enquanto faltarem
as dependências, sem skip/xfail nem redução de asserções.

## Modo real, somente por opt-in

O transporte opcional usa Featherless via HTTPS e biblioteca padrão. Exige chave
já presente em `FEATHERLESS_API_KEY` e modelo em `FEATHERLESS_MODEL` ou `--model`:

```sh
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo --real-llm --model MODELO
```

A chave nunca é passada como argumento, registrada ou impressa. O adaptador
público continua validando o conteúdo e contando chamadas; erros de transporte
omitem o corpo da resposta. Sem a flag, mesmo com chave no ambiente, não há chamada
real. Nenhuma chamada real foi feita na validação deste executor. Não há leitura
de arquivos de credenciais. O modo real não altera o FixStage determinístico.

Exit codes: 0 = cenários atingiram os estados esperados; 1 = cenário terminou em
outro estado; 2 = dependência/configuração/erro operacional impediu a execução.

## Validação local antes dos merges

O harness opcional carrega em memória os cinco módulos reais de commits fixados,
sem sobrescrever ou versionar arquivos das outras trilhas. Usa o orquestrador da
branch e executa os mesmos testes E2E, sem substituir etapas nem fabricar verdicts.
Não é o caminho de execução da demo e não mascara a falta de dependências na main.

```sh
git fetch origin pull/47/head:refs/remotes/origin/pr-47 pull/49/head:refs/remotes/origin/pr-49 pull/50/head:refs/remotes/origin/pr-50 pull/52/head:refs/remotes/origin/pr-52 pull/53/head:refs/remotes/origin/pr-53
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo.validate_pending --run-demo --full-suite
```

Os SHAs estão em `validate_pending.py`. Mudanças posteriores nos PRs exigem nova
validação. A suíte normal continua expondo dependências ausentes até seus merges.

## Comprovante de correção e acompanhamento

O executor também grava e imprime os caminhos destes documentos na pasta do caso:

- `acompanhamento.html`: página estática, responsiva e sem JavaScript, fontes ou
  imagens externas. Mostra somente as etapas efetivamente registradas, seus
  horários em UTC e um mascote SVG inline com estado visual correspondente à
  última etapa. Tentativas repetidas continuam na ordem dos eventos. Não há
  etapas futuras preenchidas nem porcentagem de progresso inventada.
- `comprovante.txt`: somente em `verified`, com aprovação independente registrada
  e evidência do verdict RED/GREEN/suíte verde. Contém id, data/hora da aprovação,
  resumo seguro, antes/depois, “Correção verificada” e código de conferência.
  A página incorpora o mesmo texto. Em modo mock, os dois documentos identificam
  “demonstração com dados simulados”. Em `needs_info`, não há comprovante: a página
  apresenta uma pergunta objetiva sobre compra, cupom e valores esperado/observado.

A geração lê `demo-result.json`, `events.jsonl` e `evidence-manifest.json` do caso.
Confere cada SHA-256 contra o arquivo correspondente e recusa referências externas,
sequência inconsistente ou aprovação sem evento/verdict. O código usa os primeiros
16 caracteres hexadecimais de SHA-256 sobre JSON canônico com id, horário de
aprovação e pares ordenados `(evidence_id, sha256)`, em quatro grupos de quatro.
É um código de conferência de integridade, sem assinatura digital ou serviço externo.

Os textos do cliente são construídos com campos permitidos: id opaco, horários e
valores monetários completos. Não copiam texto livre do relato, perguntas do LLM,
nomes de arquivos, caminhos, repositórios, logs ou diffs. O relato aparece resumido
em linguagem simples. A pergunta de dados faltantes usa um modelo seguro do cenário
de checkout. HTML usa escape, CSP restritiva e SVG/CSS inline. Os documentos são
artefatos derivados; não alteram eventos, evidências ou decisões do orquestrador.

Para regenerar a partir de um caso registrado, use a API pública
`resolveqa.demo.customer.generate_customer_artifacts(run_dir)`. Os testes próprios
independem das etapas pendentes:

```sh
.venv/bin/python -B -m pytest tests/e2e/test_customer_artifacts.py
```
