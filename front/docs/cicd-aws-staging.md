# CI/CD AWS — staging (frontend)

`main` = produção. `staging` = pré-produção com deploy automático.

## Secrets / variables (GitHub environment `staging`)
- Secrets: `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_STACK_NAME_STAGING`
- Variables: `RESOLVEQA_API_URL_STAGING` (CloudFront do backend staging)
- Optional: `RESOLVEQA_CASE_IDS_STAGING`

Build bakes:
- `RESOLVEQA_MODE=production`
- `RESOLVEQA_SNAPSHOT_PATH=/api/snapshot`
- `RESOLVEQA_EVENTS_PATH=/api/events`

## Fluxo
1. PR → `staging`
2. Merge → workflow `deploy-aws-staging.yml`
3. Abrir SiteUrl do stack staging e apontar relatos para o backend staging
