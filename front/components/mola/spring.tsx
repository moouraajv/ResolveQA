"use client";

import { useEffect, useState, type CSSProperties } from "react";
import {
  ATLAS,
  ATLAS_SRC,
  CLIPS,
  TRANSPORT_CLIP,
  backgroundPosition,
  backgroundSize,
  type ClipName,
  type TransportPhase,
} from "./atlas";

/** Hue rotations of the same rainbow atlas — index 0 is Arco-íris (unrotated). */
export const skins = [
  { name: "Arco-íris", hue: 0, color: "linear-gradient(135deg,#ff5a5a,#f2c94c,#7fd96a,#45c7e0,#b07af0)" },
  { name: "Tangerina", hue: -22, color: "linear-gradient(135deg,#ff8f3a,#f2c94c,#7fd96a)" },
  { name: "Lavanda", hue: 100, color: "linear-gradient(135deg,#b07af0,#5b8ef0,#ff5a5a)" },
  { name: "Cromo", hue: 155, color: "linear-gradient(135deg,#9aa4b0,#c8d0d8,#e8eef2)" },
  { name: "Fliperama", hue: -48, color: "linear-gradient(135deg,#f2c94c,#ff5a5a,#45c7e0)" },
  { name: "Azul", hue: 175, color: "linear-gradient(135deg,#45c7e0,#5b8ef0,#7fd96a)" },
];

/** @deprecated use TransportPhase — kept for call-site compatibility during migration. */
export type SpringPose = TransportPhase | "idle";

export type MolaSpriteProps = {
  skin?: number;
  className?: string;
  clip?: ClipName;
  frame?: number;
  carrying?: boolean;
  pose?: SpringPose;
  width?: number;
  /** When false, never invent procedural art — empty stage until atlas loads. */
  showPlaceholder?: boolean;
  style?: CSSProperties;
  "aria-label"?: string;
};

function clipFromPose(pose: SpringPose | undefined, carrying: boolean): ClipName {
  if (!pose || pose === "idle") return carrying ? "work" : "idle";
  return TRANSPORT_CLIP[pose];
}

export function MolaSprite({
  skin = 0,
  className = "",
  clip,
  frame = 0,
  carrying = false,
  pose,
  width = 192,
  showPlaceholder = false,
  style,
  "aria-label": ariaLabel,
}: MolaSpriteProps) {
  const [atlasReady, setAtlasReady] = useState(false);
  const palette = skins[skin] ?? skins[0];
  const activeClip = clip ?? clipFromPose(pose, carrying);
  const def = CLIPS[activeClip];
  const safeFrame = ((frame % def.count) + def.count) % def.count;
  const height = Math.round(width * (ATLAS.cellH / ATLAS.cellW));
  const hue = palette.hue;

  useEffect(() => {
    let cancelled = false;
    const img = new Image();
    img.onload = () => { if (!cancelled) setAtlasReady(true); };
    img.onerror = () => { if (!cancelled) setAtlasReady(false); };
    img.src = ATLAS_SRC;
    if (img.complete && img.naturalWidth > 0) queueMicrotask(() => { if (!cancelled) setAtlasReady(true); });
    return () => { cancelled = true; };
  }, []);

  const spriteStyle: CSSProperties = atlasReady
    ? {
        width,
        height,
        backgroundImage: `url(${ATLAS_SRC})`,
        backgroundRepeat: "no-repeat",
        backgroundSize: backgroundSize(width, height),
        backgroundPosition: backgroundPosition(activeClip, safeFrame, width, height),
        imageRendering: "pixelated",
        position: "relative",
        filter: hue === 0 ? undefined : `hue-rotate(${hue}deg)`,
        ...style,
      }
    : {
        width,
        height,
        ...style,
      };

  return (
    <div
      className={`mola-sprite spring-character ${carrying ? "spring-carrying" : ""} ${className}`}
      data-clip={activeClip}
      data-frame={safeFrame}
      data-atlas={atlasReady ? "ready" : "pending"}
      role="img"
      aria-label={ariaLabel ?? `Mola arco-íris ${palette.name}`}
      style={spriteStyle}
    >
      <canvas className="mola-slinky" width={224} height={272} hidden aria-hidden="true"
        style={{ position: "absolute", left: "-8.333333%", top: "-30.769231%", width: "116.666667%", height: "130.769231%", pointerEvents: "none" }} />
      {!atlasReady && showPlaceholder ? <span className="mola-atlas-pending" aria-hidden="true" /> : null}
    </div>
  );
}

/** Back-compat export used by page/moodboard slots. */
export function Spring(props: MolaSpriteProps) {
  return <MolaSprite {...props} />;
}

export type { ClipName, TransportPhase };
