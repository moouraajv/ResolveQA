---
name: ResolveQA
description: Sala de controle editorial para casos, agentes e evidências.
colors:
  paper: '#f7f7ef'
  surface: '#fffefa'
  ink: '#232622'
  muted: '#686c65'
  line: '#ddddd4'
  accent: '#bb4427'
  green: '#386943'
  admin-paper: '#101010'
  admin-surface: '#171717'
  admin-ink: '#f1f1f1'
  admin-muted: '#a8a8a8'
  admin-line: '#343434'
  admin-accent: '#e59364'
  admin-action: '#b84e2e'
  admin-action-text: '#fff8ef'
typography:
  display:
    fontFamily: 'Montserrat, Manrope, sans-serif'
    fontWeight: 700
    letterSpacing: '-0.04em'
  headline:
    fontFamily: 'Manrope, sans-serif'
    fontSize: '30px'
    fontWeight: 750
    lineHeight: 1.25
    letterSpacing: '-0.035em'
  body:
    fontFamily: 'Manrope, sans-serif'
    fontSize: '14px'
    lineHeight: 1.6
  code:
    fontFamily: 'Consolas, monospace'
    fontSize: '0.88em'
rounded:
  field: '6px'
  button: '8px'
  card: '9px'
  lane: '10px'
  panel: '12px'
spacing:
  compact: '7px'
  control: '10px'
  section: '20px'
  app-gutter: '30px'
components:
  status:
    padding: '3px 7px'
  button-primary:
    backgroundColor: '{colors.accent}'
    textColor: '#fffaf5'
    rounded: '{rounded.button}'
    padding: '10px 17px'
  button-secondary:
    backgroundColor: 'transparent'
    textColor: '{colors.ink}'
    rounded: '{rounded.button}'
    padding: '10px 17px'
  button-admin:
    backgroundColor: '{colors.admin-action}'
    textColor: '{colors.admin-action-text}'
    rounded: '{rounded.button}'
    padding: '10px 17px'
  input:
    backgroundColor: '{colors.surface}'
    rounded: '{rounded.field}'
    padding: '10px 11px'
  case-card:
    backgroundColor: '{colors.surface}'
    rounded: '{rounded.card}'
    padding: '10px'
  admin-panel:
    backgroundColor: '{colors.admin-surface}'
    rounded: '{rounded.panel}'
    padding: '19px'
---

# Design System: ResolveQA

## Overview

**Creative North Star: "Sala de controle editorial"**

Interface de engenharia com leitura editorial: títulos fortes, planos foscos, divisórias finas e conteúdo operacional compacto. Landing e Mola usam papel claro e quente; Admin usa preto e cinzas neutros, conforme a correção explícita do usuário. O laranja identifica ações e seleção.

O personagem Mola preserva o atlas arco-íris original; o movimento elástico Slinky foi integrado ao transporte. Conteúdo, controles e estados permanecem compreensíveis sem depender da animação.

**Key Characteristics:**
- Papel claro na entrada e no quadro; preto neutro no Admin.
- Hierarquia tipográfica forte sobre dados compactos.
- Demonstração identificada e ambiente explícito.
- Personagem original como comportamento funcional do quadro.

Registro extraído de `app/globals.css`, páginas e `components/workspace`, após implementação. Substitui a proposta anterior pelo sistema construído. A primeira referência aprovada é `.impeccable/mocks/01-entrada-equilibrada.png`; dados semânticos do produto, personagem original, copy de documentação/playbooks e Admin preto são adaptações aprovadas. O seed `bfa2bf7e`, candidato 6, corrobora a origem da direção; não constitui pesquisa com usuários nem prova de implementação.

## Colors

### Primary

Laranja queimado (`accent`) para ação nas superfícies claras. No Admin, pêssego (`admin-accent`) serve links e ícones; botões primários têm o preenchimento próprio `admin-action` e texto `admin-action-text`, preservando contraste. A landing tem um tratamento pontual de CTA desktop; não generalizá-lo a todos os botões.

### Secondary

Verde (`green`) identifica verificação no contexto claro. Estados claros combinam neutro para entrada, azul para atividade, ocre para revisão, verde para conclusão e terracota para atenção. Cada estado também apresenta texto e ícone.

### Neutral

Papel, superfície, tinta, texto auxiliar e divisória compõem o tema claro. Os equivalentes `admin-*` são os valores efetivos do tema escuro, superando as regras verdes anteriores na cascata. A prévia do Admin também usa preto neutro.

**The Theme Boundary Rule.** Preserve preto e cinza neutro no Admin; não propague os verdes de superfície do quadro para o painel. Acentos laranja e alertas quentes continuam semânticos.

## Typography

Manrope variável local atende corpo, controles e títulos operacionais. Montserrat variável local aparece no título principal da landing; Consolas fica nos IDs e código. Métricas, horários e código usam algarismos tabulares.

Display responsivo: a cascata final define `clamp(42px, 4.2vw, 64px)`, passa a (68px) a partir de (1200px) e a (39px) até (600px). Desktop usa entrelinha (1.03); o título preserva três linhas sem quebra interna acima de (900px). Corpo base reduz para (13px) até (600px). Títulos de painel usam (13px), controles usuais (10–13px), etiquetas e dados auxiliares (9–11px). A compactação das prévias não deve orientar novos conteúdos essenciais.

