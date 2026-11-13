# Failed visual review

Selected source: `../../../decoded/failed.png`.
Selected extraction: `frames-threshold128/failed/00.png` through `07.png`.
Selected report: `review-threshold128.json`, `ok: true`.

Eight complete separated poses. The rainbow spring reacts, slouches, compresses into a sad closed-eye sag, then recovers. Open delicate coils and violet-rear to red-front order are preserved. White eyes stay attached to the right red coil. No symbols, effects, props, clipping, or detached parts observed. The foot baseline is exactly y=175 for all extracted frames; width stays 177–180 pixels. Height changes are intentional elastic sag. Full strip plus representative extracted frames 00 and 03 were visually inspected.

Generation: built-in imagegen, grounded in canonical-base.png and failed layout guide. Original preserved at `<local-home>/.codex/generated_images/01a1b6f3-7311-7051-a988-34bf2355647e/exec-a95672a6-85b9-4269-995f-efc6c4fd532a.png`.

Bundled extract/inspect outcomes:

| Key threshold | Extract exit | Inspect exit | Result |
| --- | ---: | ---: | --- |
| 96 default | 0 | 1 | chroma fringe counts only |
| 130 | 0 | 0 | pass |
| 125 | 0 | 1 | fringe counts frames 06/07 |
| 128 selected | 0 | 0 | pass, no errors or warnings |
| 127 | 0 | 1 | frame 06 has 811 chroma-adjacent pixels |

128 is the smallest passing integer threshold between 125 and 130. Visual inspection confirms violet coils remain present. No validator/script limits changed; no despill executed. Final atlas playback is NOT_RUN within this isolated row task.
