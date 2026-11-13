# Snapshots locais

Na seção Atividade, exporte as tarefas como JSON ou importe um arquivo no mesmo formato. O quadro é um frontend demonstrativo: importar um snapshot não estabelece uma conexão contínua com agentes ou com o GitHub.

```json
{
  "version": 1,
  "tasks": [
    {
      "id": "QA-123",
      "title": "Verificar o fluxo de cadastro",
      "description": "Executar as condições de aceite e anexar evidências.",
      "status": "todo",
      "agent": "Codex",
      "tag": "QA",
      "priority": "Alta"
    }
  ]
}
```

As etapas aceitas são `todo`, `doing` e `done`. Os responsáveis disponíveis são `Codex`, `cursor` e `Antigravity`; prioridade aceita `Alta` ou `Normal`. Os identificadores precisam ser únicos. A importação aceita no máximo 100 tarefas e 2 MB. O formato e os campos de texto são validados antes de substituir o quadro.

Para uma integração futura, um adaptador pode converter o estado do orquestrador para esse formato. Credenciais e chamadas autenticadas devem permanecer no serviço que produz os eventos, fora do bundle do navegador. Este repositório não publica automaticamente ações de produção a partir dos dados importados.
