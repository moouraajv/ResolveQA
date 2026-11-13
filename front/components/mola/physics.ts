export const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));

export const approach = (current: number, target: number, maxDelta: number) =>
  current < target ? Math.min(target, current + maxDelta) : Math.max(target, current - maxDelta);

/** Critically-damped-ish spring toward a 1D target. */
export function spring1d(
  pos: number,
  vel: number,
  target: number,
  dt: number,
  stiffness = 48,
  damping = 14,
) {
  const force = (target - pos) * stiffness - vel * damping;
  const nextVel = vel + force * dt;
  const nextPos = pos + nextVel * dt;
  return { pos: nextPos, vel: nextVel };
}

export function spring2d(
  x: number,
  y: number,
  vx: number,
  vy: number,
  tx: number,
  ty: number,
  dt: number,
  stiffness = 42,
  damping = 12,
) {
  const nx = spring1d(x, vx, tx, dt, stiffness, damping);
  const ny = spring1d(y, vy, ty, dt, stiffness, damping);
  return { x: nx.pos, y: ny.pos, vx: nx.vel, vy: ny.vel };
}

export function limitDelta(seconds: number, max = 0.05) {
  return Math.min(max, Math.max(0, seconds));
}

/** Smoothstep easing for phase timelines. */
export function smoothstep(t: number) {
  const x = clamp(t, 0, 1);
  return x * x * (3 - 2 * x);
}

export function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

export function prefersReducedMotion() {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
