# CGC: CLI generation queue

The 0.3.0 enhancement tools are implemented and exercised on Beam. [ENHANCEMENT_SETUP.md](docs/ENHANCEMENT_SETUP.md) records the actual contracts and StarFall evidence, including the Nous Llama mirror, rigging, capture/retargeting, segmentation, completion, and face weights.

Status: implemented and exercised end to end. See [the acceptance record](docs/IMPLEMENTATION_STATUS.md) for actual files, runtime evidence, and verification scope.

## Scope and ownership

**Codex drives the CLI. CGC queues generation jobs, calls remote models, and writes files to the requested local paths.** Codex reads the project instructions, writes prompts, inspects results, selects files, and decides which command to run next.

Inputs are ordinary files on this system. Outputs are ordinary files on this system. Beam hosts the initial generation models. Modal is a later provider for a specifically selected larger model.

Scheduling remains mechanical. Codex chooses the next operation and passes ordinary local paths to the CLI.

The factual source review is in [REMOTE_QUEUE_REVIEW.md](docs/REMOTE_QUEUE_REVIEW.md).

## 1. Commands must correspond to actual operations

### Images: Qwen Image 2.1

Keep two image operations: `image generate` and `image edit`. The remote adapter uses the actual Qwen pipeline; it does not turn each possible creative instruction into a separate tool.

| Capability | CLI mapping | What it does |
| --- | --- | --- |
| Text to image | `image generate PROMPT --model qwen-image-2.1 -o FILE.png` | Generates an image from text. |
| Reference-guided generation | `image generate PROMPT --reference A.png --reference B.png -o NEW.png` | Generates a new image using supplied visual references. |
| Edit an existing image | `image edit PROMPT --input TARGET.png -o EDIT.png` | Uses the target image and instruction to produce an edit. |
| Edit with supporting references | `image edit PROMPT --input TARGET.png --reference STYLE.png -o EDIT.png` | Edits the target using additional visual references. |
| Transparent generation | `image generate ... --transparent` | Requests native RGBA output and verifies useful alpha. |
| Edit/extract a transparent subject | `image edit ... --input FILE.png --transparent` | Requests an RGBA edit or cutout through the image model. |
| Local visual changes | The same `image edit`, with a target and annotated/reference images | Directs a change to an indicated region. |

