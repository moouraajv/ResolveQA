# ResolveQA

ResolveQA — Converge Challenge 2026

Monorepo principal (`moouraajv/ResolveQA`):

- **Backend / agentes:** `src/resolveqa`, `scripts/`, `infra/aws/`
- **Frontend Mola:** `front/`
- **Ambiente público atual:** branch `staging` (até promoção explícita para `main`)

O repositório legado `ThiagoVenturaV/ResolveQA-front` é espelho histórico (deploys AWS desligados). Desenvolvimento e URLs oficiais ficam neste monorepo.

## URLs oficiais (staging)

| Superfície | URL |
|---|---|
| Backend | https://d2a053hki46q2m.cloudfront.net |
| Health | https://d2a053hki46q2m.cloudfront.net/health |
| Intake (form) | https://d2a053hki46q2m.cloudfront.net/form |
| Chat simulado | https://d2a053hki46q2m.cloudfront.net/chat |
| Front Mola | https://dsh3ja1i4695p.cloudfront.net |
| Quadro | https://dsh3ja1i4695p.cloudfront.net/quadro |
| Admin | https://dsh3ja1i4695p.cloudfront.net/admin |

Stacks: `resolveqa-staging-backend` / `resolveqa-staging-frontend` (ver `docs/cicd-aws-staging.md`).

Produção (`main` / stacks demo antigos) fica offline até aprovação explícita para promover `staging` → `main`.
