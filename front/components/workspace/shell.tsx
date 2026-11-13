"use client";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Bot,
  Cable,
  Columns3,
  FileText,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  Radio,
  RefreshCw,
  Terminal,
} from "lucide-react";
import type { ReactNode } from "react";
import { Logo } from "./ui";
import { useRuntime } from "./runtime";
export const adminViews = [
  { id: "overview", label: "Visão geral", icon: LayoutDashboard },
  { id: "runs", label: "Execuções", icon: ListChecks },
  { id: "logs", label: "Atividades", icon: Terminal },
  { id: "traces", label: "Tempo por etapa", icon: GitBranch },
  { id: "agents", label: "Agentes", icon: Bot },
  { id: "playbooks", label: "Procedimentos", icon: BookOpen },
  { id: "documents", label: "Documentação", icon: FileText },
  { id: "connection", label: "Conexão", icon: Cable },
];
export function WorkspaceShell({
  children,
  view = "board",
  onView,
}: {
  children: ReactNode;
  view?: string;
  onView?: (view: string) => void;
}) {
  const r = useRuntime();
  return (
    <div
      className={`rq-app ${view === "board" ? "rq-board-app" : "rq-admin-app"}`}
    >
      <aside className="app-sidebar">
        <Logo />
        <div className="workspace-select">
          <span className="workspace-monogram">RQ</span>
          <div>
            <strong>ResolveQA</strong>
            <span>Staging · central de acompanhamento</span>
          </div>
        </div>
        <span className="sidebar-caption">Área de trabalho</span>
        <nav aria-label="Ambientes">
          <Link className={view === "board" ? "selected" : ""} href="/quadro">
            <Columns3 size={17} />
            Mola <ArrowUpRight size={13} />
          </Link>
          <Link className={view !== "board" ? "selected" : ""} href="/admin">
            <Activity size={17} />
            Admin <ArrowUpRight size={13} />
          </Link>
        </nav>
        {onView && (
          <>
            <span className="sidebar-caption">Operação</span>
            <nav aria-label="Painel administrativo">
              {adminViews.map((v) => (
                <button
                  key={v.id}
                  disabled={!r.ready}
                  aria-label={v.label}
                  className={view === v.id ? "selected" : ""}
                  onClick={() => onView(v.id)}
                >
                  <v.icon size={17} />
                  {v.label}
                  {v.id === "playbooks" && (
                    <span className="nav-count">{r.playbooks.length}</span>
                  )}
                </button>
              ))}
            </nav>
          </>
        )}
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Radio size={16} />
            <strong>
              {r.mode === "demo"
                ? "Um ambiente para explorar"
                : "Acompanhamento da equipe"}
            </strong>
            <p>
              {r.mode === "demo"
                ? "Explore exemplos de como os casos avançam entre as etapas."
                : "Acompanhe o trabalho dos agentes e os resultados de cada caso."}
            </p>
          </div>
          <Link href="/">
            <ArrowLeft size={15} />
            Voltar ao início
          </Link>
        </div>
      </aside>
      <div className="app-body">
        <header className="app-topbar">
          <div>
            <span className="topbar-product">ResolveQA</span>
            <span className="breadcrumb-slash">/</span>
            <strong>{view === "board" ? "Mola" : "Admin"}</strong>
          </div>
          <div className="app-topbar-end">
            <span className={`connection-label ${r.error ? "is-error" : ""}`}>
              <i />
              {r.connection}
            </span>
            <button
              className="rq-icon-button"
              aria-label="Atualizar dados"
              onClick={r.refresh}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </header>
        {r.mode === "demo" && (
          <div className="environment-bar">
            <span className="live-dot" />
            Exemplos ilustrativos para explorar o acompanhamento
            <span>Os exemplos não alteram o trabalho da sua equipe.</span>
          </div>
        )}
        {r.error && (
          <div className="connection-error" role="alert">
            <strong>{r.error}</strong>
            <span>
              {r.lastSync
                ? `Dados da última consulta: ${new Date(r.lastSync).toLocaleTimeString("pt-BR")}.`
                : "Ainda não recebemos informações atualizadas."}
            </span>
            <button onClick={r.refresh}>Tentar novamente</button>
          </div>
        )}
        {!r.ready ? (
          <div className="app-loading" role="status">
            Preparando seu espaço…
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
