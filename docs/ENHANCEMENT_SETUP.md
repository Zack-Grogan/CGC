# Remote asset enhancement tools

The six enhancement candidates now have working Beam inference routes and local output files. Codex drives the CLI and follows file dependencies. CGC retains queue state and loaded models.

## Commands and file contracts

| Command | Actual operation | Local output |
| --- | --- | --- |
| `model rig --input FILE.glb` | TokenRig predicts joints and skin weights | Rigged GLB |
| `model skin --input FILE.glb` | TokenRig conditions skin generation on supplied joints | Rebuilt rigged GLB |
| `motion generate TEXT` | Kimodo SOMA-RP-v1.2 generates motion | SOMA77 NPZ |
| `motion extract --input FILE.mp4` | GEM-X Native77 temporal Body Motion, with contact/IK correction | Native GEM PT |
| `motion convert --input FILE.pt` | SOMA FK converts GEM parameters into checked retargeting rotations | SOMA77 NPZ |
| `model views --input FILE.glb` | CPU Blender prepares the native GeoSAM2 view package | ZIP |
| `model segment --views FILE.zip` | GeoSAM2 propagates point/mask prompts and labels canonical mesh faces | NPZ and mask/legend sidecars |
| `model split --input FILE.glb --labels FILE.npz` | Deterministic face selection with original GLB resources | GLB with `selected` and `remainder` groups |
| `model complete --input FILE.glb --part NAME` | HoloPart reconstructs one selected node/group | GLB with the reconstructed part |
| `audio face --input FILE.wav` | Audio2Face-3D v3.0 plus the SDK GPU blendshape solver | Timed SDK Mark blendshape NPZ |

These commands use the same queue, `--enqueue`, `--count`, output reservations, receipts, and recovery commands as the original generation suite. Models and weights remain remote.

## Rig and motion workflow

```sh
cgc model rig --input ./character.glb --seed 42 -o ./character-rigged.glb
cgc motion generate "A person walks forward at a steady pace." \
  --duration 4 --seed 42 --accept-license -o ./walk.npz
blender --background --python scripts/blender_python.py -- \
  ../image-to-3dlab/scripts/kimodo_retarget.py \
  --rig ./character-rigged.glb --motion ./walk.npz \
  --out ./character-walk.glb --loop --in-place
```

TokenRig uses the native texture-transfer path. The supplied-skeleton mode rebuilds bone names and bind transforms. It does not retain existing animation clips. Retarget motion to the exported rig.

Kimodo uses the pinned `NousResearch/Meta-Llama-3-8B-Instruct` mirror, its MNTP adapter, and its supervised LLM2Vec adapter. All four base-weight hashes match the original Meta shards. Beam verified the downloaded bytes. The original Llama prompt format is retained. See [the Kimodo guide](KIMODO.md).

For video capture:

```sh
cgc motion extract --input ./action.mp4 --camera-mode static \
  --accept-license -o ./capture.pt
cgc motion convert --input ./capture.pt -o ./capture.npz
blender --background --python scripts/blender_python.py -- \
  ../image-to-3dlab/scripts/kimodo_retarget.py \
  --rig ./character-rigged.glb --motion ./capture.npz --out ./captured-action.glb
```

Use `static` for a fixed camera. `background` uses the native background-based camera estimator. Extraction normalizes the clip to 30 Hz and retains raw predictions alongside contact/IK-corrected parameters. The initial profile accepts clips up to 60 seconds.

The conversion checks the rotation convention against SOMA FK. For the StarFall fixture, `runtime_rotation * inverse_bind_rotation` reconstructed joints with a maximum error below `6e-7` meters. Using runtime rotations directly produced a large error. Shared joint names alone were insufficient to establish compatibility.

## Segmentation and part completion

```sh
cgc model views --input ./ship.glb -o ./ship-views.zip
unzip ./ship-views.zip -d ./ship-views
cgc model segment --views ./ship-views.zip --points ./points.json \
  --view 0 --seed 42 -o ./ship-labels.npz
cgc model split --input ./ship.glb --labels ./ship-labels.npz \
  --label 1 -o ./ship-parts.glb
cgc model complete --input ./ship-parts.glb --part selected \
  --steps 50 --octree-depth 7 --seed 42 -o ./ship-completed.glb
```

