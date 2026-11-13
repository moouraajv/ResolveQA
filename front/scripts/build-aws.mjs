import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const cli = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));
const apiUrl = (process.env.RESOLVEQA_API_URL || "").trim();
if (!apiUrl) {
  console.error(
    "RESOLVEQA_API_URL is required for AWS static export (public backend base URL).",
  );
  process.exit(1);
}

const result = spawnSync(process.execPath, [cli, "build", "--webpack"], {
  stdio: "inherit",
  env: {
    ...process.env,
    RESOLVEQA_STATIC_EXPORT: "1",
    NEXT_TELEMETRY_DISABLED: "1",
    RESOLVEQA_MODE: process.env.RESOLVEQA_MODE?.trim() || "production",
    RESOLVEQA_API_URL: apiUrl.replace(/\/$/, ""),
  },
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
