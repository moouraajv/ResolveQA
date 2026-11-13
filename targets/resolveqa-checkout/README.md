# ResolveQA checkout (dogfood target)

First production client for the cloud agent spine: the banca reports bugs against this
controlled checkout module that ships with ResolveQA.

- Bug: coupon discount not applied in `checkout.calculate_total`
- Playbook: `.resolveqa/playbook.toml` (allowlist `checkout.py` only)
- Default intake: `client_id=resolveqa`, `repo_ref=targets/resolveqa-checkout`

Arbitrary product bugs outside this module terminate honestly (`needs_info` / `blocked`).
