# ResolveQA Backend AWS Deployment Guide & Architecture

## 1. Executive Summary & Hackathon Scope

Este documento detalha a arquitetura, modelo de custos, segurança de rede e procedimento de empacotamento na AWS para a superfície HTTP atual do **ResolveQA** (Intake e Chat simulado).

> [!IMPORTANT]
> **Esclarecimento de Escopo (Hackathon):**
> O objetivo central do hackathon é demonstrar a **jornada completa e real de resolução de bugs**:
> 1. Uma pessoa relata um defeito através do formulário Web, API ou Chat;
> 2. Um agente inteligente reproduz o bug executando a suíte de testes do repositório;
> 3. O agente implementa a correção necessária e verifica a eliminação da falha;
> 4. O sistema gera automaticamente um Pull Request documentado no GitHub com evidências.
>
> A infraestrutura apresentada neste documento é uma **etapa intermediária de runtime**. Ela empacota as superfícies de **Intake** (issue #13) e **Canal Simulado** (issue #14) em um ambiente seguro na nuvem com HTTPS, mas **NÃO substitui nem conclui a jornada ponta a ponta**. O armazenamento de casos é **estritamente efêmero em memória (`EphemeralCaseStore`)**, sem persistência durável em banco de dados e sem o agente de reprodução/correção acoplado nesta etapa.

---

## 2. Avaliação de Opções de Arquitetura AWS

Durante a investigação técnica na conta AWS `<AWS_ACCOUNT_ID>` (região `us-east-1`), avaliamos quatro alternativas de implantação:

| Critério | Opção 1: EC2 ARM64 + CloudFront HTTPS (Escolhida) | Opção 2: AWS App Runner | Opção 3: ECS Fargate + ALB | Opção 4: AWS Lambda + Function URL |
| :--- | :--- | :--- | :--- | :--- |
| **Status** | **Aprovada / Implementada** | **Rejeitada** | **Rejeitada** | **Rejeitada** |
| **Custo Estimado** | **~$7.26/mês** (detalhado abaixo) | ~$10.00 a ~$25.00/mês | ~$23.00+/mês (ALB $16 fixo + Fargate) | < $1.00/mês |
| **HTTPS / TLS** | Nativo gratuito via `*.cloudfront.net` | Nativo via `*.awsapprunner.com` | Exige ACM + Domínio registrado | Nativo via Function URL |
| **Store em Memória** | **100% preservado (processo único contínuo)** | Processo único | 1 réplica Fargate | **Inviável (múltiplas instâncias stateless perdem o estado)** |
| **Dependência Docker** | **Nenhuma no deploy (Python 3.11 nativo)** | Exige imagem OCI no ECR | Exige imagem OCI no ECR | Exige container ou zip com adapters |
| **Condição de Conta** | **Sem requisitos de subscrição** | **Inoperante: `SubscriptionRequiredException`** | Sem requisitos de subscrição | Sem requisitos de subscrição |
| **Validação de Prontidão** | `CreationPolicy` + `cfn-signal` após healthcheck | Healthcheck integrado | Healthcheck integrado | Invocação direta |

### Justificativa da Escolha da Opção 1:
1. **Restrições de Execução do App Runner**: A execução de `aws apprunner list-services` falhou com `SubscriptionRequiredException`. O serviço não está habilitado na conta e os limites de governança estabelecem que novas assinaturas de serviços não devem ser ativadas.
2. **Inviabilidade do Modelo Serverless para Store Efêmero**: No AWS Lambda, execuções concorrentes ou reciclagem de contêineres criam ambientes isolados. Uma requisição `POST /api/cases` criaria um caso na memória de uma instância que não existiria na chamada subsequente `GET /api/cases/<id>`. Além disso, a biblioteca padrão pura (`http.server`) não roda nativamente no Lambda sem dependências externas (como Mangum ou AWSGI).
3. **Custo e Complexidade do ECS/ALB**: O Application Load Balancer cobra uma taxa fixa de ~$16.20/mês apenas para existir ocioso, além de exigir certificado ACM com domínio público registrado em DNS e compilação/envio de imagem Docker para o ECR (inviabilizado pelo bloqueio de socket do daemon local).
4. **Vantagens do EC2 Graviton ARM64 + CloudFront**:
   - Uma única instância (`t4g.nano`) rodando um processo contínuo com [`ProtectedIntakeHTTPServer`](../scripts/run_server.py) assegura que todos os endpoints operem sobre a mesma instância em memória do [`EphemeralCaseStore`](../src/resolveqa/intake/store.py).
   - O CloudFront gerencia a terminação TLS publicamente em `https://dXXXXXXXX.cloudfront.net` sem requerer domínio próprio.
   - O deploy não depende do Git `main` (que é docs-only), mas de um artefato empacotado e auditado com SHA-256 via S3 e IAM mínimo.

---

## 3. Estimativa Realista de Custos na AWS

Diferente de suposições genéricas de gratuidade, os custos reais na região `us-east-1` são compostos por:

1. **Computação EC2 (Graviton ARM64)**:
   - `t4g.nano` (2 vCPU, 0.5 GB RAM): **$0.0042/hora = ~$3.02/mês**.
   - `t4g.micro` (2 vCPU, 1.0 GB RAM): **$0.0084/hora = ~$6.05/mês**.
   *(Nota: Se a conta estiver no período promocional de 750 horas do Free Tier para t4g.micro, o compute é isento, mas expira após o prazo da AWS)*.
2. **Endereço IPv4 Público (Obrigatório pela AWS desde 01/02/2024)**:
   - Cobrança de **$0.005/hora por endereço IPv4 público em uso** = **~$3.60/mês**. Essa taxa se aplica mesmo para instâncias dentro do Free Tier de computação.
3. **Armazenamento EBS (Volume Raiz AL2023)**:
   - 8 GB gp3: ~$0.08/GB-mês = **~$0.64/mês** (isento até 30 GB/mês dentro do AWS Free Tier geral de EBS).
4. **CloudFront CDN**:
   - Os primeiros **1 TB de transferência de saída** e **10.000.000 requisições HTTP/HTTPS por mês** são **permanentemente gratuitos** no AWS Free Tier do CloudFront.
   - O tráfego de saída da EC2 para o CloudFront na mesma região (`us-east-1`) tem **custo zero** ($0.00/GB).
5. **Armazenamento S3 (Artefato de Deploy)**:
   - Tarball de ~50 KB: **< $0.01/mês**.

> [!NOTE]
> **Custo Total Estimado em Produção Demo:**
> - Com `t4g.nano` sem descontos de compute: **~$7.26/mês** ($3.02 compute + $3.60 IPv4 + $0.64 EBS).
> - Se a conta usufruir de Free Tier de compute e EBS: **~$3.60/mês** (referente ao IPv4 público).

---

## 4. Segurança de Origem em Múltiplas Camadas

A arquitetura implementa proteção em duas camadas independentes para impedir acesso indevido ou bypass do CloudFront:

```
Internet / Usuário
        │
        │  HTTPS (TLS gerenciado CloudFront)
        ▼
┌──────────────────────────────────────────────────────────┐
│ CloudFront CDN (dXXXXXX.cloudfront.net)                  │
│  - Redirecionamento: redirect-to-https                   │
│  - Cache Policy: CachingDisabled                         │
│  - Origin Header: X-ResolveQA-Origin-Verify: <secret>    │
└──────────────────────────┬───────────────────────────────┘
                           │
                           │  HTTP :8080 (Somente IPs do CloudFront)
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Camada 1: Security Group EC2 (BackendSecurityGroup)      │
│  - Ingress TCP 8080 restrito a SourcePrefixListId:       │
│    pl-3b927c52 (Managed Prefix List do CloudFront)       │
│  - Bloqueia na borda qualquer IP direto da Internet      │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Camada 2: Handler de Aplicação (ProtectedIntakeServer)   │
│  - scripts/run_server.py intercepta todas as rotas       │
│  - Valida X-ResolveQA-Origin-Verify == <secret>          │
│  - Se ausente ou inválido: retorna HTTP 403 Forbidden    │
└──────────────────────────────────────────────────────────┘
```

1. **Camada de Rede (Security Group)**:
   - O Security Group da EC2 não abre a porta 8080 para `0.0.0.0/0`.
   - Utiliza `SourcePrefixListId: pl-3b927c52` (AWS Managed Prefix List para IPs de origem do CloudFront em `us-east-1`).
2. **Camada de Aplicação (ProtectedIntakeRequestHandler)**:
   - `scripts/run_server.py` implementa `ProtectedIntakeRequestHandler`, que intercepta todas as requisições (`GET`, `POST`).
   - Se o token no cabeçalho `X-ResolveQA-Origin-Verify` não for fornecido ou for inválido, responde com `HTTP 403 Forbidden` (`{"error": "forbidden: missing or invalid origin verification header"}`).
   - O segredo é gerado externamente com entropia criptográfica (`secrets.token_hex(32)`), armazenado em arquivo de parâmetros com permissão `0600` e carregado na instância via `/etc/resolveqa/backend.env` (`chmod 600`) sem exposição em `argv`.

---

## 5. Empacotamento Versionado e Bootstrap com Prontidão

### 5.1 Eliminação da Dependência do Git Main
A branch `main` oficial do repositório (`moouraajv/ResolveQA`) é atualmente docs-only (`e8ef46f`), não possuindo o código implementado nem `scripts/run_server.py`. Fazer `git clone main` em UserData causaria falha silenciosa de inicialização.

Em vez disso:
1. O script [`scripts/package_bundle.py`](../scripts/package_bundle.py) empacota `src/` e `scripts/` de forma determinística (rejeitando working tree dirty por padrão) em `dist/resolveqa-bundle.tar.gz` e calcula seu SHA-256;
2. O artefato é enviado a um bucket S3 privado;
3. A instância EC2 assume o perfil IAM mínimo [`BackendInstanceRole`](../infra/aws/template.yaml), com permissão exclusiva `s3:GetObject` sobre o objeto;
4. O `UserData` baixa o tarball e executa `echo "${ArtifactSha256} /tmp/resolveqa-bundle.tar.gz" | sha256sum -c -` antes da extração.

### 5.2 Validação de Prontidão (CreationPolicy + cfn-signal)
O template CloudFormation define uma `CreationPolicy` com timeout de 5 minutos na instância:
- O `UserData` instala dependências, configura a unidade `systemd` e inicia o backend;
- Realiza um loop local de verificação no endpoint `/health` enviando o cabeçalho secreto;
- Apenas quando o serviço responde `HTTP 200`, executa `cfn-signal -e 0` para sinalizar sucesso à CloudFormation;
- Se houver qualquer falha ou timeout, dispara `cfn-signal -e 1`, provocando o rollback seguro da stack.

---

## 6. Procedimento de Deploy e Verificação (Dry-Run e Execução)

O script [`scripts/deploy_dry_run.sh`](../scripts/deploy_dry_run.sh) atua como gerador de artefatos e comandos em modo dry-run (sem disparar mutações de nuvem), utilizando a cadeia de credenciais padrão da AWS CLI (configurável via `AWS_PROFILE` e `AWS_REGION`):

```bash
# 1. Empacotar artefato (requer árvore limpa), gerar parâmetros (chmod 600) e validar template
./scripts/deploy_dry_run.sh <NOME_DO_BUCKET> resolveqa-demo-backend demo <VPC_ID> <SUBNET_ID>
```

### Comandos de Execução (Quando Autorizado pelo Operador):
```bash
# A. Upload do bundle versionado para o S3
aws s3 cp dist/resolveqa-bundle.tar.gz s3://<NOME_DO_BUCKET>/builds/resolveqa-bundle-<SHA12>.tar.gz \
  --region "${AWS_REGION:-us-east-1}"

# B. Criação da stack no CloudFormation (referenciando arquivo de parâmetros chmod 600)
aws cloudformation create-stack \
  --stack-name resolveqa-demo-backend \
  --template-body file://infra/aws/template.yaml \
  --parameters file://dist/parameters-demo.json \
  --capabilities CAPABILITY_IAM \
  --region "${AWS_REGION:-us-east-1}"

# C. Aguardar prontidão (bloqueia até o cfn-signal emitir HTTP 200 OK)
aws cloudformation wait stack-create-complete \
  --stack-name resolveqa-demo-backend \
  --region "${AWS_REGION:-us-east-1}"

# D. Execução dos smoke tests contra o endpoint público CloudFront HTTPS
# (O CloudFront injeta automaticamente o header X-ResolveQA-Origin-Verify na origem)
CLOUDFRONT_URL=$(aws cloudformation describe-stacks \
  --stack-name resolveqa-demo-backend \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontBaseUrl'].OutputValue" \
  --output text --region "${AWS_REGION:-us-east-1}")

python3 scripts/smoke_test.py --base-url "${CLOUDFRONT_URL}"
```
