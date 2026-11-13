# Portable game-asset finishing

`cgc asset` inspects GLB assets and creates an additive engine package. It starts no generation model, GPU worker, or persistent service. The original file is copied exactly into the package. Existing output directories are refused.

The package supplies reviewable files and import instructions. It does not guarantee artistic quality or identical rendering in every engine.

## Commands

```sh
cgc asset inspect --input ./ship.glb --require-node SOCKET_WEAPON --json
cgc asset prepare --input ./ship.glb --output-dir ./ship-package \
  --engine bevy --lod-ratios 0.5,0.25 --collision convex \
  --exclude-collision-node "SCALE 1.8m pilot reference" --json
```

Profiles are `portable`, `bevy`, `godot`, `unity`, and `unreal`. Use `--lod-ratios none --collision none` with a GLB profile to preserve an animated asset without static finishing. LOD generation, collision generation, and FBX finishing currently reject skins, animations, and morph-target meshes.

`--require-node NAME` may be repeated. Each name must exist exactly once in the active source scene. The tool checks caller-provided socket or attachment names; it does not invent gameplay sockets.

`--meters-per-unit` is an explicit caller assertion about source scale. `--yaw-degrees` adds a deliberate facing conversion. The tool changes scene-root transforms and retains the original resource bytes. Neither option guesses scale or intended facing from an image. The glTF convention is right-handed, with +Y up, front +Z, and distances in meters. StarFall uses its own +Y-up/-Z-forward asset contract, so apply one deliberate root-facing conversion when required. [glTF specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html).

## Four-view local review

```sh
cgc asset render --input ./ship.glb --output-dir ./ship-review --size 512 --json
```

The local Blender worker renders `front.png`, `side.png`, `back.png`, and `three-quarter.png`. It fits orthographic cameras to the evaluated default pose, uses neutral studio lighting and 24 CPU Cycles samples, and records `inspection.json` plus `render-review.json`.

Size is 256–4096 pixels. `--blender` or `CGC_BLENDER` selects the executable. `--timeout` bounds the process duration. Existing output directories are refused. CGC snapshots the exact source bytes, renders from that snapshot, checks four complete PNG files and the inspection, and publishes the directory with an atomic no-replace operation. It records hashes for the source and artifacts. Failed reviews retain their snapshot, logs, and failure record in a separate `.failed-*` directory.

This is a static/default-pose review. The labels are relative to the imported coordinate axes, not a semantic prediction of the object's front. These images do not reproduce a specific engine's tone mapping, lighting, normal-map settings, animation deformation, or final gameplay view. They provide files for review rather than automatic visual approval. No Beam task or model worker is started.

The StarFall Fighter was rendered through the actual CLI at 384px. All four images, its source snapshot, and inspection hashes were verified under `outputs/game-assets-e2e/cli-render-review/`.

## Package contents

- `source.glb`: the original bytes and source SHA-256.
- `lod0.glb`: the preserved base asset, with only explicitly requested unit/facing transforms.
- `lod1.glb`, `lod2.glb`, and further requested levels: separate decimated derivatives.
- `collision.glb`: optional closed convex proxies, one per disconnected source component where a volume is possible.
- `asset.fbx` and `lodN.fbx`: Unity/Unreal derivatives when those profiles are selected.
- `materials.json` and `textures/`: original material definitions, texture roles, and exact embedded image payloads.
- `asset-package.json`: file hashes, actual triangle counts, achieved LOD ratios, bounds, collision details, skipped components, and import notes.
- Per-GLB Khronos validation reports, including warnings.

Every produced GLB must pass the official validator without errors. Warnings remain visible. A failed standards check preserves diagnostic output in a separate `.failed-*` directory and does not publish a successful package.

LOD0 is never decimated. The requested ratios are per-mesh targets, so the actual total ratio can differ. Small components are retained by default; `--min-component-triangles 0` allows decimation on every nonempty component. The default 32-triangle cutoff is a conservative derivative-generation choice, not a universal quality budget. Review silhouettes, seams, normal shading, and texture detail at the intended screen size. Separate files avoid assuming that every importer supports the same LOD extension or runtime selection policy.

## Review lighting and geometry

Use Blender material and clay views before judging a reconstruction. The real Dominion V2B test exposed two different problems: an invented tray was part of the generated mesh, while excessive studio light energy washed out its dark metallic material. A file-import pass establishes neither visual fidelity nor suitable lighting.

