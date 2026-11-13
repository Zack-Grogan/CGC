# Animation delivery with CGC

CGC can apply an existing SOMA77 motion file to a compatible biped rig, name a clip, and produce GLB and FBX derivatives. It can also apply Audio2Face SDK Mark weights to an existing morph rig with an explicit mapping. These operations use local Blender. They do not start a remote model, retain a GPU, or change queue scale-to-zero settings.

## Requirements and retained files

Install Blender and run `cgc validate setup` once to install the pinned Khronos validator in this project. Blender 5.2.3 LTS was used for the checks below. CGC finds the normal macOS Blender install or accepts `--blender /path/to/blender`. Other Blender versions need the same exporter API and must pass the package checks.

Retargeting also needs the existing `image-to-3dlab` checkout next to CGC. Set `CGC_3DLAB_ROOT=/absolute/path/to/image-to-3dlab` for another location. CGC copies `scripts/kimodo_retarget.py` and `scripts/arm_clearance.py` into the package before use. It does not modify that checkout. The local Blender worker is included in the CGC Python package.

Use a new output directory for each delivery. Each package contains:

- Exact copies of the source GLB and motion or face inputs, with SHA-256 hashes.
- `animation.glb` with the requested clip name, plus `animation.blend` for review.
- `animation.fbx` for the Unity and Unreal profiles.
- `animation-report.json` with sampled motion, evaluated geometry bounds, duration, root displacement, and FBX readback results when applicable.
- A separate official standards report for every GLB in the package, including source and intermediate GLBs.
- `animation-package.json` with hashes, import notes, worker identity, and declared limits.

CGC publishes a package only after all GLBs pass the standards gate and the required Blender checks pass. Warnings remain in the reports. A failed Blender operation or failed standards check retains a `.failed-*` directory with diagnostic files. Existing source files and delivery directories are preserved.

## Apply SOMA77 body motion

Use a clean skinned bind GLB and a validated Kimodo SOMA77 NPZ:

```sh
cgc animation retarget \
  --input outputs/enhancements/dominion-tokenrig.glb \
  --motion outputs/enhancements/starfall-walk.npz \
  --name Walk --loop cycle --root-motion in-place \
  --engine bevy --output-dir outputs/delivery/marine-walk --json
```

The adapter uses the existing topology-based retargeter for compatible SkinTokens/TokenRig-style T-pose bipeds. It preserves the rig hierarchy. It does not provide a universal humanoid mapper. A different skeleton, rest pose, animal, or authored control rig can require a separate reviewed retargeting adapter. Rejected anatomy must be corrected explicitly.

| Option | Result |
| --- | --- |
| `--loop none` | Keep the source interval without cycle selection or seam blending. |
| `--loop cycle` | Select a moving cycle and blend its seam. The output can be shorter. |
| `--loop whole` | Keep the main interval and blend the seam; the existing retargeter can remove a duplicate tail pose. |
| `--root-motion keep` | Retain scaled horizontal travel. |
| `--root-motion in-place` | Remove horizontal travel and retain vertical body movement. |
| `--speed 0.1..4` | Change clip timing without changing the motion file. |
| `--stiff-fingers` | Use the retargeter's fixed-finger policy. |
| `--arm-spread -30..45` | Apply the retargeter's explicit arm-spread control in degrees. |

The retargeter also applies its existing grounding and foot-plant passes. Read `blender.log` for cycle selection, floor penetration, seam distance, and planted-toe diagnostics. A small seam or zero floor penetration does not prove correct contact, appealing motion, or good skin deformation. Inspect the animated asset before admission into a game.

## Name and deliver an existing skeletal clip

```sh
cgc animation prepare \
  --input outputs/delivery/marine-walk/animation.glb \
  --clip Walk --name WalkUnreal --engine unreal \
  --output-dir outputs/delivery/marine-walk-unreal --json
```

`prepare` currently accepts one armature with a single-slot skeletal action. Use `--clip` to select an exact action name when needed. Multi-armature scenes, multi-slot action rebinding, body/face clip merging, constraints that need a new rig adapter, and arbitrary rigid-object animation are outside this adapter.

GLB imports for `prepare` and face delivery use a 60 Hz Blender timeline. Exports sample at one Blender frame. Nonaligned endpoints can add less than one frame of hold at each end. The report includes the authored frame range and timing padding. SOMA77 retargeting uses the existing 30 Hz timeline. Speed changes can also require endpoint padding. Do not infer authored timing from the frame count alone.

