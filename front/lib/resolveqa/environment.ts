import type { ConnectionConfig } from "./client";

export type RuntimeSettings = {
  mode: "demo" | "production";
  connection: ConnectionConfig;
};

/** Server-only entry point: serialize only public connection settings, never secrets. */
export function readRuntimeSettings(
  env: Record<string, string | undefined>,
): RuntimeSettings {
  const mode = env.RESOLVEQA_MODE?.trim() || "production";
  if (mode !== "demo" && mode !== "production")
    throw new Error("RESOLVEQA_MODE must be demo or production.");
  return {
    mode,
    connection: {
      baseUrl: env.RESOLVEQA_API_URL?.trim().replace(/\/$/, "") || "",
      caseIds: [
        ...new Set(
          (env.RESOLVEQA_CASE_IDS || "")
            .split(/[\n,]/)
            .map((id) => id.trim())
            .filter(Boolean),
        ),
      ],
      snapshotPath: env.RESOLVEQA_SNAPSHOT_PATH?.trim() || "",
      streamPath: env.RESOLVEQA_EVENTS_PATH?.trim() || "",
      playbooksPath: env.RESOLVEQA_PLAYBOOKS_PATH?.trim() || "",
    },
  };
}
