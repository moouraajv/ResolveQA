# CI/CD AWS (backend)

## Política
- **Merge:** manual (humano).
- **Deploy:** automático em todo push na `main` (e `workflow_dispatch`), via GitHub Actions + OIDC.

## Secrets / variables
- Secrets: `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_STACK_NAME`, `AWS_ARTIFACT_BUCKET`
- Variables: `AWS_VPC_ID`, `AWS_SUBNET_ID`, `AWS_INSTANCE_TYPE`

## Fluxo
1. Humano faz merge na `main`
2. Job `test` roda pytest
3. Job `deploy` atualiza o stack existente e executa `scripts/smoke_test.py`

O script `scripts/deploy_aws.sh` **não cria** stack nova sem bootstrap prévio (precisa `OriginSecretHeader` já existente).
