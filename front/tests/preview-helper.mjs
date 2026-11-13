import { createServer } from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

export async function startProductionPreview(backend) {
  const probe = createServer();
  await new Promise((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const port = probe.address().port;
  await new Promise((resolve) => probe.close(resolve));
  const child = spawn(
    process.execPath,
    [
      fileURLToPath(
        new URL("../node_modules/vite/bin/vite.js", import.meta.url),
      ),
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
      "--strictPort",
    ],
    {
      cwd: fileURLToPath(new URL("../", import.meta.url)),
      windowsHide: true,
      env: {
        ...process.env,
        RESOLVEQA_MODE: "production",
        RESOLVEQA_API_URL: backend,
        RESOLVEQA_CASE_IDS: "SSE-1",
        RESOLVEQA_SNAPSHOT_PATH: "/snapshot",
        RESOLVEQA_EVENTS_PATH: "/stream",
        RESOLVEQA_PLAYBOOKS_PATH: "",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let output = "";
  child.stdout.on("data", (d) => {
    output += d;
  });
  child.stderr.on("data", (d) => {
    output += d;
  });
  const url = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error(`Preview failed: ${output}`);
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(2000) })).ok)
        return { url, close: () => child.kill() };
    } catch {
      /* Wait for initial compilation. */
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  child.kill();
  throw new Error(`Preview did not start: ${output}`);
}
