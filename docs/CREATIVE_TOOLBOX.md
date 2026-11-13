# CGC creative toolbox and quality boundary

CGC handles remote generation, local files, a durable queue, measured checks, and deterministic finishing. Codex supplies references and briefs, inspects candidates, chooses revisions, and runs the next command. Keep the source and lossless master for every asset.

## What the CLI can establish

| Area | CLI work | What still needs judgment or authored data |
| --- | --- | --- |
| Images | Reference-conditioned generation/editing, native sampling controls, dimensions/alpha checks, color-managed derivatives, texture-channel preparation | Composition, style agreement, identity consistency, legibility, and exact semantic edits |
| Meshes | Reconstruction, static part labels/splits, part reconstruction, geometry/material inspection, standards validation, source-preserving packages | Hero topology, useful interiors, exact proportions, clean deformation topology, and believable design |
| Rigging and motion | Native rig/skin generation, motion generation/capture, checked retarget conversion, named clip delivery | Shoulder/hip deformation, convincing acting, interaction contacts, weapon grips, and gameplay root-motion policy |
| Faces | Audio-driven SDK Mark weights and explicit compatible-target mapping | A compatible facial rig, correct channel correspondence, expression quality, and character performance |
| Audio | Voice/SFX/music generation, explicit mastering/encoding, measured peaks/loudness, seam checks and chosen fades | Acting, speaker continuity, musical taste, adaptive composition, and whether a loop is perceptually convincing |
| Engine delivery | GLB master, optional FBX derivatives, fitted review renders, LOD/collision files, declared scale/rotation, material/import manifests | Engine project wiring, reviewed collision, authored sockets/interiors, shader appearance, and gameplay behavior |
| Queue | Snapshot/hash admission, bounded warm retention, scale-to-zero workers, explicit recovery and collection | The local host must run to dispatch backlog; uncertain submissions require reconciliation |

A technically valid file can still be the wrong asset. A successful engine import can still have poor scale, bad collision, or unsuitable animation. CGC reports those layers separately.

The [real Dominion V2B test](DOMINION_VISUAL_VALIDATION.md) demonstrates this boundary. All four raw reconstructions were visually rejected despite recognizable ship features and, for one candidate, a clean format check. A separate manual tray removal is retained as an explicit repair. The earlier low-detail fixture is not a visual-quality baseline for complex Dominion ships.

## Quality workflow

1. Write the asset brief and choose authoritative reference files. Define known dimensions and the target use.
2. Generate a small candidate set. Use explicit native controls or a documented compute profile. A profile is a sampling budget, not a quality certificate.
3. Inspect the candidates. Keep the selected source and its receipt. Refine prompts, references, or masks when the result misses the brief.
4. Run media/geometry checks and standards validation. Fix a failed contract or retain the candidate as rejected evidence.
5. Prepare engine derivatives from the retained master. Choose collision nodes explicitly; decorative geometry and scale references are not automatically gameplay collision.
6. Import into the actual engine version. Check dimensions, facing, materials, animation, sockets, and collision in context.
7. Approve the asset for the project only after that review. CGC does not assign artistic approval from a numeric score.

Use [model controls](MODEL_QUALITY_CONTROLS.md), [media finishing](MEDIA_FINISHING.md), [game-asset packaging](GAME_ASSET_PIPELINE.md), [animation delivery](ANIMATION_WORKFLOW.md), and [standards checks](STANDARDS_VALIDATION.md) for the corresponding commands. [Queue reliability](QUEUE_RELIABILITY.md) describes recovery and cost controls.

## Portability decisions

Use self-contained glTF 2.0 GLB as the interchange master. Preserve original material maps and their channel roles. FBX derivatives are useful for some editor workflows, but their material representation is not equivalent to every glTF PBR feature. Unity needs a supported glTF importer when using GLB. Unreal import settings and material reconstruction remain explicit. Godot collision suffixes have a specific importer meaning; Bevy and Unity need explicit physics setup.

Keep one consistent import transform for visuals, sockets, and collision. StarFall uses +Y up and -Z forward; glTF interchange uses +Y up and +Z forward. Choose the intended facing once and verify it. Uniform meter conversion is explicit. Do not silently apply a visual-only transform to collision-bearing roots.

LODs are derivatives. The original stays intact. Automatic decimation is suitable for reviewed static meshes; it is not a substitute for animation topology or authored character LODs. Convex hulls are proxies and can fill concavities. Traversable interiors need authored walls, floors, doors, and collision rather than a convex exterior hull.

## Inspect at a useful scale

`cgc asset render --input ./asset.glb --output-dir ./review --size 768 --json` creates fitted review images through local Blender. It preserves the source and records image hashes. These views use neutral lighting and the imported default pose.

The StarFall Bevy inspector previously used fixed camera distances for the Iron Sovereign. A small fighter therefore appeared as a few pixels. It now fits the loaded geometry for the selected view and viewport shape, with scale-dependent clipping, zoom, and grid spacing. Keys `1`, `2`, and `3` reset fitted views; the wheel changes the relative zoom. The capture labels use the actual asset identifier and material counts. Import verification and visual review remain separate checks.

## Research and proven practice

The implementation draws from primary model APIs, engine documentation, and their reference tools. Practical findings changed the work:

- The official Khronos validator found schema errors that header checks and successful imports had missed. Format validation is now a separate, reproducible layer.
- Portable compression is target-dependent. The glTF Transform cookbook's Draco/WebP optimization example is not a safe default for Bevy's supported-extension set.
- glTF material channels and Unity metallic/smoothness channels differ. Data textures need explicit channel operations rather than a color conversion.
- An sRGB color texture and a normal/roughness mask require different processing. Resizing color with transparency also needs correct alpha and transfer-function handling.
- There is no universal game-audio loudness target. Mastering and loop preparation use chosen settings, retain originals, and measure results.
- Reusing a container is insufficient if model objects reload per job. The queue keeps the actual inference objects resident within a finite warm window.

The linked area guides retain source URLs, exact controls, tests, and measured limits. Unity and Unreal export preparation must not be represented as editor verification when those editors were not run.

## What Codex can reasonably do manually

Codex can inspect rendered views and source data, write/refine briefs and masks, choose generation candidates, adjust a known import transform, add specifically defined nodes through Blender scripts, tune LOD/collider choices, and diagnose failed imports. It can iterate audio trims and delivery direction and check technical regressions.

That work is strongest when the asset specification and acceptance conditions are concrete. Detailed hero retopology, expressive facial rigging, convincing character performance, intricate production UVs, and final art direction remain artist work or require close review. More sampling cannot guarantee those results.

## Cost and hosting

No always-on host or always-on GPU is required. CGC retains the local queue and submits remote jobs on demand. Beam workers have zero minimum containers and a finite idle window. Idle warm retention is billable; choose a window that suits the batch, and use `cgc queue cool` after work. Waiting for a cold start is a valid cost choice.
