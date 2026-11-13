/** Atlas contract — ground/grab calibrated from alpha bbox on atlas.png (Codex measure pass). */
export const ATLAS_SRC = "/mascot/mola-rainbow/atlas.png";

export const ATLAS = {
  src: ATLAS_SRC,
  width: 1536,
  height: 1872,
  columns: 8,
  rows: 9,
  cellW: 192,
  cellH: 208,
} as const;

export type ClipName =
  | "idle"
  | "runRight"
  | "runLeft"
  | "wave"
  | "jump"
  | "fail"
  | "wait"
  | "work"
  | "review";

export type ClipDef = {
  row: number;
  count: number;
  fps: number;
  /** Rest/land ground for hero foot anchoring (cell px from top). */
  ground: number;
  /**
   * Per-frame alpha-bbox ground — QA metadata only.
   * Do NOT use for hero py: jump frame2 already rises ~58px inside the cell;
   * anchoring each frame to grounds[] flattens the leap onto the floor.
   */
  grounds?: number[];
  /** Default grab [x,y] — card rests on top of the coil (no extra hands). */
  grab: [number, number];
  /** Per-frame grab y measured as bbox-top+8; x stays 96 unless overridden. */
  grabs?: [number, number][];
};

const gx = (ys: number[]): [number, number][] => ys.map(y => [96, y] as [number, number]);

/**
 * Nine rows / 57 frames. Ground + grab from alpha bbox calibration.
 * Jump: fr0+4 ground 201; air 179/143/169 preserved in-cell (no second procedural hop).
 */
export const CLIPS: Record<ClipName, ClipDef> = {
  idle: {
    row: 0, count: 6, fps: 6, ground: 179, grab: [96, 47],
    grabs: gx([47, 37, 47, 47, 47, 47]),
  },
  runRight: {
    row: 1, count: 8, fps: 12, ground: 174, grab: [96, 43],
    grabs: gx([43, 54, 60, 43, 42, 52, 60, 42]),
  },
  runLeft: {
    row: 2, count: 8, fps: 12, ground: 174, grab: [96, 43],
    grabs: gx([43, 54, 60, 43, 42, 52, 60, 42]),
  },
  wave: {
    row: 3, count: 4, fps: 8, ground: 174, grab: [96, 45],
    grabs: gx([45, 43, 42, 47]),
  },
  jump: {
    // Anchor always 201 (rest/land). Air height is drawn in-atlas (fr2 ≈ −58px).
    row: 4, count: 5, fps: 10, ground: 201,
    grounds: [201, 179, 143, 169, 201], // QA measure only — not used by groundAt()
    grab: [96, 82],
    grabs: gx([82, 49, 15, 39, 73]),
  },
  fail: {
    row: 5, count: 8, fps: 10, ground: 175, grab: [96, 41],
    grabs: gx([41, 46, 59, 78, 78, 61, 46, 41]),
  },
  wait: {
    row: 6, count: 6, fps: 5, ground: 175, grab: [96, 47],
    grabs: gx([47, 46, 41, 41, 46, 48]),
  },
  work: {
    row: 7, count: 6, fps: 9, ground: 175, grab: [96, 54],
    grabs: gx([54, 59, 67, 57, 41, 54]),
  },
  review: {
    row: 8, count: 6, fps: 8, ground: 173, grab: [96, 42],
    grabs: gx([42, 45, 50, 49, 42, 42]),
  },
};

export type TransportPhase = "idle" | "seek" | "compress" | "reach" | "carry" | "deliver" | "celebrate" | "return";

export const TRANSPORT_CLIP: Record<TransportPhase, ClipName> = {
  idle: "idle",
  seek: "runRight",
  return: "runLeft",
  compress: "wait",
  reach: "work",
  carry: "runRight",
  deliver: "work",
  celebrate: "review",
};

export function frameIndex(clip: ClipName, frame: number) {
  const def = CLIPS[clip];
  const f = ((frame % def.count) + def.count) % def.count;
  return def.row * ATLAS.columns + f;
}

/** Foot anchor for paint. Always rest ground — never per-frame grounds (cancels drawn hop). */
export function groundAt(clip: ClipName, _frame?: number) {
  return CLIPS[clip].ground;
}

export function grabAt(clip: ClipName, frame: number): [number, number] {
  const def = CLIPS[clip];
  const f = ((frame % def.count) + def.count) % def.count;
  return def.grabs?.[f] ?? def.grab;
}

export function backgroundPosition(clip: ClipName, frame: number, displayW: number, displayH: number) {
  const index = frameIndex(clip, frame);
  const col = index % ATLAS.columns;
  const row = Math.floor(index / ATLAS.columns);
  return `${-(col * displayW)}px ${-(row * displayH)}px`;
}

export function backgroundSize(displayW: number, displayH: number) {
  return `${ATLAS.columns * displayW}px ${ATLAS.rows * displayH}px`;
}

