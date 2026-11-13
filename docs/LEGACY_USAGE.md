# Historical usage

This is the pre-migration README, retained as a record. Use the current root README for commands and defaults.

# CGC: Creative Generation Control

An expressive command line studio with local Apple-silicon image generation and Beam-backed audio: art-directed images, reference edits, speech, voice design, and authorized voice cloning. **The chosen image model is FLUX.3 Image Klein Q4 for both generation and editing.** Built for exploring many creative directions, not repeatedly showing the same company homepage.

## Current status

The proposed CLI-only remote generation queue is documented in [PLAN.md](../PLAN.md), with current implementation findings in [the source review](REMOTE_QUEUE_REVIEW.md). Codex drives the CLI using local input and output paths. The plan adds no MCP or custom AI orchestrator. The behavior below describes the existing CLI.

The planned interface supports reference-guided image generation and distinguishes an edit target from supporting references. The [game-audio suite](AUDIO_SUITE.md) adds character voices, SFX, and music to the planned scope; the new SFX/music adapters are not implemented yet.

- **Beam GPU choice: RTX5090.** GPU recipes and main VoxCPM2 audio use the verified 5090. The earlier 4090 comparison is dropped; CPU-only Phonon stays on CPU.
- **Audio now defaults to Beam:** normal `cgc audio speak`, `design`, and `clone` commands run Phonon on Beam CPU or VoxCPM2 BF16 on RTX5090. Add `--backend local` to preserve the previous MLX workflow. Other optional audio models still run locally. This is paid remote usage and sends the speech inputs to Beam; image commands remain local.

- **Installed and tested on this Mac:** MFLUX 0.24.0, MLX Audio 0.6.4, FLUX.3 Klein Q4 generation/reference editing, Phonon 31M English speech, VoxCPM2 Q4 voice design/synthetic-reference cloning, and Blender 5.2.3 LTS headless Eevee rendering.
- **Actual outputs:** saved in `outputs/`, with local receipts/logs. Phonon and both VoxCPM2 samples passed a local Whisper Tiny transcription smoke check with every intended word matched after punctuation/case normalization. This is not a blind naturalness or speaker-similarity score.
- **Resource-aware:** one heavy job at a time. The M4 mini has 16 GB unified memory and limited SSD headroom. Remaining larger model tests are limited by current space; do not download the entire catalog at once.
- **Still not established:** an overall quality winner, arbitrary production-resolution performance, real-person clone similarity, music/SFX generation, production-scale Blender animation performance, or completed Hyperframes video integration.

See [verification](VERIFICATION.md) for measured results and remaining limits, [model research](MODELS.md) for the full shortlist, and [extension guide](EXTENDING.md). The initial registry-access problem was resolved; package installation and actual inference now work.


## The one-model image workflow

FLUX.3 Image Klein Q4 is the selected default for both operations. There is no resident server to manage: each command starts a process, loads cached weights, renders, then exits and releases its working memory. Ctrl+C cancels an active job. Help/planning does not load the model.

```sh
cgc image generate "Your complete visual brief" --accept-license
cgc image edit "Your targeted change" --reference ./source.png --accept-license
```

Default quality settings are 1024 pixels on the long edge, 16 steps, Q4 weights, and low-RAM mode. The measured 1024 square generation took **243.7 seconds total** from a new process with already-downloaded weights, including **234 seconds denoising**. The remaining roughly ten seconds cover launch, loading, encoding and decoding together; pure model-load time was not separately measured. Peak backend-reported MLX memory was **3.90 GB**, not total macOS memory. This is a practical quality choice, not proof of an absolute quality ceiling or a global model winner.

FIBO stays installed as an optional edit-only comparison; no further model selection is required for normal use. Qwen is not installed because it did not fit with conservative disk headroom. Existing files and weights were left intact.

## Start without installing anything

```sh
cd /Users/zgrogan/Repos/CGC
./bin/cgc --help
./bin/cgc models
./bin/cgc doctor
./bin/cgc styles
./bin/cgc image generate "A sculptural ceramic vase on warm travertine" \
  --style product --aspect social --seed 42 --dry-run
```

