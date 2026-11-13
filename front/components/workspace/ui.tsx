"use client";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Check,
  Circle,
  Code2,
  Columns3,
  FileText,
  GitBranch,
  Infinity as Loop,
  Layers,
  Play,
  Search,
  Terminal,
  X,
} from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import {
  agentOf,
  elapsed,
  labels,
  laneOf,
  duration,
  type Run,
  type RunEvent,
  type Snapshot,
  type Span,
} from "@/lib/resolveqa/domain";
import { makeDemo } from "@/lib/resolveqa/demo";
import { MolaSprite } from "@/components/mola/spring";
import {
  agentLabel,
  sourceLabel,
  activityLabel,
  explainText,
  caseReason,
} from "@/lib/resolveqa/copy";
export function Logo() {
  return (
    <Link className="rq-logo" href="/" aria-label="ResolveQA, início">
      <Loop aria-hidden="true" size={32} />
      <span>ResolveQA</span>
    </Link>
  );
}
export function SiteNav() {
  return (
    <header className="rq-header">
      <Logo />
      <nav aria-label="Navegação principal">
        <Link href="/#produto">Produto</Link>
        <Link href="/#como-funciona">Como funciona</Link>
        <Link href="/#conhecimento">Para sua empresa</Link>
      </nav>
      <Link className="rq-button small" href="/admin">
        Acessar Admin
        <ArrowRight size={14} />
      </Link>
    </header>
  );
}
export function Status({ run }: { run: Run }) {
  return (
    <span className={`status status-${laneOf(run.state)}`}>
      {run.state === "verified" ? <Check size={12} /> : <Circle size={9} />}
      {labels[run.state]}
    </span>
  );
}
export function Empty({
  title,
  children,
  icon = <Layers size={28} />,
}: {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="rq-empty">
      {icon}
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function SearchBox({
  value,
  onChange,
  placeholder = "Buscar por caso, relato ou projeto…",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="search-box">
      <Search size={16} />
      <span className="sr-only">{placeholder}</span>
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}
export function Clock({
  value,
  date = false,
}: {
  value: string;
  date?: boolean;
}) {
  return (
    <time dateTime={value}>
      {new Date(value).toLocaleString(
        "pt-BR",
        date
          ? {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
              timeZone: "America/Fortaleza",
            }
          : {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
              timeZone: "America/Fortaleza",
            },
      )}
    </time>
  );
}
export function LatencyChart({
  runs,
  small = false,
}: {
  runs: Run[];
  small?: boolean;
}) {
  const values = [...runs]
    .sort((a, b) => a.updated_at.localeCompare(b.updated_at))
    .slice(-24)
    .map(duration);
  if (!values.length)
    return (
      <Empty title="Sem amostras de latência">
        As execuções recebidas aparecerão aqui.
      </Empty>
    );
  const max = Math.max(1000, ...values);
  const bottom = small ? 72 : 112;
  const range = small ? 53 : 88;
  const axisY = small ? 99 : 141;
  const pts = values
    .map(
      (v, i) =>
        `${40 + (i / Math.max(1, values.length - 1)) * 500},${bottom - (v / max) * range}`,
    )
    .join(" ");
  return (
    <svg
      viewBox={small ? "0 0 560 108" : "0 0 560 150"}
      className={`latency-chart ${small ? "chart-small" : ""}`}
      role="img"
      aria-label="Duração das execuções, da mais antiga à mais recente"
    >
      <title>Duração registrada por execução</title>
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line
            x1="40"
            x2="540"
            y1={bottom - f * range}
            y2={bottom - f * range}
          />
          <text x="0" y={bottom + 4 - f * range}>
            {elapsed(max * f)}
          </text>
        </g>
      ))}
      <polyline points={pts} />
      {values.map((v, i) => (
        <circle
          key={i}
          cx={40 + (i / Math.max(1, values.length - 1)) * 500}
          cy={bottom - (v / max) * range}
          r="3"
        >
          <title>{elapsed(v)}</title>
        </circle>
      ))}
      <text x="40" y={axisY}>
        Mais antigas
      </text>
      <text x="468" y={axisY}>
        Mais recentes
      </text>
    </svg>
  );
}
export function TraceWaterfall({ spans }: { spans: Span[] }) {
  const total = Math.max(1, ...spans.map((s) => s.start_ms + s.duration_ms));
  return (
    <div className="trace-waterfall">
      {spans.map((s) => (
        <div className="span-row" key={s.id}>
          <span title={explainText(s.name)}>{explainText(s.name)}</span>
          <div className="span-track">
            <div
              className={`span-bar span-${s.status}`}
              style={{
                marginLeft: `${(s.start_ms / total) * 80}%`,
                width: `${Math.max(4, (s.duration_ms / total) * 80)}%`,
              }}
            >
              <span>{elapsed(s.duration_ms)}</span>
            </div>
          </div>
        </div>
      ))}
      <div className="trace-scale">
        <span>0 s</span>
        <span>{elapsed(total)}</span>
      </div>
    </div>
  );
}
export function EventRows({
  events,
  limit = 6,
}: {
  events: RunEvent[];
  limit?: number;
}) {
  return (
    <div className="event-rows">
      {events.slice(0, limit).map((e) => (
        <div className="event-line" key={e.event_id}>
          <Clock value={e.ts} />
          <span className={`event-dot source-${e.source}`} />
          <span>{sourceLabel(e.source)}</span>
          <span>
            {explainText(e.reason || activityLabel(e.type))}
            {e.replay_of &&
              ` · Revisão do histórico de ${e.replay_of.original_ts}`}
          </span>
        </div>
      ))}
    </div>
  );
}
const preview = makeDemo(Date.parse("2026-11-07T18:24:00Z"));
export function BoardPreview({ hero = false }: { hero?: boolean }) {
  return (
    <div
      className={`board-preview ${hero ? "preview-hero" : ""}`}
      aria-label="Prévia ilustrativa do Kanban"
    >
      <div className="preview-title">
        <span>
          <Columns3 size={17} />
          Mola
        </span>
        <span className="sample-label">Exemplo de acompanhamento</span>
      </div>
      <div className="preview-lanes">
        {["intake", "active", "review", "done"].map((lane, i) => (
          <div key={lane} className={`preview-lane preview-${lane}`}>
            <h3>
              <Circle size={12} />
              {["Entrada", "Em execução", "Verificação", "Concluído"][i]}
              <span>
                {preview.cases.filter((c) => laneOf(c.state) === lane).length}
              </span>
            </h3>
            {preview.cases
              .filter((c) => laneOf(c.state) === lane)
              .slice(0, 2)
              .map((c) => (
                <div className="preview-task" key={c.case_id}>
                  <code>{c.case_id}</code>
                  <p>{explainText(c.report_text)}</p>
                  <span>
                    <Code2 size={11} />
                    {agentLabel(agentOf(c.state))}
                    {c.state === "verified" && <Check size={11} />}
                  </span>
                </div>
              ))}
          </div>
        ))}
      </div>
      <div className="preview-mascot">
        <MolaSprite width={84} clip="runRight" frame={2} />
        <span className="mini-load">
          <FileText size={12} />
          RQA-1044
        </span>
      </div>
      {hero && (
        <div className="preview-events">
          <div className="preview-title">
            <span>
              <Terminal size={14} />
              Eventos da execução
            </span>
            <code>RQA-1044</code>
          </div>
          {["triage", "reproduction", "fix", "verification"].map((s, i) => (
            <div className="preview-event" key={s}>
              <code>15:2{i}:04</code>
              <span className={`event-dot source-${s}`} />
              <span>{sourceLabel(s)}</span>
              <span>
                {
                  [
                    "Relato classificado · checkout",
                    "Problema confirmado na verificação",
                    "Correção proposta em um arquivo",
                    "Verificação independente aprovada",
                  ][i]
                }
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
export function AdminPreview() {
  return (
    <div
      className="admin-preview"
      aria-label="Prévia ilustrativa do painel administrativo"
    >
      <div className="mini-sidebar">
        <span className="mini-brand">
          <Loop size={17} />
          ResolveQA
        </span>
        {[
          [Activity, "Visão geral"],
          [Play, "Execuções"],
          [Terminal, "Atividades"],
          [GitBranch, "Tempo por etapa"],
          [BookOpen, "Procedimentos"],
        ].map(([Icon, label]) => {
          const I = Icon as typeof Activity;
          return (
            <span key={String(label)}>
              <I size={12} />
              {String(label)}
            </span>
          );
        })}
      </div>
      <div className="mini-admin-main">
        <div className="preview-title">
          <strong>Acompanhamento</strong>
          <span className="sample-label">Exemplo ilustrativo</span>
        </div>
        <div className="mini-chart">
          <span>Tempo de resolução</span>
          <LatencyChart runs={preview.cases} small />
        </div>
        <div className="mini-run-table">
          {preview.cases.slice(2, 6).map((c) => (
            <div key={c.case_id}>
              <code>{c.case_id}</code>
              <span>{explainText(c.report_text)}</span>
              <Status run={c} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
export function CaseDetail({
  run,
  snapshot,
  onClose,
}: {
  run: Run;
  snapshot: Snapshot;
  onClose: () => void;
}) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      before?.focus();
    };
  }, [onClose]);
  const events = snapshot.events.filter((e) => e.case_id === run.case_id),
    spans = snapshot.spans.filter((s) => s.case_id === run.case_id);
  return (
    <aside
      className="case-drawer"
      aria-label={`Detalhes do caso ${run.case_id}`}
    >
      <header>
        <code>{run.case_id}</code>
        <button
          ref={close}
          className="rq-icon-button"
          aria-label="Fechar detalhes"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </header>
      <Status run={run} />
      <h2>{explainText(run.report_text)}</h2>
      <dl className="case-properties">
        <div>
          <dt>Empresa</dt>
          <dd>{run.client_id}</dd>
        </div>
        <div>
          <dt>Projeto</dt>
          <dd>{run.repo_ref}</dd>
        </div>
        <div>
          <dt>Etapa</dt>
          <dd>{agentLabel(agentOf(run.state))}</dd>
        </div>
        <div>
          <dt>Atualização</dt>
          <dd>
            <Clock value={run.updated_at} date />
          </dd>
        </div>
        <div>
          <dt>Tentativas de correção</dt>
          <dd>{run.attempts.fix}</dd>
        </div>
        <div>
          <dt>Consultas ao assistente</dt>
          <dd>{run.attempts.llm_calls}</dd>
        </div>
      </dl>
      {run.terminal_reason && (
        <p className="rq-alert">{caseReason(run.terminal_reason)}</p>
      )}
      <h3>Evidências</h3>
      {run.evidence_ids.length ? (
        <ul className="evidence-list">
          {run.evidence_ids.map((id, i) => (
            <li key={id} data-evidence-id={id}>
              <FileText size={14} />
              <span>Comprovante {i + 1} registrado</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Nenhuma evidência recebida.</p>
      )}
      <h3>Histórico da correção</h3>
      <p className="revision-line">
        <GitBranch size={14} />
        <span>
          {run.base_revision
            ? "Versão original registrada"
            : "Aguardando análise inicial"}
        </span>
        <ArrowRight size={13} />
        <span>
          {run.fix_revision ? "Correção registrada" : "Aguardando correção"}
        </span>
      </p>
      <h3>Tempo gasto em cada etapa</h3>
      {spans.length ? (
        <TraceWaterfall spans={spans} />
      ) : (
        <p className="muted">
          O tempo de cada etapa aparecerá quando o acompanhamento estiver
          disponível.
        </p>
      )}
      <h3>Linha do tempo</h3>
      {events.length ? (
        <EventRows events={events} limit={100} />
      ) : (
        <p className="muted">Nenhum evento recebido.</p>
      )}
    </aside>
  );
}
