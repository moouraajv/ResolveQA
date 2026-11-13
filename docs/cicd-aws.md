# CI/CD AWS (backend)

## Política
- **`staging`:** pré-produção. Ver [`cicd-aws-staging.md`](cicd-aws-staging.md).
- **`main`:** produção. Merge manual (humano) → deploy automático.

## Secrets / variables (produção / `main`)
- Secrets: `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_STACK_NAME`, `AWS_ARTIFACT_BUCKET`
- Variables: `AWS_VPC_ID`, `AWS_SUBNET_ID`, `AWS_INSTANCE_TYPE`

## Fluxo produção
1. Humano faz merge na `main` (idealmente a partir de `staging` já validado)
2. Job `test` roda pytest
3. Job `deploy` atualiza o stack existente e executa `scripts/smoke_test.py`

O script `scripts/deploy_aws.sh` **não cria** stack nova sem bootstrap prévio (precisa `OriginSecretHeader` já existente).
