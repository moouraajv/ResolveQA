# CI/CD AWS — staging

`main` = produção. `staging` = ambiente de pré-produção com deploy automático.

## Política
- **Merge para `staging`:** via PR (humano aprova).
- **Deploy staging:** automático em todo push na `staging` (workflow `deploy-aws-staging.yml`).
- **Merge para `main`:** só depois de validar no staging.

## Secrets / variables (GitHub environment `staging`)
- Secrets: `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_ARTIFACT_BUCKET`, `AWS_STACK_NAME_STAGING`
- Variables: `AWS_VPC_ID`, `AWS_SUBNET_ID`, `AWS_INSTANCE_TYPE`

Use um stack **separado** do demo/prod (ex.: `resolveqa-staging-backend`).

## Bootstrap
Staging pode **criar** o stack automaticamente (`ALLOW_STACK_CREATE=1`, `EnvironmentName=staging`).
Default do nome: `resolveqa-staging-backend` (override com secret `AWS_STACK_NAME_STAGING`).

Runtime no staging (UserData):
- API + worker no mesmo host
- `RESOLVEQA_CASE_STORE=file`, `RESOLVEQA_QUEUE=file`
- `RESOLVEQA_ALLOW_OPERATOR_ADVANCE=0`
- `RESOLVEQA_AGENT_MODE=general`

Overlay SQS/Dynamo/EFS worker dedicado: `infra/aws/cloud-agents-overlay.yaml` (fase seguinte).

## Fluxo diário
1. PR → `staging` (features)
2. Merge → Actions faz test + deploy + smoke
3. Abrir o CloudFront staging no Quadro (front staging apontando para essa API)
4. Quando estável: PR `staging` → `main` (produção)
