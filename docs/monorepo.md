# Monorepo ResolveQA

Back + front no mesmo repositório `moouraajv/ResolveQA`.

```
/
  src/resolveqa/     # backend Python
  front/             # Next.js Mola (ex-ResolveQA-front)
  infra/aws/         # CloudFormation
  .github/workflows/ # deploy staging back + front
```

## Desenvolvimento
```bash
# API + worker local
export PYTHONPATH=src RESOLVEQA_CASE_STORE=file RESOLVEQA_QUEUE=file
python scripts/run_server.py --port 8080
python -m resolveqa.worker --store file --queue file

# Front
cd front && npm ci && npm run dev
```

## Staging
Push/merge na branch `staging` dispara:
- `deploy-aws-staging.yml` (backend)
- `deploy-front-staging.yml` (frontend em `front/`)