`./bin/cgc` works from this project; its absolute path works from any directory. Alternatively use `python3 -m cgc` from this folder. Python 3.11+ is required for the control layer. `NO_COLOR=1` disables terminal color. Nothing is added to your shell profile.

The `cgc` command is already installed at `/Users/zgrogan/.local/bin/cgc` on your existing PATH and works from any directory. Its editable installation points at this project. Reinstall command if ever needed: `uv tool install --editable /Users/zgrogan/Repos/CGC`. No shell-profile edit was made.

## Backend setup and first real run

The image/audio environments are already installed here. These commands also document setup for a clean checkout.

The backends live in separate `.backends/image` and `.backends/audio` virtual environments, using Python 3.12. No system Python packages are modified. Setup installs pinned packages from PyPI but does not request model weights.

```sh
./bin/cgc setup image --dry-run
./bin/cgc setup image
./bin/cgc setup audio

# FLUX.3 is already cached on this Mac. For a new machine, add --download (~4.97 GiB).
./bin/cgc image generate "A hand-built wooden camera, playful studio campaign" \
  --model flux3 --style product --size 512 --seed 42 --accept-license

# Later use: cached Hugging Face assets only.
./bin/cgc image generate "A luminous paper sculpture, quiet gallery" --seed 43 --accept-license
```

`--download` controls local model/auxiliary downloads only. For local runs, CGC sets Hugging Face and Transformers offline flags unless it is given. Beam audio always needs the network: it sends text, direction, and any authorized clone reference/transcript to Beam and downloads public model weights inside the remote worker. **These flags are not a network firewall:** auxiliary libraries may have their own asset-fetching behavior. Kokoro's pronunciation/spaCy resources are a particular caveat. Do not assume complete air-gapped operation until all assets are preloaded and verified with network access disabled externally.

CGC uses explicit prequantized MFLUX repositories. Stable MFLUX's bare model alias plus `-q 4` can otherwise stage larger original weights before quantizing. `--low-ram` is enabled for image runs. Start at 512 or 768, run jobs one at a time, and leave space for macOS swap. Do not download the entire catalog onto a 25 GiB-free disk.

## Your requested image candidates

```sh
./bin/cgc models qwen-image-2.1
./bin/cgc models flux3
./bin/cgc models fibo2

./bin/cgc image generate "A complete scene description of an imaginative botanical hotel website concept" \
  --model flux3 --aspect landscape --size 768 --seed 12 --dry-run

./bin/cgc image edit "Keep the camera and materials. Turn the palette into oxblood and pale mint." \
  --model fibo2-edit --reference ./source.png --size 768 --seed 12 --dry-run

./bin/cgc image edit "Replace only the poster headline with NIGHT GARDEN" \
  --model qwen-image-2.1-turbo --reference ./poster.png --size 512 --dry-run
```

Qwen Image 2.1, FLUX.3, and FIBO 2.0 have **restricted weight licenses**, not the same Apache-2.0 terms as the smaller fallback models. The tested default is FLUX.3. CGC requires `--accept-license` before executing them. That flag is your acknowledgement that your intended use is permitted, **not a license purchase or grant**. Review the linked original model terms before making commercial company content. Download availability does not remove those terms. Qwen's approximately 9–10 GiB Q4 weights make it particularly tight on 16 GB unified memory.

## Art direction and edits

```sh
# Same subject, a different art direction. Prompt + final seed are stored in the receipt.
./bin/cgc image generate "A fictional astronomy museum's summer exhibition" \
  --style editorial --aspect portrait --size 1024 --seed 2026 --dry-run

# Repeat --reference for a multi-image composition (up to four).
./bin/cgc image edit "Use the object from image 1 in the setting from image 2, preserve its shape" \
  --reference ./object.png --reference ./setting.png --aspect landscape --dry-run
```

Styles: `raw`, `editorial`, `cinematic`, `product`, `playful`, `interface`. `interface` produces a **static concept image**, not working HTML or a website. Use actual website-building tools for interactive showcases.

Sizes specify the long edge. Aspect ratios are rounded to valid model dimensions (16 pixels, or 32 for Qwen Image). Use both `--width` and `--height` to set exact dimensions. The default 1024 is the tested practical-quality setting for FLUX.3 on this Mac; the cached cold-start test took about four minutes. Use 512 for quicker drafts. Sizes above 1024 remain unbenchmarked. These distilled defaults do not expose unsupported negative prompts or generic edit-strength controls.

