# CGC enhancement research: additions for StarFall

Follow-up: [source-verified review and qualification plan](CGC_ENHANCEMENT_REVIEW.md). The review updates the CGC baseline, motion version selection, existing helper inventory, and file contracts.

The strongest additions are automatic character rigging, motion generation, video-based motion capture, and 3D part segmentation. Together, they would extend CGC from producing static assets toward producing characters that move and ships with individually editable components.

This report lists proposed new capabilities only. It reflects a read-only review of CGC's README, plan, code, and the active queue work on 2026-11-11. The queue implementation is still changing, so integration status can change. No candidate below was installed, benchmarked, or qualified for CGC during this research.

| Priority | New capability | Candidate | Why it matters |
|---|---|---|---|
| 1 | Rig an existing character | **SkinTokens / TokenRig** | Gives a static marine a candidate skeleton and skin weights |
| 2 | Generate character motion | **Kimodo** | Produces prototype movement clips from text and constraints |
| 3 | Segment an existing 3D mesh | **GeoSAM2** | Helps isolate parts such as a turret or barrel |
| 4 | Complete segmented 3D parts | **HoloPart** | Attempts to reconstruct complete parts from a segmented object |
| 5 | Capture motion from video | **GEM-X** | Creates motion candidates from acted reference footage |
| 6 | Animate a face from speech | **Audio2Face-3D** | Connects voiced dialogue to facial performance for visible characters |

## 1. Rigging: SkinTokens / TokenRig

**Input:** An existing character mesh.
**Output:** A candidate skeleton and skin weights that can be reviewed and animated.

