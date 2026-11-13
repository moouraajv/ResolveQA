"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";
import { ATLAS, CLIPS, TRANSPORT_CLIP, grabAt, type ClipName } from "./atlas";
import { paintSlinky, walkGrab } from "./slinky";
import { smoothstep } from "./physics";
import type { TransportSnapshot } from "./transport";
import { MolaSprite, skins } from "./spring";

export type TransportHandle = {
  show: (task: { id: string; title: string }, skin: number) => void;
  paint: (snap: Pick<TransportSnapshot, "phase" | "x" | "y" | "clipFrame" | "facing" | "local" | "state" | "slinkyCycle">) => void;
  hide: () => void;
};

type GrabState = { x: number; y: number; clip: string; frame: number };

/**
 * Path (x,y) = world grab/card anchor (top of coil). Sprite offset so atlas grab
 * coincides with the card. Grab eases across clip changes to avoid card snaps.
 */
export const TransportLayer = forwardRef<TransportHandle>(function TransportLayer(_, ref) {
  const rootRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const idRef = useRef<HTMLSpanElement>(null);
  const titleRef = useRef<HTMLElement>(null);
  const spriteHost = useRef<HTMLDivElement>(null);
  const grabSmooth = useRef<GrabState | null>(null);

  useImperativeHandle(ref, () => ({
    show(task, skin) {
      grabSmooth.current = null;
      const root = rootRef.current;
      if (!root) return;
      root.hidden = false;
      if (cardRef.current) cardRef.current.hidden = true;
      if (idRef.current) idRef.current.textContent = task.id;
      if (titleRef.current) titleRef.current.textContent = task.title;
      const sprite = spriteHost.current?.querySelector<HTMLElement>(".mola-sprite");
      if (sprite) {
        const hue = skins[skin]?.hue ?? 0;
        sprite.style.filter = hue === 0 ? "none" : `hue-rotate(${hue}deg)`;
      }
    },
    paint(snap) {
      const root = rootRef.current;
      if (!root || root.hidden) return;
      root.style.left = `${snap.x}px`;
      root.style.top = `${snap.y}px`;
      root.dataset.phase = snap.phase;

      root.dataset.state = snap.state ?? "IDLE";
      const walking = snap.phase === "carry";
      const clip: ClipName = walking ? (snap.facing === -1 ? "runLeft" : "runRight") : TRANSPORT_CLIP[snap.phase];
      const def = CLIPS[clip];
      const frame = ((snap.clipFrame % def.count) + def.count) % def.count;
      const w = 128;
      const h = Math.round(w * (ATLAS.cellH / ATLAS.cellW));
      const scale = w / ATLAS.cellW;
      const loadFrame = walking ? snap.clipFrame : 1;
      const loaded = ["reach", "carry", "deliver"].includes(snap.phase);
      const [tx, ty] = loaded ? walkGrab(loadFrame) : grabAt(clip, frame);

      let gx = tx;
      let gy = ty;
      const prev = grabSmooth.current;
      if (prev && (prev.clip !== clip || Math.abs(prev.y - ty) > 10 || Math.abs(prev.x - tx) > 4)) {
        // Cross-clip / large grab jump: ease toward new anchor (~1 frame at 60fps ≈ 0.22 blend keeps C0 feel).
        const blend = 0.28;
        gx = prev.x + (tx - prev.x) * blend;
        gy = prev.y + (ty - prev.y) * blend;
      } else if (prev) {
        const blend = 0.55;
        gx = prev.x + (tx - prev.x) * blend;
        gy = prev.y + (ty - prev.y) * blend;
      }
      grabSmooth.current = { x: gx, y: gy, clip, frame };

      if (spriteHost.current) {
        // Keep the sprite's floor fixed; the load follows the animated top coil.
        spriteHost.current.style.transform = `translate(${-96 * scale}px, ${-43 * scale}px)`;
      }
      const sprite = spriteHost.current?.querySelector<HTMLElement>(".mola-sprite");
      if (sprite) {
        const index = def.row * ATLAS.columns + frame;
        const col = index % ATLAS.columns;
        const row = Math.floor(index / ATLAS.columns);
        sprite.style.width = `${w}px`;
        sprite.style.height = `${h}px`;
        sprite.style.backgroundSize = `${ATLAS.columns * w}px ${ATLAS.rows * h}px`;
        sprite.style.backgroundPosition = `${-col * w}px ${-row * h}px`;
        sprite.dataset.clip = clip;
        sprite.dataset.frame = String(frame);
        const unloaded = ["seek", "return", "idle", "celebrate", "compress"].includes(snap.phase);
        const moving = snap.phase === "seek" || snap.phase === "return";
        const local = snap.local ?? 0;
        const strength = moving ? Math.sin(Math.PI * local) ** 0.4 : snap.phase === "compress" ? 0.16 * (1 - smoothstep(local)) : 0;
        paintSlinky(sprite, unloaded ? { cycle: moving ? (snap.slinkyCycle ?? 0) : 0, strength, facing: snap.facing ?? 1 } : null, unloaded ? undefined : loadFrame, snap.facing ?? 1);
      }

      if (cardRef.current) {
        cardRef.current.hidden = ["seek", "return", "idle", "celebrate"].includes(snap.phase);
        const rot = snap.phase === "carry" ? -4 : snap.phase === "reach" ? -8 : 0;
        cardRef.current.style.transform = `translate(-50%, -100%) translate(${((gx - 96) * scale).toFixed(2)}px, ${((gy - 43) * scale).toFixed(2)}px) rotate(${rot}deg)`;
        cardRef.current.style.opacity = snap.phase === "compress" ? String((snap.local ?? 0) * 0.75) : "1";
      }
    },
    hide() {
      grabSmooth.current = null;
      const root = rootRef.current;
      if (root) root.hidden = true;
    },
  }));

  return (
    <div className="transport" ref={rootRef} aria-hidden="true" hidden>
      <div className="transport-card" ref={cardRef}>
        <span ref={idRef} />
        <strong ref={titleRef} />
      </div>
      <div className="transport-sprite" ref={spriteHost}>
        <MolaSprite skin={0} width={128} pose="carry" frame={0} carrying />
      </div>
    </div>
  );
});
