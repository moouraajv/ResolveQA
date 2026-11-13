# Mola — frontend ResolveQA

Executor: cursor. Coordenador: Codex. Resultado: frontend navegável, responsivo, com personalidade visual e uma mola pixel art que transporta cards entre colunas.

Checkout: `.`. Vinext/React/TypeScript já instalado.

Escrita exclusiva do executor: `app/page.tsx`, `app/globals.css`, componentes próprios em `components/mola/`. Não alterar outros arquivos, Git, dependências, configuração ou publicar. Codex cuida de layout, imagens, README, build, QA e publicação.

## Interface

- Design premium e lúdico: fundo papel #f4f2e9, texto #292b23, verde ácido #c8ec67, laranja queimado; composição editorial com bastante espaço e detalhes pixel. Evitar dashboard corporativo genérico.
- Marca MOLA / agent workspace. Texto principal “Trabalho em movimento.”, com mola grande e expressiva em pixel art. A referência https://keytotwo.com.br/ é de mascote animado pelo site, não copiar sua marca ou layout.
- Navegação: Quadro, Pranchas, Atividade. Badge claro “Modo demonstração”. A atividade simulada nunca é apresentada como atividade real dos agentes.
- Kanban: A fazer / Em andamento / Concluído, seis tarefas ilustrativas dos agentes Codex, cursor e Antigravity. Metadados mono, ações por card.
- Personagem mola de brinquedo (Slinky) reconhecível, várias espiras visíveis, canvas de baixa resolução ou SVG com visual pixel. O personagem deve percorrer a tela ENTRE as colunas e transportar o card enquanto ele muda de estado. Não basta um ícone parado ou um worm.
- Seis skins selecionáveis: Lima, Tangerina, Lavanda, Cromo, Fliperama e Azul.
- Botão Avançar tarefa; autoplay play/pause; movimento manual por botão e drag/drop desktop; adicionar tarefa por formulário; filtro por agente; modal de detalhes fechável com Escape; persistência localStorage versionada; log de eventos.
- Evitar intervalos concorrentes, atualizações de estado obsoletas e duplicação de movimentos. Respeitar prefers-reduced-motion. Mobile e teclado funcionais.
- Pranchas: duas imagens que Codex vai gerar em `/moodboards/mola-paper.png` e `/moodboards/mola-night.png`. Abrir imagem ampliada. Pode usar fallback visual enquanto assets não chegaram.
- Atividade: eventos reais da sessão demonstrativa. Permitir importar snapshot JSON com validação e indicação de origem se viável, sem simular conexão ao GitHub.
- Sem dependências novas nem fontes remotas obrigatórias. Lucide-react está instalado.

## Aceite

Interface completa e bonita; controles funcionam; mola realmente acompanha o transporte do card; dados persistem; modo demo identificado; sem status de backend inventado. Verificar `npx tsc --noEmit` e reportar o exit code. Não rodar build ou commitar. Reportar arquivos, verificações e limitações via `maestri ask "Codex" "<resultado>"` quando terminar.
