"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  applyEvent,
  eventSchema,
  snapshotSchema,
  playbookSchema,
  type Snapshot,
  type RunEvent,
  type Run,
  type Playbook,
} from "@/lib/resolveqa/domain";
import {
  makeDemo,
  demoPlaybooks,
  makeRun,
  nextDemoEvent,
} from "@/lib/resolveqa/demo";
import {
  apiUrl,
  createCase,
  deleteRemotePlaybook,
  fetchCase,
  fetchSnapshot,
  listPlaybooks,
  parseStream,
  saveRemotePlaybook,
  type ConnectionConfig,
} from "@/lib/resolveqa/client";

import { friendlyError } from "@/lib/resolveqa/copy";
import type { RuntimeSettings } from "@/lib/resolveqa/environment";
export type MotionJob = { key: string; before: Run; after: Run };
const empty: Snapshot = { cases: [], events: [], spans: [], documents: [] };
const KEY = "resolveqa.workspace.v2";
type Runtime = {
  snapshot: Snapshot;
  mode: RuntimeSettings["mode"];
  config: ConnectionConfig;
  ready: boolean;
  connection: string;
  error: string;
  playing: boolean;
  playbooks: Playbook[];
  jobs: MotionJob[];
  lastSync: string;
  refresh: () => void;
  setPlaying: (p: boolean) => void;
  step: () => void;
  reset: () => void;
  completeJob: (key: string) => void;
  addCase: (r: {
    client_id: string;
    repo_ref: string;
    report_text: string;
  }) => Promise<void>;
  moveCase: (id: string, state: Run["state"]) => Promise<void>;
  /** @deprecated use moveCase — kept for older demo call sites during rename */
  moveDemo: (id: string, state: Run["state"]) => void;
  savePlaybook: (p: Playbook) => Promise<void>;
  removePlaybook: (id: string) => Promise<void>;
};
const Context = createContext<Runtime | null>(null);
export function useRuntime() {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("Workspace provider missing");
  return ctx;
}

