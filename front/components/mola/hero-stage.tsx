"use client";

import { useEffect, useRef, useState } from "react";
import { Hand, Pause, Play, Sparkles } from "lucide-react";
import { ATLAS, CLIPS, groundAt, type ClipName } from "./atlas";
import { approach, clamp, limitDelta, prefersReducedMotion, spring1d } from "./physics";
import { paintSlinky } from "./slinky";
import { MolaSprite } from "./spring";

type Mode = "idle" | "move" | "wave" | "jump" | "wait" | "fail" | "drag" | "return";

type HeroStageProps = {
  skin: number;
};

const WALK_CAP = 220;
const RUN_CAP = 380;
const ACCEL = 900;
const BRAKE = 1600;
const STOP_EPS = 0.01;
const VEL_EPS = 0.025;
const HOME_X = 0.58;
const EDGE_PAD = 8;

/** Normalized x limits so the full sprite (+ pad) stays inside the playfield. */
export function heroXBounds(fieldWidth: number, size: number) {
  if (fieldWidth <= 0) return { min: HOME_X, max: HOME_X };
  const half = size / 2 + EDGE_PAD;
  let min = half / fieldWidth;
  let max = 1 - min;
  if (min > max) {
    min = 0.5;
    max = 0.5;
  }
  return { min, max };
}

export function heroSpriteSize(fieldWidth: number) {
  return Math.min(210, Math.max(140, fieldWidth * 0.42));
}

