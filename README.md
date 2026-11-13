# ResolveQA

ResolveQA — Converge Challenge 2026

Monorepo principal (`moouraajv/ResolveQA`):

- **Backend / agentes:** `src/resolveqa`, `scripts/`, `infra/aws/`
- **Frontend Mola:** `front/`
- **Staging:** branch `staging` com deploy AWS automático (API+worker e front)

O repositório legado `ThiagoVenturaV/ResolveQA-front` fica como espelho histórico; desenvolvimento novo no monorepo.

## Demo pública (AWS CloudFront, HTTPS)

| Superfície | URL |
|---|---|
| Backend (base) | https://d2f79ulrlhg51j.cloudfront.net |
| Health | https://d2f79ulrlhg51j.cloudfront.net/health |
| Intake (form) | https://d2f79ulrlhg51j.cloudfront.net/form |
| Chat simulado | https://d2f79ulrlhg51j.cloudfront.net/chat |
| Front Mola | https://d10ry6ff7l79jo.cloudfront.net |
| Quadro | https://d10ry6ff7l79jo.cloudfront.net/quadro |
| Admin | https://d10ry6ff7l79jo.cloudfront.net/admin |

## Staging (`staging` branch)

| Superfície | URL |
|---|---|
| Backend | https://d2a053hki46q2m.cloudfront.net |
| Health | https://d2a053hki46q2m.cloudfront.net/health |
| Front Mola | https://dsh3ja1i4695p.cloudfront.net |
| Quadro | https://dsh3ja1i4695p.cloudfront.net/quadro |
| Admin | https://dsh3ja1i4695p.cloudfront.net/admin |

Stacks: `resolveqa-staging-backend` / `resolveqa-staging-frontend` (ver `docs/cicd-aws-staging.md`).
