"""Simulated messaging-channel UI and Intake bridge (RFC-0001 §2.1, RF-02, RNF-07).

Technical routes (wired by resolveqa.web.server):
  GET  /chat                -> HTML chat UI (permanent "Canal simulado" label)
  POST /chat/messages       -> form-urlencoded create via Intake (channel=simulated_chat)
  POST /api/chat/messages   -> JSON create via the same Intake path

Every successful send calls Intake.create(ReportInput(..., channel=SIMULATED_CHAT)).
The UI shows only honest send/receipt/case_id — no invented pipeline progress.
"""

from __future__ import annotations

import html
from typing import Any

from resolveqa.contracts import ChannelType, ReportInput, RunState
from resolveqa.intake import Intake

# Permanent visible demo label (RF-02 / RNF-07). Do not translate away in UI chrome.
SIMULATED_CHANNEL_LABEL = "Canal simulado"


def submit_simulated_chat_report(
    intake: Intake,
    *,
    client_id: Any,
    repo_ref: Any,
    report_text: Any,
) -> RunState:
    """Create a case through the shared Intake using channel=simulated_chat.

    Passes values through to ReportInput without coercion so contracts enforce types.
    """
    report = ReportInput(
        client_id=client_id,
        repo_ref=repo_ref,
        channel=ChannelType.SIMULATED_CHAT,
        report_text=report_text,
    )
    return intake.create(report)


