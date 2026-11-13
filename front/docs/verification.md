# Evidências — ResolveQA workspace

Validação local em 08/11/2026, com Chrome em desktop **1536×1024** e celular **390×844**. A branch foi reaplicada sobre `main` em `00a6214`, preservando as novas poses e o transporte Slinky do PR #5.

## Resultado

| Verificação | Resultado |
|---|---|
| `npm test` | 15 testes de contratos, ambiente, linguagem, estados, evidências e percentis |
| `npx tsc --noEmit` | Passou |
| `npm run lint` | Sem erros; 2 avisos herdados em `atlas.ts` e no smoke histórico de artwork |
| `npm run build` | Passou, com `/`, `/admin` e `/quadro` |
| `npm run test:browser` | 18 verificações, sem erros de página |
| `npm run test:stream` | 6 verificações HTTP/SSE locais, sem erros de página |

Os testes do navegador verificam a copy, os acessos diretos, o painel Admin preto com contraste de títulos ≥7:1 e botões ≥4,5:1, logs, waterfall, CRUD/persistência de playbooks, documentação, ausência de overflow da página no celular, rolagem interna do Kanban, criação/detalhes de casos, transporte da Mola, ausência do seletor, linguagem simplificada, env prevalecendo sobre preferências antigas e recuperação de armazenamento inválido.

O serviço HTTP/SSE controlado inicia um front separado com variáveis de produção e verifica conexão, transições, duplicação, descoberta/persistência de casos criados por agentes, evidências e falhas sem dados fictícios. A preferência antiga do navegador não altera o ambiente. Resultados completos: [browser](evidence/functional-checks.json) e [SSE](evidence/stream-checks.json).

## Capturas

| Superfície | Desktop | Celular |
|---|---|---|
| Landing | [Página](evidence/desktop.png) · [primeiro viewport](evidence/desktop-viewport.png) | [Página](evidence/mobile.png) |
| Admin preto | [Painel](evidence/admin-desktop.png) | [Painel](evidence/admin-mobile.png) |
| Mola | [Quadro](evidence/board-desktop.png) · [transporte em execução](evidence/board-motion.png) | [Quadro](evidence/board-mobile.png) |

Outras telas: [logs](evidence/logs-desktop.png), [traces](evidence/traces-desktop.png), [playbooks](evidence/playbooks-desktop.png).

![Landing baseada na primeira referência](evidence/desktop-viewport.png)

![Admin preto e cinza](evidence/admin-desktop.png)

![Mola transportando um card](evidence/board-motion.png)

## Revisão da base visual

A primeira referência foi a base aprovada. A copy de documentação/playbooks e o Admin preto são alterações solicitadas depois dos mockups. A revisão independente identificou sete ajustes de contraste, composição, ações, fundo, densidade e documentação do processo; o retorno de revisão marcou os sete como resolvidos (`ship`, restrito aos ajustes avaliados). Na revisão da base, a comparação mecânica do primeiro viewport atingiu 75,22%, acima do limiar de 72%; não se trata de uma reprodução pixel a pixel da imagem gerada. Conteúdo operacional semântico e o personagem original foram mantidos no código.

## Limites da validação

- O backend do João foi clonado e seus contratos foram auditados. A API existente oferece criação/consulta de casos.
- As verificações de produção usam respostas locais controladas, não uma ativação remota.
- Snapshot, SSE, spans e CRUD de playbooks exigem as extensões descritas em [production-connection.md](production-connection.md).
- O front não autentica administradores, executa agentes, atualiza arquivos de documentação nem faz merge/deploy. Essas operações pertencem ao backend/gateway autorizado.
- Não houve publicação ou merge nesta entrega. O PR contém o código e as evidências para revisão.

## Ajuste posterior: ambiente e linguagem

O seletor de demonstração/produção e os campos de configuração foram removidos de todas as telas. O ambiente e os endereços vêm apenas das variáveis documentadas em .env.example. A interface usa Atividades, Tempo por etapa, Projeto e Procedimentos; erros, identificadores de versões e critérios de verificação recebem explicações em português. A landing não apresenta detalhes de configuração.
