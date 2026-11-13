# Historical remote queue source review

This records the pre-implementation review. Current behavior and evidence are in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

Reviewed 2026-11-11. Read-only review of existing implementation and saved evidence, followed by creation of this document and the proposed [PLAN.md](../PLAN.md). No paid generation, weight download, deployment, or account change was performed.

Scope correction: Codex drives a CLI using local file paths. The revised plan replaces the earlier hosted workflow/agent proposal with a local queue worker and remote generation workers. MCP, a custom AI runner, user-facing artifact IDs, and mandatory Railway/PostgreSQL services are excluded.

Further clarification: reference-guided image generation is included. The proposed CLI distinguishes an edit target (`--input`) from supporting images (`--reference`); Qwen receives these through its shared ordered image-conditioning input. Character voices, SFX, and music are all required scope. The source-backed mapping and remaining qualification work are in [AUDIO_SUITE.md](AUDIO_SUITE.md).

## Sources inspected

- CGC: `README.md`, `pyproject.toml`, `cgc/{cli,planning,runtime,catalog,beam_audio,beam_audio_worker}.py`, Beam recipes, tests, and verification records.
- `image-to-3dlab`: repository instructions, Beam transport, CUDA TRELLIS generator, studio/MCP code, asset-specific Beam proof runner, and saved model manifests. Source root: `/Users/zgrogan/Repos/image-to-3dlab`.
- StarFall: model import contract, current test-world guide, visual manifest, and V2 ship/character/weapon design documents. Source root: `/Users/zgrogan/.t3/projects/starfall`.
- Complete user/assistant message histories in [Map Remote GPU Options](t3-thread://v2/c4c101a8-6805-4cd3-a92e-664c44aece52/f24c09ce-d11b-4f68-bd35-1dadf7fc7a86) and [Multiplayer Space War Design](t3-thread://v2/c4c101a8-6805-4cd3-a92e-664c44aece52/b9af0305-08c3-43d2-9c99-b610b2d26737).
- Current official platform and model documentation, linked below. Platform limits must be checked again against the installed SDK and account before deployment.

No project-scoped copy of the requested `asd-ste100` skill was found. Home-level skills were excluded under the session rules. This document uses plain technical prose and makes no certified compliance claim.

## CGC today

The current CLI is useful generation tooling, but it has no durable background generation queue. Codex supplies the workflow; a workflow graph engine is not required.

- Images use local MFLUX/MLX. FLUX.3 is the existing default. Qwen Image 2.1 entries are local adapters, not deployed CUDA services.
- Tested Phonon and VoxCPM2 audio operations use Beam by default. The client stages only the standalone worker and requested inputs, checks output hashes, and writes local receipts. Preserve these input and provenance boundaries.
- `beam_audio.py` invokes a one-shot `function` with `retries=0`. It has no weight volume or model keep-alive. `beam_audio_worker.generate()` constructs the model inside each invocation.
- `beam/flux3_smoke.py` is a real CUDA image proof, but it is not connected to the normal image CLI as a durable service.
- `batch_plans()` accepts 1–50 jobs, validates them before execution, and runs them serially. References must already exist. Failure stops the remaining batch.
- `runtime.run()` tracks a subprocess through local receipts. History searches the default outputs folder. Neither is a remote workflow index.
- Interruptions already preserve `remote_outcome_unknown`. That honest state must survive the migration.
- The control package uses the standard library and lazy model imports. Preserve a lightweight CLI; isolate optional provider dependencies from model runtimes.
- This directory has no `.git` metadata. `git status` fails because it is not a Git checkout. Source packaging needs an explicit baseline before deployment.

Verification during this review: **76 core tests passed** with `python3 -m unittest discover -s tests -q`; **20 Beam planning/recipe tests passed** with `python3 -m unittest discover -s beam -p 'test_*.py' -q`. These are offline tests, not live provider or warm-worker acceptance tests.

## Image-to-3D today

`image_to_3dlab/beam_client.py` provides authenticated submit/status/cancel operations and deliberately avoids automatic submission retries. The reviewed studio generation path does not yet provide the complete reusable Beam workflow described in the plan.

The thread went beyond transport setup: it generated a marine and fighter on Beam RTX 4090 workers. Both local GLBs still match the SHA-256 values in their generation manifests. Saved Blender inspection records report one mesh per output. This review rechecked hashes and records; it did not rerun inference or Blender.

Evidence paths, relative to `image-to-3dlab`:

- `output/beam/starfall-dominion-marine-front-v1/`: GLB, generation/provenance records, source crop, and review renders. Recorded pipeline load: 215.93 seconds. Sampling: 79.63 seconds. Decode plus baking: 47.49 seconds. Saved mesh inspection: 97,894 triangles.
- `output/beam/starfall-dominion-fighter-side-v1/`: equivalent fighter package. Recorded pipeline load: 111.89 seconds. Sampling: 78.37 seconds. Decode plus baking: 37.64 seconds. Saved mesh inspection: 98,398 triangles.

Those are two different proof runs, with different loading paths. They do not measure resident-model throughput or establish a speedup from warm reuse.

The marine preserves the broad armor silhouette but has softer fine details and an inferred back. The fighter changes unseen geometry, including wings, engines, and tails. Each is editable, but the records do not establish separate components, a rig, animation, authored collision, or a walkable interior.

`scripts/trellis_cuda_generate.py` already exposes `load_pipeline()`, but `generate()` calls it on every run. The proof runner launches generation as a subprocess. Refactor the generation boundary to accept a resident pipeline; keeping only its outer Beam container alive cannot preserve that child process's model.

Retain the repository's pre-inference run-policy check, explicit weight-route approval, BRIA exclusion, and per-component license sidecars. Prior thread approval covers the recorded TRELLIS NVIDIA setup and explicit DINOv3 mirror choice; it is not blanket permission to download every backend. Preserve the mirror identity and hash rather than claiming equivalence to a separately gated source.

## StarFall requirements

StarFall uses Bevy/Rust and now has a local proving ground with a character bay, two weapon display roots, and a held-weapon root. Its import contract requires source preservation, known scale, and one explicit axis conversion. Render hierarchy and gameplay collision/controller state are separate.

The Iron Sovereign manifest is a useful example of source path, scene index, bounds, and import rotation. It is not a general automated import pipeline for arbitrary generated assets. Native test results recorded by the game project do not prove new generated packages work until those packages pass their own checks.

Use current V2 descriptions for generation. V1 supplies historical identities and references. Expanse's civilian retrofit direction is established; Dominion and Accord still need design iteration. LoRA curation is a later activity with explicit sample approval, not an automatic side effect of producing an asset library.

## Verified platform facts and design implications

**Async task transport.** Beam task queues accept asynchronous work and return task IDs. Use them for generation, with CGC's local ledger retaining job state and the larger backlog. [Beam task queues](https://docs.beam.cloud/v2/task-queue/running-tasks).

**Model residency.** Beam's `on_start` hook runs at worker startup and exposes its return value to handlers. It can hold a loaded pipeline between requests. The installed `beta9` task-queue implementation also exposes this hook. [Pre-loading models](https://docs.beam.cloud/v2/endpoint/loaders).

**Idle cost.** `keep_warm_seconds` retains idle containers and incurs billable usage. A nonzero `min_containers` maintains a running baseline. Use a finite idle window and a zero minimum initially. Neither setting guarantees uninterrupted operation through failures. [Keeping containers warm](https://docs.beam.cloud/v2/endpoint/keep-warm).

**Scaling.** Beam supports queue-depth scaling with minimum and maximum container counts. Per-model autoscaling limits do not impose CGC's cross-model GPU budget; the scheduler must do that separately. [Scaling out](https://docs.beam.cloud/v2/scaling/concurrency).

**Finite provider backlog.** Beam documents task-queue pending expiry of two hours by default and an explicitly configured TTL capped at 24 hours. Task queues have automatic retry defaults. Set policy explicitly and keep long backlogs in CGC. The installed task-queue constructor has `max_pending_tasks=100` by default; that is a local SDK default, not verified account capacity. [Timeouts and retries](https://docs.beam.cloud/v2/topics/timeouts-and-retries).

**Storage.** Beam volumes persist files between tasks, but changes can take time to appear in other containers. Use them for weights and recoverable remote files, with explicit integrity and visibility checks. Keep the SQLite queue ledger on the local filesystem. [Distributed volumes](https://docs.beam.cloud/v2/data/volume).

**Results.** Beam's `Output` mechanism produces public URLs and is documented as ephemeral storage. Retain remote results for recovery, then verify and place them at the local output paths requested by Codex. Do not require a separate asset registry or bucket service as the user interface. [Beam output files](https://docs.beam.cloud/v2/data/output).

**Status collection.** The local queue worker can query provider task status and collect results without exposing an inbound web service. Beam also offers callbacks, but an inbound callback service is not required for the revised CLI. [Task callbacks](https://docs.beam.cloud/v2/topics/callbacks).

**Qwen CUDA route.** The official 2.1 card documents a unified generation/editing pipeline, transparency, and CPU offload. The new remote adapter needs its own tested CUDA dependencies and memory profile. Do not copy MLX arguments or promise that the complete BF16 pipeline fits a particular card. [Qwen Image 2.1](https://huggingface.co/Qwen/Qwen-Image-2.1).

**Turbo compatibility.** The Turbo card specifies eight steps and pipeline-configured sampling support in Diffusers. Pin the compatible implementation and checkpoint; do not substitute Turbo weights into an arbitrary older image. [Qwen Image 2.1 Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo).

**Existing license requirement.** Qwen 2.1's published weight license limits use to noncommercial purposes unless a separate commercial license is obtained. CGC's existing verification notes report that the user has a commercial license, but do not identify its model/entity/use scope. Record the applicable scope in the execution policy for game production; a CLI acknowledgment does not grant those rights. This is a model-onboarding requirement, not a reason to pause planning or ask again for an already approved route. [Published Qwen license](https://huggingface.co/Qwen/Qwen-Image-2.1/raw/main/LICENSE).

**Later Modal adapter.** Modal supports asynchronous job submission and configurable container scaling. [Modal job processing](https://modal.com/docs/guide/job-queue), [scaling](https://modal.com/docs/guide/scale). Its GPU memory snapshot documentation currently marks that feature alpha and lists compatibility/performance limits. Ordinary reusable workers must work before snapshots become an optimization dependency. [Memory snapshots](https://modal.com/docs/guide/memory-snapshots).

## Implementation boundaries

Add local queue persistence, a background submission/collection worker, provider adapters, and concrete generation commands. Extend `planning.py` to validate actual model inputs and local file contracts. Extend `runtime.py` to enqueue, wait, and collect. `catalog.py` must report which operations are remotely implemented and tested. Codex owns prompt construction, file inspection, selection, and deciding the next command.

The revised capability mapping was checked against the [official Qwen 2.1 project](https://github.com/QwenLM/Qwen-Image-2.1), the [TRELLIS generation example](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/example.py), and its [mesh texturing example](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/example_texturing.py). Multi-reference edits and transparent generation belong to image generate/edit. Mesh texturing uses a separate upstream pipeline and remains an unimplemented CGC adapter. Local region guidance must not be misrepresented as a verified hard-mask API or exact pixel preservation.

Audio expansion was checked against the VoxCPM2 and Qwen3-TTS sources, the MOSS-SoundEffect-v2.0 model card, and ACE-Step 1.5's inference specification. MOSS v2 uses its dedicated implementation inside `OpenMOSS/MOSS-TTS`; it is not the earlier MLX SFX candidate in `MODELS.md`. No new audio model was installed or tested on Beam during this documentation pass.

In `image-to-3dlab`, extract resident generation without weakening policy or provenance checks. Add tests of the actual extracted functions under that repository's test requirements. Keep proof-specific images, crops, and scripts as evidence rather than turning them into reusable product defaults.

Do not declare completion from passing unit tests, a deployment URL, or one valid image. Completion requires Codex-driven image and image-to-3D commands, verified model reuse, queue restart recovery, and validated files written to the requested local paths. If the Mac sleeps, local dispatch and collection resume when its queue worker runs again; there is no promise of a separate adaptive AI continuing on its behalf. StarFall import checks use the actual generated files.
