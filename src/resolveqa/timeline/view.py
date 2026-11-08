"""Support-facing timeline projections (RF-10, RNF-07)."""

from __future__ import annotations

import html

from .reader import TimelineEntry


def timeline_to_dict(case_id: str, entries: list[TimelineEntry]) -> dict[str, object]:
    return {
        "case_id": case_id,
        "entries": [entry.to_dict() for entry in entries],
        "note": "Sequência real lida de events.jsonl; nenhum progresso foi simulado.",
    }


def build_timeline_html(case_id: str, entries: list[TimelineEntry]) -> str:
    """Simple support HTML: each transition shows timestamp and source; replays show original_ts."""
    safe_case = html.escape(case_id, quote=True)
    if not entries:
        body = (
            '<p class="empty">Nenhum evento registrado ainda. '
            "A linha do tempo só mostra o que está em events.jsonl.</p>"
        )
    else:
        rows: list[str] = []
        for entry in entries:
            label = html.escape(str(entry.to_dict()["label"]), quote=False)
            reason = ""
            if entry.reason:
                reason = (
                    f'<div class="reason">motivo: '
                    f"{html.escape(entry.reason, quote=False)}</div>"
                )
            evidence = ""
            if entry.evidence_refs:
                refs = ", ".join(html.escape(ref, quote=True) for ref in entry.evidence_refs)
                evidence = f'<div class="evidence">evidências: {refs}</div>'
            replay_badge = (
                '<span class="badge">replay</span>' if entry.is_replay else ""
            )
            rows.append(
                "<li>"
                f'<div class="meta">{label} {replay_badge}</div>'
                f"{reason}{evidence}"
                "</li>"
            )
        body = "<ol class=\"timeline\">\n" + "\n".join(rows) + "\n</ol>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Linha do tempo · {safe_case}</title>
  <style>
    body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 2rem; color: #14213d; }}
    .banner {{ background: #fff3cd; padding: 0.75rem 1rem; border-radius: 6px; }}
    .timeline {{ padding-left: 1.25rem; }}
    .timeline li {{ margin: 0.85rem 0; }}
    .meta {{ font-weight: 600; }}
    .reason, .evidence {{ color: #5c6b7a; font-size: 0.95rem; }}
    .badge {{ background: #0b6e4f; color: #fff; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem; }}
    .empty {{ color: #5c6b7a; }}
  </style>
</head>
<body>
  <p class="banner">Linha do tempo real do caso <code>{safe_case}</code> — sem progresso inventado.</p>
  {body}
</body>
</html>
"""
