# Mola transport

The board keeps its existing task commit and locking behavior. Transport adds a
toolbar-relative home, seeking and return legs. The existing directional atlas
rows drive walking, preserving the rainbow artwork. A single RAF owns the timeline.
Walking poses advance every 100 ms; position updates on every animation frame.
The sprite floor stays anchored while the card follows its calibrated top coil.

Transport states are exposed in `data-state`: IDLE, SEEKING_TASK, PICKING_TASK,
CARRYING_TASK, DELIVERING_TASK and RETURNING. Legacy phase names remain available
for existing consumers. Delivery is committed after the delivery phase, once.
Cancellation clears RAF without committing; missing DOM uses the board's existing
completion fallback. Reduced motion skips transport, including preference changes.

Run `node --experimental-strip-types scripts/test-mola-transport.mjs` on Node 22.13+.
Tests cover phase continuity, pose timing independent of travel, complete lifecycle,
cancellation, missing elements and reduced motion without extra dependencies.

Unloaded motion selects eight individually drawn frames from
`public/mascot/mola-rainbow/slinky-poses-feet-v2.webp` (1536x1024, 4x2 cells).
The sequence depicts compression, front-end reach, full arch, lifted rear end,
rollover, closing arch, landing and recovery. Every pose includes the mascot's
feet attached to the corresponding spring ends, including airborne ends.
The face and rainbow identity remain. Art was created with built-in ImageGen
using the original atlas and the user's moodboard as references. The WebP is a
lossless encoding of the generated transparent PNG.

`paintSlinky` draws one complete cell at a fixed scale and baseline. It no longer
warps strips of an idle frame or calculates hops/squash. Only facing is mirrored.
The hero and 0.8-second seeking/returning legs select eight poses at 10 FPS.
Carrying uses eight new walking poses from `walk-poses-v2.webp` at 10 FPS,
created using the approved Slinky sheet as the art reference. Pickup and delivery
also use this matching walking art. Both sheets share a calibrated foot baseline;
the card follows each walking pose's measured top-coil anchor. Reduced
motion freezes the hero and skips task transport. No new runtime dependencies.

Validation: TypeScript, targeted lint, build and timeline tests passed. Chrome
checks cover desktop, mobile, reduced motion and correct unloaded/carrying mode
transitions with no page errors.