Point prompts use source-image pixels in the selected 1024px view:

```json
[
  {"frame_idx": 0, "obj_id": 1, "point": [330, 530], "label": 1},
  {"frame_idx": 0, "obj_id": 1, "point": [622, 530], "label": 0}
]
```

The point label is `1` for a positive point and `0` for a negative point. Alternatively, supply `--mask FILE.npy` or a native EXR/image mask. Use the segmentation sidecar's legend to interpret positive output IDs. Output label `0` retains background or unobserved faces. Native background sentinel `999` is preserved in `native_labels` and mapped to `0` in the public label array.

The view package contains the exact source GLB, camera metadata, and 12 matching color/depth/normal views. GeoSAM2's selected checkpoint requires 1024px geometry maps. CGC corrects the renderer/inference translation-order mismatch and records its coordinate convention. The render audit checks camera coverage.

Labels include their canonical vertices/faces and source hash. Splitting maps triangles back to the source GLB. It retains material definitions, embedded images, normals, UVs, and all unselected faces. The texture fixture preserved all 98,332 triangles and both PNG payloads exactly. See [the texture audit](../outputs/enhancements/texture-split-audit.json).

Point prompting can select a broader assembly than the intended material surface. In the nozzle test, the point route included neighboring engine geometry. A supplied surface mask selected only nozzle faces, with 100% precision and 76.3% recall against the known component. The remaining faces were retained rather than silently assigned to the selected part. This fixture measures one selection; it is not a general accuracy benchmark.

HoloPart reconstructs new geometry. Its new surfaces have no original UVs or textures. Other source resources are retained through GLB node replacement. The partial nozzle test changed an open 58-face selection into a closed surface. It remains a reconstruction draft that needs a shape review.

This route uses the upstream non-flash, scikit-image Marching Cubes extractor. It does not install or use DISO, whose package declares CC BY-NC 4.0. [DISO package metadata](https://pypi.org/project/diso/0.1.4/).

## Face animation

```sh
cgc audio face --input ./dialogue.wav --accept-license -o ./dialogue-face.npz
```

The output contains `weights`, `times`, and `channel_names`: 52 skin channels and 16 tongue channels for the SDK Mark basis. The SDK executor and TensorRT engine stay loaded between jobs. Engines are cached for the actual GPU, driver, network hash, and TensorRT version. The native track state is reset for each input.

The tested 2.4-second voice line produced 144 changing frames at 60 Hz. The route uses the model's default emotion and requires no gated Audio2Emotion model.

StarFall's inspected GLBs have no facial morph targets. These weights therefore need a compatible facial rig and channel mapping before character-face playback. The adapter does not create that rig or convert an arbitrary marine head into the SDK topology.

## Queue and transport

Referenced files are snapshotted locally and uploaded to the private `cgc-inputs` volume by content hash. Task messages contain small descriptors. Workers copy referenced files into per-job temporary storage and verify their size and SHA-256 before use. This removes the 16 MiB RPC payload problem for larger meshes and multi-file requests.

Models load once per resident worker. Continuous jobs on the same profile reuse the same inference objects. CGC uses one GPU task at a time, groups model work, and releases the previous GPU profile when switching. `cgc queue configure --keep-warm-seconds 300` sets a longer review window. `cgc queue cool` releases a retained GPU worker.

The local queue still needs a running host to dispatch new jobs and collect files. Submitted Beam tasks can continue while the Mac is unavailable. Unknown submission outcomes are not automatically resubmitted.

## Evidence and scope

See [the enhancement acceptance record](../outputs/enhancements/enhancement-acceptance.json) and [the timing chart](../outputs/enhancements/generation-speeds.html).

The acceptance package covers live inference for all six candidates, resident-session reuse, native StarFall animation playback, material/texture-preserving splitting, selected-part reconstruction, and large-input transport. It also records the exact limits of the face basis and the selection/capture fixtures. Original StarFall assets were preserved.
