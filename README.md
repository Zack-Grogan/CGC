# CGC: CLI generation queue

CGC (Creative Generation Control) is a personal CLI tool for image, 3D, motion, and audio workflows. It queues remote generation and writes results to local paths. Codex or another CLI client can drive it. There is no AI orchestrator or MCP service.

Generation runs on Beam. The local control layer needs Python 3.11+ and uses SQLite for durable job state. Help, plans, and queue inspection do not load a model. The Beam client runs in `.backends/beam`; model libraries and weights stay on remote workers. Local MLX adapters remain available explicitly with `--backend local`.

The [creative toolbox guide](docs/CREATIVE_TOOLBOX.md) maps the complete workflow, engine requirements, quality checks, and work that still needs artistic judgment. Workers scale to zero. There is no required always-on host or GPU.

## Install from source

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
git clone https://github.com/Zack-Grogan/CGC.git
cd CGC
uv tool install --editable .
cgc --help
cgc capabilities --json
```

Keep the checkout in place: the editable installation and local state use it. The default Beam backend uses Python 3.12 in an isolated environment:

```sh
cgc setup beam
.backends/beam/bin/beam login
```

Help and offline tests need no cloud credentials. Remote generation requires your own Beam account, credits, and access to the required models. Published worker image IDs refer to the original workspace; another account may need to build the worker images from the retained recipes. See [public setup notes](docs/PUBLIC_SETUP.md) before running generation.

The repository excludes `.cgc/`, `.backends/`, and `outputs/`. These directories hold local queue state, installed backends, and generated media. Git operations do not remove them.

## Commands

```sh
cgc capabilities --json
cgc image generate "A full visual brief" --accept-license -o ./concept.png
cgc image generate "Use this shape and this material palette" \
  --reference ./shape.png --reference ./materials.png --accept-license -o ./new.png
cgc image edit "Keep the pose; use the reference equipment" \
  --input ./character.png --reference ./equipment.png --accept-license -o ./edited.png
```

The default image profile is Qwen Image 2.1 Turbo on Beam. Select `--model qwen-image-2.1` for Base. Editing uses `--input` for the target and repeated `--reference` for supporting images. Generation also accepts references. The adapter passes an ordered image list to Qwen; it does not guarantee exact preservation of unrequested pixels.

Use `--transparent` to request and validate alpha output. Use `--width` and `--height`, or `--size` and `--aspect`, for dimensions. `--seed` is recorded. Turbo uses its saved eight-step schedule. Base defaults to 40 steps.

Use `--quality draft|standard|detail` for documented compute budgets. Explicit controls take precedence. A detail profile does not guarantee a better result. The [native-control guide](docs/MODEL_QUALITY_CONTROLS.md) lists actual model parameters, fixed schedules, unsupported controls, and upstream cookbooks.

```sh
cgc image generate "A single isolated frontier cargo crate" --transparent \
  --count 4 --output-dir ./crate-candidates --seed 42 --accept-license --enqueue --json
```

`--count` reserves numbered files in the output directory and returns one job ID per generation. Without `--enqueue`, the CLI waits for completed local files. With `--enqueue`, it starts the queue worker and returns promptly after admission. Existing files and run records are never overwritten.

## Images to 3D

```sh
cgc model generate --reference ./selected.png --resolution 1024 \
  --texture-size 2048 --decimation-target 100000 --save-latents -o ./draft.glb
cgc model generate --from-latents ./draft_latents.pt \
  --texture-size 1024 --decimation-target 50000 -o ./smaller.glb
cgc model texture --input ./clean-static-mesh.glb --reference ./selected.png \
  --resolution 512 --texture-size 1024 --seed 42 -o ./textured.glb
