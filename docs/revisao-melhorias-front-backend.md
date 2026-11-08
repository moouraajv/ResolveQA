# Revisão e melhorias — ResolveQA front + backend

**Data:** 2026-11-08  
**Autor da revisão:** Trilha B (Thiago) / agent review  
**Escopo:**
- Front: [ThiagoVenturaV/ResolveQA-front](https://github.com/ThiagoVenturaV/ResolveQA-front) — PRs #2–#6
- Backend: [moouraajv/ResolveQA](https://github.com/moouraajv/ResolveQA) — `main` pós-merge do #51 (Trilha B) + PRs abertos da Trilha A

Este documento consolida a revisão dos PRs do front, o estado do backend e uma lista priorizada de melhorias. Não altera contratos congelados (`src/resolveqa/contracts/`); mudanças de contrato, se necessárias, entram por PR próprio (RFC §8).

---

## 1. Resumo executivo

| Área | Estado | Gargalo principal |
|------|--------|-------------------|
| Front (#2–#5) | Mergeados | Assets pesados, complexidade de animação Mola |
| Front (#6) | Aberto | Admin/CSS monólitos; backend incompleto para “produção” |
| Backend Trilha B | Na `main` (#44 + #51) | API ainda demo-local; sem listagem/SSE/auth |
| Backend Trilha A | Parcial | `triage` / `reproduction` / `fix` / `verification` ainda stubs na `main`; PRs #49–#54 em aberto |
| Integração | Frágil | Front espera snapshot/SSE/playbooks; backend expõe intake + timeline/reply/delivery por caso |

**Não há ~100 issues** no backend: ~26 issues no total; numeração alta é compartilhada com PRs.

---

## 2. Revisão dos PRs do front

### 2.1 PR #2 — Mola arco-íris com transporte fluido (MERGED)

**Entrega:** Atlas arco-íris, física do herói, transporte Kanban com entrega antes da mudança de coluna (`components/mola/*`, artwork, docs).

**Pontos fortes**
- Experiência visual coerente; `prefers-reduced-motion` e `aria-label` no palco.
- Transporte desacoplado (`transport.ts` / `transport-layer.tsx`).

**Riscos / dívida**
- Volume grande de binários em `artwork/` e `public/mascot/` (clone/CI pesados; sem Git LFS).
- Poucos testes automatizados de transporte neste PR.

### 2.2 PR #3 — Hospedar frontend Mola na AWS (MERGED)

**Entrega:** CloudFormation (S3 privado + CloudFront + OAC), rewrite de rotas estáticas, scripts de deploy.

**Pontos fortes**
- Export estático alinhado a Next `output: 'export'`; bucket privado + HTTPS.

**Riscos / dívida**
- Sem BFF: CORS/auth ficam no gateway.
- Deploy script em bash (atrito no Windows).
- Rewrite limitado a rotas conhecidas (`/admin`, `/quadro`).

### 2.3 PR #4 — Seeking and return transport (MERGED)

**Entrega:** Fases seek → celebrate → return; waypoints; script `scripts/test-mola-transport.mjs`.

**Pontos fortes**
- Máquina de fases explícita; teste Node sem bundler.

**Riscos / dívida**
- Acoplamento forte layout DOM ↔ geometria do transporte; resize durante animação é frágil.

### 2.4 PR #5 — Mola slinky animation (MERGED)

**Entrega:** Modo Slinky, novos atlases WebP, reescrita de `hero-stage.tsx`.

**Pontos fortes**
- Camada visual distinta sem quebrar o contrato de transporte.

**Riscos / dívida**
- `hero-stage.tsx` muito grande; dois sistemas de sprite aumentam superfície de bug; custo de CPU em mobile.

### 2.5 PR #6 — Landing, Admin preto e Kanban por eventos (OPEN)

**Entrega:** Landing, Admin operacional, workspace (`components/workspace/*`), domínio Zod (`lib/resolveqa/domain.ts`), cliente HTTP, demo/produção, polling + SSE opcional, testes browser/stream, docs de integração.

**Pontos fortes**
- Domínio tipado com dedup de eventos e anti-regressão por `seq`/`updated_at`.
- Documentação honesta sobre endpoints ainda inexistentes no backend.
- Pirâmide mínima de testes (`npm test`, `test:browser`, `test:stream`).

**Riscos / dívida**
- `app/admin/page.tsx` (~900+ linhas) e `app/globals.css` (~3700+ linhas) monólitos.
- “Produção” limitada a IDs conhecidos sem snapshot/listagem no backend.
- Sem auth no front estático — `/admin` não pode ser a única barreira.
- Front ainda não consome `GET /api/cases/:id/timeline` (já existe no backend pós-#51).

---

## 3. Estado do backend (ResolveQA)

### 3.1 O que já está sólido na `main`

- **Contratos** (`src/resolveqa/contracts/`): estados, eventos, evidências, estágios — base congelada.
- **Sandbox + LLM** (`sandbox/`, `llm/`): isolamento e mock determinístico; varredura de padrões de segredo.
- **Orquestrador + EventStore** (`orchestrator/`, `store/events.py`): máquina de estados e `events.jsonl` append-only.
- **Trilha B** (PRs #44/#51):
  - Intake + canal simulado + `web/server.py`
  - Timeline, Reply, Delivery (pacote “PR não publicado”)
  - Security scan, playbook mínimo, docs/KB no pacote
  - Testes em `tests/edge`, `tests/security`, `tests/e2e`

### 3.2 Lacunas críticas

| Lacuna | Onde | Impacto |
|--------|------|---------|
| Estágios A ainda stub na `main` | `triage/`, `reproduction/`, `fix/`, `verification/` só `__init__.py` | Sem pipeline real relato→patch→verdict; e2e B usa fixtures |
| PRs A em aberto | #49 triage, #50 reproduction, #52 fix, #53/#54 verification, #46 Featherless, #47 evidence store | Precisam aterrar na `main` com ordem clara |
| Sandbox Windows | `sandbox/executor.py` usa `os.killpg` | Testes de sandbox falham no Windows nativo |
| Persistência cindida | Intake efêmero em memória vs `runs/<case_id>/` no disco | Front/demo não têm fonte única de verdade |
| API insuficiente para o Admin front | Sem `GET /api/cases` (lista), SSE, spans, CRUD playbooks | PR #6 do front documenta extensões que o backend ainda não tem |
| Playbook paralelo | `src/resolveqa/playbook/` (B) vs issue #22 (A) | Risco de dois schemas até congelar contratos |
| Auth / multi-tenant | Ausente no servidor stdlib | Demo OK; produção insegura se exposta |

### 3.3 Superfície HTTP atual (`web/server.py`)

Já existe:
- `POST/GET /api/cases`, form, chat simulado
- `GET /api/cases/<id>/timeline`, HTML timeline
- `POST /api/cases/<id>/reply`, `POST .../delivery`

Falta para alinhar ao front #6:
- Listagem / snapshot global de casos
- Stream SSE (ou WebSocket) de eventos
- Spans/traces de execução
- API de playbooks (CRUD) alinhada ao schema A (#22)
- Autenticação e isolamento por `client_id`

---

## 4. Melhorias priorizadas

### P0 — Bloqueiam demo integrada / produção mínima

1. **Aterrar Trilha A na `main`:** merge ordenado de #49 → #50 → #52 → #53/#54 (triage → repro → fix → verification), depois wiring no orquestrador com estágios reais.
2. **Corrigir sandbox no Windows:** abstrair terminação de processo (`os.killpg` → fallback `taskkill` / `terminate` no Win32) em `src/resolveqa/sandbox/executor.py`.
3. **Unificar persistência:** Intake deve gravar `CaseCreated` em `EventStore` e reconstruir estado a partir de `runs/`, não só memória efêmera.
4. **Contrato mínimo front↔backend:** implementar `GET /api/cases` (lista) + documentar/implementar stream de eventos; atualizar `docs` do front e do backend.
5. **Gateway + auth** antes de expor Admin CloudFront + API (CORS, token, isolamento por cliente).

### P1 — Qualidade e alinhamento

6. **Congelar playbook (#22)** em contratos e fazer Delivery/Reply B consumirem o schema oficial (substituir subset ad hoc).
7. **Evidence store (#47)** + varredura de segredos antes de persistir artefatos (alinhar RNF-01 com store, não só scan no delivery).
8. **Front #6:** quebrar `app/admin/page.tsx` e modularizar `app/globals.css`; consumir timeline real do backend.
9. **CI:** backend `pytest` em Linux + job Windows smoke; front `npm test` / `test:stream` / `tsc` / `build` no PR #6.
10. **Fechar issues B** (#13–#19, #24–#27) já cobertas pelo #51 após validação de aceite.
11. **LLM real (#46 Featherless)** atrás do adapter, com limites e redaction.

### P2 — Roadmap / higiene

12. Git LFS ou artefatos externos para artwork do front.
13. Remover deps mortas do starter no `package.json` do front.
14. Roadmap A: isolamento por cliente (#20), playbook por tipo (#28), memória (#29) — só após MVP verde.
15. Storybook / página de dev só para Mola.
16. Virtualização de listas no Admin quando snapshot crescer.
17. CSP e cache headers no CloudFront.

---

## 5. Ordem sugerida de trabalho

```text
1. Sandbox Windows + CI verde
2. Merge A: triage → reproduction → fix → verification
3. Wiring orquestrador + Intake→EventStore (fonte única)
4. GET /api/cases (+ opcional SSE mínimo)
5. Auth/gateway na frente do Admin/API
6. Congelar playbook (#22) e alinhar B
7. Refator Admin/CSS no front #6 + consumir timeline
8. Fechar issues B e atualizar docs de integração
9. Roadmap P2
```

---

## 6. Checklist de aceite desta revisão

- [ ] Time A confirma ordem de merge dos PRs #49–#54
- [ ] Time B valida lista/API proposta contra o cliente do front (`lib/resolveqa/client.ts`)
- [ ] Issue #22 (playbook) priorizada antes de expandir Delivery/Reply
- [ ] Front #6 só marca “produção” completa após auth + listagem/stream
- [ ] Issues B (#13–#27) fechadas com referência ao #51 quando o aceite for revisado por humano

---

## 7. Referências

- Backend RFC: `docs/rfc/0001-arquitetura-e-contratos.md`
- Backend PRD: `docs/PRD.md`
- Front PR #6: https://github.com/ThiagoVenturaV/ResolveQA-front/pull/6
- Front audit (no PR #6): `docs/backend-integration-audit.md`, `docs/production-connection.md`
- Backend Trilha B merge: https://github.com/moouraajv/ResolveQA/pull/51