```sh
cgc asset render --input ./asset.glb --output-dir ./review-pbr \
  --size 1024 --samples 48 --light-scale .12 --json
cgc asset render --input ./asset.glb --output-dir ./review-clay \
  --size 1024 --samples 48 --light-scale .12 --clay --json
```

The studio light multiplier now defaults to `0.12`; the earlier `1.0` level overexposed this dark metallic reference. Adjust it for the material and intended review. More samples reduce rendering noise; they do not improve generated geometry. Clay overrides materials for inspection and leaves the input file unchanged. Both settings are retained in the review receipt.

## Collision policy

Collision is opt-in. Use repeated `--collision-node NAME` to include only specific source mesh nodes, or `--exclude-collision-node NAME` to omit reference, glazing, decorative, or other nonphysical geometry. Names must exist uniquely and inclusion/exclusion cannot overlap. Selection is recorded and uses original names even if an export profile sanitizes render names.

Convex hulls are generated separately for disconnected components after coincident collider-only vertices are welded. Closed-manifold and volume checks reject coplanar or degenerate components. Skips are recorded. Thin panels need deliberately authored slabs or primitive colliders if they must collide.

A convex hull fills concavities. It may block a doorway or cockpit even when the original visual geometry is open. The tool does not choose physical mass, gameplay layers, interior walkability, or acceptable collision clearance. It also preserves source debug/reference geometry; remove unwanted reference meshes before generating production collision.

Godot proxies use `-convcolonly`. With name-suffix import enabled, Godot converts these into collision nodes. For moving objects, review and reparent collision shapes to the intended physics body. Simple primitives often have the best reliability and performance. [Godot suffix rules](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/node_type_customization.html), [Godot advanced import settings](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/advanced_import_settings.html).

Unreal FBX proxies use `UCX_<render mesh name>_<component number>`, matching the corresponding render object. The manifest records names and component counts. [Epic FBX collision rules](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine).

## Engine import guidance

### Bevy / StarFall

Load `lod0.glb` using the selected scene label. Bevy applications must choose LOD handles and create physics colliders explicitly. The package does not attach a specific physics library or create a new AI orchestrator. Named-node checks can enforce a project's declared attachment contract. [Bevy glTF example](https://bevy.org/examples/gltf/update-gltf-scene/).

### Godot

GLB is the primary package format. Godot also has its own imported mesh LOD generation; choose either the packaged explicit levels or the engine's generation policy. Avoid configuring both without knowing which levels are active. [Godot formats](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html), [Godot LOD guidance](https://docs.godotengine.org/en/stable/tutorials/3d/mesh_lod.html).

### Unity

`asset.fbx` follows Unity's standard model-import path. Add separate LOD files to an `LODGroup` and assign reviewed convex proxies to `MeshCollider` components. The original GLB is also retained; a glTF import package is another option. [Unity model formats](https://docs.unity.com/en-us/engine/6000.0/manual/assets-and-media/asset-types/models/creating-dccassets/3d-formats), [Unity glTFast](https://docs.unity3d.com/Packages/com.unity.cloud.gltfast@6.0/manual/index.html).

### Unreal

