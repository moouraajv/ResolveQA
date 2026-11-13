# Running-right visual review

Selected source: `../../../decoded/running-right.png`.
Selected extraction: `frames-threshold130/running-right/00.png` through `07.png`.
Selected bundled report: `review-threshold130.json`, `ok: true`.

Eight complete separated poses, consistently facing screen-right. Violet rear, blue/cyan/green/yellow/orange intermediate coils, red front with white eyes remain stable. The toy spring arch visibly compresses/expands and the dark attached feet alternate between planted and lifted positions. No guide marks, effects, clipping, or detached pieces observed. Grounded baseline is y=173–174 after shared-scale extraction. Intentional arch height varies; apparent width stays 172–180 pixels. Source and representative extracted frames 00 and 07 were visually inspected.

Commands/results:

- Built-in image generation with canonical base and running-right guide: completed. Original preserved at `<local-home>/.codex/generated_images/01a1b6f3-7311-7051-a988-34bf2355647e/exec-0a370499-75e0-4185-a935-dad5975a17af.png`.
- `extract_strip_frames.py --states running-right --method auto`: exit 0.
- `inspect_frames.py --states running-right --require-components`: exit 1; only chroma-adjacent fringe counts exceeded threshold.
- Re-extraction with `--key-threshold 125`: exit 0; inspection exit 1 (two fringe counts above threshold).
- Re-extraction with `--key-threshold 130`: exit 0; inspection exit 0, no errors or warnings. Violet identity and open coils remain intact on visual inspection.

No bundled scripts or validator limits were edited. No despill pass executed. Final atlas playback and despill belong to parent assembly and are NOT_RUN for this isolated row.
