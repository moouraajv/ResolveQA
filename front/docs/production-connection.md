# Conectar o workspace ao backend

A escolha do ambiente e todos os endereços ficam exclusivamente no .env.local ou nas variáveis do deploy. Não há seletor de ambiente nem editor de configuração na interface. Configurações antigas em localStorage são ignoradas.

Copie .env.example na primeira instalação e configure:

```dotenv
RESOLVEQA_MODE=production
RESOLVEQA_API_URL=https://api.sua-empresa.com
RESOLVEQA_CASE_IDS=case-1,case-2
RESOLVEQA_SNAPSHOT_PATH=
RESOLVEQA_EVENTS_PATH=
RESOLVEQA_PLAYBOOKS_PATH=
```

Use demo explicitamente para exemplos locais. Sem RESOLVEQA_MODE, o padrão é production; valores desconhecidos são recusados. Reinicie o servidor ou refaça o build após mudar o arquivo. Somente esses seis campos públicos são permitidos no runtime; segredos continuam no servidor. A tela Conexão mostra apenas a situação do acompanhamento e a ação de atualizar.

## O que funciona com a API existente

Contratos conferidos no repositório `moouraajv/ResolveQA`, branch `integration/backend-pipeline`, commit `f2abd1e`:

- `GET /health`: testa disponibilidade.
- `POST /api/cases`: envia `{client_id, repo_ref, report_text}` e recebe `{case: RunState}`.
- `GET /api/cases/:case_id`: recebe `{case: RunState}`.

O backend precisa liberar a origem do frontend via CORS ou ser servido pelo mesmo gateway. O token de verificação CloudFront/origem fica no servidor. O front não implementa autenticação ou autorização administrativa: o gateway de produção deve proteger a superfície e isolar os dados por empresa.

Sem serviço de snapshot, o front consulta a cada cinco segundos os IDs cadastrados e os casos que criou. Uma mudança de estado recebida nessa consulta aciona a mesma fila de animação do stream. A API atual não lista casos, portanto **descobrir automaticamente casos criados por outros agentes exige o snapshot e/ou o stream adicional**.

## Serviços adicionais: contrato proposto para o gateway

As rotas abaixo são configuráveis, não são endpoints existentes presumidos. Deixe as variáveis opcionais vazias até o backend implementar as rotas.

### Snapshot de operação

`GET <snapshotPath>` retorna:

```json
{
  "cases": [],
  "events": [],
  "spans": [],
  "documents": []
}
```

`cases` contém `RunState` e `events` contém o contrato `Event` do backend. Validação executável em `lib/resolveqa/domain.ts`. O snapshot deve respeitar o escopo autenticado e conter os casos que o usuário pode visualizar.

Campos adicionais de observabilidade, opcionais:

```json
{
  "spans": [{
    "id": "span-1", "case_id": "case-1", "name": "verification",
    "start_ms": 0, "duration_ms": 1200, "status": "ok"
  }],
  "documents": [{
    "id": "doc-1", "case_id": "case-1", "title": "Regra de desconto",
    "path": "docs/checkout.md", "summary": "Comportamento corrigido e teste de regressão.",
    "updated_at": "2026-11-08T03:00:00Z"
  }]
}
```

`status` de span: `ok | error | running`. `start_ms` é relativo ao início da execução. Eventos não são transformados em spans fictícios. A duração do caso no dashboard usa `updated_at - created_at` de casos terminais, não tempo de CPU nem uma métrica de rede.

### Eventos ao vivo

`GET <streamPath>` usa SSE (`Content-Type: text/event-stream`). Cada `data` contém um `Event` válido, com `event_id`, `case_id`, `seq`, `ts`, `source`, `type`, estados e referências de evidência. Aceita mensagens sem nome e eventos nomeados pelos tipos do contrato:

```text
event: StateChanged
data: {"event_id":"e-2","case_id":"case-1","seq":2,"ts":"2026-11-08T03:00:05Z","source":"triage","type":"StateChanged","from_state":"created","to_state":"triaging","reason":"Triagem iniciada","evidence_refs":[]}

```

O frontend ignora IDs repetidos e sequências atrasadas. Casos desconhecidos e lacunas de sequência são reconciliados por `GET /api/cases/:id`. A consulta periódica continua ativa durante reconexões do stream. O snapshot do gateway deve refletir os mesmos estados do stream. A ordenação é por caso; não envie transições conflitantes para a mesma sequência.

O estado recebido é aplicado antes da animação. A Mola apresenta uma fila visual; uma animação não decide se um bug foi corrigido. Apenas `verified` vai para **Concluído**. `needs_info`, `blocked` e `infra_error` vão para **Atenção**. Redução de movimento e cards fora do filtro não atrasam a atualização dos dados.

### Playbooks

API opcional configurada em `<playbooksPath>`:

- `GET <path>` → array de playbooks.
- `POST <path>` → cria e retorna o playbook confirmado.
- `PUT <path>/:id` → atualiza e retorna o playbook confirmado.
- `DELETE <path>/:id` → `204` ou JSON.

```json
{
  "id": "pb-1", "name": "Checkout", "company": "empresa-1",
  "repository": "empresa/checkout", "instructions": "Reproduzir, corrigir, verificar e atualizar docs.",
  "enabled": true, "updated_at": "2026-11-08T03:00:00Z"
}
```

O cadastro é efetivo no armazenamento local em **Demo**. Em **Produção**, só é permitido quando a API está configurada, e a interface espera a confirmação HTTP. O uso de um playbook na execução dos agentes e a edição dos arquivos de documentação são responsabilidades do backend, não operações executadas pelo navegador.

## Demonstração e validação

Demo e produção têm estados separados. O ambiente é fixado no servidor; o navegador não pode selecioná-lo nem substituir os endereços configurados. Desconexões são explícitas; dados antigos exibem o horário da última consulta e não são substituídos por exemplos.

Testes de navegador exercitam a API de produção com respostas controladas localmente. Isso valida o adaptador e o transporte, **não comprova um backend remoto implantado ou instrumentado**.