```

The TRELLIS profile reuses the approved RTX 4090 runtime and persistent weights from image-to-3dlab. It retains policy checks, the BRIA exclusion, encoder provenance, and license sidecars. The default project is the sibling `image-to-3dlab` directory; set `CGC_3DLAB_ROOT` if it lives elsewhere. A missing runtime or weight set fails rather than silently bootstrapping another route.

Generated GLBs use standard textures for Bevy compatibility. A GLB is a reconstruction draft. Generation does not supply a rig, skin weights, separated moving parts, collision, or ship interiors.

Existing-mesh texturing replaces UVs and materials while checking world triangles, winding, and node transforms. Its preflight rejects degenerate triangles and ambiguous ownership before inference. Any source cleanup must be explicit; the [control guide](docs/MODEL_QUALITY_CONTROLS.md) includes the reproducible qualification recipe.

A fitted four-view review is available through local Blender:

```sh
cgc asset render --input ./draft.glb --output-dir ./draft-review --size 1024 --samples 48 --json
```

## Character motion

Rig a generated character before retargeting motion:

```sh
cgc model rig --input ./character.glb --seed 42 -o ./character-rigged.glb
cgc model skin --input ./character-with-skeleton.glb --seed 42 -o ./character-skinned.glb
```

TokenRig uses native texture transfer. Supplied-skeleton skinning rebuilds the output rig and requires retargeting existing animation.

```sh
cgc motion generate "A person walks forward at a steady pace." \
  --duration 4 --steps 100 --seed 42 --accept-license -o ./walk.npz
```

Kimodo SOMA-RP-v1.2 generates motion on a 77-joint source skeleton. It uses the verified Nous Llama 3 mirror with both LLM2Vec adapters. The models stay loaded between queued jobs. The local NPZ must be retargeted to a character rig before game playback. See [the motion guide](docs/KIMODO.md) for the pinned components and file contract.

Video capture, segmentation, part splitting/completion, and face weights are also available:

```sh
cgc motion extract --input ./action.mp4 --camera-mode static --accept-license -o ./capture.pt
cgc motion convert --input ./capture.pt -o ./capture.npz
cgc model views --input ./ship.glb -o ./ship-views.zip
cgc model segment --views ./ship-views.zip --points ./points.json --view 0 -o ./labels.npz
cgc model split --input ./ship.glb --labels ./labels.npz --label 1 -o ./parts.glb
cgc model complete --input ./parts.glb --part selected --seed 42 -o ./completed.glb
cgc audio face --input ./dialogue.wav --accept-license -o ./face-weights.npz
```

The [enhancement guide](docs/ENHANCEMENT_SETUP.md) defines each file contract, the live test evidence, and the limits of the reconstructed geometry and SDK Mark facial basis.

## Character voices

```sh
cgc audio design "Docking checks complete. Ready when you are." \
  --direction "An adult frontier mechanic, low warm voice, calm and clear" \
  -o ./voice-reference.wav
cgc audio clone "Get clear of the airlock!" \
  --reference ./voice-reference.wav \
  --transcript "Docking checks complete. Ready when you are." \
  --direction "An urgent shouted warning, keep the same speaker" --consent \
  -o ./warning.wav
cgc audio speak "System checks complete." -o ./system-message.wav
```

Design and clone use VoxCPM2. Plain speech uses Phonon on CPU. Save the selected reference WAV and its exact transcript, then reuse them for later character lines. `--text-file` and `--transcript-file` read local text files. Dialogue batches are ordinary queue entries with distinct output paths. Delivery control and speaker continuity require listening; a valid WAV is not a performance rating.

Speech inputs are bounded per job. Remote clone references use complete PCM16 WAV, at most 60 seconds and 8 MiB. Use generated voices or recordings you have permission to use. Nonverbal efforts can be auditioned with the SFX model; do not assume they match a speech character's identity.

## SFX and music

```sh
cgc audio sfx "Heavy powered hatch opens, pneumatic hiss, metallic stop, no music" \
  --duration 4 -o ./hatch.wav
cgc audio sfx "Quiet engine hum and ventilation inside a spacecraft cabin" \
  --duration 6 --count 3 --output-dir ./ambience --enqueue --json