[SkinTokens](https://github.com/VAST-AI-Research/SkinTokens) is the most promising first addition. Its authors provide pretrained TokenRig and skin-weight tokenizer checkpoints and document a minimum **14 GB NVIDIA GPU** for inference. That is an upstream requirement; actual Beam memory use and cost remain unmeasured. [Installation and checkpoints](https://github.com/VAST-AI-Research/SkinTokens/blob/main/README.md)

For StarFall, this could turn a generated marine into an animation candidate while preserving the existing visual design. The test is not only whether it makes bones, but whether the marine bends correctly around armor, gloves, hips, shoulders, and hands.

**First qualification:** Rig the existing marine and compare it with a manually prepared control. Inspect joint placement, weights, material preservation, export, and deformation in several poses. Then play an animation on the resulting GLB in Bevy.

**Practical limit:** Automatic rigging will still need correction when armor should remain rigid or the predicted skeleton does not match the game's chosen humanoid bone layout. Review the model, weight, dependency, and output terms before onboarding.

## 2. Text-to-motion: Kimodo

**Input:** A motion description, with optional pose or path constraints.
**Output:** Motion for a supported humanoid skeleton.

[Kimodo](https://github.com/nv-tlabs/kimodo) supports text prompts and constraints such as key poses, end-effector positions, and paths. NVIDIA provides a CLI and several model variants. This makes it a candidate for Codex to queue as a specific file-producing operation.

For StarFall, start with idle, walk, run, turn, and crew actions. These can populate a prototype and provide a motion library for comparison. Weapon handling should be a later test: a clip can look plausible while letting a hand drift away from the rifle.

**First qualification:** Generate an idle and walk on a supported skeleton, retarget them to a known-good marine rig, export the clips, and play and blend them in Bevy. Measure foot sliding, loop seams, root movement, and armor deformation.

**Dependencies:** Kimodo's code and checkpoints have separate licenses, and its documented text encoder uses a gated Llama model. Check the selected checkpoint and encoder terms and access independently. [Model table](https://github.com/nv-tlabs/kimodo), [installation](https://github.com/nv-tlabs/kimodo/blob/main/docs/source/getting_started/installation.md)

## 3. Mesh segmentation: GeoSAM2

**Input:** A 3D mesh, rendered views, and a mask prompt.
**Output:** Segmentation information that identifies selected parts of the mesh.

[GeoSAM2](https://github.com/VAST-AI-Research/GeoSAM2) uses information from rendered views to identify parts on a 3D mesh. Its documented inference path expects rendered color, depth and normal views, along with a mask prompt. [GeoSAM2 inference code](https://github.com/VAST-AI-Research/GeoSAM2/blob/main/inference.py)

This is useful for StarFall because a turret, hatch, or engine assembly must be distinguishable from the surrounding hull before it can be edited independently.

**First qualification:** Use a small turret mesh with an obvious base and barrel. Check whether the selected faces match the intended components, including occluded edges, and whether the segmentation survives export into an editable workflow.

**Practical limit:** A segmentation mask does not create a pivot, collision, muzzle socket, or gameplay behavior. Those remain explicit authoring and validation steps.

## 4. Part completion: HoloPart

**Input:** A mesh that has already been segmented into parts.
**Output:** Candidate complete 3D parts.

[HoloPart](https://github.com/VAST-AI-Research/HoloPart) is complementary to segmentation. Its documented workflow starts with a segmented mesh or face mask, then attempts to reconstruct complete parts, including regions hidden by the rest of the object.

This matters when separating a turret from a hull exposes a missing underside, or when one component intersects another. GeoSAM2 and HoloPart are plausible components of the same experiment, but their output and input formats need to be tested together; their combination is not yet established in CGC.

**First qualification:** Compare a segmented turret with and without HoloPart completion. Inspect whether the completed pieces fit together, retain the intended shape, and require less manual repair.

**Practical limit:** The reconstructed hidden geometry is an inference. It may look plausible while being mechanically wrong, so part fit and clearances must be reviewed.

## 5. Video-to-motion: GEM-X

**Input:** A video of a person performing an action, plus the model's required body and camera-processing inputs.
**Output:** Estimated body motion that can be processed and retargeted.

[NVIDIA GEM-X](https://github.com/NVlabs/GEM-X) documents a body-motion inference route for video, including optional contact and inverse-kinematics post-processing. It requires model checkpoints and supporting geometry assets; the output is a motion representation, not an automatically finished StarFall animation.

This would let the team act out movements such as operating a control panel, reacting to an impact, bracing on a ship, or moving through a hatch. It offers a different source of motion from text prompting.

**First qualification:** Record a short, clearly visible action and compare the recovered motion with the footage. Retarget it to the same control rig used for Kimodo, then assess timing, foot contact, occluded limbs, and cleanup time.

**Practical limit:** Camera calibration, occlusion, and post-processing affect the result. Its source, weights, assets, and some adapted components have separate terms that must be checked. [GEM-X documentation and licensing](https://github.com/NVlabs/GEM-X)

## 6. Speech-driven facial animation: Audio2Face-3D

**Input:** Recorded speech and a compatible facial setup.
**Output:** Facial geometry or animation controls, depending on the selected pipeline.

[NVIDIA Audio2Face-3D](https://github.com/NVIDIA/Audio2Face-3D) is relevant if StarFall uses visible characters in briefings, story scenes, or close-range interactions. Its SDK describes generating facial motion from audio and optionally solving that motion to an existing blendshape rig. [SDK documentation](https://github.com/NVIDIA/Audio2Face-3D-SDK/blob/main/docs/README.md)

**First qualification:** Use one short, authorized character line and a face that already has a compatible blendshape setup. Export the generated curves, attach them to the character, and verify playback and synchronization in Bevy.

**Practical limit:** This does not make an unrigged face production-ready. Compatible facial shapes, retargeting, expression review, and export are separate work. Code, models, and deployment packages have different terms. It is lower priority if most infantry faces remain behind helmets.

## Recommended order

1. **SkinTokens:** Establish whether the current marine can be rigged with useful deformation.
2. **Kimodo:** Animate that marine, using a known-good control rig to isolate problems.
3. **GeoSAM2 and HoloPart:** Test a turret through segmentation and part completion.
4. **GEM-X:** Add acted motion once retargeting and playback work.
5. **Audio2Face-3D:** Pursue when a visible-face character and facial rig exist.

Each test should preserve source files and record the exact model version, GPU, load and generation time, output files, defects, and license basis. The decision to add a candidate should follow an actual file-to-processing-to-reviewed-output-to-Bevy-playback test. CGC should expose the real operation rather than a broad promise such as “make game-ready.”
