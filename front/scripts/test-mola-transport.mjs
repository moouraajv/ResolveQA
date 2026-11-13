// Node >=22.13: node --experimental-strip-types scripts/test-mola-transport.mjs
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// Resolve the app's extensionless TS imports without adding a test dependency.
const dir = await mkdtemp(join(tmpdir(), 'mola-test-'));
try {
  for (const name of ['atlas', 'physics', 'transport', 'slinky']) {
    const source = await readFile(new URL(`../components/mola/${name}.ts`, import.meta.url), 'utf8');
    await writeFile(join(dir, `${name}.ts`), source.replace(/from "\.\/(atlas|physics)"/g, 'from "./$1.ts"'));
  }
  const { runTransport, buildWaypoints, samplePath } = await import(pathToFileURL(join(dir, 'transport.ts')));
  const home = { x: 80, y: 80 }, from = { x: 200, y: 180 }, to = { x: 600, y: 150 };
  const wp = buildWaypoints(from, to, home);
  const phases = ['seek', 'compress', 'reach', 'carry', 'deliver', 'celebrate', 'return', 'idle'];
  for (let i = 1; i < phases.length; i++) {
    const a = samplePath(wp, phases[i - 1], 1), b = samplePath(wp, phases[i], 0);
    assert.ok(Math.hypot(a.x - b.x, a.y - b.y) < 1e-9, `continuous ${phases[i]}`);
  }
  const { slinkyFrame, SLINKY_SHEET } = await import(pathToFileURL(join(dir, 'slinky.ts')));
  assert.equal(SLINKY_SHEET.count, 8);
  for (let i = 0; i < 8; i++) assert.equal(slinkyFrame(i / 8), i, 'all eight drawn poses selected');
  assert.equal(slinkyFrame(1), 0, 'loop returns to first pose');
  assert.equal(slinkyFrame(-0.125), 7, 'reverse wrapping');
  assert.equal(slinkyFrame(0.124), 0, 'pose held until next frame');
  let queue = new Map(), serial = 0;
  globalThis.requestAnimationFrame = cb => { queue.set(++serial, cb); return serial; };
  globalThis.cancelAnimationFrame = id => queue.delete(id);
  globalThis.window = { matchMedia: () => ({ matches: false }) };
  let frames = [], completions = [];
  const options = { getHome: () => home, getFrom: () => from, getTo: () => to, onFrame: s => frames.push(s), onComplete: s => completions.push(s) };
  const tick = now => { const pending = [...queue.values()]; queue.clear(); pending.forEach(cb => cb(now)); };
  runTransport(options);
  for (let now = 1000; now < 7000; now += 10) tick(now);
  assert.deepEqual([...new Set(frames.map(s => s.phase))], phases);
  assert.deepEqual(completions, [{ aborted: false }]);
  assert.equal(queue.size, 0);
  const carry = frames.filter(s => s.phase === 'carry');
  const switches = carry.flatMap((s, i) => i && s.clipFrame !== carry[i - 1].clipFrame ? [i] : []);
  for (let i = 1; i < switches.length; i++) assert.equal(switches[i] - switches[i - 1], 10, 'poses every 100ms');
  assert.ok(carry.some((s, i) => i && s.clipFrame === carry[i - 1].clipFrame && s.x !== carry[i - 1].x), 'position advances between poses');
  frames = []; completions = [];
  const cancel = runTransport(options); tick(1000); cancel(); tick(1100);
  assert.equal(queue.size, 0); assert.equal(completions.length, 0);
  runTransport({ ...options, getFrom: () => null });
  assert.deepEqual(completions, [{ aborted: true }]);
  completions = [];
  runTransport({ ...options, reducedMotion: true });
  assert.deepEqual(completions, [{ aborted: false }]); assert.equal(queue.size, 0);
  console.log('PASS: phase continuity, lifecycle, 10 FPS, smooth travel, cancellation, missing DOM, reduced motion');
} finally { await rm(dir, { recursive: true, force: true }); }