cgc audio music generate "Tense orbital exploration, dark synthesizers, restrained percussion" \
  --instrumental --duration 30 -o ./orbital-cue.wav
cgc audio music generate "Warm electronic song with clear English vocals" \
  --lyrics-file ./lyrics.txt --language en --duration 30 -o ./song.wav
```

SFX uses MOSS-SoundEffect v2.0, with a maximum 30-second generation. It accepts text, not reference-image or reference-audio conditioning. Instrumental music defaults to ACE-Step 1.5 Turbo; supplied lyrics default to the Base profile. Use `--language en` for the tested English vocal route. Music style references use `--reference`; source-audio operations use `--input`.

```sh
cgc audio music generate "A quieter arrangement in this musical style" \
  --reference ./style.wav --instrumental --duration 30 -o ./new-cue.wav
cgc audio music repaint "Replace this passage with restrained percussion" \
  --input ./orbital-cue.wav --start 3 --end 8 -o ./repaint.wav
cgc audio music cover "Sparse atmospheric synthesizer arrangement" \
  --input ./orbital-cue.wav -o ./cover.wav
cgc audio music extract --model ace-step-1.5-base \
  --input ./orbital-cue.wav --track drums -o ./drums.wav
cgc audio music layer "Warm sustained strings" --model ace-step-1.5-base \
  --input ./orbital-cue.wav --track strings -o ./strings.wav
cgc audio music complete "Restrained industrial arrangement" --model ace-step-1.5-base \
  --input ./orbital-cue.wav --tracks drums,bass -o ./completed.wav
```

Base-only operations reject a Turbo profile. Generated stems are not guaranteed to reconstruct the source mix exactly or to align as adaptive game music. Use `cgc media audio` for explicit fades, channel conversion, loudness, encoding, and loop preparation. Keep the original lossless output. A prompt requesting a loop does not prove a seamless boundary.

## Media finishing and engine delivery

CGC includes local finishing commands that preserve source files and write hashed receipts:

```sh
cgc media setup
cgc media inspect --input ./warning.wav --json
cgc media audio --input ./warning.wav --profile game --lufs -18 \
  --fade-in .005 --fade-out .01 -o ./warning-game.wav --json
cgc media image --input ./concept.png --role basecolor --color-action to-srgb \
  --assume-srgb --max-size 1024 -o ./concept-game.png --json
```

The chosen loudness is a caller setting. Color images, normal maps, and material masks need different processing. `media pack` and `media channel` prepare explicit glTF ORM and Unity metallic/smoothness maps. See [media finishing](docs/MEDIA_FINISHING.md) for precision limits, true-peak checks, loop overlap, Vorbis delivery, ICC handling, and linear-light resizing.

```sh
cgc validate setup
cgc validate gltf --input ./draft.glb --json
cgc asset clean --input ./draft.glb --output ./draft-clean.glb --json
cgc asset inspect --input ./draft.glb --json
cgc asset render --input ./draft.glb --output-dir ./draft-review --json
cgc asset prepare --input ./draft.glb --engine bevy \
  --lod-ratios .5,.25 --output-dir ./game-asset --json
