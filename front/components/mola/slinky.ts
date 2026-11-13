import { ATLAS_SRC } from "./atlas";

export const SLINKY_SHEET = {
  src: "/mascot/mola-rainbow/slinky-poses-feet-v2.webp",
  columns: 4, rows: 2, cellW: 384, cellH: 512, count: 8, fps: 10,
} as const;
export const WALK_SHEET = { ...SLINKY_SHEET, src: "/mascot/mola-rainbow/walk-poses-v2.webp" } as const;
const WALK_GROUNDS = [470, 470, 470, 470, 449, 449, 449, 449];
const WALK_TOPS = [240, 237, 230, 221, 221, 227, 218, 211];
export function walkGrab(frame: number): [number, number] {
  const i = ((frame % 8) + 8) % 8;
  return [96, 179 + (WALK_TOPS[i] - WALK_GROUNDS[i]) * 0.5 + 4];
}
export type SlinkyPose = { cycle: number; strength: number; facing: 1 | -1 };

export function slinkyFrame(cycle: number) {
  return ((Math.floor(cycle * SLINKY_SHEET.count) % SLINKY_SHEET.count) + SLINKY_SHEET.count) % SLINKY_SHEET.count;
}

const images = new Map<string, HTMLImageElement>();

/** Select a newly drawn pose. No strip deformation, squash, or procedural hop. */
export function paintSlinky(host: HTMLElement, pose: SlinkyPose | null, walkFrame?: number, facing: 1 | -1 = 1) {
  const canvas = host.querySelector<HTMLCanvasElement>(".mola-slinky");
  if (!canvas) return;
  if (!pose && walkFrame === undefined) {
    canvas.hidden = true;
    host.style.backgroundImage = `url(${ATLAS_SRC})`;
    host.dataset.locomotion = "walk";
    delete host.dataset.slinkyFrame;
    return;
  }
  // Warm both sheets before pickup so switching to carrying does not wait on I/O.
  for (const src of [SLINKY_SHEET.src, WALK_SHEET.src]) {
    if (!images.has(src)) { const img = new Image(); img.src = src; images.set(src, img); }
  }
  const source = pose ? SLINKY_SHEET.src : WALK_SHEET.src;
  let image = images.get(source);
  if (!image) { image = new Image(); image.src = source; images.set(source, image); }
  if (!image.complete || !image.naturalWidth) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const frame = pose ? (pose.strength === 0 ? 0 : slinkyFrame(pose.cycle)) : ((walkFrame! % 8) + 8) % 8;
  const direction = pose?.facing ?? facing;
  const ground = pose ? (frame < 4 ? 470 : 472) : WALK_GROUNDS[frame];
  canvas.hidden = false;
  host.style.backgroundImage = "none";
  host.dataset.locomotion = pose ? "slinky" : "walk";
  host.dataset.poseFrame = String(frame);
  if (pose) host.dataset.slinkyFrame = String(frame);
  else delete host.dataset.slinkyFrame;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.translate(16 + (direction < 0 ? 192 : 0), 64);
  ctx.scale(direction, 1);
  ctx.imageSmoothingEnabled = false;
  // One fixed scale and baseline for every pose. Motion comes from the artwork.
  ctx.drawImage(image, (frame % 4) * 384, Math.floor(frame / 4) * 512,
    384, 512, 0, 179 - ground * 0.5, 192, 256);
  ctx.restore();
}
