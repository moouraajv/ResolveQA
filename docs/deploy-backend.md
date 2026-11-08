# ResolveQA Backend AWS Deployment Guide & Architecture

## 1. Executive Summary & Hackathon Scope

Este documento especifica a arquitetura, empacotamento e estratégia de implantação na AWS para a superfície HTTP atual do **ResolveQA** (Intake e Chat simulado).

> [!IMPORTANT]
> **Esclarecimento de Escopo (Hackathon):**
> O objetivo do hackathon exige a **jornada completa e real de resolução de bugs**:
> 1. Uma pessoa relata um defeito (via Web, API ou Chat);
> 2. Um agente inteligente reproduz o bug com teste de regressão;
> 3. O agente implementa a correção e verifica a suíte de testes;
> 4. O sistema gera automaticamente um Pull Request no GitHub com evidências.
>
> A entrega desta tarefa de infraestrutura é uma **etapa intermediária de runtime**. Ela empacota as superfícies de **Intake** e **Canal Simulado** (issues #13 e #14) para execução em nuvem com HTTPS, mas **NÃO constitui a entrega final ponta a ponta**. O armazenamento de casos é **estritamente efêmero em memória (`EphemeralCaseStore`)**, sem banco de dados persistente e sem o pipeline completo de reprodução/PR conectado ainda.

---

## 2. Avaliação de Opções de Arquitetura AWS

Durante a investigação técnica e testes no ambiente com credenciais reais da AWS (conta `<AWS_ACCOUNT_ID>`, perfil AWS configurado, região `us-east-1`), avaliamos quatro alternativas de implantação:

| Critério | Opção 1: EC2 Mínimo + CloudFront HTTPS (Escolhida) | Opção 2: AWS App Runner | Opção 3: ECS Fargate + ALB | Opção 4: AWS Lambda + Function URL |
| :--- | :--- | :--- | :--- | :--- |
| **Status** | **Aprovada / Implementada** | **Rejeitada** | **Rejeitada** | **Rejeitada** |
| **Custo Mensal Estimado** | **$0.00 a ~$3.02/mês** (`t4g.nano` Graviton ARM) | ~$5.00 a ~$15.00/mês | ~$23.00/mês (ALB fixo $16 + Fargate) | < $0.50/mês |
| **HTTPS / TLS** | Nativo gratuito via `*.cloudfront.net` | Nativo via `*.awsapprunner.com` | Exige ACM + Domínio próprio em Route 53 | Nativo via Function URL |
| **Preservação do Store Efêmero** | **100% (Processo único contínuo)** | Alto (instância única) | Alto (1 réplica) | **Inviável (múltiplos workers stateless perdem o estado em memória entre requisições)** |
| **Dependência do Docker Local** | **Nenhuma (executa Python 3.11 nativo)** | Exige push OCI para ECR | Exige push OCI para ECR | Exige build de imagem ou zip com adaptadores |
| **Assinaturas / Subscrições** | **Nenhuma necessária** | **Falha: `SubscriptionRequiredException`** | Nenhuma | Nenhuma |
| **Complexidade de Template** | Baixa a Moderada (1 template CloudFormation) | Baixa | Alta (VPC, Subnets, ALB, Target Groups, ECS) | Moderada (requer adapter WSGI/ASGI) |

### Por que a Opção 1 (EC2 Mínimo + CloudFront) foi selecionada?
1. **Sem bloqueio de subscrição**: A tentativa de listar serviços no App Runner (`aws apprunner list-services`) falhou com `SubscriptionRequiredException`. O usuário determinou estritamente não habilitar novas subscrições na conta.
2. **Independência do daemon Docker local**: No host de desenvolvimento, o daemon Docker retornou `permission denied` no socket unix. A Opção 1 executa Python 3.11 nativo diretamente no Amazon Linux 2023 gerenciado pelo `systemd`, dispensando a necessidade de compilar ou enviar imagens no deploy.
3. **Fidelidade do armazenamento em memória**: Por se tratar de um demo efêmero em processo único (`ThreadingHTTPServer`), uma única instância garante que todas as chamadas (criação de caso via POST `/api/cases` ou `/chat/messages` e consulta via GET `/api/cases/<id>`) acessem a mesma instância do `EphemeralCaseStore`.
4. **HTTPS automático sem custos**: O CloudFront fornece terminação TLS com certificado gerenciado da AWS na URL padrão `https://dXXXXXXXX.cloudfront.net`, redirecionando HTTP para HTTPS sem necessidade de registrar domínios no Route 53.
5. **Custo mínimo**: A instância `t4g.nano` (ARM64 Graviton2) custa ~$0.0042/hora (~$3/mês), e contas dentro do AWS Free Tier podem usar `t4g.micro` ou `t3.micro` sem custo.

---

## 3. Topologia e Segurança

A infraestrutura é provisionada via CloudFormation em [`infra/aws/template.yaml`](file://.orchestration/ResolveQA/worktrees/backend-aws/infra/aws/template.yaml):

```
+-----------------------------------------------------------------------------------+
|                                  AWS Cloud                                        |
|                                                                                   |
|   Cliente / Navegador                                                             |
|           │ (HTTPS seguro)                                                        |
|           ▼                                                                       |
|   ┌───────────────────────────────────────────────────────────┐                   |
|   │ AWS CloudFront Distribution (dXXXXXX.cloudfront.net)     │                   |
|   │ - Enforce HTTPS: redirect-to-https                        │                   |
|   │ - CachingDisabled (todas as requisições repassadas)       │                   |
|   │ - Injeção de Header Secreto: X-ResolveQA-Origin-Verify    │                   |
|   └─────────────────────────────┬─────────────────────────────┘                   |
|                                 │ (HTTP :8080)                                    |
|                                 ▼                                                 |
|   ┌───────────────────────────────────────────────────────────┐                   |
|   │ Amazon EC2 Instance (t4g.nano / Amazon Linux 2023)        │                   |
|   │ - Security Group: Ingress TCP 8080                        │                   |
|   │ - systemd: resolveqa-backend.service                      │                   |
|   │ - Runtime: Python 3.11 standard library only              │                   |
|   │ - Store: EphemeralCaseStore (in-memory)                   │                   |
|   └───────────────────────────────────────────────────────────┘                   |
+-----------------------------------------------------------------------------------+
```

### Mecanismos de Proteção e Dados
- **Restrição de Origem**: O CloudFront injeta um cabeçalho customizado secreto (`X-ResolveQA-Origin-Verify`) para validar que o tráfego recebido no backend provém da CDN e não de varreduras diretas da Internet.
- **Isolamento de Dados no Intake**: Conforme estabelecido no Intake (RF-01) e Chat Simulado, relatos de bugs enviados por usuários são rigorosamente escapados em HTML (`html.escape`) e tratados como *dados passivos*, impedindo injeção de instruções ou scripts no renderizador.

---

## 4. Estrutura do Pacote e Arquivos

- [`Dockerfile`](file://.orchestration/ResolveQA/worktrees/backend-aws/Dockerfile): Imagem OCI baseada em `python:3.11-slim` com usuário não privilegiado (`resolveqa`, UID 10001), healthcheck nativo com biblioteca padrão e sem dependências externas.
- [`.dockerignore`](file://.orchestration/ResolveQA/worktrees/backend-aws/.dockerignore): Exclusão de caches, testes, documentação e infraestrutura para manter o contexto limpo.
- [`infra/aws/template.yaml`](file://.orchestration/ResolveQA/worktrees/backend-aws/infra/aws/template.yaml): Template CloudFormation validado pela AWS API em `us-east-1`.
- [`scripts/run_server.py`](file://.orchestration/ResolveQA/worktrees/backend-aws/scripts/run_server.py): Entrypoint com tratamento de sinais (`SIGTERM`/`SIGINT`), banners de disclaimer efêmero e configuração por variáveis de ambiente (`RESOLVEQA_HOST`, `RESOLVEQA_PORT`).
- [`scripts/smoke_test.py`](file://.orchestration/ResolveQA/worktrees/backend-aws/scripts/smoke_test.py): Validador completo de endpoints que testa `/health`, `/form`, `/api/cases`, `/chat` e `/chat/messages` sem dependências externas.
- [`scripts/validate_template.sh`](file://.orchestration/ResolveQA/worktrees/backend-aws/scripts/validate_template.sh): Script de validação sintática e semântica do CloudFormation.

---

## 5. Como Executar e Validar

### 5.1 Execução Local do Servidor
Para iniciar o servidor localmente:
```bash
python scripts/run_server.py --host 127.0.0.1 --port 8080
```

### 5.2 Execução da Suíte de Smoke Tests
Em outro terminal ou contra uma URL remota:
```bash
python scripts/smoke_test.py --base-url http://127.0.0.1:8080
```

### 5.3 Validação do Template CloudFormation
Para validar o template contra a API da AWS (somente leitura, sem criar recursos):
```bash
./scripts/validate_template.sh
```

---

## 6. Procedimento de Implantação na AWS (Quando Autorizado)

> [!NOTE]
> De acordo com as diretrizes operacionais, **nenhuma mutação de nuvem (`create-stack`, deploy) foi executada nesta etapa**. Quando a coordenação autorizar o provisionamento, o comando abaixo poderá ser utilizado com o perfil AWS configurado:

```bash
aws cloudformation create-stack \
  --stack-name resolveqa-demo-backend \
  --template-body file://infra/aws/template.yaml \
  --parameters \
      ParameterKey=EnvironmentName,ParameterValue=demo \
      ParameterKey=InstanceType,ParameterValue=t4g.nano \
      ParameterKey=VpcId,ParameterValue=<VPC_ID> \
      ParameterKey=SubnetId,ParameterValue=<SUBNET_ID> \
   \
  --region us-east-1
```

Após a conclusão (`UPDATE_COMPLETE` ou `CREATE_COMPLETE`), os endpoints HTTPS estarão disponíveis nos outputs do CloudFormation:
```bash
aws cloudformation describe-stacks \
  --stack-name resolveqa-demo-backend \
  --query "Stacks[0].Outputs" \
   \
  --region us-east-1
```

---

## 7. Limitações Conhecidas e Próximos Passos (Hackathon)

1. **Armazenamento Volátil**:
   - O estado do sistema reside exclusivamente na memória RAM da instância. Se o processo reiniciar ou a instância for reinicializada, todos os casos cadastrados e mensagens serão perdidos.
2. **Jornada de Resolução Incompleta**:
   - Esta entrega disponibiliza o canal de entrada (Intake / Chat) e verificação de saúde (`/health`).
   - Para atender ao critério de vitória do hackathon, as próximas fases devem acoplar o **Agent Runner** a este runtime, conectando o processamento de fila para execução automática do pipeline:
     `Intake -> Reprodução de Falha -> Geração de Patch -> Execução de Testes -> Abertura de PR no GitHub`.