```

The official Khronos validator checks glTF independently of engine imports. Static asset packages retain the original, a GLB master, optional LODs, declared scale/facing, material maps, and engine instructions. Convex collision is opt-in; select the intended nodes and inspect the result. Unity/Unreal profiles add FBX derivatives. Unity needs a supported importer for GLB. Engine profiles do not install project integrations. See [game asset delivery](docs/GAME_ASSET_PIPELINE.md) and [standards validation](docs/STANDARDS_VALIDATION.md).

`asset clean` explicitly removes exactly zero-area triangles and unused vertex slots from supported static GLBs, then requires an official standards pass. It preserves surviving attribute samples, textures, materials, transforms, and the original file. It does not remove an invented stand or repair an incorrect design. Retained normals change only with explicit `--normalize-normals`; unsupported repairs fail clearly.

`cgc animation retarget`, `animation prepare`, and `animation face` deliver compatible character clips and explicit facial mappings. They support named clips, root-motion/loop settings, GLB, and Unity/Unreal FBX packages. See [animation delivery](docs/ANIMATION_WORKFLOW.md). A compatible rig and reviewed deformation remain necessary.

## Queue and recovery

```sh
cgc queue add ./jobs.ndjson --accept-license --consent --json
cgc jobs list --limit 100 --json
cgc jobs show JOB_ID --json
cgc jobs wait JOB_ID OTHER_JOB_ID --json
cgc queue configure --keep-warm-seconds 60 --json
cgc queue pause --json
cgc queue resume --json
cgc jobs cancel JOB_ID --json
cgc jobs collect JOB_ID --json
cgc jobs retry JOB_ID --json
cgc queue cool --json
```

Each NDJSON row describes an individual generation:

```json
{"operation":"image.generate","prompt":"A single isolated cargo crate","model":"qwen-image-2.1-turbo","output":"./crate.png","transparent":true,"seed":42}
```

References and outputs resolve against the caller's working directory. Inputs are snapshotted before admission; changing the original file later does not change a queued job. Reimporting unchanged rows from the same import file returns their existing jobs. Permission acknowledgments come from CLI flags, not job-file fields.

The backlog is stored locally without a 50-job cap. The worker favors compatible queued models within a bounded service interval. It uses one inference process per GPU and one CGC GPU allocation at a time, including a prior warm worker when switching models. A healthy worker retains its loaded model for subsequent jobs; idle workers scale down after the configured window (60 seconds by default). `queue configure --keep-warm-seconds` changes the window; `CGC_KEEP_WARM_SECONDS` overrides it. `queue cool` waits for the current local GPU client, releases the idle CGC session, and never cancels inference; pause new dispatch first when draining a backlog. Crashes and code/profile changes can require reloading.

State lives in `CGC/.cgc/`, independent of your working directory. `CGC_STATE_DIR` selects another state directory. Concurrent CLI clients must share the same state directory for a given Beam workspace/profile set. Do not run separate state directories against those same profiles or output files. Logs and receipts are placed beside outputs; `.remote.json` retains provider task IDs and `.result.json` retains hashes, model/runtime details, session IDs, and timings.

Closing a terminal detaches from the background queue. If the Mac sleeps, submitted Beam tasks may continue; further dispatch and collection resume when the worker runs again. `queue start` restarts a stopped worker and reconciles known remote tasks. Unknown submission outcomes are not retried automatically. `jobs collect` retrieves a retained result; `jobs retry` requires a confirmed failed/cancelled provider attempt and preserves prior records.

Recovery reconciles an active provider task before dispatch. Output locks, atomic receipts, snapshot verification, and disk-space checks protect concurrent clients. The [queue reliability guide](docs/QUEUE_RELIABILITY.md) describes the tested disconnect/recovery behavior and remaining operational boundaries.

## Setup and validation

```sh
cgc setup beam
.backends/beam/bin/beam login
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s beam -p 'test_*.py' -q
```

Use the installed Beam CLI's normal authentication. No secrets belong in repository files. The built worker images are tied to the current Beam workspace; their recipes are retained in `cgc/remote_client.py`. Model and component revisions are recorded separately from package/image versions.

Remote execution consumes Beam credits. Idle warm time and host memory also cost money. Task timeouts and queue admission are not provider spending caps. Qwen's restricted weight terms require `--accept-license` for execution; this acknowledges your applicable rights and does not purchase or grant a license.

See [the implementation evidence](docs/IMPLEMENTATION_STATUS.md), [the queue design](PLAN.md), and [the audio capability mapping](docs/AUDIO_SUITE.md). Earlier Mac/one-shot usage remains in [LEGACY_USAGE.md](docs/LEGACY_USAGE.md); it does not describe the new defaults.

## License

CGC source code is available under the [MIT License](LICENSE). Model weights, upstream components, and generated content remain subject to their respective terms; this license does not replace them.