Import the FBX as static meshes and leave Combine Meshes disabled when using the per-object UCX names. Separate `lodN.fbx` files can be imported as LOD levels. Epic documents FBX 2020.2 as its pipeline version; Blender's FBX exporter is a derivative route that still needs a native Unreal import check. Socket names are preserved where supported but are not automatically rewritten to Unreal's socket association scheme. [Epic FBX pipeline](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine), [Epic LOD import](https://dev.epicgames.com/documentation/unreal-engine/importing-static-mesh-lods-using-fbx-in-unreal-engine?lang=en-US).

## PBR fidelity

The original GLB and original texture payloads remain authoritative. FBX does not preserve every glTF PBR material or extension. Unity metallic/smoothness workflows need metallic in R and smoothness in A; glTF's packed texture stores roughness in G and metallic in B. Unreal material normal settings may need Flip Green Channel for a DirectX normal convention. Use the original maps and the explicit channel manifest rather than assuming that embedded FBX materials will render identically.

Complex procedural Blender materials, baked lighting, face-rig mapping, hand-authored topology, and automatic visual approval are outside this operation.

## Measured validation

The StarFall Dominion Fighter fixture contains 2,054 source triangles. Blender 5.2.3 produced 1,072- and 581-triangle LOD derivatives. All five GLBs in the Godot-profile package passed Khronos validation with zero errors and warnings. Collider generation produced 40 closed proxies and recorded three non-volume skips.

A project-local official Godot 4.5.1 binary imported the actual source scene and proxy scene headlessly. It reported 21 mesh instances, 2,054 render triangles, and 40 `ConvexPolygonShape3D` shapes. This verifies import and suffix handling, not collision gameplay or visual approval.

The Unity-profile textured crate FBX was re-imported by Blender with 95,641 render triangles. All three GLBs in that package passed standards validation without errors or warnings. This confirms export/readback, not Unity shader fidelity.

A second Godot test used caller-selected `ENGINE pod` geometry only, with an explicit 90-degree yaw. It imported the same 21 visual meshes and exactly two convex collision shapes.

The Unreal-profile FBX was re-imported in Blender with 2,054 render triangles and matching meter-scale bounds. That is a Blender roundtrip, not a native Unreal test. Unity and Unreal editors were not installed or used. The lead's Bevy checks are separate.

Evidence is under `outputs/game-assets-e2e/`: `godot-fighter/`, `godot-headless/`, `godot-check.log`, `unreal-fighter-v2/`, and `engine-validation.json`. Earlier `bevy-fighter/` and `unreal-fighter/` collision artifacts preceded the closed-hull correction; use the current `godot-fighter/` or regenerated v2 packages for collision review.

## Explicit removal of degenerate static triangles

A generated mesh can contain an exactly zero-area triangle and an unusable normal on a vertex referenced only by that triangle. Use a separate cleanup derivative before packaging or rigging:

```sh
cgc asset clean --input ./raw.glb --output ./raw-clean.glb --json
```

This command removes exactly zero-area triangle faces and then compacts unreferenced vertex slots within each primitive. It uses no area tolerance. Thin triangles with nonzero area remain. It does not weld vertices, smooth the mesh, remove duplicate valid faces, change triangle winding, infer topology, or start a model/GPU worker.

Remaining position, UV, normal, color, tangent, and other supported vertex samples retain their original bytes. The tool rebuilds accessor/buffer layouts and triangle indices to reference the retained samples. Materials, images, samplers, mesh/node metadata, scene transforms, and primitive material assignments remain intact. Embedded image payloads are copied exactly. The receipt records per-attribute source-retained/output hashes, removed face/vertex indices, counts, image hashes, and source/output hashes.

The bounded adapter accepts core, static, uncompressed GLB 2.0 with one embedded binary buffer and TRIANGLES primitives. It supports indexed and nonindexed triangles, including interleaved vertex data. Positions must be FLOAT VEC3. External images, extensions/compression, skins, skin-weight attributes, animation, morph targets, sparse data, matrix/implicit-zero accessors, inconsistent counts, nonfinite attributes, and unsupported layouts are refused before a derivative is written. If every face of a primitive is degenerate, the entire operation is refused; it does not silently delete an object.

Normals remain byte-exact by default. `--normalize-normals` explicitly permits normalization of existing nonzero FLOAT VEC3 normals:

```sh
cgc asset clean --input ./raw.glb --output ./raw-unit-normals.glb \
  --normalize-normals --json
```

The receipt counts changed normal samples. A zero normal that is still referenced by a valid triangle is refused, including with this flag. The adapter does not guess a normal direction or reconstruct an authored smoothing convention. Use a separately reviewed normal-repair process for that case.

The original and any existing output/report paths are preserved. Each successful derivative has `.clean.json` and `.validation.json` sidecars. The official Khronos validator must pass the derivative with zero errors before publication. Complete files are published with same-filesystem no-replace links; the GLB is committed after its reports are ready. Gate/publication failures retain diagnostic files and an exact source snapshot in a `.failed-*` directory. Cleanup is explicit: generation does not silently change its raw output, and cleanup does not assign artistic approval.

The actual Dominion reference tests are under `outputs/dominion-reference-validation-v1/`. The draft changed from 47,506 to 47,502 triangles after four exact degenerates and 12 unused vertex slots were removed. The detail result changed from 290,817 to 290,799 triangles after 18 exact degenerates and 33 unused slots were removed. Both cleaned derivatives passed Khronos with zero errors and zero warnings. All retained vertex-attribute samples and embedded image payloads match their source hashes, with zero normals changed. The raw GLBs and saved latents remain unchanged. Their appearance, reconstruction quality, and suitability for rigging still need review.
