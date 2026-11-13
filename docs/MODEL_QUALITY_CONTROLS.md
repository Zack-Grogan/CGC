# Native model controls and quality boundaries

Reviewed 2026-11-12 against the deployed adapter revisions and upstream source. The controls below change real model or export parameters. A successful model call does not establish aesthetic quality, character identity, seamless audio, useful topology, or engine compatibility.

## Implemented controls

`quality` accepts `draft`, `standard`, or `detail` on configurable generation profiles. Profiles fill unspecified values. Explicit settings, including `--no-save-latents`, win. Omitting `quality` retains the previous defaults. The plan and result store the selected budget and effective controls.

| Profile | Draft | Standard | Detail |
| --- | --- | --- | --- |
| Qwen Base | 20 steps | 40 steps | 40 steps |
| Qwen Turbo | Saved 8-step schedule | Saved 8-step schedule | Saved 8-step schedule |
| TRELLIS image to mesh | 512 resolution, 1024 texture, 50,000-face export target | 1024, 2048, 100,000 | 1024, 2048, 300,000; retain latents |
| MOSS SFX | 50 steps | 100 steps | 100 steps |
| ACE Base | 32 steps | 32 steps | 64 steps |
| ACE Turbo | 8 steps | 8 steps | 8 steps |
| VoxCPM2 | 6 CFM steps | 10 CFM steps | 10 CFM steps |
| Kimodo | 50 denoising steps | 100 | 100 |
| HoloPart | 25 steps, depth 6 | 50 steps, depth 7 | 50 steps, depth 8 |
| TokenRig | 4 beams | 10 beams | 10 beams |

These are compute and retention budgets, not winners from a blind quality study. Some standard and detail values are deliberately equal. Raising steps indiscriminately can waste compute or change results adversely. Higher mesh export targets retain available geometry; they do not invent reliable surface detail. Keep a lossless source and select acceptable candidates before engine optimization.

The fixed capture, segmentation, face-solver, and deterministic conversion profiles have no budget profile. They reject a supplied `quality` value rather than pretend to apply it.

### Images

- `steps` maps to Qwen Base's `num_inference_steps`. Turbo retains the checkpoint's saved sigmas; an explicit step count other than eight is rejected.
- `guidance_scale` maps to Qwen's **`true_cfg_scale`**, not a nonexistent generic pipeline parameter.
- Qwen Base negative conditioning requires a negative prompt and scale greater than one. An empty negative prompt is valid when explicitly supplied with CFG. Inert combinations are rejected before network work.
- Turbo keeps CFG=1 and rejects negative conditioning and other CFG values. It does not silently switch to Base.
- The published non-square 2048-class canvases are accepted: 2400×1792, 2528×1696, 2752×1536, and their rotations. This does not expose unlimited image dimensions or prove their latency on every worker.
- Generate and edit accept ordered reference images. The edit target remains first. A mask or marked-up image can be supplied as conditioning, but the pinned unified API has no `mask_image` argument. Pixel preservation outside a region requires deterministic compositing and a comparison check.