## Speech and voice direction

The installed CLI uses Beam by default for its tested Phonon and VoxCPM2 adapters. No `--download` flag is required for Beam. A one-shot task is submitted for each command, with no resident endpoint, warm keep-alive, retries, or automatic local fallback. Remote outputs, SHA-256 validation, model revision, actual GPU/CPU, task ID and stage timings are saved beside the WAV. Valid media does not prove every word was spoken; listen or transcribe important narration. Phonon can stop individual chunks at an internal budget without an exposed completion flag.

```sh
cgc audio speak "Welcome to Night Garden." -o ./narration.wav
cgc audio design "Every small detail tells a bigger story." \
  --direction "A warm adult narrator, relaxed and clear" -o ./designed.wav
cgc audio clone "A new sentence in this authorized synthetic voice." \
  --reference ./designed.wav --transcript "Every small detail tells a bigger story." \
  --consent -o ./clone.wav

# Explicitly preserve the old Mac-only MLX workflow:
cgc audio speak "This stays on my Mac." --backend local
cgc audio design "This also stays on my Mac." --direction "Warm adult narrator" --backend local
```

Beam uses existing credentials from its normal CLI configuration. `cgc setup beam` installs only a pinned client in `.backends/beam`; it does not log in, create tokens, enable top-ups, or change account settings. This checkout reuses the verified, already-published Beam container images. If those images are removed or a different account cannot access them, the client fails rather than silently rebuilding. See `beam/audio_smoke.py` for the pinned image recipe.

Beam speech text, direction, and transcript are limited to 2,000 characters each per job. Remote clone references must be complete PCM16 mono/stereo WAV, at most 60 seconds and 8 MiB; other formats remain supported by applicable local models with `--backend local`. `--consent` confirms permission to use the voice; with the Beam target, the reference and its transcript are uploaded. Only the standalone worker source and requested speech inputs are sent, not the checkout, credentials, or unrelated files.

Remote Phonon uses CPU Q8 and the default voice; VoxCPM2 uses CUDA BF16 on a verified RTX5090, not the local MLX Q4 checkpoint. Beam speech supports `--voice default`; use local mode for existing Phonon voice embeddings. GPU identity is checked and a mismatch fails before model inference. VoxCPM2 jobs are capped at 512 generation tokens (at most about 82 seconds); hitting a generation cap is an error rather than a successful truncated recording. Split longer narration into separate jobs. Server execution is bounded to 300 seconds for Phonon and 600 seconds for VoxCPM2, with a 30-minute client deadline. These timeouts are not a provider billing cap. If interrupted or disconnected, the receipt says `remote_outcome_unknown`: check Beam task/container status before retrying, because killing the client does not prove remote cancellation.

```sh
./bin/cgc audio speak "Not another template. A world built around your idea." \
  --direction "Warm, conversational, a slight smile; pause after the first sentence" \
  --model qwen3-voice --voice Ryan --dry-run

./bin/cgc audio design "Welcome to the night garden." \
  --direction "An adult narrator with a low, airy voice, subtle British accent, curious and intimate" \
  --model qwen3-design --dry-run

./bin/cgc audio design "Every small detail tells a bigger story." \
  --model voxcpm2 --direction "An expressive adult storyteller, relaxed and clear" --dry-run

./bin/cgc audio clone "Here is the new narration in my own voice." \
  --reference ./my-clean-voice.wav --transcript "The exact words I said in that recording." \
  --consent --dry-run
```

- Default plain speech: **Phonon 31M English on Beam CPU**, installed and tested remotely and locally. Use `cgc audio speak "Your script" --metrics`. It uses a default preset voice, not a real-person clone.
- Default clone and voice design: **VoxCPM2 BF16 on Beam RTX5090**, with `--backend local` selecting the installed MLX Q4 variant. Both were tested with generated synthetic references. Remote stage/memory metrics are always recorded; local `--metrics` enables verbose backend reporting.
- **Qwen3-TTS 1.7B CustomVoice Q4** remains an optional, untested-here directed preset-voice candidate. Select `--model qwen3-voice` explicitly.
- **Qwen3 Base** (`qwen3-clone`, `qwen3-clone-hq`) and **Qwen3 VoiceDesign** remain optional, uninstalled comparison candidates, not the tested defaults.
- **Kokoro 82M**: small weights and preset-voice speech, not cloning. Run `cgc setup kokoro` for its additional English frontend. Its `misaki[en]` extras include sizable dependencies, so small model size does not mean tiny installation. Use `--model kokoro --voice af_heart --language a --speed 1.05`.

