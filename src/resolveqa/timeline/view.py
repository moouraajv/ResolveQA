"""Support-facing timeline projections (RF-10, RNF-07)."""

from __future__ import annotations

import html
from typing import Any, Mapping, Optional

from .reader import TimelineEntry


def timeline_to_dict(case_id: str, entries: list[TimelineEntry]) -> dict[str, object]:
    return {
        "case_id": case_id,
        "entries": [entry.to_dict() for entry in entries],
        "note": "Sequência real lida de events.jsonl; nenhum progresso foi simulado.",
    }


def build_timeline_html(
    case_id: str,
    entries: list[TimelineEntry],
    *,
    usage: Optional[Mapping[str, Any]] = None,
) -> str:
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

    usage_block = ""
    if usage is not None:
        calls = html.escape(str(usage.get("llm_calls", 0)), quote=True)
        tin = html.escape(str(usage.get("tokens_in", 0)), quote=True)
        tout = html.escape(str(usage.get("tokens_out", 0)), quote=True)
        usd = usage.get("estimated_usd", 0.0)
        try:
            usd_txt = f"{float(usd):.6f}"
        except (TypeError, ValueError):
            usd_txt = "0.000000"
        label = html.escape(str(usage.get("label", "estimate")), quote=True)
        currency = html.escape(str(usage.get("currency", "USD")), quote=True)
        usage_block = (
            '<section class="usage">'
            "<h2>Uso de LLM (estimate)</h2>"
            f"<p>Chamadas: <strong>{calls}</strong> · "
            f"tokens in/out: <strong>{tin}</strong>/<strong>{tout}</strong> · "
            f"custo estimado: <strong>{currency} {html.escape(usd_txt, quote=True)}</strong> "
            f"(<em>{label}</em>, não é fatura do provedor)</p>"
            "</section>"
        )

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
    .usage {{ margin: 1.25rem 0; padding: 0.85rem 1rem; background: #f4f7fb; border-radius: 6px; }}
  </style>
</head>
<body>
  <p class="banner">Linha do tempo real do caso <code>{safe_case}</code> — sem progresso inventado.</p>
  {usage_block}
  {body}
</body>
</html>
"""
