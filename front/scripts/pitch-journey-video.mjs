#!/usr/bin/env node
/**
 * Record a ~2 minute silent product-journey video of the public ResolveQA demo.
 * Intended to be muxed with the pitch voiceover afterwards.
 *
 * Usage:
 *   node scripts/pitch-journey-video.mjs
 *   RESOLVEQA_FRONT_URL=https://d10ry6ff7l79jo.cloudfront.net node scripts/pitch-journey-video.mjs
 */
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const outDir = path.join(root, "docs/evidence/pitch");
const front =
  (process.env.RESOLVEQA_FRONT_URL || "https://d10ry6ff7l79jo.cloudfront.net").replace(
    /\/$/,
    "",
  );
const back =
  (process.env.RESOLVEQA_API_URL || "https://d2f79ulrlhg51j.cloudfront.net").replace(
    /\/$/,
    "",
  );

const TARGET_MS = Number(process.env.PITCH_VIDEO_MS || 120_000);
const started = Date.now();

async function beat(page, ms, label) {
  const elapsed = Date.now() - started;
  console.log(`t=${(elapsed / 1000).toFixed(1)}s  ${label} (+${ms}ms)`);
  await page.waitForTimeout(ms);
}

async function safeClick(page, selector, timeout = 4000) {
  const loc = page.locator(selector).first();
  if ((await loc.count()) === 0) return false;
  try {
    await loc.click({ timeout });
    return true;
  } catch {
    return false;
  }
}

await fs.mkdir(outDir, { recursive: true });
await fs.rm(path.join(outDir, "takes"), { recursive: true, force: true });
await fs.mkdir(path.join(outDir, "takes"), { recursive: true });

const browser = await chromium.launch({
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : { channel: "chrome" }),
  headless: true,
});

const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
  recordVideo: {
    dir: path.join(outDir, "takes"),
    size: { width: 1440, height: 900 },
  },
});

const page = await context.newPage();
page.setDefaultTimeout(15_000);

// --- 0:00–0:18 Landing ---
await page.goto(`${front}/`, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready.catch(() => {}));
await beat(page, 4000, "Landing — brand + hero");
await page.mouse.wheel(0, 420);
await beat(page, 5000, "Landing — scroll value props");
await page.mouse.wheel(0, -420);
await beat(page, 4000, "Landing — hold on CTA");

// Prefer in-app navigation when links exist
if (!(await safeClick(page, 'a[href="/quadro"], a[href*="quadro"]'))) {
  await page.goto(`${front}/quadro`, { waitUntil: "networkidle" });
}

// --- 0:18–1:10 Quadro / Mola ---
await beat(page, 5000, "Quadro — board with seeded cards");
await page.mouse.move(720, 420);
await beat(page, 3000, "Quadro — hover board");
// Try opening first card / detail if present
await safeClick(
  page,
  '[data-testid="case-card"], .kanban-card, article, [class*="card"]',
);
await beat(page, 6000, "Quadro — card detail / focus");
await page.keyboard.press("Escape").catch(() => {});
await beat(page, 4000, "Quadro — Mola / columns settle");
await page.mouse.wheel(0, 280);
await beat(page, 5000, "Quadro — scroll activity");
await page.mouse.wheel(0, -280);
await beat(page, 4000, "Quadro — return to board");

if (!(await safeClick(page, 'a[href="/admin"], a[href*="admin"]'))) {
  await page.goto(`${front}/admin`, { waitUntil: "networkidle" });
}

// --- 1:10–1:50 Admin ---
await beat(page, 5000, "Admin — KPIs / operations");
await page.mouse.wheel(0, 360);
await beat(page, 5000, "Admin — scroll metrics");
await safeClick(page, 'button:has-text("Carregar"), button:has-text("Atualizar")');
await beat(page, 5000, "Admin — connection / cost panel");
await page.mouse.wheel(0, 420);
await beat(page, 5000, "Admin — deeper ops view");

// --- 1:50–2:00 Backend pulse + return to quadro ---
await page.goto(`${back}/health`, { waitUntil: "networkidle" });
await beat(page, 3000, "Backend — /health OK");
await page.goto(`${front}/quadro`, { waitUntil: "networkidle" });

const remaining = TARGET_MS - (Date.now() - started);
if (remaining > 500) {
  await beat(page, Math.min(remaining, 12_000), "Finale — Quadro hold for pitch close");
} else {
  await beat(page, 1500, "Finale — short hold");
}

const video = page.video();
await context.close();
await browser.close();

const takePath = await video.path();
const finalPath = path.join(outDir, "resolveqa-pitch-journey-2min.webm");
await fs.rename(takePath, finalPath);
const stat = await fs.stat(finalPath);
const elapsed = Date.now() - started;

const note = `# Pitch journey video

- File: \`docs/evidence/pitch/resolveqa-pitch-journey-2min.webm\`
- Duration target: ~2 min (recorded wall ${Math.round(elapsed / 1000)}s)
- Front: ${front}
- Back health beat: ${back}/health
- Audio: **not muxed** — no voiceover file was attached to the request; overlay the pitch audio in post.

## Beats
1. Landing hero + value
2. Quadro with seeded cards / Mola board
3. Admin operations / cost panel
4. Backend health pulse
5. Return to Quadro for close
`;
await fs.writeFile(path.join(outDir, "README.md"), note);

console.log(
  JSON.stringify(
    {
      ok: true,
      video: finalPath,
      bytes: stat.size,
      elapsed_ms: elapsed,
      front,
      back,
    },
    null,
    2,
  ),
);
