"use client";
import { agentLabel, explainText } from "@/lib/resolveqa/copy";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Bot,
  Check,
  Circle,
  Columns3,
  FileText,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  RotateCcw,
  SkipForward,
} from "lucide-react";
import { WorkspaceShell } from "@/components/workspace/shell";
import {
  CaseDetail,
  Clock,
  Empty,
  SearchBox,
  Status,
} from "@/components/workspace/ui";
import { NewCaseForm } from "@/components/workspace/forms";
import { useRuntime } from "@/components/workspace/runtime";
import {
  agentOf,
  labels,
  laneOf,
  lanes,
  type CaseState,
} from "@/lib/resolveqa/domain";
import {
  MolaSprite,
  TransportLayer,
  runTransport,
  prefersReducedMotion,
  type TransportHandle,
} from "@/components/mola";

export default function BoardPage() {
  const r = useRuntime();
  const [query, setQuery] = useState("");
  const [agent, setAgent] = useState("all");
  const [company, setCompany] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [hidden, setHidden] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [skin, setSkin] = useState(0);
  const [layout, setLayout] = useState("board");
  const transport = useRef<TransportHandle>(null);
  const dock = useRef<HTMLDivElement>(null);
  const closeDetails = useCallback(() => setSelected(null), []);
  const firstJob = r.jobs[0];
  const completeJob = r.completeJob;
  useEffect(() => {
    if (!firstJob) return;
    const job = firstJob;
    if (laneOf(job.before.state) === laneOf(job.after.state)) {
      queueMicrotask(() => completeJob(job.key));
      return;
    }
    const selector = `[data-run-id="${CSS.escape(job.before.case_id)}"]`;
    const source = document.querySelector<HTMLElement>(selector);
    const target = document.querySelector<HTMLElement>(
      `[data-lane="${laneOf(job.after.state)}"] .lane-drop`,
    );
    if (!source || !target || prefersReducedMotion()) {
      queueMicrotask(() => {
        setAnnouncement(`${job.after.case_id}: ${labels[job.after.state]}`);
        completeJob(job.key);
      });
      return;
    }
    const srcRect = source.getBoundingClientRect(),
      destRect = target.getBoundingClientRect();
    if (
      srcRect.right < 0 ||
      srcRect.left > innerWidth ||
      destRect.right < 0 ||
      destRect.left > innerWidth
    ) {
      queueMicrotask(() => {
        setAnnouncement(
          `Mola entregou ${job.after.case_id} em ${labels[job.after.state]}.`,
        );
        completeJob(job.key);
      });
      return;
    }
    const layer = transport.current;
    layer?.show(
      { id: job.before.case_id, title: job.before.report_text },
      skin,
    );
    let phase = "";
    const stop = runTransport({
      getHome: () => {
        const box = dock.current?.getBoundingClientRect();
        return box ? { x: box.left + box.width / 2, y: box.top + 18 } : null;
      },
      getFrom: () => {
        const box = source.getBoundingClientRect();
        return { x: box.left + box.width / 2, y: box.top + 24 };
      },
      getTo: () => {
        const box = target.getBoundingClientRect();
        return { x: box.left + box.width / 2, y: box.top + 78 };
      },
      onFrame: (snap) => {
        layer?.paint(snap);
        if (phase !== snap.phase) {
          phase = snap.phase;
          setHidden(
            ["seek", "return", "idle", "celebrate"].includes(snap.phase)
              ? null
              : job.before.case_id,
          );
        }
      },
      onComplete: () => {
        layer?.hide();
        setHidden(null);
        setAnnouncement(
          `Mola entregou ${job.after.case_id} em ${labels[job.after.state]}.`,
        );
        completeJob(job.key);
      },
    });
    return () => {
      stop();
      layer?.hide();
      setHidden(null);
    };
  }, [firstJob, skin, query, agent, company, layout, completeJob]);
  const projected = r.snapshot.cases.map((c) => {
    const pending = r.jobs.find((j) => j.before.case_id === c.case_id);
    return pending ? pending.before : c;
  });
  const cases = projected.filter(
    (c) =>
      `${c.case_id} ${explainText(c.report_text)} ${c.repo_ref}`
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (agent === "all" || agentOf(c.state) === agent) &&
      (company === "all" || c.client_id === company),
  );
  const detail = r.snapshot.cases.find((c) => c.case_id === selected);
  const targetStates: Record<string, CaseState> = {
    intake: "created",
    active: "fixing",
    review: "verifying",
    done: "verified",
    attention: "blocked",
  };
  return (
    <WorkspaceShell>
      <main className="board-content">
        <div className="page-heading">
          <div>
            <div className="board-page-title">
              <h1>O trabalho em movimento.</h1>
              <span className="count-badge">
                {r.snapshot.cases.length} casos
              </span>
            </div>
            <p>Os agentes executam. A Mola acompanha cada passagem.</p>
          </div>
          <button className="rq-button primary" onClick={() => setAdding(true)}>
            <Plus size={16} />
            Novo relato
          </button>
        </div>
        {r.mode === "production" && !r.config.baseUrl && (
          <div className="rq-alert">
            Estamos aguardando as informações da equipe.{" "}
            <Link href="/admin" className="inline-action">
              Ver acompanhamento <ArrowRight size={14} />
            </Link>
          </div>
        )}
        <div className="board-project-bar">
          <div>
            <span className="project-icon">
              <Columns3 size={19} />
            </span>
            <strong>Fluxo de resolução</strong>
            <span className="muted">/</span>
            <span>{r.mode === "demo" ? "Acme Commerce" : "Minha equipe"}</span>
          </div>
          <div
            className="board-layout-toggle"
            role="group"
            aria-label="Visualização"
          >
            <button
              aria-pressed={layout === "board"}
              onClick={() => setLayout("board")}
            >
              <Columns3 size={14} />
              Quadro
            </button>
            <button
              aria-pressed={layout === "list"}
              onClick={() => setLayout("list")}
            >
              <FileText size={14} />
              Lista
            </button>
          </div>
        </div>
        <div className="board-filters">
          <SearchBox value={query} onChange={setQuery} />
          <label className="filter-control">
            <Bot size={14} />
            <span className="sr-only">Filtrar agente</span>
            <select value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="all">Todos os agentes</option>
              {["Triage", "Reproducer", "Fixer", "Verifier"].map((a) => (
                <option key={a} value={a}>
                  {agentLabel(a)}
                </option>
              ))}
            </select>
          </label>
          <label className="filter-control">
            <span className="sr-only">Filtrar empresa</span>
            <select
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            >
              <option value="all">Todas as empresas</option>
              {[...new Set(r.snapshot.cases.map((c) => c.client_id))].map(
                (c) => (
                  <option key={c}>{c}</option>
                ),
              )}
            </select>
          </label>
          {r.mode === "demo" && (
            <div className="demo-controls">
              <button
                className="rq-button small"
                onClick={r.step}
                title="Avança o exemplo local"
              >
                <SkipForward size={14} />
                Avançar tarefa
              </button>
              <button
                className="rq-button small"
                onClick={() => r.setPlaying(!r.playing)}
              >
                {r.playing ? <Pause size={14} /> : <Play size={14} />}
                {r.playing ? "Pausar" : "Reproduzir"}
              </button>
              <button
                className="rq-icon-button"
                aria-label="Reiniciar exemplos"
                onClick={r.reset}
              >
                <RotateCcw size={15} />
              </button>
            </div>
          )}
        </div>
        {layout === "board" ? (
          <section className="live-board" aria-label="Quadro Kanban">
            {lanes.map((lane) => (
              <div
                className={`live-lane lane-${lane.id}`}
                data-lane={lane.id}
                key={lane.id}
                onDragOver={(e) => {
                  if (r.mode !== "demo") return;
                  e.preventDefault();
                }}
                onDrop={(e) => {
                  if (r.mode !== "demo") return;
                  e.preventDefault();
                  const id = e.dataTransfer.getData("text/resolveqa-id");
                  if (id) void r.moveCase(id, targetStates[lane.id]);
                }}
              >
                <header>
                  <div>
                    <Circle size={12} />
                    <h2>{lane.title}</h2>
                    <span>
                      {cases.filter((c) => laneOf(c.state) === lane.id).length}
                    </span>
                  </div>
                  <p>{lane.description}</p>
                </header>
                <div className="lane-drop">
                  {cases
                    .filter((c) => laneOf(c.state) === lane.id)
                    .map((c) => (
                      <article
                        className={`live-card ${hidden === c.case_id ? "card-carrying" : ""}`}
                        key={c.case_id}
                        data-run-id={c.case_id}
                        draggable={r.mode === "demo" && !r.jobs.length}
                        onDragStart={(e) => {
                          if (r.mode !== "demo") return;
                          e.dataTransfer.setData(
                            "text/resolveqa-id",
                            c.case_id,
                          );
                          e.dataTransfer.effectAllowed = "move";
                        }}
                      >
                        <div className="live-card-meta">
                          <code>{c.case_id}</code>
                          <button
                            className="rq-icon-button"
                            aria-label={`Abrir ${c.case_id}`}
                            onClick={() => setSelected(c.case_id)}
                          >
                            <MoreHorizontal size={16} />
                          </button>
                        </div>
                        <button
                          className="live-card-title"
                          onClick={() => setSelected(c.case_id)}
                        >
                          {explainText(c.report_text)}
                        </button>
                        <span className="card-repo">
                          <BookOpen size={11} />
                          {c.repo_ref}
                        </span>
                        <span className={`card-state state-${lane.id}`}>
                          {c.state === "verified" ? (
                            <Check size={11} />
                          ) : (
                            <Circle size={8} />
                          )}
                          {labels[c.state]}
                        </span>
                        <footer>
                          <span className="agent-label">
                            <span
                              className={`agent-orb agent-${agentOf(c.state).toLowerCase()}`}
                            >
                              <Bot size={12} />
                            </span>
                            {agentLabel(agentOf(c.state))}
                          </span>
                          <span>
                            <FileText size={11} />
                            {c.evidence_ids.length}
                          </span>
                        </footer>
                      </article>
                    ))}
                  {!cases.some((c) => laneOf(c.state) === lane.id) && (
                    <div className="lane-empty">
                      <Circle size={18} />
                      <span>
                        {query || agent !== "all" || company !== "all"
                          ? "Sem resultados neste filtro"
                          : "Aguardando o próximo caso"}
                      </span>
                    </div>
                  )}
                </div>
                {lane.id === "intake" && (
                  <button
                    className="add-case-lane"
                    onClick={() => setAdding(true)}
                  >
                    <Plus size={14} />
                    Adicionar relato
                  </button>
                )}
              </div>
            ))}
          </section>
        ) : (
          <section className="data-panel">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Caso</th>
                    <th>Relato</th>
                    <th>Agente</th>
                    <th>Estado</th>
                    <th>Atualização</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => (
                    <tr key={c.case_id}>
                      <td>
                        <button
                          className="inline-action"
                          onClick={() => setSelected(c.case_id)}
                        >
                          <code>{c.case_id}</code>
                        </button>
                      </td>
                      <td>
                        <button
                          className="run-title"
                          onClick={() => setSelected(c.case_id)}
                        >
                          {explainText(c.report_text)}
                        </button>
                      </td>
                      <td>{agentLabel(agentOf(c.state))}</td>
                      <td>
                        <Status run={c} />
                      </td>
                      <td>
                        <Clock value={c.updated_at} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!cases.length && (
              <Empty title="Nenhum caso neste filtro">
                Ajuste a busca ou adicione um relato.
              </Empty>
            )}
          </section>
        )}
        <div className="mola-dock">
          <div ref={dock} className="mola-home">
            <MolaSprite
              width={70}
              clip={r.jobs.length ? "work" : "idle"}
              frame={0}
              skin={skin}
            />
          </div>
          <div>
            <strong>
              {r.jobs.length
                ? `Mola em movimento · ${r.jobs.length} passagem(ns) na fila`
                : "Mola pronta para o próximo evento"}
            </strong>
            <p>
              {r.mode === "demo"
                ? "Veja os exemplos avançarem: os agentes trabalham e a Mola leva cada caso para a próxima etapa."
                : r.config.streamPath
                  ? "Acompanhando as atividades da equipe em tempo real."
                  : "Atualizando as etapas dos casos automaticamente."}
            </p>
          </div>
          <label className="filter-control">
            <span className="sr-only">Cor da Mola</span>
            <select
              value={skin}
              onChange={(e) => setSkin(Number(e.target.value))}
            >
              <option value={0}>Arco-íris</option>
              <option value={1}>Tangerina</option>
              <option value={2}>Lavanda</option>
              <option value={5}>Azul</option>
            </select>
          </label>
        </div>
        <footer className="app-footnote">
          <span>
            <span className="live-dot" />
            {r.mode === "demo"
              ? "Exemplos ilustrativos · arraste os casos ou avance as atividades"
              : "Etapas atualizadas pelos agentes"}
          </span>
          <span>
            Concluído exige verificação · Falhas e bloqueios ficam em Atenção
          </span>
        </footer>
        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>
      </main>
      <TransportLayer ref={transport} />
      {detail && (
        <CaseDetail run={detail} snapshot={r.snapshot} onClose={closeDetails} />
      )}
      {adding && <NewCaseForm onClose={() => setAdding(false)} />}
    </WorkspaceShell>
  );
}
