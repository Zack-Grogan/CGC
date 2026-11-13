# Model research and selection

Checked 2026-11-08 against the published MFLUX **0.24.0** source distribution and MLX Audio **0.6.4** source/release metadata. The broad catalog is source research. A subset has now been tested locally; see VERIFICATION.md for measured evidence and limitations.

## Practical decision for this Mac

The Mac is an Apple M4 mini with 16 GB unified memory and approximately 25.6 GiB free. A checkpoint's disk size is not total working memory; text/vision encoders, activations, VAE, image dimensions and macOS all consume memory. A model can load yet swap badly or fail during decoding.

- **Start testing your requested image families with FLUX.3 Image Klein Q4** if your intended use is permitted by its terms. Its ~4.97 GiB weights are the most plausible of those named candidates on this machine. Sixteen steps are the backend default. This is a shortlist recommendation, not a quality winner.
- **Qwen Image 2.1** is a serious generation/edit candidate, but its ~9–10 GiB Q4 repositories put it near the memory ceiling before runtime overhead. Use the edit-capable pipeline for both generation and edits; the separate text-only path can leave its large encoder unquantized. Base: 40 steps. Turbo: 8 steps, guidance 1, recommends 1024+ for quality; 512 smoke output may have grid artifacts.
- **FIBO 2.0 Dev** supports generation/editing, with ~6.70 GiB Q4 weights and 50 steps. **Edit Turbo** is the four-step editing option. CGC does not expose Turbo text generation merely because the backend has an experimental path.
- **FLUX.2 Klein 4B Q4** remains the smaller Apache-2.0 fallback for image generation and editing. It is about 4.30 GiB, four steps, and reasonably aligned with this Mac. **Z-Image Turbo Q4** is an Apache-2.0 generator alternative, about 5.50 GiB, nine steps.
- **Audio:** Qwen3-TTS 0.6B Base Q4 is a conservative cloning starting point; compare 1.7B Base and VoxCPM2 against it on the same consented recording. Qwen CustomVoice offers expressive preset speech; VoiceDesign invents a voice from a description. These are different checkpoints. Tested defaults now use Phonon for plain English speech and VoxCPM2 for voice design/cloning; the Qwen audio checkpoints are comparison candidates, not installed winners.

## Image adapters

All image adapters use MFLUX 0.24.0, explicit prequantized community repositories, and `--low-ram`. No full original-weight staging is requested by CGC. It invokes a new process per job to keep model lifetimes separate.

| CGC ID | Repository | Base alias | Approx. repository size | Capability |
|---|---|---|---:|---|
| klein | mflux-community/flux2-klein-4b-mflux-q4 | flux2-klein-4b | 4.30 GiB | generate, edit |
| z-image | mflux-community/z-image-turbo-mflux-q4 | z-image-turbo | 5.50 GiB | generate |
| qwen-image-2.1 | mflux-community/qwen-image-2-1-mflux-q4 | qwen-image-2.1 | 9.91 GiB | generate, edit |
| qwen-image-2.1-turbo | mflux-community/qwen-image-2-1-turbo-mflux-q4 | qwen-image-2.1-turbo | 9.28 GiB | generate, edit |
| flux3 | mflux-community/flux-3-image-klein-mflux-q4 | flux3-image-klein | 4.97 GiB | generate, edit |
| fibo2 | mflux-community/fibo-2-0-dev-mflux-q4 | fibo2 | 6.70 GiB | generate, edit |
| fibo2-edit | mflux-community/fibo-2-0-edit-turbo-mflux-q4 | fibo2-edit-turbo | 6.70 GiB | edit |

Observed repository revisions, for later benchmark provenance (CGC does not yet pin snapshot revisions during automatic loading):

- Klein: `794cd159538149ad9830848508c31f0ea7088e58`
- Z: `f427e257d8e6ffa03edd4d9ac554a05809da456c`
- Qwen base: `b6c0fc76350650482d13aea89b316c28cd487f7f`
- Qwen turbo: `84970354375db04f65d3cd23ee7890ca11956e37`
- FLUX.3: `79c0034de040c460e9685bf0127f40af042a2abe`
- FIBO Dev: `90cb45c2017672d0e39e84b3e5c7a8be3804c8e6`
- FIBO Edit Turbo: `b7c949d7e2a9e3e6b86859a3a97a40f7318293c4`