def build_chat_html(
    *,
    notice: str | None = None,
    outbound_text: str | None = None,
    case: RunState | None = None,
    preset_client_id: str = "",
    preset_repo_ref: str = "",
) -> str:
    """Responsive chat shell with permanent simulated-channel label and keyboard-usable composer.

    User/report content is HTML-escaped. Receipts state only what Intake actually returned.
    """
    notice_block = ""
    if notice:
        notice_block = (
            f'<div class="notice" role="alert">{html.escape(notice, quote=True)}</div>'
        )

    bubbles: list[str] = []
    if outbound_text is not None:
        bubbles.append(
            '<div class="bubble outbound" data-role="user-report">'
            '<div class="meta">Você · relato (dado)</div>'
            f'<div class="body">{html.escape(outbound_text, quote=False)}</div>'
            "</div>"
        )
    if case is not None:
        receipt = (
            f"Recibo honesto: caso criado. case_id={case.case_id}; "
            f"state={case.state.value}; channel={case.channel.value}. "
            "Nenhum progresso adicional foi inventado nesta demo."
        )
        bubbles.append(
            '<div class="bubble inbound" data-role="system-receipt">'
            f'<div class="meta">{html.escape(SIMULATED_CHANNEL_LABEL, quote=True)} · sistema</div>'
            f'<div class="body">{html.escape(receipt, quote=False)}</div>'
            f'<div class="case-id">case_id: {html.escape(case.case_id, quote=True)}</div>'
            "</div>"
        )

    thread = "\n".join(bubbles) if bubbles else (
        '<p class="empty">Nenhuma mensagem ainda. Envie um relato — campos são dados, '
        "não instruções.</p>"
    )

    client_val = html.escape(preset_client_id, quote=True)
    repo_val = html.escape(preset_repo_ref, quote=True)
    label = html.escape(SIMULATED_CHANNEL_LABEL, quote=True)
    from resolveqa.env_label import environment_banner, environment_name

    env = environment_name()
    env_banner = html.escape(environment_banner(), quote=True)
    env_sub = html.escape(
        f"{env} · não é WhatsApp real · progresso só via worker/agentes",
        quote=True,
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{label} — ResolveQA</title>
  <style>
    :root {{
      --bg: #e8eef5;
      --panel: #ffffff;
      --accent: #0b6e4f;
      --outbound: #d1f0e4;
      --inbound: #ffffff;
      --ink: #14213d;
      --muted: #5c6b7a;
      --danger: #8a1f1f;
      --banner: #fff3cd;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--ink);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    .channel-banner {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: var(--banner);
      border-bottom: 2px solid #e0a800;
      padding: 0.65rem 1rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      text-align: center;
    }}
    .channel-banner .sub {{
      display: block;
      font-weight: 500;
      font-size: 0.85rem;
      color: var(--muted);
      margin-top: 0.15rem;
    }}
    .ephemeral {{
      background: #f4f4f4;
      padding: 0.4rem 1rem;
      font-size: 0.85rem;
      color: var(--muted);
      text-align: center;
    }}
    main {{
      flex: 1;
      display: flex;
      flex-direction: column;
      width: min(100%, 40rem);
      margin: 0 auto;
      background: var(--panel);
      box-shadow: 0 0 0 1px rgba(0,0,0,0.06);
      min-height: 0;
    }}
    .thread {{
      flex: 1;
      overflow-y: auto;
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      min-height: 12rem;
    }}
    .bubble {{
      max-width: 92%;
      padding: 0.65rem 0.85rem;
      border-radius: 0.85rem;
      line-height: 1.35;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .bubble.outbound {{
      align-self: flex-end;
      background: var(--outbound);
      border-bottom-right-radius: 0.2rem;
    }}
    .bubble.inbound {{
      align-self: flex-start;
      background: var(--inbound);
      border: 1px solid #dde3ea;
      border-bottom-left-radius: 0.2rem;
    }}
    .meta {{ font-size: 0.75rem; color: var(--muted); margin-bottom: 0.25rem; }}
    .case-id {{ margin-top: 0.4rem; font-size: 0.8rem; font-family: ui-monospace, monospace; }}
    .empty {{ color: var(--muted); text-align: center; margin: 2rem 0; }}
    .notice {{
      margin: 0.5rem 1rem 0;
      padding: 0.5rem 0.75rem;
      background: #fde8e8;
      color: var(--danger);
      border-radius: 0.4rem;
    }}
    .composer {{
      border-top: 1px solid #dde3ea;
      padding: 0.75rem 1rem 1rem;
      background: #fafbfc;
      display: grid;
      gap: 0.45rem;
    }}
    .composer label {{
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--muted);
    }}
    .composer input,
    .composer textarea {{
      width: 100%;
      font: inherit;
      padding: 0.55rem 0.65rem;
      border: 1px solid #c5d0db;
      border-radius: 0.45rem;
    }}
    .composer textarea {{ min-height: 4.5rem; resize: vertical; }}
    .composer button {{
      margin-top: 0.25rem;
      justify-self: end;
      background: var(--accent);
      color: #fff;
      border: 0;
      border-radius: 999px;
      padding: 0.55rem 1.25rem;
      font-weight: 600;
      cursor: pointer;
    }}
    .composer button:focus-visible,
    .composer input:focus-visible,
    .composer textarea:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }}
    @media (max-width: 480px) {{
      .bubble {{ max-width: 100%; }}
      .composer button {{ width: 100%; justify-self: stretch; }}
    }}
  </style>
</head>
<body>
  <div class="channel-banner" role="status" data-channel-label="simulated">
    {label}
    <span class="sub">{env_sub}</span>
  </div>
  <div class="ephemeral">{env_banner}</div>
  {notice_block}
  <main>
    <div class="thread" aria-live="polite">{thread}</div>
    <form class="composer" method="post" action="/chat/messages" accept-charset="utf-8">
      <label for="client_id">client_id (obrigatório, dado)</label>
      <input id="client_id" name="client_id" type="text" required autocomplete="username" value="{client_val}"/>
      <label for="repo_ref">repo_ref (dado)</label>
      <input id="repo_ref" name="repo_ref" type="text" required value="{repo_val}"/>
      <label for="report_text">Mensagem / relato (dado)</label>
      <textarea id="report_text" name="report_text" required placeholder="Descreva o problema…"></textarea>
      <button type="submit">Enviar</button>
    </form>
  </main>
</body>
</html>
"""
