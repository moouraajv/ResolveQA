# Checklist de entrega — Edital §8 (congelamento)

Tudo abaixo deve estar **anexado / linkado no GitHub** na hora do congelamento.

## Obrigatórios

| # | Entregável | Artefato | Status |
|---|---|---|---|
| 1 | Protótipo funcional (ao vivo ou gravado) | [demo-ao-vivo.md](demo-ao-vivo.md) + URLs staging no [README](../../README.md) | Pronto (ao vivo). Gravação: opcional plano B |
| 2 | BMC atualizado | [bmc.md](bmc.md) | Pronto |
| 3 | Pitch (3 min regional / 5 min final) | [pitch/](../../pitch/) + [pitch-roteiro-3min.md](pitch-roteiro-3min.md) | Pronto (deck + roteiro 3 min) |
| 4 | Fluxo do agente (inputs, lógica, outputs) | [fluxo-agente.md](fluxo-agente.md) | Pronto |

## Apoio à banca (recomendado)

| Item | Artefato |
|---|---|
| Equipe | [equipe.md](equipe.md) — completar nomes da inscrição |
| Critérios §9.1 / §9.4 | Seções no README + fluxo-agente |
| Smoke pré-congelamento | `python3 scripts/smoke_test.py --base-url https://dec5ise4h3d48.cloudfront.net` |

## 30 minutos antes do congelamento

- [ ] `GET /health` → `environment=staging`, `queue=true`
- [ ] Form + Quadro abrem (HTTPS)
- [ ] Caso cupom cria `202` e aparece no Quadro
- [ ] Links do README batem com as URLs reais
- [ ] Deck PDF abre; roteiro impresso / segunda tela
- [ ] Nomes em `equipe.md` iguais à ficha AKCIT
- [ ] (Opcional) MP4 da demo em `docs/akcit/assets/` ou link externo no README

## Final (§8.6) — diferença

Além dos quatro itens: BMC e fluxo **atualizados**, pitch de **5 min** com mercado/investimento, evidência de evolução desde o regional ([`evolucao-regional.md`](evolucao-regional.md) — rascunho).