Model cards and current sources:
- [MFLUX](https://github.com/mflux-community/mflux), [PyPI release](https://pypi.org/project/mflux/0.24.0/)
- [FLUX.2 backend](https://github.com/mflux-community/mflux/blob/main/src/mflux/models/flux2/README.md)
- [Qwen original license](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE), [Turbo license](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/LICENSE)
- [FLUX.3 original license](https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md)
- [FIBO Dev](https://huggingface.co/briaai/Fibo-2.0-dev), [FIBO Edit Turbo](https://huggingface.co/briaai/Fibo-2.0-edit-turbo)

### License distinctions for company content

“Runs locally,” “downloadable,” “open weights” and “unrestricted open-source use” are different claims.

- Qwen Image 2.1's **research license** requires reviewing permitted use and any commercial rights you separately hold.
- FLUX.3 uses **FLUX Kommunity v1**, including a qualifying commercial-output exception below its stated US$5 million threshold. Review the actual terms and entity eligibility rather than assuming all commercial use is forbidden or allowed.
- FIBO defaults to **noncommercial terms / a separate commercial agreement**. An existing commercial license may cover the intended use; CGC does not adjudicate it.
- Klein 4B, Z-Image Turbo and the listed audio checkpoints are Apache-2.0 according to their cards. The MFLUX and MLX Audio framework licenses do not override weight terms.

CGC's `--accept-license` acknowledges your assessment of the intended use. It does not accept an agreement with a provider, purchase rights, or verify an agreement's scope.

## Audio adapters

Use Python 3.12. MLX Audio is pinned to 0.6.4. Default module is `python -m mlx_audio.tts.generate` with `--output_path`, `--file_prefix`, `--audio_format wav`, and `--join_audio`; this produces one requested WAV. Qwen Base cloning takes `--ref_audio` and `--ref_text`, without a preset voice. CustomVoice takes `--voice` and optionally `--instruct`. VoiceDesign takes `--instruct`, not a preset voice. The release CLI has **no `--seed` flag**, so CGC rejects audio seeds. VoxCPM2 infers language from text; CGC omits language and preset-voice arguments because that model ignores them.

| CGC ID | Checkpoint | Approx. repository size | Intended use |
|---|---|---:|---|
| phonon | gradium/phonon-31m-en | 0.223 GB whole repo | tested plain English speech |
| qwen3-clone | mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit | 1.71 GB | clone |
| qwen3-clone-hq | mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit | 2.34 GB | clone comparison |
| qwen3-voice | mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit | 2.31 GB | directed preset speech |
| qwen3-design | mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit | 2.31 GB | descriptive voice design |
| voxcpm2 | mlx-community/VoxCPM2-4bit | 2.30 GB | clone and design, 48 kHz |
| kokoro | mlx-community/Kokoro-82M-bf16 | 0.355 GB | lightweight preset speech |

Kokoro's English frontend is a separate `misaki[en]==0.9.4` installation. Its published Python constraint excludes 3.13+, hence Python 3.12 for audio. It pulls dependencies including torch/spaCy, so its total setup is larger than its model file suggests. Qwen/VoxCPM do not need that extra.

Sources: [MLX Audio](https://github.com/Neywa-Labs/mlx-audio), [0.6.4 generate source](https://github.com/Neywa-Labs/mlx-audio/blob/v0.6.4/mlx_audio/tts/generate.py), [Qwen3 docs](https://github.com/Neywa-Labs/mlx-audio/blob/main/docs/models/tts/qwen3-tts.md), [VoxCPM2 card](https://huggingface.co/mlx-community/VoxCPM2-4bit), [Misaki](https://pypi.org/project/misaki/0.9.4/).

## Earlier local music and sound-effect research

The local candidates below are the earlier research record. The current remote suite plan evaluates MOSS-SoundEffect v2.0 on CUDA and ACE-Step 1.5 on Beam, with character-voice, SFX, and music operation mappings in [AUDIO_SUITE.md](AUDIO_SUITE.md). The remote profiles have now passed actual acceptance runs; see [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). The local routes below remain the earlier research record.

- [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) has an official Mac MLX route and MIT code/weights, but its default full repository is approximately 10.1 GB plus Python/PyTorch dependencies. The CLI is `python cli.py --config config.toml`, not a speech-style prompt command. Evaluate short 20–30 second, batch-one, 2B turbo runs with no LM first, only after a storage plan.
- [MOSS-SoundEffect MLX 4-bit](https://huggingface.co/mlx-community/MOSS-SoundEffect-MLX-4bit) is about 4.7 GB, Apache-2.0, with a separate mlx-speech script. It is a candidate for local sound effects, not a shipped CGC backend, and 16 GB feasibility remains untested.
- Stable Audio 3 MLX has a small implementation but custom weight/Gemma terms. It must not be described as MIT/open-source weights because its code is MIT.

No music/SFX package or weights were installed. The optional music/SFX candidates remain untested; local image/speech/Blender results are recorded separately in VERIFICATION.md.

## How to decide the actual winner

Use fixed representative prompts and identical references. For images: test typography accuracy, prompt obedience, brand/object preservation, local edits, material quality, visual distinction, peak memory and wall-clock time. Compare at each model's recommended settings, not just equal step counts. For speech: use the same short authorized reference, varied punctuation, names, numbers, excited/calm delivery and a longer paragraph. Listen for identity preservation, naturalness, pronunciation and seams. Keep receipts and explicitly separate first-download/first-load time from warm generation.