These capabilities are documented by the [official Qwen project](https://github.com/QwenLM/Qwen-Image-2.1). They are not all implemented in CGC today. The remote adapter must qualify each before advertising it.

Specific interface requirements:

- `generate` accepts zero or more `--reference` paths. `edit` requires one `--input` target and accepts zero or more supporting `--reference` paths. This separates the intended use of the files at the CLI boundary.
- Qwen's native interface uses a shared image-conditioning input, not separate target and style-reference arguments. For edits, pass `[target, reference_1, ...]`; for generation, pass the ordered references. Record that mapping and identify the numbered images in the instruction. Do not imply reference images receive a native style-only constraint.
- The documented ten-image reference limit must include the edit target. The qualified remote adapter may use a lower memory limit and must report it. Test generation with references and editing with a target plus references separately.
- `--transparent` is a proposed CLI convenience: it adds the documented transparency instruction and validates the returned alpha. It is not a claimed pipeline argument. Preserve alpha in uploaded references and downloaded PNGs.
- A separate mask may be supplied as conditioning material if the pinned implementation supports that route. Do not invent a native `mask_image`, edit-strength, or pixel-preservation guarantee. Establish the exact mapping before exposing a dedicated mask flag. An annotated-image edit can use the existing reference input.
- Prompt-directed edits can change unrequested pixels. A strict preservation compositor would be a separate deterministic implementation, not a model capability.
- Base and Turbo are checkpoint selections, not new operations. Follow each checkpoint's actual sampling schedule. Turbo's saved schedule is documented in its [model card](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo).
- Width, height, seed, and supported sampling controls map to actual pipeline inputs. `--count N` queues N independently recorded generations; it does not imply the model performs all N simultaneously.
- Concept sheets, another camera view, material changes, icons, and character variations are prompt uses of generate/edit. Do not add invented commands such as `design_faction`, `approve_asset`, or `create_game_package`.
- Generated alternate views are images; consistency with a single real 3D object must still be checked by Codex.

CGC currently uses local MFLUX/MLX for Qwen. Build and test a separate CUDA adapter on Beam. Qualify actual memory use on the selected GPU; local Q4 checkpoint sizes do not establish CUDA memory needs. Keep model downloads and license choices within their recorded authorization.

### 3D: TRELLIS.2 through image-to-3dlab

| Operation | Proposed CLI mapping | Actual implementation/source |
| --- | --- | --- |
| Image to textured mesh | `model generate --reference FILE.png --model trellis2 -o FILE.glb` | Existing `scripts/trellis_cuda_generate.py` and TRELLIS image-to-3D pipeline. |
| Export from saved generation latents | `model generate --from-latents FILE.pt --model trellis2 -o FILE.glb` | Existing `generate_from_latents()`: skips sampling and repeats decode/bake/export. |
| Texture an existing mesh from an image | Later: `model texture --mesh FILE.glb --reference FILE.png -o TEXTURED.glb` | Separate upstream `Trellis2TexturingPipeline`; not established as a working CGC/Beam adapter. |

The [upstream generation example](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/example.py) produces a mesh and exports GLB. The [texturing example](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/example_texturing.py) takes a mesh plus an image. Keep those operations distinct. Do not confuse re-exporting cached material data with generating new textures.

For the initial adapter, accept one isolated object image. Preserve an existing cutout; otherwise use image-to-3dlab's selected background remover and record it. A contact sheet is not native multi-view conditioning. Expose the generator's supported resolution, seed, texture size, decimation/export controls, and optional saved latents with their actual backend meanings.

Reuse policy checks, encoder provenance, BRIA exclusion, and sidecar writing from image-to-3dlab. Refactor its pipeline lifetime to reuse an initialized model. Package a pinned source revision; do not productize the marine/fighter-specific proof runners.

A textured GLB is editable geometry. Generation does not create a rig, skin weights, separate armor plates, moving ship parts, collision, or interiors. Those require actual tools or authoring work. Do not add placeholder CLI verbs that imply they already exist.

### Audio: character voices, SFX, and music are required scope

| Command | Model | Inputs | Output |
| --- | --- | --- | --- |
| `audio speak` | Phonon | Spoken text | WAV with the supported default voice; CPU worker. |
| `audio design` | VoxCPM2 | Spoken text and voice/delivery direction | WAV generated using that direction. |
| `audio clone` | VoxCPM2 | Spoken text, reference WAV, exact reference transcript, consent | WAV conditioned on the reference voice. |

These are existing CGC adapter distinctions, verified from `cgc/beam_audio_worker.py`. Preserve the actual input limits, audio validation, and truncation checks. Move execution onto reusable queue workers. Other catalog entries remain optional until their remote adapters work; list each model's supported operations and readiness honestly.

Expand beyond speech with concrete, separate backends:

- **Character voices:** design sample voices, save a chosen reference WAV and its transcript, then reuse that reference for dialogue and barks with delivery instructions. Start with VoxCPM2; evaluate the distinct Qwen3-TTS design, clone, and preset-voice checkpoints where useful. Character identity is represented by files, not a new orchestration service.
- **SFX and ambience:** add `audio sfx PROMPT --duration SECONDS -o FILE.wav`. First qualification candidate: MOSS-SoundEffect v2.0, using its actual text-to-sound pipeline. Do not expose audio/image reference inputs that this backend does not implement.
- **Music:** add `audio music generate PROMPT ... -o FILE.wav` for instrumentals or supplied lyrics, with supported style-reference audio. First qualification candidate: ACE-Step 1.5. Its source-audio modes and checkpoint restrictions must be mapped explicitly before adding edit/extract commands.

The [audio suite specification](docs/AUDIO_SUITE.md) defines the source mappings, proposed CLI, character voice files, game-audio checks, and implementation requirements. SFX and music are part of completion, not a future optional footnote. The Beam acceptance runs and actual output files are recorded in IMPLEMENTATION_STATUS.md.

### Blender and game integration

Blender already has its own CLI and scripting API. Codex can target a saved `.blend` or import a GLB through a real script. CGC's current Blender scripts are smoke tests, not a general rigging/render/cleanup service.

Do not make a custom `game-ready` or `rig-character` command part of the initial CLI. If a reusable Blender operation is later wrapped, document its real input files, parameters, script, and outputs first. StarFall import tests remain in StarFall and operate on the files produced here.

## 2. Local files are the interface

Every generation command accepts local paths and an explicit output file or directory. Support paths outside CGC, including the StarFall project. Resolve relative paths against the caller's working directory and preserve normal shell quoting.

At enqueue time:

1. Validate the command and input files without loading a local generation model.
2. Resolve output paths and reserve them against other queued jobs.
3. Snapshot or upload the exact input bytes, record their hashes, and pin model/settings. A later edit to a source path must not silently change a queued request.
4. Record the job durably before returning its job ID.

Remote storage is transport and recovery detail. Codex passes `--reference ./marine.png`, not an artifact registry ID. Deduplicate uploads by hash where practical. Never upload the whole checkout or unrelated files.

On completion, download to a temporary file beside the requested output, verify its hash and media structure, and atomically place the completed file. Write logs and a JSON receipt beside it. Preserve 3D provenance sidecars. Refuse existing output files and reserve names before GPU work; never overwrite another job's result. A collision discovered at collection time leaves the remote result recoverable.

For `--count`, require an output directory and generate stable, collision-checked names. Return an ordered list of local output paths and seeds. Do not call a result locally complete until its files and receipts have been placed successfully. Distinguish `remote_completed` from `completed` when download is pending or local disk is full.

## 3. Queue mechanics

Use a local SQLite job ledger and a local background queue worker. This worker performs submission, status checks, cancellation, and file collection. It makes no creative decisions and calls no reasoning model. No additional hosted application is required for the initial CLI.

Keep queue state in the project's `.cgc/` directory, with an explicit override for another state directory. Use the same configured queue from every working directory; changing to StarFall to target its files must not accidentally create a second queue.

Default direct commands enqueue and wait, then return local paths. `--enqueue` returns after inputs and the job record are durable. `--json` prints machine-readable IDs, state, paths, and errors; logs go to stderr or files.

Submitting work ensures the local queue worker is running. `queue start` is also available for explicit startup/recovery. A multi-image request returns the individual job IDs and reserved output paths.

The queue commands are mechanical:

| Command | Purpose |
| --- | --- |
| `queue add jobs.ndjson` | Import many ordinary generation requests with resumable row keys. |
| `queue start` | Start the local queue worker without keeping the terminal attached. |
| `queue pause` / `queue resume` | Stop/start new dispatch; leave running remote work tracked. |
| `jobs list` / `jobs show ID` | Report queue state, provider task, error, and local paths. |
| `jobs wait ID [ID ...]` | Wait and ensure outputs are collected to disk. |
| `jobs collect ID` | Recover a completed remote result to its reserved local destination. |
| `jobs cancel ID` | Cancel queued work or request and confirm remote cancellation. |
| `jobs retry ID` | Explicitly retry a confirmed failed attempt. |

Import rows contain an operation, model, prompt, local reference paths, parameters, and output path. They are individual jobs, not a workflow graph. Remove the current 50-job cap from this path; use streaming import, indexed queries, pagination, and explicit disk limits. A 10,000-row offline test should not allocate GPUs.

Codex submits the next dependent operation after `jobs wait` returns its files. There is no workflow engine, selection service, decision callback, or adaptive runner. If future users need prequeued file dependencies, add an explicit producer-job/file relationship separately; it is not required for the first implementation.

Store job ID, import key, exact request, input hashes, output reservation, provider task ID, attempts, timestamps, and collection state. Make only one local queue worker own dispatch at a time. After restart, reconcile persisted provider tasks before submitting more work. Do not resend a request whose remote outcome is unknown; check status and retained output first. Cancellation must confirm the remote outcome rather than assume a terminated client stopped GPU billing.

**Host lifecycle:** a closed terminal does not stop the background worker. If the Mac sleeps or shuts down, submitted Beam tasks can continue within provider limits; new local backlog dispatch and file collection resume when the queue worker runs again. Codex also continues only while its own session runs. Do not promise Mac-independent orchestration. A later always-on host may run this same CLI queue worker if required, without introducing a second AI orchestrator.

## 4. Keeping a model loaded on Beam

Deploy a Beam task queue per tested model/runtime profile. Its `on_start` loads the pipeline once; job handlers reuse the same Python object. Refactor TRELLIS generation and the audio handlers accordingly. A fresh model subprocess for every job defeats this requirement.

Start with one process per GPU, one task at a time, zero always-on workers, explicit provider retries disabled, and a configurable finite idle window, initially five minutes. Keep approved weights in persistent model storage and compiled dependencies in pinned images or verified runtime archives. Normal jobs must not rebuild their environment or fetch unselected checkpoints.

Group queued jobs that use the same compatible checkpoint, precision, and adapter set. Different prompts or seeds must not force a reload. Bound reordering so another model's jobs are not starved. Stream a small amount of work to Beam while the rest remains in the local ledger; provider queue capacity and expiry must not define how many jobs CGC can retain.

Expose GPU concurrency and idle-window settings. Start with one GPU allocation overall, counting active and idle-warm allocations. When switching model queues under that limit, drain and retire the old idle worker before starting the next. Do not silently spin up one GPU for every model in a bulk file.

Record worker session ID, checkpoint revision, actual GPU, model-load count, and separate load/inference times. Prove multiple jobs use the same loaded instance. Cached weights alone do not prove warm reuse. Worker failure or redeployment may require loading again.

Keep provider task IDs and result locations in the ledger. Retain remote results long enough for explicit collection after disconnection; document the retention period. Do not rely solely on an expiring public result URL. Use authenticated persistent Beam storage with a small file-transfer interface as an implementation detail, not a new asset-management application. Qualify upload/download integrity and availability before calling detached execution complete.

## 5. Example: Codex carries the workflow

Implemented CLI example:

```sh
# Queue several Qwen images. Final files will be ordinary PNGs in this directory.
cgc image generate "Single full-body frontier mechanic in a retrofitted pressure suit" \
  --model qwen-image-2.1 --transparent --count 4 \
  --output-dir ./assets/reference/V2/characters/expanse/mechanic --enqueue --json

# Codex waits, views the PNGs using its existing file/image tools, and picks a file.
cgc jobs wait JOB_ID_1 JOB_ID_2 JOB_ID_3 JOB_ID_4 --json

# Codex describes an edit to that target, optionally using other reference images.
cgc image edit "Keep the suit and pose. Replace the glossy armor with worn canvas panels." \
  --model qwen-image-2.1 \
  --input ./assets/reference/V2/characters/expanse/mechanic/0002.png \
  --transparent -o ./assets/reference/V2/characters/expanse/mechanic/0002-edit.png

# Only if a model is wanted, Codex submits that PNG to TRELLIS.
cgc model generate --model trellis2 \
  --reference ./assets/reference/V2/characters/expanse/mechanic/0002-edit.png \
  --resolution 1024 --texture-size 2048 \
  -o ./assets/models/V2/characters/expanse/mechanic-draft.glb
```

If images satisfy the request, Codex stops after the PNGs. If a model is needed, it targets a PNG with `model generate`. It can then use Blender's existing tools on the GLB. CGC does not decide to continue on its own.

## 6. Implementation order and completion checks

1. **File-based queue:** SQLite ledger, output reservations, background worker, streaming bulk import, status/wait/collect/cancel/retry, and JSON responses. Verify restart recovery, duplicate import prevention, path quoting, source snapshots, output collisions, collection after disk-full errors, and uncertain remote outcomes.
2. **Qwen on Beam:** implement generation with optional references, editing with a required target and optional references, and transparent output. Test the distinct file roles and recorded image ordering. Keep Base/Turbo sampling correct and expose only qualified controls. Prove at least three compatible jobs use one loaded pipeline and place verified outputs/receipts on disk.
3. **TRELLIS wrapper:** accept a local image and return a local textured GLB with sidecars. Reuse the resident pipeline and add saved-latent export through the actual existing function. Run a Codex-driven PNG-to-GLB test without manual cloud operations.
4. **Character voice suite:** move tested speech/design/clone handlers onto the queue. Produce a reusable character reference, several lines in that voice, and delivery variants. Validate spoken content and review identity consistency. Preserve real adapter limits; qualifying a new speech backend does not imply all checkpoints share its controls.
5. **SFX and music suite:** qualify MOSS-SoundEffect v2.0 and ACE-Step 1.5 on Beam, or select an explicit replacement if a candidate fails. Deliver one-shots, ambience, instrumental music, supplied-lyrics generation, and reference-conditioned music. Qualify the documented music source-edit/stem operations on their required checkpoints. Validate the real local WAVs, durations, and supported controls. Prove warm reuse for each worker and test deterministic game-audio processing separately.
6. **StarFall exercise:** Codex reads its current V2 briefs, queues candidates, inspects local files, edits one, and generates a chosen 3D draft plus character lines, SFX, and a music cue. Check the GLB and audio with actual game tools. Do not claim a rig or game-ready model from a static import. Respect scale/axes and preserve originals.
7. **Additional operations when needed:** qualify TRELLIS mesh texturing, any specific reusable Blender wrapper, and later larger-model Modal workers. Add commands only when their implementation and file contracts exist.

Completion means Codex can use the CLI to produce reference-guided images, edit targets with supporting references, optionally reconstruct models, and generate character voices, SFX, and music as actual files. A large backlog must survive queue-worker restart; compatible jobs must reuse model memory; and successful jobs must leave verified files at their requested paths. No MCP integration or custom AI runner is part of completion.