The [Base model card](https://huggingface.co/Qwen/Qwen-Image-2.1) publishes the 40-step example and reference/alpha workflows. The [Turbo card](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo) explains why `num_inference_steps` alone does not replace its saved schedule. The [deployed Diffusers signature](https://github.com/huggingface/diffusers/blob/0905b667fe3f37f43b6ef9c6e05ad20636206938/src/diffusers/pipelines/qwenimage21/pipeline_qwenimage21.py) establishes actual CFG behavior.

### Sound and speech

- MOSS accepts `steps` and `cfg_scale`, with native defaults 100 and 4.0. Duration remains at most 30 seconds. These are separate from speech identity or direction controls.
- ACE Base accepts `steps` and `guidance_scale`. Turbo stays at eight steps and rejects guidance overrides. Source-only extract, layer, and complete commands select Base by default. A caller's explicit unsupported Turbo choice still fails.
- Music validates finite repaint intervals and the published BPM range. More steps do not establish lyric correctness, a mix that sums from stems, or a seamless loop.
- Pinned VoxCPM 2.0.3 accepts `steps` as `inference_timesteps` and `guidance_scale` as `cfg_value`. It does **not** accept a `seed` argument. The newer upstream README includes seed examples, so using current examples against the pinned package would be incorrect.
- Voice design directions remain parenthesized prefixes. Directed cloning uses reference-only conditioning to avoid speaking the direction text. The pipeline does not silently enable a denoiser, retry a rejected performance, or fetch another voice model.

Sources: [MOSS model defaults](https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0), [pinned MOSS callable](https://github.com/OpenMOSS/MOSS-TTS/blob/934d6826b084c46a0d033402174d5f8ac4ed2519/moss_soundeffect_v2/pipeline_moss_soundeffect.py), [pinned ACE GenerationParams](https://github.com/ace-step/ACE-Step-1.5/blob/ca1e85fe9430179831e6bc6be790c332190a3866/acestep/inference.py), [VoxCPM 2.0.3 distribution](https://pypi.org/project/voxcpm/2.0.3/), and [upstream Vox cookbook](https://github.com/OpenBMB/VoxCPM#-usage).

### Geometry and animation

TokenRig's `num_beams` maps directly to its native search width. HoloPart guidance maps to the diffusion pipeline's `guidance_scale`. Supplied skeleton conditioning still rebuilds bind transforms and names; it is not a drop-in weight replacement for existing animation clips.

TRELLIS rejects zero-valued texture/export controls instead of substituting defaults. Latent re-export rejects an explicit generation seed, resolution, or new-latent retention request and reports that sampling was skipped. Texture and export settings can change; saved latents retain the existing sampled shape.

The source workflows are [TokenRig's demo](https://github.com/VAST-AI-Research/SkinTokens/blob/273b691d35989d71cd17ff2895fdc735097b92d1/demo.py), [HoloPart inference](https://github.com/VAST-AI-Research/HoloPart/blob/48dd632c9a7412e6688573bb4f153e0ade7e7325/scripts/inference_holopart.py), [Kimodo generation](https://github.com/nv-tlabs/kimodo/blob/e1c219c99b4b94ba48be1fb6a1cbc64ecee4c954/kimodo/scripts/generate.py), and [TRELLIS examples](https://github.com/microsoft/TRELLIS.2).

## Practical capability inventory

| Area | Working CGC boundary | Additional upstream capability or manual boundary |
| --- | --- | --- |
| Qwen | Generate/edit, ordered references, alpha, Base CFG/negative prompt, native canvas presets | Annotation/mask guidance is conditioning. Exact outside-mask retention is a compositor task. LoRA training, latent injection, and alternate sigma experiments are not qualified CLI operations. |
| TRELLIS | Image to mesh, saved-latent export, existing-mesh reference texturing | Generation and texturing are distinct pipelines. Single-image conditioning is not native multi-view reconstruction. Exact retopology, interiors, moving-part separation, and collision require processing. |
| TokenRig | Predicted rig and supplied-joint skinning, native beam width, texture transfer | Deformation quality and bone naming require checks. Voxel skin postprocessing and arbitrary non-humanoid rigs are not universally qualified. |
| Kimodo | Text motion with SOMA77, seed/duration/steps, contact processing | Native pose, endpoint and path constraints, multi-prompt sequences, and robot representations need separate schemas and tests. A generated walk is not a certified loop or foot-contact solution. |
| GEM-X | Temporal body video, explicit camera mode, source timing, contact/IK, checked SOMA conversion | Framewise hand pose, external camera calibration, ViPE, and gated hand assets are separate routes. No motion capture from heavily occluded or stylized footage is guaranteed. |
| GeoSAM2 | Native view rendering and point/mask propagation to canonical face labels | Text-only semantic part selection is not the source API. Occluded selection and prompt precision require review. The caller can refine masks. |
| HoloPart | Selected-part reconstruction with original unselected resources retained | New surfaces have no old UV/material layout. Closed geometry alone does not establish correct shape, fit, or lower repair effort. |
| Audio2Face | Timed skin/tongue weights for the SDK Mark basis | It does not rig arbitrary faces. Compatible topology/morph channels, facial motion retargeting, and game playback remain character-specific. Audio2Emotion is optional and not invoked. |
| VoxCPM | Voice design/clone and direction, native CFM/guidance | Acting, pronunciation and timbre need auditioning. Pinned seeded generation is unavailable. Training and alternate denoisers require separate qualification. |
| MOSS | Text SFX with duration, steps and guidance | It has no implemented audio/image-reference or speech-character identity conditioning. Nonverbal efforts require listening. |
| ACE | Instrumental/lyric generation, style references, source modes | LM thinking/codes, custom task instructions, wavelet refinements and custom timesteps need explicit qualification. Mix alignment and adaptive game music require processing and checks. |

Sources for fixed enhancement boundaries: [GEM-X native mode guide](https://github.com/NVlabs/GEM-X/blob/4aef1452e5df171deff4f293c08e643eb450981e/docs/DEMO.md), [GeoSAM2 source](https://github.com/VAST-AI-Research/GeoSAM2), and [Audio2Face SDK samples](https://github.com/NVIDIA/Audio2Face-3D-SDK/blob/1ca0f02535ed774f5dbcd724a31cd486368dc783/audio2face-sdk/source/samples/README.md).

## High-level workflow recipes

For a reusable game asset, keep the brief and references as files. Specify silhouette, material intent, camera, unit scale, transparency, movable-part boundaries, and target engine budget. Generate a small candidate set before scaling the queue. Select a candidate using renders and measurable checks. Retain its seed, model revision, raw output, and intermediate latents where available.

Use orthogonal checks for different failure types: captions and reference comparison for appearance; topology/UV/normal checks for geometry; exaggerated poses for weights; contacts and seams for animation; audition, transcription, peaks, and seam measurements for audio. A file parser cannot replace those judgments.

The upstream examples are useful executable cookbooks: [Qwen generation/editing and reference examples](https://github.com/QwenLM/Qwen-Image-2.1), [Diffusers Qwen LoRA example](https://github.com/huggingface/diffusers/tree/main/examples/dreambooth), [TRELLIS existing-mesh texturing example](https://github.com/microsoft/TRELLIS.2/blob/main/example_texturing.py), [Kimodo constrained generation CLI](https://github.com/nv-tlabs/kimodo/tree/main/docs/source/user_guide), and [Audio2Face default-emotion executor sample](https://github.com/NVIDIA/Audio2Face-3D-SDK/tree/1ca0f02535ed774f5dbcd724a31cd486368dc783/audio2face-sdk/source/samples/sample-a2f-executor).

## Verification scope

The control tests exercise planner refusal paths, explicit-over-default precedence, native keyword mapping, fixed Turbo schedules, unsupported flags, native canvas boundaries, and latent-export seed reporting. Numeric texturing tests exercise surface corruption refusal, triangle loss refusal, UV seam duplication, hierarchy, and nonuniform transforms without loading an AI model.

Live native texturing evidence is recorded under `outputs/quality-upgrade/texture-e2e/`. No new checkpoint, denoiser, or forbidden background remover is added by that route. Existing generation qualification does not automatically qualify new presets as visual-quality improvements.

Two real StarFall texture jobs passed the complete official Khronos validator with zero errors and warnings. Each retained all 2,022 source triangles, 24 imported mesh nodes, and all source node names. An independent check after GLB serialization measured zero world-position and node-matrix error. The outputs contain two embedded 1024×1024 PNG maps: base color/alpha and metallic/roughness. They require no glTF extension. Blender 5.2.3 imported and rendered the first output in three views.

The first worker load took 223.90 seconds, then its first texture call took 102.52 seconds. The next queued call reused the same session with `session_call=2` and `model_load_count=1`; it took 12.50 seconds. These are two fixture measurements, not latency guarantees. Native qualification covers model resolution 512 and texture size 1024; other accepted native sizes have no new comparative quality or latency qualification. The GPU was released with `cgc queue cool`, and a subsequent Beam container list was empty.

The qualification also found and fixed native C++ stdout crossing the JSON protocol boundary. TRELLIS now reserves a separate file descriptor for JSON and sends native output to stderr. A subprocess regression writes raw `os.write(1, ...)` noise to exercise this boundary.

The existing TRELLIS cache pins `microsoft/TRELLIS.2-4B` to `af44b45f2e35a493886929c6d786e563ec68364d`. It already includes the texturing configuration and shape encoder. The adapter reuses its loaded texture decoder, texture flow models, and image encoder. It does not call the upstream texturing loader, which constructs the default background remover. The prior image-encoder mirror remains identified in the existing provenance receipt; that receipt does not establish byte equivalence to the upstream gated encoder.

### Texturing source preflight and explicit cleanup

The local planner checks static triangle accessors and node transforms before submission. It rejects zero-area faces, ambiguous coincident faces across nodes, external resources, required extensions, compressed/sparse geometry, and morph or skeletal inputs. Duplicate faces inside one node are permitted only if native output retains their multiplicity and winding. The native output check also refuses missing faces, reversed winding, changed surface positions, or changed node transforms. UV seams can duplicate vertices.

Texturing does not clean the input. The authored Dominion fighter contained 32 zero-area faces in `HULL wing ochre stripe`. Qualification used an explicit derivative with these faces removed: 2,054 source triangles became 2,022. A further source review removed 48 unreferenced vertices and recomputed unit normals. The original remained unchanged. Cleanup reports and hashes are under `outputs/quality-upgrade/texture-e2e/`. Trimesh splits some material primitives into child geometry nodes on import; original parent transforms remain, but output node and material counts can differ.

For the same explicit cleanup on another static GLB, first install the optional review dependencies into a project directory. These packages are for local inspection; they do not download models. The code refuses an existing output and records each removed face count.

```sh
uv venv --python 3.12 .backends/mesh-review
uv pip install --python .backends/mesh-review/bin/python numpy==2.5.4 trimesh==5.2.1 Pillow==13.0.0
.backends/mesh-review/bin/python - SOURCE.glb SOURCE-nondegenerate.glb <<'PY'
import hashlib, json, sys
from pathlib import Path
import trimesh, numpy as np
from cgc.texture_preflight import inspect_source
source, output = map(Path, sys.argv[1:])
if output.exists():
    raise SystemExit('Output exists; choose a new destination')
scene = trimesh.load(source, force='scene', process=False)
removed = []
for name, mesh in scene.geometry.items():
    old_vertices = len(mesh.vertices)
    keep = mesh.area_faces > 0
    mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    normals = np.asarray(mesh.vertex_normals).copy()
    lengths = np.linalg.norm(normals, axis=1)
    missing = lengths < 1e-12
    normals[~missing] /= lengths[~missing, None]
    for vertex in np.flatnonzero(missing):
        face = int(np.flatnonzero((mesh.faces == vertex).any(axis=1))[0])
        normals[vertex] = mesh.face_normals[face]
    mesh.vertex_normals = normals
    removed.append({'geometry': name, 'zero_area_faces_removed': int((~keep).sum()),
                    'unreferenced_vertices_removed': old_vertices - len(mesh.vertices),
                    'normals_recomputed': True})
scene.export(output, extension_webp=False)
report = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'output': str(output), 'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
          'removed': removed, 'preflight': inspect_source(output), 'automatic_in_model_texture': False}
output.with_suffix('.cleanup.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
PY
```

Review the derivative before you queue it and run `cgc validate gltf --input SOURCE-nondegenerate.glb`. This procedure removes exactly zero-area faces and unreferenced vertices, then recomputes unit normals. It does not repair intersections, overlapping nodes, non-manifold edges, winding, or near-zero slivers. A source that still fails preflight needs an explicit modeling repair.
