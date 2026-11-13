# CGC enhancement review

Reviewed 2026-11-11 against the current CGC code, local image-to-3dlab helpers, and upstream source snapshots. This supplements [CGC_ENHANCEMENT_RESEARCH.md](CGC_ENHANCEMENT_RESEARCH.md). No candidate environment, weights, or GPU job was installed or run for this review.

Implementation update, 2026-11-12: the remote CLI routes and StarFall qualification runs are now recorded in [ENHANCEMENT_SETUP.md](ENHANCEMENT_SETUP.md). The original source-review findings below describe the earlier review scope.

## Decision

Keep the shortlist. Start with a **rigging and retargeting qualification**, using SkinTokens and the existing image-to-3dlab retargeting code. Make a known-good skeleton, bind pose, coordinate system, and animation-export contract the first deliverable. A motion generator cannot compensate for an incorrect rig mapping.

Run the segmentation experiment as a separate workstream when editable ship components become the priority. HoloPart should be conditional on a demonstrated need for missing part surfaces. Keep video capture and facial animation behind the corresponding body and facial rig contracts.

These are engineering recommendations from the source review, not measured winners.

## Corrections and additions to the original report

1. **Update the CGC baseline.** The original report describes a queue under construction. CGC 0.2.0 now has a tested remote generation queue and file-based adapters. These enhancements need new operation schemas and isolated workers, not a new workflow orchestrator. See [the current acceptance record](IMPLEMENTATION_STATUS.md).
2. **Separate prediction, binding, and retargeting.** SkinTokens is the skin-weight representation; TokenRig is the rigging model built around it. Skeleton prediction, skin weighting on a supplied skeleton, and motion retargeting are distinct operations.
3. **Do not build the retargeter twice.** `image-to-3dlab/scripts/kimodo_retarget.py` and its tests already exist. The script explicitly maps SOMA77 motion to inferred SkinTokens bone trees. Its presence and source assertions do not qualify every new mesh or current checkpoint; inspect and test it on the chosen pair before extending it.
4. **Specify motion model versions.** Kimodo now lists SOMA-RP-v1.2 variants and a 77-joint SOMA contract. Its release notes distinguish corrected benchmark splits from earlier releases. Do not select an unspecified Kimodo model or treat earlier benchmark figures as interchangeable. [Kimodo source](https://github.com/nv-tlabs/kimodo).
5. **Segmentation needs a real prompt.** A phrase such as “select the turret” is not the documented GeoSAM2 mesh-inference interface. The wrapper needs rendered views and a selected-view mask, or the separate point-prompt preparation route.
6. **Import success is insufficient for animation.** CGC's current GLB checks record skin/animation counts, but cannot establish correct bone mapping, deformation, root motion, or facial synchronization.

## Candidate findings

### SkinTokens / TokenRig: first model experiment

Upstream provides both rig prediction and skinning using an existing skeleton. The documented `--use_transfer` path preserves source texture and scale; it must be enabled and verified for the game-asset test. The demo also starts a separate `bpy_server.py`, so its CLI is not simply one resident Torch call. [README and command modes](https://github.com/VAST-AI-Research/SkinTokens), [demo implementation](https://github.com/VAST-AI-Research/SkinTokens/blob/273b691d35989d71cd17ff2895fdc735097b92d1/demo.py).

The checkpoint card identifies two required checkpoints and declares a 14 GB NVIDIA memory requirement. Its license metadata is MIT. This supports an initial 4090/5090 qualification target, not a claim that every mesh or worker build fits. [Checkpoint card](https://huggingface.co/VAST-AI/SkinTokens).

Test two modes independently: infer a rig, and skin a mesh with a supplied skeleton. Compare both with a manually corrected/Rigify control. Preserve mesh/material identity, source scale, and bind transforms. Require normalized weights, bounded influences, no invalid joint indices, and deformation poses that expose shoulders, hips, elbows, knees, hands, and rigid armor. A present `skins` array alone does not pass.

### Kimodo: select a skeleton and checkpoint first

Use SOMA-RP-v1.2 as the initial candidate. Upstream distinguishes the regular and ARDY-representation variants, so choose one representation explicitly. The default output is an NPZ motion package, not a character GLB. Its README documents approximately 17 GB GPU memory with the text encoder, or reduced GPU use with CPU text encoding. These are upstream figures, not Beam measurements. [Model table, representations, output schema, and memory notes](https://github.com/nv-tlabs/kimodo).

The local encoder depends on gated Llama-3 weights, independently of the motion checkpoint. The pinned loader selects an LLM2Vec encoder with McGill adapter repositories; those adapter repositories are public, but do not contain the complete base weights. It also supports an explicit encoder API mode and an injected encoder. Compatible cached features can bypass per-job text encoding through the low-level sampling path. This avoids repeated loading for known prompts, not the need to obtain compatible features for new prompts. Cache approved encoder assets remotely and keep the access token in Beam secrets. [Installation requirements](https://github.com/nv-tlabs/kimodo/blob/e1c219c99b4b94ba48be1fb6a1cbc64ecee4c954/docs/source/getting_started/installation.md).

Qualification must validate the exact NPZ field meanings against the existing retargeter. Do not assume equal joint counts imply equal rotations, rest poses, or root conventions. Retarget a known clip first; then test generated idle/walk clips, foot contact, loop seams, and root versus in-place playback in Bevy. Keep checkpoint-specific license labels distinct, especially the SMPL-X route.

### GeoSAM2: a useful prompted segmentation operation

The documented path renders 12 color/depth/normal views with camera metadata. A separate utility can turn point prompts into a 2D label map. Mesh inference propagates a selected mask and lifts labels to the mesh. This is a concrete candidate for file-based CLI integration. [Rendering and prompt workflow](https://github.com/VAST-AI-Research/GeoSAM2), [inference implementation](https://github.com/VAST-AI-Research/GeoSAM2/blob/b5de23c60ab487d407b623d394a1614f9714761c/inference.py).

Keep render metadata, mesh fingerprints, and the face-index mapping together. Test a simple two-part asset with known labels, then the generated turret/hull case. Preserve unselected geometry, UVs, materials, and transforms during the deterministic split. Score visible and occluded selections separately. No measured VRAM or throughput claim is established here.

### HoloPart: add only when splitting exposes a problem

HoloPart's example converts face labels into separate submeshes before inference. Its input code iterates scene geometry and samples/normalizes parts; that is a stronger format requirement than “any segmented GLB.” The example also downloads weights automatically. [Preparation and invocation](https://github.com/VAST-AI-Research/HoloPart), [input implementation](https://github.com/VAST-AI-Research/HoloPart/blob/48dd632c9a7412e6688573bb4f153e0ade7e7325/scripts/inference_holopart.py).

Build a deterministic adapter from GeoSAM2 labels to that scene representation. Verify face identity after loading, node transforms, component IDs, scale, and assembly placement. Do not assume masks remain valid after mesh reordering or that new geometry retains original UVs/materials. Compare source splits against completed parts for fit, topology, and cleanup effort. If the source component is already complete, prefer the unchanged split.

### GEM-X: choose temporal Body Motion explicitly

Current GEM-X separates Body Pose, Hand Pose, and temporal Body Motion. Framewise `pose-video` is not the temporal `motion-video` route. The original report's video-motion idea is sound, but the adapter must select the correct model and mode. [Mode table](https://github.com/NVlabs/GEM-X).

The Native77 route requires matching pose/motion assets, keypoint observations, and detection inputs; SOMA geometry is needed for the relevant reconstruction/postprocessing steps. The repository publishes task-specific checkpoint and detector requirements. [Checkpoint requirements](https://github.com/NVlabs/GEM-X/blob/4aef1452e5df171deff4f293c08e643eb450981e/docs/PRETRAINED_MODELS.md).

Start after the body retargeting path works. Use a short authorized video with a visible full body and fixed camera. Retain camera/timing assumptions, confidence/occlusion information, and contact processing. Compare the recovered action with the footage and a manually checked clip. Shared SOMA naming does not by itself prove compatibility with the selected Kimodo representation.

### Audio2Face-3D: valuable after a facial rig exists

The SDK produces facial geometry and related motion; a solver can derive blendshape weights for a compatible setup. It does not create a production face rig from an arbitrary marine GLB. [SDK architecture and outputs](https://github.com/NVIDIA/Audio2Face-3D-SDK/blob/1ca0f02535ed774f5dbcd724a31cd486368dc783/docs/README.md).

Its build documentation specifies a distinct CUDA/TensorRT toolchain and older Python tooling for dependencies/downloads. Treat this as its own worker image, not another package in CGC's current Torch image. TensorRT engines also need explicit GPU/runtime compatibility. Scope the selected models instead of invoking a generic fetch-all script. [Build requirements and gated-model setup](https://github.com/NVIDIA/Audio2Face-3D-SDK).

First test one existing CGC speech WAV against a known blendshape rig. Preserve sample-to-frame timing, neutral pose, channel names, jaw/eye behavior, and clip duration through GLB export and Bevy playback. Verify morph-target animation support and the actual mesh/channel mapping. Keep lower priority while the relevant characters remain helmeted.

## Existing local work to reuse

Inspected under `/Users/zgrogan/Repos/image-to-3dlab`:

- `scripts/kimodo_retarget.py`: SOMA77 mapping, root-height scaling, grounding, and loop processing.
- `tests/test_kimodo_retarget.py`: source tests for tree mapping, rotations, root travel, and grounding/loop behavior.
- `scripts/blender_bind_rig.py`: Rigify binding through a voxel proxy, with scale and transform safeguards.
- `scripts/rig_check.py`, `blender_split_regions.py`, and `blender_split_props.py`: candidates for inspection and deterministic authoring steps.

This is source discovery only. These helpers and their claimed historical results were not executed or requalified in this review. Keep their owning repository's test and script-registration requirements when changing them.

## Proposed CLI boundaries

These commands are proposals, not currently registered CGC operations:

```sh
cgc model rig --input ./marine.glb --model tokenrig -o ./marine-rigged.glb
cgc model skin --input ./marine-with-skeleton.glb --model tokenrig -o ./marine-skinned.glb
cgc motion generate "Walk forward and stop" --model kimodo-soma-rp-v1.2 -o ./walk.npz
cgc motion retarget --input ./walk.npz --rig ./marine-rigged.glb \
  --mapping ./skeleton-map.json -o ./marine-walk.glb
cgc model segment --input ./turret.glb --mask ./selected-view.npy \
  --views ./turret-views -o ./turret-face-labels.npz
cgc model split --input ./turret.glb --labels ./turret-face-labels.npz \
  --output-dir ./turret-parts
```

Rig/skin/segment are model operations. Retarget/split are deterministic processing steps that can initially use the existing scripts directly. Body-motion extraction and facial solving should receive similarly concrete file contracts after their chosen upstream routes are qualified. Do not add a broad “make game-ready” tool.

For learned models, retain a resident inference object on Beam. A new subprocess per job can preserve the old cold-load problem even if the outer container stays warm. Separate loading from per-file work, isolate incompatible environments, and record actual hardware and revisions. Existing CLI queue IDs and local paths are sufficient; no MCP or additional AI runner is needed.

## First qualification package

1. Record a neutral humanoid rig contract: hierarchy, rest/bind pose, joint axes, units, root policy, influence limits, and names/mapping version. Keep the original and a manually corrected control asset.
2. Evaluate TokenRig on that control and the existing marine, including source appearance/scale preservation and supplied-skeleton mode.
3. Run the existing retargeter on a known motion and the selected Kimodo schema. Only then generate idle/walk candidates and test native playback.
4. Independently qualify GeoSAM2 plus deterministic splitting on a small labeled asset. Add HoloPart only if completion measurably reduces repair work.
5. Add video capture and face animation when their target rigs exist.

Record errors, preprocessing/load/inference/export time, peak VRAM and host RAM, files/hashes, component terms, and manual correction effort. Compare at the requested task, not an equal step count across unrelated models. Skeleton and segmentation manifests must travel with results so Codex can target those files in later CLI commands.

## Source snapshots and confidence

The source revisions below were resolved live. Checkpoint metadata checked through the public Hugging Face API identified MIT for SkinTokens and HoloPart, Apache-2.0 for GeoSAM2, and a separate license entry for Kimodo-SOMA-RP-v1.2. These labels do not settle every dependency, geometry asset, dataset, or intended-use question. No paid access or account terms were accepted.

| Repository | Reviewed source revision |
| --- | --- |
| SkinTokens | `273b691d35989d71cd17ff2895fdc735097b92d1` |
| Kimodo | `e1c219c99b4b94ba48be1fb6a1cbc64ecee4c954` |
| GeoSAM2 | `b5de23c60ab487d407b623d394a1614f9714761c` |
| HoloPart | `48dd632c9a7412e6688573bb4f153e0ade7e7325` |
| GEM-X | `4aef1452e5df171deff4f293c08e643eb450981e` |
| Audio2Face-3D SDK | `1ca0f02535ed774f5dbcd724a31cd486368dc783` |

Confidence is high that these source interfaces exist. Confidence in Beam fit, inference speed, StarFall deformation quality, and end-to-end interoperability remains unmeasured until the qualification package runs.