GLB is the portable animation and PBR source. Blender exports node/bone transforms and morph weights to glTF, and slotted actions affect how clips are collected. CGC binds the selected action, disables NLA contribution for the selected skeleton, and checks that the output has exactly the requested GLB animation name. See the [Blender glTF manual](https://docs.blender.org/manual/en/5.2/addons/scene_gltf2.html) and [glTF animation specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations).

FBX export retains all bones, disables extra leaf bones, uses the current action, disables NLA/all-action export, and disables key simplification. It does not decimate animated geometry or reparent bones. The file is imported back into Blender. Skeletal readback must retain bone names, bone parents, and duration, with sampled joint-position error at most 5 mm. Morph readback must retain named mapped targets and sampled values within 0.0001. These checks cover sampled baked frames, not every interpolated time or target-engine behavior. See the [Blender FBX manual](https://docs.blender.org/manual/en/5.2/files/import_export/fbx_legacy.html) and [export API](https://docs.blender.org/api/5.2/bpy.ops.export_scene.html).

## Apply Audio2Face to an existing facial rig

Audio2Face weights describe SDK Mark channels. They do not create a character's eyes, lips, jaw, or morph targets. Supply a clean GLB with existing, uniquely named morph targets and one mapped mesh. Use an explicit JSON mapping:

```json
{
  "format": "cgc.face-map/1",
  "channels": {
    "source_channel_name": {
      "node": "ExactFaceMeshNode",
      "target": "ExistingJawOpenTarget",
      "scale": 1.0,
      "offset": 0.0
    }
  },
  "ignore_channels": ["every_other_source_channel_name"]
}
```

Replace these placeholders with the actual NPZ channel names and target names. All 68 source names must appear exactly once across `channels` and `ignore_channels`. No source name can be omitted silently. Each mapped channel needs a unique destination. Duplicate mesh names, duplicate target names, missing targets, nonfinite controls, and implicit channel combination are rejected. Split multi-mesh mappings into separate clips. Use scale/offset only when the target's documented range requires them.

```sh
cgc animation face \
  --input path/to/compatible-face-rig.glb \
  --weights outputs/enhancements/a2f-qualified/0002.npz \
  --mapping path/to/reviewed-face-map.json \
  --name Dialogue --engine unity \
  --output-dir outputs/delivery/dialogue --json
```

The current StarFall TokenRig fixture has no facial morph targets. CGC correctly rejects a facial mapping for it. A character artist must author or supply compatible facial targets before this path can deliver useful facial acting. The positive face test below uses a deliberately simple QA control mesh, not a production facial rig or a claim of realistic lipsync.

## Import into an engine

| Engine | Delivery and required application setup |
| --- | --- |
| Bevy / StarFall | Use `animation.glb`, load the named clip into an `AnimationGraph`, and start the spawned `AnimationPlayer`. Set repeating playback explicitly. Implement any root-motion consumption in the game. |
| Godot | Use `animation.glb` with `AnimationPlayer` / `AnimationTree`. Set the loop mode and choose the root-motion track. Consume the reported root-motion delta in the movement controller. |
| Unity | Use `animation.fbx`. Start with the Generic rig and select its root node. A Humanoid import needs a reviewed Avatar mapping. Set clip loop options and root-transform handling, then configure the Animator's motion application. |
| Unreal | Use `animation.fbx` with the matching Skeleton. Review the imported take name. Enable root motion in the Animation Sequence and configure Animation Blueprint root-motion mode when required. |
| Other engines | Start with the named GLB. Confirm supported skin/morph limits, coordinate conversion, materials, clip binding, and loop/controller behavior in that engine. |

Godot recommends glTF for scene delivery. Its `AnimationTree` can extract a selected root-motion track, but controller integration is still explicit. Its documentation also identifies special shading considerations for skinned morph meshes with nondeforming bones; this adapter preserves the hierarchy rather than silently changing those bones. See [available formats](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html) and [AnimationTree root motion](https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html#root-motion).

Unity distinguishes Generic root-node configuration from Humanoid Avatar mapping. Root-transform settings control which displacement stays in the pose. See [Rig import settings](https://docs.unity3d.com/6000.0/Documentation/Manual/FBXImporter-Rig.html) and [root motion](https://docs.unity3d.com/6000.0/Documentation/Manual/RootMotion.html).

Unreal documents an FBX 2020.2 import pipeline. The verified Blender exporter writes FBX 7400, so Blender readback does not establish target-editor compatibility. Unreal also requires root-motion settings in the animation and blueprint. See [FBX animation pipeline](https://dev.epicgames.com/documentation/unreal-engine/fbx-animation-pipeline-in-unreal-engine) and [root motion](https://dev.epicgames.com/documentation/en-us/unreal-engine/root-motion-in-unreal-engine).

## Recorded end-to-end checks

Evidence is under `outputs/animation-e2e/`, dated 2026-11-12:

| Check | Observed result |
| --- | --- |
| Real StarFall TokenRig + existing SOMA77 walk, Unity delivery | `final-unity`: 40 bones, 32 frames, named `Walk`, 1.0333 s; names and parents preserved in FBX; maximum sampled joint error 0.000003981 m. |
| Same clip, Unreal delivery | `final-unreal`: named `WalkUnreal`, 1.0333 s; FBX maximum sampled joint error about 0.00000395 m. |
| Root motion kept | `final-root`: 120 frames, 3.9667 s; horizontal root displacement about 6.6945 m. The in-place counterpart has zero horizontal displacement. |
| Real SDK Mark NPZ + explicit QA morph mesh | `final-face`: all 68 channels mapped; 2.3833 s; FBX maximum sampled morph-weight error about 0.0000000149. |
| StarFall face incompatibility | `starfall-face-rejection.json`: existing mesh found, required morph target absent, rejected before Blender. |
| Official GLB checks | All retained source/intermediate/delivery GLBs passed with zero errors. The body fixture retains one `NODE_SKINNED_MESH_NON_ROOT` warning; no hierarchy change is hidden. |
| Actual Bevy 0.20.1 runtime | `bevy-final-unity.log` and `bevy-final-root.log`: both passed; one animation player each, 31 / 24 changed nodes, 120 evaluated frames each. |
| Multi-clip selection | `selected-clip`: a two-clip GLB delivers only the requested renamed clip; missing `--clip` is rejected. |
| Offline contracts | `python -m unittest discover -s tests -p test_animation_assets.py -v` covers admission, mappings, original preservation, failed publication, and CLI dispatch. |

Unity, Unreal, and Godot editor imports were not run. The relevant editors were not installed. FBX material fidelity, Humanoid/Avatar configuration, convincing facial acting, large-crowd performance, gameplay collision, terrain-aware foot placement, and animated LODs are not established by these checks. Keep original geometry and review those concerns in the destination project.