export function RuntimeProvider({
  children,
  settings,
}: {
  children: ReactNode;
  settings: RuntimeSettings;
}) {
  const mode = settings.mode;
  const [config, setConfig] = useState<ConnectionConfig>(settings.connection);
  const initialConnection = useRef(settings.connection);
  const watchedCases = useRef<Record<string, string[]>>({});
  const [snapshot, setSnapshot] = useState<Snapshot>(empty);
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [ready, setReady] = useState(false);
  const [connection, setConnection] = useState("Carregando");
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [revision, setRevision] = useState(0);
  const [jobs, setJobs] = useState<MotionJob[]>([]);
  const [lastSync, setLastSync] = useState("");
  const current = useRef(snapshot);
  const demoCache = useRef<{
    snapshot: Snapshot;
    playbooks: Playbook[];
  } | null>(null);
  const modeRef = useRef(mode);
  const configRef = useRef(config);
  const generation = useRef(0);
  const commit = useCallback((s: Snapshot) => {
    current.current = s;
    setSnapshot(s);
  }, []);
  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);
  useEffect(() => {
    configRef.current = config;
  }, [config]);

  useEffect(() => {
    queueMicrotask(() => {
      let saved: {
        demo?: unknown;
        playbooks?: unknown;
        watchedCases?: Record<string, unknown>;
      } = {};
      try {
        const value = JSON.parse(localStorage.getItem(KEY) || "{}");
        if (value && typeof value === "object" && !Array.isArray(value))
          saved = value;
      } catch {
        /* Storage is optional. */
      }
      const parsed = snapshotSchema.safeParse(saved.demo);
      const demo = parsed.success ? parsed.data : makeDemo();
      const pbs = Array.isArray(saved.playbooks)
        ? saved.playbooks
            .map((p) => playbookSchema.safeParse(p))
            .filter((p) => p.success)
            .map((p) => p.data!)
        : demoPlaybooks;
      demoCache.current = { snapshot: demo, playbooks: pbs };
      const deployment = initialConnection.current;
      const savedIds = saved.watchedCases?.[deployment.baseUrl];
      const ids = Array.isArray(savedIds)
        ? savedIds
            .filter(
              (id): id is string =>
                typeof id === "string" && id.length > 0 && id.length <= 200,
            )
            .slice(0, 500)
        : [];
      watchedCases.current = { [deployment.baseUrl]: ids };
      if (mode === "production" && ids.length)
        setConfig({
          ...deployment,
          caseIds: [...new Set([...deployment.caseIds, ...ids])],
        });
      commit(mode === "demo" ? demo : empty);
      setPlaybooks(mode === "demo" ? pbs : []);
      setConnection(
        mode === "demo" ? "Exemplos para explorar" : "Aguardando atualização",
      );
      setReady(true);
    });
  }, [commit, mode]);
  useEffect(() => {
    if (!ready) return;
    if (mode === "demo") demoCache.current = { snapshot, playbooks };
    if (mode === "production")
      watchedCases.current[config.baseUrl] = config.caseIds;
    try {
      localStorage.setItem(
        KEY,
        JSON.stringify({
          demo: demoCache.current?.snapshot,
          playbooks: demoCache.current?.playbooks,
          watchedCases: watchedCases.current,
        }),
      );
    } catch {
      /* Private browsing may disable storage. */
    }
  }, [snapshot, playbooks, mode, config, ready]);

  const ingest = useCallback(
    (event: RunEvent) => {
      const before = current.current.cases.find(
        (c) => c.case_id === event.case_id,
      );
      const next = applyEvent(current.current, event);
      if (next === current.current) return;
      commit(next);
      const after = next.cases.find((c) => c.case_id === event.case_id);
      if (before && after && before.state !== after.state)
        if (window.location.pathname === "/quadro")
          setJobs((old) =>
            [...old, { key: event.event_id, before, after }].slice(-80),
          );
    },
    [commit],
  );

  useEffect(() => {
    if (!ready || mode !== "production") return;
    const controller = new AbortController();
    let stopped = false;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout>;
    let chain = Promise.resolve();
    const acceptSnapshot = (next: Snapshot) => {
      const previous = current.current;
      // A slower HTTP response must not roll back a newer stream transition.
      next = {
        ...next,
        cases: next.cases.map((c) => {
          const newer = previous.cases.find(
            (p) =>
              p.case_id === c.case_id &&
              Date.parse(p.updated_at) > Date.parse(c.updated_at),
          );
          return newer || c;
        }),
      };
      for (const after of next.cases) {
        const before = previous.cases.find((c) => c.case_id === after.case_id);
        if (before && before.state !== after.state)
          if (window.location.pathname === "/quadro")
            setJobs((old) =>
              [
                ...old,
                {
                  key: `poll-${after.case_id}-${after.updated_at}`,
                  before,
                  after,
                },
              ].slice(-80),
            );
      }
      commit({
        ...next,
        events: next.events.length ? next.events : previous.events,
      });
    };
    const poll = async () => {
      try {
        if (!config.baseUrl) {
          setConnection("Aguardando informações");
          return;
        }
        if (!current.current.cases.length) setConnection("Conectando");
        const next = await fetchSnapshot(config, controller.signal);
        const pbs = config.playbooksPath
          ? await listPlaybooks(config, controller.signal)
          : [];
        if (stopped) return;
        acceptSnapshot(next);
        setPlaybooks(pbs);
        setError("");
        setLastSync(new Date().toISOString());
        setConnection(
          source?.readyState === EventSource.OPEN
            ? "Informações atualizadas"
            : "Acompanhamento atualizado",
        );
      } catch (e) {
        if (!stopped) {
          setError(friendlyError(e));
          setConnection("Atualizações interrompidas");
        }
      } finally {
        if (!stopped) timer = setTimeout(poll, 5000);
      }
    };
    void poll();
    if (config.baseUrl && config.streamPath) {
      try {
        source = new EventSource(apiUrl(config, config.streamPath));
        source.onopen = () => {
          if (!stopped) setConnection("Stream conectado");
        };
        source.onerror = () => {
          if (!stopped) setConnection("Retomando as atualizações");
        };
        const receive = (message: MessageEvent) => {
          chain = chain
            .then(async () => {
              if (stopped) return;
              const event = parseStream(message.data);
              const known = current.current.cases.find(
                (c) => c.case_id === event.case_id,
              );
              const previousSeq = Math.max(
                0,
                ...current.current.events
                  .filter((e) => e.case_id === event.case_id)
                  .map((e) => e.seq),
              );
              if (
                current.current.events.some(
                  (e) => e.event_id === event.event_id,
                ) ||
                event.seq <= previousSeq
              )
                return;
              if (!known || event.seq > previousSeq + 1) {
                const updated = await fetchCase(
                  config,
                  event.case_id,
                  controller.signal,
                );
                if (stopped) return;
                if (known && known.state !== updated.state)
                  if (window.location.pathname === "/quadro")
                    setJobs((old) =>
                      [
                        ...old,
                        { key: event.event_id, before: known, after: updated },
                      ].slice(-80),
                    );
                commit({
                  ...current.current,
                  cases: [
                    ...current.current.cases.filter(
                      (c) => c.case_id !== updated.case_id,
                    ),
                    updated,
                  ],
                });
                setConfig((c) => ({
                  ...c,
                  caseIds: [...new Set([...c.caseIds, updated.case_id])],
                }));
              }
              ingest(event);
              setLastSync(new Date().toISOString());
            })
            .catch((e) => {
              if (!stopped) setError(friendlyError(e));
            });
        };
        source.onmessage = receive;
        for (const type of [
          "CaseCreated",
          "StateChanged",
          "EvidenceAdded",
          "LimitReached",
          "MessageSent",
          "ReplayStarted",
        ])
          source.addEventListener(type, receive as EventListener);
      } catch (e) {
        queueMicrotask(() => {
          if (!stopped) setError(friendlyError(e));
        });
      }
    }
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
      source?.close();
    };
  }, [mode, ready, config, revision, commit, ingest]);

  const step = useCallback(() => {
    if (modeRef.current !== "demo") return;
    const next = nextDemoEvent(current.current);
    if (next.run)
      commit({
        ...current.current,
        cases: [next.run, ...current.current.cases],
      });
    ingest(next.event);
  }, [commit, ingest]);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(step, 5500);
    return () => clearInterval(t);
  }, [playing, step]);
  const addCase = async (report: {
    client_id: string;
    repo_ref: string;
    report_text: string;
  }) => {
    const gen = generation.current;
    const run =
      mode === "demo"
        ? {
            ...makeRun(
              `RQA-${Date.now().toString().slice(-7)}`,
              report.report_text,
            ),
            client_id: report.client_id,
            repo_ref: report.repo_ref,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }
        : await createCase(config, report);
    if (gen !== generation.current) return;
    commit({
      ...current.current,
      cases: [
        run,
        ...current.current.cases.filter((c) => c.case_id !== run.case_id),
      ],
    });
    if (mode === "production")
      setConfig((c) => ({
        ...c,
        caseIds: [...new Set([...c.caseIds, run.case_id])],
      }));
    else
      ingest({
        event_id: crypto.randomUUID(),
        case_id: run.case_id,
        seq: 1,
        ts: run.created_at,
        source: "intake",
        type: "CaseCreated",
        reason: "Relato de exemplo criado.",
        evidence_refs: [],
      });
  };
  const savePlaybook = async (p: Playbook) => {
    const gen = generation.current;
    if (mode === "production" && !config.playbooksPath)
      throw new Error(
        "O cadastro de procedimentos ainda não está disponível. Fale com a equipe responsável.",
      );
    const saved =
      mode === "demo"
        ? p
        : await saveRemotePlaybook(
            config,
            p,
            playbooks.some((b) => b.id === p.id),
          );
    if (gen === generation.current)
      setPlaybooks((old) => [saved, ...old.filter((b) => b.id !== saved.id)]);
  };
  const removePlaybook = async (id: string) => {
    const gen = generation.current;
    if (mode === "production") {
      if (!config.playbooksPath)
        throw new Error(
          "O cadastro de procedimentos ainda não está disponível. Fale com a equipe responsável.",
        );
      await deleteRemotePlaybook(config, id);
    }
    if (gen === generation.current)
      setPlaybooks((old) => old.filter((p) => p.id !== id));
  };
  const completeJob = useCallback(
    (key: string) => setJobs((old) => old.filter((j) => j.key !== key)),
    [],
  );
  return (
    <Context.Provider
      value={{
        snapshot,
        mode,
        config,
        ready,
        connection,
        error,
        playing,
        playbooks,
        jobs,
        lastSync,
        refresh: () => setRevision((r) => r + 1),
        setPlaying,
        step,
        reset: () => {
          if (mode !== "demo") return;
          setPlaying(false);
          setJobs([]);
          commit(makeDemo());
          setPlaybooks(demoPlaybooks);
        },
        completeJob,
        addCase,
        savePlaybook,
        removePlaybook,
        moveCase: async (id, state) => {
          const run = current.current.cases.find((c) => c.case_id === id);
          if (!run || run.state === state) return;
          if (mode !== "demo") {
            setError(
              "Em produção o quadro só observa o worker; movimento manual desligado.",
            );
            return;
          }
          const ev = eventSchema.parse({
            event_id: crypto.randomUUID(),
            case_id: id,
            seq:
              Math.max(
                0,
                ...current.current.events
                  .filter((e) => e.case_id === id)
                  .map((e) => e.seq),
              ) + 1,
            ts: new Date().toISOString(),
            source: "orchestrator",
            type: "StateChanged",
            from_state: run.state,
            to_state: state,
            reason:
              "Movimento manual de demonstração; não constitui verificação real.",
            evidence_refs: [],
          });
          ingest(ev);
        },
        moveDemo: (id, state) => {
          if (modeRef.current !== "demo") return;
          void rMove(id, state);
          async function rMove(caseId: string, next: typeof state) {
            const run = current.current.cases.find((c) => c.case_id === caseId);
            if (!run || run.state === next) return;
            const ev = eventSchema.parse({
              event_id: crypto.randomUUID(),
              case_id: caseId,
              seq:
                Math.max(
                  0,
                  ...current.current.events
                    .filter((e) => e.case_id === caseId)
                    .map((e) => e.seq),
                ) + 1,
              ts: new Date().toISOString(),
              source: "orchestrator",
              type: "StateChanged",
              from_state: run.state,
              to_state: next,
              reason:
                "Movimento manual de demonstração; não constitui verificação real.",
              evidence_refs: [],
            });
            ingest(ev);
          }
        },
      }}
    >
      {children}
    </Context.Provider>
  );
}
