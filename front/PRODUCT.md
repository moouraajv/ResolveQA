# ResolveQA
<!-- impeccable:product-schema 1 -->
## Platform
web
## Users
Operadores de suporte e engenharia acompanham casos e agentes em nuvem. Administradores observam execuções e cadastram playbooks.
## Product Purpose
Converter relatos de bugs em reprodução, correção mínima e verificação independente com evidências. Atualizar documentação e oferecer suporte aos playbooks das empresas são diferenciais confirmados pelo usuário. Merge exige revisão humana.
## Operating Context
Landing dá acesso direto a /admin e /quadro. Admin é painel de operação, nunca outra landing. Mola é Kanban operacional com transporte animado de cards em resposta aos eventos do backend.
## Capabilities and Constraints
Demonstração explícita e alternância para produção sem dados sintéticos no modo real. Eventos seguem CaseCreated, StateChanged, EvidenceAdded, LimitReached, MessageSent, ReplayStarted. Estados: created, triaging, triaged, reproducing, reproduced, fixing, fixed, verifying, verified, needs_info, blocked, infra_error. verified só após verificação independente.
Backend confirmado pelo usuário: https://github.com/moouraajv/ResolveQA.git. main contém contratos; integration/backend-pipeline tem criação POST /api/cases e consulta GET /api/cases/:id. Nas branches inspecionadas não há API de observabilidade, stream, listagem de casos ou playbooks; contratos de transporte e endpoints adicionais precisam ser definidos explicitamente, sem fingir disponibilidade.
## Brand Commitments
Nome ResolveQA, interface Mola e personagem animado existente preservados. Referências funcionais: Trello, GitHub Projects, Jira. Usuário rejeita visual InterHub Sites e solicita Impeccable. Português brasileiro.
## Evidence on Hand
Backend clonado em ../work/ResolveQA-backend; PRD, RFC-0001 e contratos Python lidos. Front existente em React/TypeScript Vinext. Atlas e transporte em components/mola e public/mascot.
## Workflow Approval
Usuário aprovou explicitamente a primeira referência (entrada equilibrada entre Mola e Admin) e autorizou implementação em código e criação de PR.

## Configuração e linguagem da interface

Escolha entre exemplos e serviço real exclusivamente por RESOLVEQA_MODE no env. Nenhum seletor ou campo de configuração técnica na UI; configurações antigas de navegador não podem sobrepor o servidor. Termos técnicos recebem nomes e explicações úteis para a pessoa, com dados originais preservados.