export function HeroStage({ skin }: HeroStageProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const playfieldRef = useRef<HTMLDivElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);
  const hitRef = useRef<HTMLButtonElement>(null);
  const spriteWrapRef = useRef<HTMLDivElement>(null);
  const shadowRef = useRef<HTMLSpanElement>(null);
  const state = useRef({
    x: 0.58,
    y: 0,
    vx: 0,
    vy: 0,
    facing: 1 as 1 | -1,
    mode: "idle" as Mode,
    clip: "idle" as ClipName,
    frame: 0,
    clipClock: 0,
    slinkyCycle: 0,
    slinkyStrength: 0,
    /** Active seconds in current mode (pauses do not advance — avoids teleport on resume). */
    modeActive: 0,
    target: null as number | null,
    mouse: false,
    paused: false,
    inView: true,
    pageVisible: true,
    reduced: false,
    drag: null as null | { px: number; py: number; ox: number; oy: number },
    homeX: HOME_X,
  });
  const [paused, setPaused] = useState(false);
  const [live, setLive] = useState(false);
  const raf = useRef(0);

  useEffect(() => {
    const stage = stageRef.current;
    const playfield = playfieldRef.current;
    if (!stage || !playfield) return;
    const s = state.current;
    s.reduced = prefersReducedMotion();
    s.paused = paused;
    s.pageVisible = document.visibilityState === "visible";

    const isActive = () => s.inView && s.pageVisible && !s.paused;

    const measure = () => {
      const rect = playfield.getBoundingClientRect();
      const size = heroSpriteSize(rect.width);
      const { min, max } = heroXBounds(rect.width, size);
      return { rect, size, min, max };
    };

    const clampX = (x: number) => {
      const { min, max } = measure();
      return clamp(x, min, max);
    };

    /** Keep position/target in bounds; never rewrite the canonical home (0.58). */
    const applyBounds = () => {
      s.x = clampX(s.x);
      if (s.target !== null) s.target = clampX(s.target);
    };

    const paint = () => {
      const wrap = spriteWrapRef.current;
      const shadow = shadowRef.current;
      if (!wrap || !playfield) return;
      const { rect, size } = measure();
      // Controls sit in a dedicated dock below the playfield (not an overlay).
      // Floor clears the in-playfield art-label band + 18px so feet/shadow stay visible.
      const labelEl = playfield.querySelector<HTMLElement>(".art-label");
      const labelBand = labelEl ? labelEl.offsetHeight + 8 : 18;
      const scale = size / ATLAS.cellW;
      const ground = groundAt(s.clip, s.frame) * scale;
      const floor = Math.max(ground + 8, rect.height - labelBand - 18);
      const px = s.x * rect.width - size / 2;
      const py = floor - ground + s.y;
      wrap.style.width = `${size}px`;
      wrap.style.height = `${size * (ATLAS.cellH / ATLAS.cellW)}px`;
      wrap.style.transform = `translate3d(${px.toFixed(2)}px, ${py.toFixed(2)}px, 0)`;
      wrap.dataset.clip = s.clip;
      wrap.dataset.facing = String(s.facing);
      if (shadow) {
        shadow.style.transform = `translate3d(${(s.x * rect.width).toFixed(2)}px, ${floor.toFixed(2)}px, 0) translateX(-50%)`;
        shadow.style.opacity = s.mode === "drag" ? "0.2" : "0.45";
      }
      const sprite = wrap.querySelector<HTMLElement>(".mola-sprite");
      if (sprite) {
        const w = size;
        const h = size * (ATLAS.cellH / ATLAS.cellW);
        const def = CLIPS[s.clip];
        const frame = Math.min(s.frame, def.count - 1);
        const index = def.row * ATLAS.columns + frame;
        const col = index % ATLAS.columns;
        const row = Math.floor(index / ATLAS.columns);
        sprite.style.width = `${w}px`;
        sprite.style.height = `${h}px`;
        sprite.style.backgroundSize = `${ATLAS.columns * w}px ${ATLAS.rows * h}px`;
        sprite.style.backgroundPosition = `${-col * w}px ${-row * h}px`;
        sprite.dataset.frame = String(frame);
        sprite.dataset.clip = s.clip;
        const elastic = ["idle", "move", "wait", "return"].includes(s.mode);
        paintSlinky(sprite, elastic ? { cycle: s.slinkyCycle, strength: s.reduced ? 0 : s.slinkyStrength, facing: s.facing } : null);
      }
    };

    const setMode = (mode: Mode, clip?: ClipName) => {
      s.mode = mode;
      s.modeActive = 0;
      s.frame = 0;
      s.clipClock = 0;
      if (clip) s.clip = clip;
      else if (mode === "idle") s.clip = "idle";
      else if (mode === "wave") s.clip = "wave";
      else if (mode === "jump") s.clip = "jump";
      else if (mode === "wait") s.clip = "wait";
      else if (mode === "fail") s.clip = "fail";
      else if (mode === "drag") s.clip = "work";
      else if (mode === "return") s.clip = "fail";
    };

    const pickLocomotion = () => {
      s.clip = "idle"; // Unloaded locomotion is painted as an elastic Slinky.
    };

    /** Cadence scales with speed: walk ~6fps … run ~12fps (same atlas rows). */
    const locoFps = () => {
      const speed = Math.abs(s.vx) * 400;
      return clamp(6 + (speed / RUN_CAP) * 6, 5, 12);
    };

    const steerToTarget = (dt: number) => {
      if (s.target === null) return;
      const dx = s.target - s.x;
      const dist = Math.abs(dx);
      const dir = (Math.sign(dx) || s.facing) as 1 | -1;

      if (dist <= STOP_EPS && Math.abs(s.vx) <= VEL_EPS) {
        s.x = s.target;
        s.vx = 0;
        if (!s.mouse) s.target = null;
        setMode("idle");
        return;
      }

      if (dir !== s.facing && Math.abs(s.vx) > 0.2) {
        s.vx = approach(s.vx, 0, BRAKE * dt / 400);
        if (Math.abs(s.vx) < VEL_EPS) {
          s.vx = 0;
          s.facing = dir;
        }
        s.mode = "move";
        pickLocomotion();
        return;
      }
      s.facing = dir;

      const brakeAccel = BRAKE / 400;
      const speed = Math.abs(s.vx);
      const stopDist = (speed * speed) / (2 * Math.max(brakeAccel, 0.001)) + STOP_EPS;
      let desired: number;
      if (dist < stopDist || dist < 0.1) {
        desired = dir * Math.min(WALK_CAP / 400, dist * 3.2);
      } else {
        const cap = (dist > 0.28 ? RUN_CAP : WALK_CAP) / 400;
        desired = dir * cap;
      }

      const rate = Math.abs(desired) > Math.abs(s.vx) ? ACCEL : BRAKE;
      s.vx = approach(s.vx, desired, rate * dt / 400);

      const next = s.x + s.vx * dt;
      if ((s.vx > 0 && next >= s.target) || (s.vx < 0 && next <= s.target)) {
        s.x = s.target;
        s.vx = 0;
        if (!s.mouse) s.target = null;
        setMode("idle");
        return;
      }
      s.x = clampX(next);
      s.mode = "move";
      pickLocomotion();
    };

    let last = 0;
    const tick = (now: number) => {
      raf.current = requestAnimationFrame(tick);
      if (!isActive()) {
        last = 0;
        return;
      }
      if (!last) last = now;
      const dt = limitDelta((now - last) / 1000);
      last = now;

      if (s.reduced) {
        s.clip = "idle";
        s.frame = 0;
        s.x = clampX(s.homeX);
        s.y = 0;
        paint();
        return;
      }

      s.modeActive += dt;
      const { min: xMin, max: xMax } = measure();
      // Visual return target respects bounds; canonical homeX stays 0.58.
      const homeVisual = clamp(s.homeX, xMin, xMax);

      if (s.mode === "drag") {
        // pointer handlers own x/y
      } else if (s.mode === "return") {
        const springX = spring1d(s.x, s.vx, homeVisual, dt, 55, 14);
        const springY = spring1d(s.y, s.vy, 0, dt, 70, 16);
        s.x = clamp(springX.pos, xMin, xMax);
        s.vx = springX.vel;
        s.y = springY.pos;
        s.vy = springY.vel;
        s.clip = "fail";
        if (Math.abs(s.x - homeVisual) < 0.008 && Math.abs(s.y) < 1.5 && Math.abs(s.vx) < 0.04 && Math.abs(s.vy) < 1) {
          s.x = homeVisual;
          s.y = 0;
          s.vx = 0;
          s.vy = 0;
          setMode("wave", "wave");
        }
      } else if (s.mode === "jump") {
        s.clip = "jump";
        s.y = 0; // hop is drawn as displaced pixels in the atlas cell; py stays on rest ground 201
      } else if (s.mode === "wave") {
        s.clip = "wave";
        if (s.modeActive > CLIPS.wave.count / CLIPS.wave.fps + 0.12) setMode("idle");
      } else if (s.mode === "wait") {
        s.clip = "wait";
        if (s.modeActive > 1.6) setMode("idle");
      } else if (s.mode === "fail") {
        s.clip = "fail";
        if (s.modeActive > 0.9) setMode("idle");
      } else if (s.target !== null) {
        steerToTarget(dt);
      } else if (s.mode === "idle") {
        s.clip = "idle";
        if (!s.mouse && s.modeActive > 4.2) setMode("wait");
      }

      const def = CLIPS[s.clip];
      const fps = s.mode === "move" ? locoFps() : def.fps;
      s.clipClock += dt;
      while (s.clipClock >= 1 / fps) {
        s.clipClock -= 1 / fps;
        if (s.mode === "jump") {
          if (s.frame < def.count - 1) s.frame += 1;
          else {
            s.frame = def.count - 1;
            setMode("idle");
            break;
          }
        } else {
          s.frame = (s.frame + 1) % def.count;
        }
      }
      // Integrate the unloaded gait with the existing RAF and speed controller.
      s.slinkyCycle += dt * 1.25;
      s.slinkyStrength = approach(s.slinkyStrength, s.mode === "move" ? 1 : 0.45, dt * 5);
      paint();
    };

    raf.current = requestAnimationFrame(tick);
    setLive(true);

    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch" || s.drag || s.paused || s.reduced) return;
      const rect = playfield.getBoundingClientRect();
      s.mouse = true;
      s.target = clampX((e.clientX - rect.left) / rect.width);
      if (s.mode === "idle" || s.mode === "wait") {
        s.mode = "move";
        s.modeActive = 0;
      }
    };
    const onLeave = () => {
      s.mouse = false;
    };
    const onDownHit = (e: PointerEvent) => {
      if (s.paused || s.reduced) return;
      if (e.pointerType === "mouse" && e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      hitRef.current?.setPointerCapture(e.pointerId);
      const rect = playfield.getBoundingClientRect();
      s.drag = { px: e.clientX, py: e.clientY, ox: s.x * rect.width, oy: s.y };
      setMode("drag", "work");
    };
    const onMoveHit = (e: PointerEvent) => {
      if (!s.drag) return;
      const rect = playfield.getBoundingClientRect();
      s.x = clampX((s.drag.ox + (e.clientX - s.drag.px)) / rect.width);
      s.y = clamp(s.drag.oy + (e.clientY - s.drag.py), -rect.height * 0.55, 20);
    };
    const onUpHit = (e: PointerEvent) => {
      if (!s.drag) return;
      s.drag = null;
      try { hitRef.current?.releasePointerCapture(e.pointerId); } catch { /* released */ }
      setMode("return", "fail");
    };

    playfield.addEventListener("pointermove", onMove);
    playfield.addEventListener("pointerleave", onLeave);
    const hit = hitRef.current;
    hit?.addEventListener("pointerdown", onDownHit);
    hit?.addEventListener("pointermove", onMoveHit);
    hit?.addEventListener("pointerup", onUpHit);
    hit?.addEventListener("pointercancel", onUpHit);

    const io = new IntersectionObserver(([entry]) => {
      s.inView = entry.isIntersecting;
    }, { threshold: 0.05 });
    io.observe(stage);

    const onVis = () => {
      s.pageVisible = document.visibilityState === "visible";
    };
    document.addEventListener("visibilitychange", onVis);

    const ro = new ResizeObserver(() => {
      applyBounds(); // clamp x/target only — homeX stays 0.58
      paint();
    });
    ro.observe(playfield);
    if (dockRef.current) ro.observe(dockRef.current);
    applyBounds();
    paint();

    return () => {
      cancelAnimationFrame(raf.current);
      playfield.removeEventListener("pointermove", onMove);
      playfield.removeEventListener("pointerleave", onLeave);
      hit?.removeEventListener("pointerdown", onDownHit);
      hit?.removeEventListener("pointermove", onMoveHit);
      hit?.removeEventListener("pointerup", onUpHit);
      hit?.removeEventListener("pointercancel", onUpHit);
      document.removeEventListener("visibilitychange", onVis);
      io.disconnect();
      ro.disconnect();
    };
  }, [paused]);

  useEffect(() => {
    state.current.paused = paused;
  }, [paused]);

  const trigger = (kind: "jump" | "wave") => {
    const s = state.current;
    if (s.paused || s.reduced || s.drag || s.mode === "return" || s.mode === "jump") return;
    s.target = null;
    s.vx = 0;
    s.y = 0;
    s.modeActive = 0;
    s.frame = 0;
    s.clipClock = 0;
    if (kind === "jump") {
      s.mode = "jump";
      s.clip = "jump";
    } else {
      s.mode = "wave";
      s.clip = "wave";
    }
  };

  return (
    <div className={`hero-stage ${live ? "is-live" : ""} ${paused ? "is-paused" : ""}`} ref={stageRef}>
      <div className="hero-playfield" ref={playfieldRef}>
        <div className="art-grid" />
        <div className="art-orbit orbit-one" />
        <div className="art-orbit orbit-two" />
        <span className="pixel-spark spark-one">✦</span>
        <span className="pixel-spark spark-two">+</span>
        <span className="pixel-spark spark-three">+</span>
        <div className="floating-label"><span className="live-dot" /> PRONTA PARA O PRÓXIMO SALTO</div>
        <span className="hero-shadow" ref={shadowRef} aria-hidden="true" />
        <div className="hero-sprite-wrap" ref={spriteWrapRef}>
          <MolaSprite skin={skin} className="hero-spring" width={180} clip="idle" frame={0} />
          <button type="button" className="hero-hitbox" ref={hitRef} aria-label="Arrastar a mola no palco" />
        </div>
        <span className="art-label">100% ESPIRAL. 0% ENROLAÇÃO.</span>
      </div>
      <div className="hero-dock" ref={dockRef}>
        <div className="hero-controls" role="group" aria-label="Controles da mola">
          <button type="button" className="hero-control" onClick={() => trigger("jump")} aria-label="Saltar">
            <Sparkles size={14} /> Saltar
          </button>
          <button type="button" className="hero-control" onClick={() => trigger("wave")} aria-label="Saudar">
            <Hand size={14} /> Saudar
          </button>
          <button
            type="button"
            className="hero-control"
            aria-pressed={paused}
            aria-label={paused ? "Retomar movimento" : "Pausar movimento"}
            onClick={() => setPaused(p => !p)}
          >
            {paused ? <Play size={14} /> : <Pause size={14} />} {paused ? "Retomar" : "Pausar"}
          </button>
        </div>
      </div>
    </div>
  );
}
