# Executor da demo (#19)

Na raiz do clone, com pytest instalado no ambiente:

```sh
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo --scenario coupon
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo --scenario vague
.venv/bin/python -B -m pytest tests/e2e/test_demo_executor.py
```

O padrão é **modo mock**, sem rede, usando `LLMAdapter(use_real=False)` mesmo se
`RESOLVEQA_LIVE` existir no ambiente. Intake, Orchestrator, etapas, Delivery e Reply
são APIs públicas da branch. Não há importação de scripts de desenvolvimento nem
execução de código Git pelo pacote `resolveqa`.

Cada execução cria casos novos e grava eventos, evidências, manifesto SHA-256 e
resumo JSON em `runs/<case_id>/`. O cupom termina em verified somente com decisão
do verificador; o relato vago termina em needs_info, sem patch/pacote. A resposta
correta deriva de `triage.expected` após aprovação, sem valor fixo. A pergunta
conserva seu ponto de interrogação sem o ponto final adicional. O canal e a resposta
são simulados e rotulados. O pacote local fica identificado como “PR não publicado”.

## Modo real

```sh
PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo --real-llm
```

O único provedor é o `LLMAdapter(use_real=True)` integrado na main pelo #46:
transporte sem redirects, retries e fallback conforme `src/resolveqa/llm/config.json`.
A chave é lida pelo adaptador somente de `~/.config/resolveqa/featherless.env`, com
permissão 0600. A demo não lê chave de variável de ambiente nem guarda credencial
em instância própria. Sem arquivo/chave válida, o modo real falha claramente antes
de carregar etapas. Não há transporte HTTP próprio no pacote demo e não há flag
própria de modelo; os modelos vêm da configuração pública do adaptador.

## Dependências ainda pendentes

Enquanto faltarem APIs de reprodução #50, correção #52 ou verificação #53 na main,
o comando normal lista os componentes ausentes e retorna 2, sem fabricar resultados.
O modo ao vivo requer os merges; o replay de palco é o Plano B. Store #47, adaptador
#46 e triagem #49 já estão integrados na main usada nesta revisão.

## Validação somente para desenvolvimento

```sh
PYTHONPATH=src .venv/bin/python -B scripts/dev_validate_pending.py --full-suite
```

O script fica **fora de src/** e nunca é importado pela aplicação. Ele usa somente
blobs Git locais de commits fixados, preenchendo apenas módulos ausentes. Não faz
fetch nem merge e não substitui APIs presentes na main. Os snapshots são escritos
num diretório temporário; `module.__file__` aponta para o arquivo real do snapshot
durante toda a validação. A saída diz “SOMENTE DESENVOLVIMENTO”. Não se trata de uma
execução da demo sobre main já integrada nem de um caminho de apresentação.

Os blobs precisam existir no clone. Nenhuma chamada real ao provedor é necessária:

```sh
git fetch origin pull/50/head:refs/remotes/origin/pr-50 pull/52/head:refs/remotes/origin/pr-52 pull/53/head:refs/remotes/origin/pr-53
PYTHONPATH=src .venv/bin/python -B scripts/dev_validate_pending.py --run-demo
```

Os testes E2E montam o alvo e a configuração em `tmp_path`; não gravam runs no clone.
Testes do modo real usam somente HOME temporário vazio ou arquivo 0600 com chave
sintética e transporte de teste. O live opcional da suíte permanece desabilitado
quando RESOLVEQA_LIVE não está definido.

Exit codes: 0 = estados esperados; 1 = cenário terminou em outro estado; 2 =
configuração, dependência ou erro operacional impediu a execução.