**The Data Type Rule.** Use mono e números tabulares para identificação e medição; preserve sans legível nos relatos e ações.

## Layout

Landing centralizada com limite (1600px), margem interna horizontal (34px), depois (24px) até (900px) e (19px) até (600px). Acima de (900px), hero em duas colunas (`minmax(350px, .85fr)` e `minmax(0, 1.5fr)`), título à esquerda e demonstração à direita. Fluxo de quatro etapas vem abaixo; dois acessos de produto dividem a linha seguinte. Até (900px), hero e acessos empilham.

Aplicação usa lateral (216px) e conteúdo flexível; cabeçalho (67px). Conteúdo tem limite (1700px) e margem interna (30px). Navegação muda no responsivo; filtros e ações quebram linha. Tabelas preservam rolagem local e a aplicação contém vazamento horizontal. Quadro tem cinco colunas `repeat(5, minmax(190px, 1fr))`, intervalo (13px), rolagem horizontal e encaixe por proximidade.

**The Evidence Hierarchy Rule.** Separe contexto, ações, indicadores e dados por alinhamento e divisórias; mantenha busca, acompanhamento e detalhes disponíveis no responsivo.

## Elevation & Depth

Profundidade vem principalmente de planos sólidos, bordas de (1px) e diferença tonal. Cards e links de prévia recebem sombra suave no hover. Diálogo e gaveta usam sombra larga de sobreposição; diálogo tem backdrop escurecido. Valores exatos de sombra e movimento ficam no sidecar.

## Shapes

Retângulos suavemente arredondados: controles e botões compactos, cards com cantos médios, painéis com cantos mais largos. Etiquetas de estado usam (5px), ícones clicáveis (6px), diálogo (14px). Círculos pequenos identificam atividade; Mola preserva silhueta e arco-íris do atlas.

## Components

### Buttons

Botão padrão com altura mínima (43px), peso (650) e variante compacta (35px). Primário preenchido; secundário transparente com borda. Hero desktop tem altura (53px), texto (19px) e maior peso visual. Hover altera preenchimento; desabilitado reduz opacidade para (.48). Ícones são SVG.

### Chips

Estado une texto, ícone e fundo tonal. Admin usa conclusão e entrada em cinza, atividade/revisão em tons quentes e atenção terracota. Exemplos ilustrativos são identificados sem expor termos de configuração.

### Cards / Containers

Card de caso claro com borda, relato, ID, repositório, agente e estado. Painéis administrativos agrupam métricas, séries, execuções, logs, traces e playbooks. Métricas usam quatro divisões com linhas verticais, em vez de cards decorativos separados.

### Inputs / Fields

Campos têm rótulo associado, preenchimento sólido e borda; busca incorpora ícone e rótulo acessível oculto. Busca usa contorno no grupo quando recebe foco. Erros usam `role="alert"`; sucesso usa `role="status"`. Preservar descrições auxiliares e estados vazios reais.

### Navigation

Landing usa navegação horizontal e acessos diretos à Mola e ao Admin. Aplicação usa lateral agrupada e seleção visível. Não renderizar seletor Demo/Produção: o ambiente e os endereços são definidos exclusivamente no .env. Foco visível global: contorno laranja de (3px), deslocado (3px); busca tem contorno próprio de (2px).

### Mola e detalhes

Mola transporta card entre colunas em resposta a eventos e retorna ao repouso. Atlas original continua fonte visual; deformação Slinky acrescenta locomoção. Transporte decorativo é oculto para leitores de tela. Gaveta de detalhes tem nome acessível e fechamento rotulado; diálogo usa elemento nativo. `prefers-reduced-motion` remove transições/animações CSS e rolagem suave, e é consultado pelo transporte JavaScript. Estado de domínio não depende de completar a viagem visual.

## Do's and Don'ts

### Do:
- **Do** preserve a separação entre papel claro e Admin preto neutro.
- **Do** mantenha texto e ícone junto dos estados e ambiente explícito.
- **Do** preserve foco visível, rótulos, redução de movimento e rolagem local dos dados.
- **Do** derive novas superfícies dos controles e hierarquias existentes.

### Don't:
- **Don't** reintroduza verde nos fundos e planos do Admin.
- **Don't** substitua o personagem original por uma ilustração genérica.
- **Don't** apresente dados de demonstração como operação remota comprovada.

Não canonizado: microtipografia de prévias comprimidas e ajustes pontuais de composição não são tokens gerais. A avaliação final informada aprovou as sete correções materiais; a diferença numérica de hero (75,22%) é registro de revisão, não regra visual nem alegação de paridade pixel a pixel.

## Linguagem da interface

Atividades explica o histórico antes chamado Logs; Tempo por etapa apresenta o detalhamento antes chamado Traces. Projeto substitui repositório. Procedimentos explica os playbooks da empresa. Não apresentar códigos de erro, nomes de variáveis, hashes ou configuração de serviços nas jornadas; dados originais continuam preservados para integração.
