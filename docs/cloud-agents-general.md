# feat/cloud-agents-general

General agent mode on top of the cloud spine.

## Mode switch

```bash
export RESOLVEQA_AGENT_MODE=general   # default on this branch
# export RESOLVEQA_AGENT_MODE=dogfood # deterministic FixStage only
```

- Triage + Reproduction: LLM (mock or Featherless)
- Fix: `LLMFixStage` + playbook gate (`PlaybookGatedFix`)
- Verification: deterministic (unchanged)

Playbook loaded from `<repo_ref>/.resolveqa/playbook.toml`.
Suspects/patches outside `paths.allowed` → `needs_info` / `PatchRejected`.

## Evals

```bash
PYTHONPATH=src python -m pytest tests/evals/test_general_agent.py -q
```

Cases: coupon → verified; vague → needs_info; protected path rejected.
