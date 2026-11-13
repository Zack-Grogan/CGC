# Historical verification record

For CGC 0.2.0 remote-queue acceptance, see [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

2026-11-08, `/Users/zgrogan/Repos/CGC`, Apple M4 Mac mini with 16 GB unified memory.

## Selected default

**FLUX.3 Image Klein Q4** is the single selected image model for both generation and editing. It is already downloaded and runs through MFLUX 0.24.0. The quality default is a 1024-pixel long edge, 16 steps, and low-RAM mode. FIBO remains installed but is not the default. No additional models are being downloaded.

The `cgc` command is installed on the existing PATH at `/Users/zgrogan/.local/bin/cgc` and was verified from `/tmp`. Help launched in 0.08 seconds without loading a model. Each real job is a new process; no resident image/audio service remains after completion. Ctrl+C is the cancellation path.

## Actual local inference

| Test | Output | Total wall time | Model processing | Backend peak MLX memory | Finding |
|---|---|---:|---:|---:|---|
| FLUX.3 generation, 512 | RGB PNG, 512×512 | 167.1 s | 54 s denoising | 3.60 GB | Valid, visually coherent ceramic object; includes about 100 s first download |
| FLUX.3 generation, 1024 | RGB PNG, 1024×1024 | **243.7 s** | **234 s denoising** | **3.90 GB** | Cached new-process start, no download; coherent glaze/material detail, lighting and composition |
| FLUX.3 background edit | RGB PNG, 512×512 | 110.3 s | 104 s denoising | 4.23 GB | Object/camera retained; terracotta background followed, walnut plinth instruction only partly followed (looks like dark stone) |
| FLUX.3 color edit | RGB PNG, 512×512 | 109.9 s | 104 s denoising | 4.23 GB | Same object retained, blue changed to yellow; more original glaze texture retained than FIBO in this sample |
| FIBO 2.0 Edit Turbo color edit | RGB PNG, 512×512 | 203.2 s | 55 s denoising | 5.37 GB | Same reference/prompt as FLUX color test; convincing yellow variant and identity retention; includes about 135 s first download |
| Phonon 31M speech | Mono WAV, 24 kHz, 10.0 s | 3.45 s | Not separately captured | Not captured | All intended words matched local transcription; cached weights |
| VoxCPM2 voice design | Mono WAV, 48 kHz, 7.04 s | 60.41 s | Not separately captured | Not captured | Synthetic voice, all intended words matched; includes about 40 s first download |
| VoxCPM2 synthetic-reference clone | Mono WAV, 48 kHz, 6.40 s | 19.37 s | 13.29 s | 3.46 GB | Reference-audio path worked; all intended new words matched; no real person cloned |

“Cold” here means a fresh process using already-downloaded weights. OS file caches were not flushed and the Mac was not rebooted. No resident warm-process benchmark was performed. The approximately ten seconds outside denoising in the 1024 image run include launch, model loading, text encoding and image decoding together, **not a separately measured load time**. Backend peak MLX allocation is **not whole-system RAM usage**.

The 1024 image was decoded with Pillow and inspected visually. It has coherent ceramic texture, natural shadows and no obvious tiling seam in this sample. This is not a blind quality contest, a typography benchmark, or proof that 1024 is the maximum possible resolution. Larger resolutions and other content classes remain untested.

FIBO's faster denoising on one color edit supports it as an optional targeted-variant tool, not as a universal image-quality winner. Its installed Turbo checkpoint is edit-only. The selected FLUX.3 default covers both roles with one checkpoint.

## Audio validation

Phonon initially failed because the released backend lacked a required `requests` dependency. CGC correctly marked the attempt failed despite upstream exiting zero. Requests 2.34.2 was installed and added to the setup specification; the retry succeeded. The failed receipt remains preserved.

All successful WAVs were decoded, checked for finite nonzero audio, and transcribed locally with `mlx-community/whisper-tiny-asr-fp16` (about 79 MB). No expected text was supplied to ASR. Every word matched after punctuation/case normalization. This is an intelligibility smoke check, **not** a naturalness score or speaker-identity similarity test. Voices and transcripts were generated locally; no real-person recording was used or uploaded for inference.

## Blender

Blender **5.2.3 LTS** was installed from the official Blender download through the Homebrew cask. No security protections were disabled.

- Headless Eevee: a new procedural ring/plinth scene saved as `.blend` and rendered to a visually checked 320×320 PNG. Total process time 6.94 s; scene/script operation 3.97 s.
- Motion/export: 12 PNG frames rendered at 320×320 in 4.775 s, encoded with the existing FFmpeg to a one-second H.264 MP4 at 12 fps. FFprobe confirmed dimensions/frame count/codec/duration, and FFmpeg decoded the full clip successfully.
- These are small pipeline tests, not production animation benchmarks, Cycles/Metal ray-tracing tests, or completed Hyperframes integration.

## Software verification

- 53 automated tests pass on Python 3.14.7 and Python 3.12.13.
- Compile checks pass for `cgc`, tests and scripts.
- Actual installed backend `--help` and package versions were checked.
- Image/audio backends are separate project-local virtual environments. Package snapshots are in `requirements/`.
- Command construction, strict types, output/log/manifest collision guards, dry-run behavior, partial batch failures, subprocess cleanup, zero-exit/no-output failure detection, artifact hashes/metadata and tested defaults are covered by tests.
- Receipts for new runs include the actual checkpoint ID, cached revision, model/license metadata, output SHA-256, image dimensions or WAV properties, and parent-reference hashes. `BENCHMARK_RESULTS.json` collects all existing run evidence, including older receipts.

## Storage and remaining limits

At Qwen preflight, 9.81 GiB was free. The conservative check required about 17.8 GiB for Qwen Image 2.1 or 16.9 GiB for Turbo, including a working reserve. Both were blocked **before download/inference**. Free space later fluctuated around 10–11 GiB as macOS released working storage. No existing model, file, cache or app was removed to make room.

Qwen Image 2.1, FIBO Dev generation, Qwen audio checkpoints, Kokoro and music/SFX models remain untested here. We have not established a global best model, maximum possible resolution, production throughput, or reliability on arbitrary long scripts and edits.

The user reported having a commercial license; its exact scope was not independently verified. Public downloadability does not establish commercial rights. Model-specific terms remain linked in the catalog. These were local synthetic benchmarks, not published company content. No paid service, license purchase, external publishing or cloud GPU launch was performed by this local test task.

## Evidence

See `BENCHMARK_RESULTS.json` for hashes, snapshots, exact receipt paths and transcription checks. Full media is under `outputs/`. The standalone high-resolution sample is `outputs/benchmark-flux3-generate-1024.png`.

## Beam CLI integration, November 9, 2026

The earlier tables describe local MLX runs. The main installed `cgc` command now defaults to Beam for Phonon speech and VoxCPM2 voice design/cloning; `--backend local` preserves those local adapters. Optional Qwen/Kokoro models and image generation remain local.

Real CLI-to-local-file tests are recorded in `outputs/beam-cli-20261109/`, with full commands, subprocess wall time, receipts, Beam task IDs, decoded audio metadata/hashes, and independent local transcription checks. Container images were already published; each fresh remote worker still downloaded/loaded model weights. Timings therefore are not warm-model latency, and do not include one-time package installation or initial image publication.

The Beam backend uploads only its standalone worker source and requested speech inputs. For cloning, the reference WAV and exact transcript are transmitted to Beam; tests used generated synthetic voices only. No real person was cloned. Existing credentials and credits were used, with no top-up or subscription changes.

VoxCPM2 uses BF16 CUDA on an actual RTX5090, not the local MLX Q4 model. Phonon uses the native Q8 CPU backend. Earlier RTX4090 image allocations returned A10G; that comparison was dropped after the user selected RTX5090. No 4090 result is claimed and no retry is pending.

Validated audio and successful ASR matching are intelligibility smoke checks, not naturalness or speaker-similarity measurements. Runtime content completeness is not guaranteed for arbitrary text; Phonon's internal chunk budget does not expose an EOS/completion flag. VoxCPM2 cap hits are rejected to avoid silently accepting a potentially truncated clip.
