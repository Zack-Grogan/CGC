# Real Dominion reference validation

Reviewed 2026-11-12 with the existing StarFall Dominion V2B dreadnought sheet, Qwen Image 2.1 Base, TRELLIS.2 and Blender 5.2.3 LTS.

The test completed, but none of the four raw reconstructions received visual approval. The earlier low-detail fighter fixture established file preservation, worker reuse and import behavior. It did not establish the visual quality required for this complex Dominion reference. No model weights were trained or fine-tuned in either exercise.

## Source and method

The source is `assets/reference/V2/ships/dominion/dominion-dreadnought-v2b.png` in StarFall. It is exploratory art. Its printed statistics and dimensions are not canonical specifications.

Qwen Base isolated one complete ship from the sheet at 2048×1024, 40 steps and seed 73142. The derived image retained the recognizable armored hull and removed the sheet layout. It remained an approximate generated interpretation, including a surviving V2B hull marking. The original sheet remains the visual authority.

TRELLIS received the same isolated image for all four reconstructions. The first pair used seed 73142: draft requested resolution 512, a 1024 texture and 50,000-face export target; detail requested resolution 1024, a 2048 texture and 300,000-face target. Two additional detail candidates used seeds 42 and 43.

Blender supplied fitted material and clay views, reference images, saved projects and geometry/UV inspection. The original pair used shared cameras and lighting without independent rescaling or geometry edits. Later candidate views used the same review method. The initial studio lights were too strong for these metallic materials; those overlit renders remain labeled diagnostic evidence. Lower-energy lighting restored the dark gray and muted warm-trim palette.

## Observed results

| Candidate | Raw triangles | Visual finding | Disposition |
| --- | ---: | --- | --- |
| Draft, seed 73142 | 47,506 | Recognizable hull masses, softened turrets and armor; invented rectangular tray | Rejected |
| Detail, seed 73142 | 290,817 | More turret and armor structure than draft, but softened details and the same invented tray | Rejected |
| Detail, seed 42 | 286,558 | Large rectangular enclosure obscures the ship | Rejected |
| Detail, seed 43 | 287,149 | Folded side plate and floating/intersecting strips | Rejected |

Higher detail improved some visible geometry on the matched pair. It did not remove the incorrect structure. Additional seeds were separate candidates, not evidence that the first defect was repaired. The current single-image route is not qualified to produce final Dominion capital-ship assets automatically.

The source has sharper plate boundaries, distinct elongated turret barrels and narrow deck/bridge recesses. The reconstruction rounds or merges these shapes. Many panel lines and trim details remain texture-led. Clay views expose that distinction. No normal map was generated for the original pair.

## Explicit repairs and CLI changes

Raw draft and detail GLBs also contained zero-area triangles that produced invalid normals. `cgc asset clean` now removes exactly zero-area triangles and unused vertex slots from supported static GLBs. It preserves surviving attribute samples, face winding, images, materials and transforms, then requires an official Khronos pass. It does not fix invented geometry or a wrong design. Both original cleanup derivatives passed with zero errors and warnings.

A separate manual repair removed only the reviewed tray component from the original detail candidate. It retained the other geometry and original material data. The result has 272,838 triangles and passes Khronos validation with zero errors and warnings. It remains a closer starting point with softened geometry; it has no production-art approval. The raw model and repair are saved separately.

`cgc asset render` now exposes `--light-scale`, `--samples` and `--clay`. The studio light multiplier defaults to 0.12 after the real metallic-reference review. Clay uses a neutral material override. These controls change review rendering, not model geometry. A separate artifact-collection fix retries bounded file downloads when the provider manifest is visible before the main file; it never repeats inference.

## Use this workflow for future assets

1. Select an actual project reference and record its status and source hash.
2. Inspect the isolated conditioning image before submitting 3D work.
3. Treat each reconstruction as a candidate. Keep its raw file and receipt.
4. Review fitted Blender material and clay views against the reference. Reject invented objects, damaged silhouettes and unconvincing geometry even when a format validator passes.
5. Apply explicit repairs to separate derivatives and record exactly what changed.
6. Prepare engine derivatives only after visual review. Check the destination engine separately.

The owner specified a five-container GPU ceiling. This experiment used the serialized CGC GPU queue and retained no always-on allocation. The model workers were released after generation. Local Blender rendering used CPU.

Evidence: `outputs/dominion-reference-validation-v1/acceptance.json`, `BLENDER_REVIEW.md`, `candidate-visual-findings.json`, `cleanup-preservation-audit.json` and the saved Blender projects in that directory. The interactive visual review retains the actual source, input, raw failures, clay comparison and separately labeled repair.

The official [TRELLIS preprocessing source](https://github.com/microsoft/TRELLIS.2/blob/main/trellis2/pipelines/trellis2_image_to_3d.py) uses a high-alpha foreground bound and composites RGB with alpha. Faint background alpha alone was not established as the cause of the invented tray. The test does not claim a root cause without evidence.