Use a clean recording of your own voice or a speaker who explicitly authorized the use. Reference text is mandatory in CGC to prevent an unexpected automatic speech-recognition model download. Do not use cloning to mislead people about who spoke. MLX Audio 0.6.4 does not expose a seed in its CLI, so audio sampling is not reproducibly seeded by CGC. Image seed repeatability is best effort across backend versions/hardware, not bitwise guaranteed.

## Creative briefs and repeatable content

```sh
./bin/cgc batch examples/creative-brief.json --dry-run
./bin/cgc batch examples/creative-brief.json --dry-run --json
```

A brief is versioned JSON with a list of jobs. All job schemas are validated before execution, then jobs run sequentially and stop on first failure. It can mix visual concepts and narration. Permissions (`--download`, `--consent`, `--accept-license`) and the audio target (`--backend auto|local|beam`) come from the command line, never from the brief file. Paths are relative to your current terminal directory. Use unique outputs; existing media, logs, and manifests are never deliberately overwritten. Briefs do not support dependencies on outputs that do not yet exist: run source generation before planning reference edits.

The included brief explores three fictional clients: a ceramic atelier, a nocturnal botanical hotel, and a playful running club. These are independent visual worlds, rather than crops of the company website. It is a starting asset pack, **not 15–20 finished posts, edited video, publishing, or a content calendar**. No posting is performed.

## Results and automation

Default outputs go to `CGC/outputs/` with unique names. Each real attempt records:
- the final command, prompt, model/license metadata, image seed and parameters;
- status (`running`, `completed`, `failed`, `cancelled`), timing and exit code;
- a backend log and validated nonempty PNG/WAV header on success;
- output SHA-256, actual dimensions or WAV rate/channels/duration, and parent-reference hashes for new runs.

`--output` chooses another new path. `cgc history` lists default-folder receipts; custom destinations retain their receipts next to the output but are not indexed. MLX Audio sometimes catches errors while exiting zero, so CGC also verifies that the requested output exists and has the expected media signature. This is not a subjective quality check.

Prompts, reference file paths and reference transcripts are stored in local receipts/logs. For Beam audio, text/direction and any reference audio/transcript also leave the Mac and may be retained in Beam task data. Treat these as private; do not commit or share voice references inadvertently. `.gitignore` excludes outputs and backend environments.

`--json` returns a machine-readable plan with `--dry-run`, or the completed receipt after execution. Backend stdout stays in its log in JSON mode. Batch failures include already-completed receipts, the failed job and the remaining count.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q cgc tests
```

The control layer uses only the Python standard library. Optional image/audio packages are never imported by catalog, help, planning or tests. Beam tests consume existing account credits. No account setup, top-up, subscription change, model-license purchase, GitHub publishing, or shell-profile change was performed. The requested model assets and official Blender app were installed locally.

## Blender smoke test

Blender 5.2.3 LTS is installed at `/Applications/Blender.app`, with `blender` on the existing Homebrew PATH. `scripts/blender_smoke.py` created an original procedural ring/plinth scene and verified a 320×320 headless Eevee render. The `.blend`, PNG, JSON report and log are in `outputs/benchmark-blender-eevee.*`.

```sh
blender --background --factory-startup --python scripts/blender_smoke.py
```

The smoke script intentionally refuses to overwrite its existing outputs. A second test, `scripts/blender_motion_smoke.py`, rendered 12 frames and encoded a one-second 320×320 H.264 clip at 12 fps. This verifies basic frame-sequence/MP4 export, not a finished production animation or Hyperframes integration. Keep model inference and Blender rendering sequential on this 16 GB Mac. Use Blender for camera/light/material motion and CGC for designed imagery/voice, then compose real functional website demos and these assets in Hyperframes.
