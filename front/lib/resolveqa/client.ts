import {
  caseSchema,
  eventSchema,
  snapshotSchema,
  playbookSchema,
  type Run,
  type Snapshot,
  type Playbook,
} from "./domain";
import { z } from "zod";

export type ConnectionConfig = {
  baseUrl: string;
  caseIds: string[];
  snapshotPath: string;
  streamPath: string;
  playbooksPath: string;
};
export const defaultConfig: ConnectionConfig = {
  baseUrl: "",
  caseIds: [],
  snapshotPath: "",
  streamPath: "",
  playbooksPath: "",
};
export const connectionConfigSchema = z.object({
  baseUrl: z.string(),
  caseIds: z.array(z.string()),
  snapshotPath: z.string(),
  streamPath: z.string(),
  playbooksPath: z.string(),
});
export function apiUrl(config: ConnectionConfig, path: string): string {
  const base = new URL(config.baseUrl || window.location.origin);
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password
  )
    throw new Error("Use uma URL HTTP(S), sem credenciais.");
  if (
    window.location.protocol === "https:" &&
    base.protocol !== "https:" &&
    !["localhost", "127.0.0.1"].includes(base.hostname)
  )
    throw new Error("Use HTTPS para conectar este backend.");
  if (!path.startsWith("/") || path.startsWith("//"))
    throw new Error("O caminho da API deve começar com uma única barra.");
  return `${base.origin}${path}`;
}
async function request(
  config: ConnectionConfig,
  path: string,
  signal?: AbortSignal,
  init?: RequestInit,
) {
  const result = await fetch(apiUrl(config, path), {
    cache: "no-store",
    signal,
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!result.ok)
    throw new Error(
      `Backend respondeu HTTP ${result.status}. Verifique o endereço, a rota e as permissões.`,
    );
  return result.status === 204 ? null : result.json();
}
export async function fetchCase(
  config: ConnectionConfig,
  id: string,
  signal?: AbortSignal,
): Promise<Run> {
  return z
    .object({ case: caseSchema })
    .parse(
      await request(config, `/api/cases/${encodeURIComponent(id)}`, signal),
    ).case;
}
export async function fetchSnapshot(
  config: ConnectionConfig,
  signal: AbortSignal,
): Promise<Snapshot> {
  if (config.snapshotPath)
    return snapshotSchema.parse(
      await request(config, config.snapshotPath, signal),
    );
  await request(config, "/health", signal);
  const cases = await Promise.all(
    config.caseIds.map((id) => fetchCase(config, id, signal)),
  );
  return { cases, events: [], spans: [], documents: [] };
}
export async function createCase(
  config: ConnectionConfig,
  report: { client_id: string; repo_ref: string; report_text: string },
): Promise<Run> {
  return z.object({ case: caseSchema }).parse(
    await request(config, "/api/cases", undefined, {
      method: "POST",
      body: JSON.stringify(report),
    }),
  ).case;
}
export async function advanceCase(
  config: ConnectionConfig,
  id: string,
  body: { to_state?: Run["state"]; reason?: string } = {},
): Promise<{ case: Run; from_state: Run["state"] | null }> {
  const payload = z
    .object({
      case: caseSchema,
      event: z
        .object({
          from_state: caseSchema.shape.state.nullable().optional(),
          to_state: caseSchema.shape.state.nullable().optional(),
        })
        .passthrough()
        .nullable()
        .optional(),
    })
    .parse(
      await request(
        config,
        `/api/cases/${encodeURIComponent(id)}/advance`,
        undefined,
        { method: "POST", body: JSON.stringify(body) },
      ),
    );
  return {
    case: payload.case,
    from_state: payload.event?.from_state ?? null,
  };
}
export function parseStream(data: string) {
  return eventSchema.parse(JSON.parse(data));
}
export async function listPlaybooks(
  config: ConnectionConfig,
  signal: AbortSignal,
) {
  return z
    .array(playbookSchema)
    .parse(await request(config, config.playbooksPath, signal));
}
export async function saveRemotePlaybook(
  config: ConnectionConfig,
  playbook: Playbook,
  exists: boolean,
) {
  return playbookSchema.parse(
    await request(
      config,
      exists
        ? `${config.playbooksPath}/${encodeURIComponent(playbook.id)}`
        : config.playbooksPath,
      undefined,
      { method: exists ? "PUT" : "POST", body: JSON.stringify(playbook) },
    ),
  );
}
export async function deleteRemotePlaybook(
  config: ConnectionConfig,
  id: string,
) {
  await request(
    config,
    `${config.playbooksPath}/${encodeURIComponent(id)}`,
    undefined,
    { method: "DELETE" },
  );
}
