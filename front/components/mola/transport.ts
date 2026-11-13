import { CLIPS, TRANSPORT_CLIP, type TransportPhase } from "./atlas";
import { lerp, limitDelta, prefersReducedMotion, smoothstep } from "./physics";

export type Point = { x: number; y: number };

export type TransportSnapshot = {
  phase: TransportPhase;
  x: number;
  y: number;
  clipFrame: number;
  slinkyCycle?: number;
  facing?: 1 | -1;
  local?: number;
  state?: "IDLE" | "SEEKING_TASK" | "PICKING_TASK" | "CARRYING_TASK" | "DELIVERING_TASK" | "RETURNING";
  progress: number;
  done: boolean;
  aborted?: boolean;
};

type EndpointFns = {
  getHome?: () => Point | null;
  getFrom: () => Point | null;
  getTo: () => Point | null;
};

type TransportOptions = EndpointFns & {
  reducedMotion?: boolean;
  onFrame: (snap: TransportSnapshot) => void;
  onComplete: (info: { aborted: boolean }) => void;
};

const PHASES: { phase: TransportPhase; duration: number }[] = [
  { phase: "seek", duration: 0.8 },
  { phase: "compress", duration: 0.32 },
  { phase: "reach", duration: 0.36 },
  { phase: "carry", duration: 1.15 },
  { phase: "deliver", duration: 0.28 },
  { phase: "celebrate", duration: 0.3 },
  { phase: "return", duration: 0.8 },
  { phase: "idle", duration: 0.1 },
];

const TOTAL = PHASES.reduce((s, p) => s + p.duration, 0);

type Waypoints = {
  home: Point;
  start: Point;
  afterCompress: Point;
  afterReach: Point;
  afterCarry: Point;
  landed: Point;
};

/**
 * Shared joints eliminate the measured 6 / 24 / 8 / 14 px discontinuities:
 * compress↔reach, reach↔carry, carry↔deliver, deliver↔celebrate.
 */
export function buildWaypoints(from: Point, to: Point, home: Point = from): Waypoints {
  const dx = to.x - from.x;
  return {
    home,
    start: { x: from.x, y: from.y },
    afterCompress: { x: from.x, y: from.y + 6 },
    afterReach: { x: from.x + dx * 0.08, y: from.y - 14 },
    afterCarry: { x: to.x, y: to.y - 8 },
    landed: { x: to.x, y: to.y },
  };
}

function lerpPoint(a: Point, b: Point, t: number): Point {
  return { x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) };
}

function phaseAt(elapsed: number) {
  let t = elapsed;
  for (const step of PHASES) {
    if (t <= step.duration) return { ...step, local: clamp01(t / step.duration) };
    t -= step.duration;
  }
  const last = PHASES[PHASES.length - 1];
  return { ...last, local: 1 };
}

function clamp01(t: number) {
  return Math.min(1, Math.max(0, t));
}

export function samplePath(wp: Waypoints, phase: TransportPhase, local: number): Point {
  const u = smoothstep(local);
  if (phase === "seek") return lerpPoint(wp.home, wp.start, u);
  if (phase === "return") return lerpPoint(wp.landed, wp.home, u);
  if (phase === "idle") return wp.home;
  if (phase === "compress") return lerpPoint(wp.start, wp.afterCompress, u);
  if (phase === "reach") return lerpPoint(wp.afterCompress, wp.afterReach, u);
  if (phase === "carry") {
    const p = lerpPoint(wp.afterReach, wp.afterCarry, u);
    // Arc vanishes at endpoints → C0 at carry joints (removes the old ~24px snap).
    p.y -= Math.sin(u * Math.PI) * 4;
    return p;
  }
  if (phase === "deliver") return lerpPoint(wp.afterCarry, wp.landed, u);
  // Celebrate starts on landed (fixes old 14px drop-in); bounce amplitude 0 at ends.
  const bounce = Math.sin(local * Math.PI) * 16 * (1 - local);
  return { x: wp.landed.x, y: wp.landed.y - bounce };
}

/**
 * Single RAF transport. Endpoints re-read each frame so scroll/resize stay coherent;
 * missing DOM → safe abort (caller commits, hides layer, clears lock).
 */
export function runTransport(opts: TransportOptions) {
  const reduced = opts.reducedMotion ?? prefersReducedMotion();
  let raf = 0;
  let last = 0;
  let elapsed = 0;
  let clipClock = 0;
  let frame = 0;
  let stopped = false;
  let phaseFrameBase = 0;
  let lastPhase: TransportPhase | null = null;


  const finish = (aborted: boolean) => {
    if (stopped) return;
    stopped = true;
    cancelAnimationFrame(raf);

    opts.onComplete({ aborted });
  };



  const emit = (snap: TransportSnapshot) => {
    if (!stopped) opts.onFrame(snap);
  };

  const from0 = opts.getFrom();
  const to0 = opts.getTo();
  if (reduced || !from0 || !to0) {
    const p = to0 ?? from0 ?? { x: 0, y: 0 };
    emit({ phase: "celebrate", x: p.x, y: p.y, clipFrame: 0, progress: 1, done: true, aborted: !to0 && !from0 });
    opts.onComplete({ aborted: !from0 || !to0 });
    return () => { stopped = true; };
  }



  const tick = (now: number) => {
    if (stopped) return;
    if (opts.reducedMotion === undefined && prefersReducedMotion()) {
      finish(false);
      return;
    }
    if (!last) last = now;
    const dt = limitDelta((now - last) / 1000);
    last = now;

    const from = opts.getFrom();
    const to = opts.getTo();
    if (!from || !to) {
      finish(true);
      return;
    }

    const wp = buildWaypoints(from, to, opts.getHome?.() ?? from);
    elapsed += dt;
    clipClock += dt;

    if (elapsed >= TOTAL) {
      const clip = TRANSPORT_CLIP.idle;
      const end = samplePath(wp, "idle", 1);
      emit({
        phase: "idle",
        state: "IDLE",
        x: end.x,
        y: end.y,
        clipFrame: CLIPS[clip].count - 1,
        progress: 1,
        done: true,
      });
      finish(false);
      return;
    }

    const { phase, local } = phaseAt(elapsed);
    if (phase !== lastPhase) {
      lastPhase = phase;
      phaseFrameBase = frame;
      clipClock = 0;
    }
    const clip = TRANSPORT_CLIP[phase];
    const walking = phase === "carry";
    const fps = walking ? 10 : CLIPS[clip].fps;
    while (clipClock >= 1 / fps) {
      clipClock -= 1 / fps;
      frame += 1;
    }

    const pos = samplePath(wp, phase, local);
    emit({
      phase,
      local,
      slinkyCycle: local, // Eight distinct poses over the 0.8-second unloaded leg.
      state: phase === "seek" ? "SEEKING_TASK" : phase === "carry" ? "CARRYING_TASK" : phase === "return" ? "RETURNING" : phase === "idle" ? "IDLE" : phase === "compress" || phase === "reach" ? "PICKING_TASK" : "DELIVERING_TASK",
      facing: (phase === "seek" ? from.x - wp.home.x : phase === "return" ? wp.home.x - to.x : to.x - from.x) < 0 ? -1 : 1,
      x: pos.x,
      y: pos.y,
      clipFrame: (frame - phaseFrameBase) % CLIPS[clip].count,
      progress: elapsed / TOTAL,
      done: false,
    });

    raf = requestAnimationFrame(tick);
  };

  raf = requestAnimationFrame(tick);

  return () => {
    stopped = true;
    cancelAnimationFrame(raf);

  };
}

