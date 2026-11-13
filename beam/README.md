# Beam image and audio E2E tests

Verified on November 9, 2026. These one-shot recipes run inference on Beam and save media locally. These recipes do not deploy a persistent endpoint. The main CGC audio CLI also uses Beam for its Phonon and VoxCPM2 defaults; see the project README.

## GPU selection

RTX5090 is the selected GPU. Image/audio recipes, the default benchmark suite, the GPU probe, and main CGC VoxCPM2 audio all default to RTX5090. Phonon remains CPU-only. The 4090 comparison was dropped at the user’s request; there is no pending retry. Explicit `--gpu RTX4090` and named legacy cases remain available only for deliberate future overrides. Hardware checks still reject a different allocated GPU instead of silently substituting it.

## Verified results

| Case | CLI to validated output | Important initialization detail |
|---|---:|---|
| FLUX.3 RTX 5090 | 82.49 seconds | Prepared container image, fresh model download/load. |
| Phonon CPU speech | 54.19 seconds | Includes 27.79 seconds of initial image preparation. |
| VoxCPM2 RTX 5090 design and clone | 254.09 seconds | Includes 146.47 seconds of initial image preparation. |
| Earlier FLUX.3 RTX 4090 comparison | Dropped | Earlier requests received A10G. RTX5090 was selected; no further comparison is planned. |

See `../outputs/beam-results-20261109.md` and its JSON companion for full findings. Total posted credit use, including debugging, GPU diagnostics and main-CLI audio integration, was $0.279661. Final active-container check returned an empty list. Billing can lag.

The successful image is SDNQ INT4, not bit-equivalent to the Mac MLX Q4 model. Phonon uses ptts CPU Q8; VoxCPM2 uses CUDA BF16 and a synthetic reference generated within the Beam worker. No real-person recording is uploaded.

## Commands

Use the Python interpreter with the installed Beam SDK:

```sh
cd beam
../.backends/beam/bin/python benchmark_suite.py
```

This prints a plan for image-5090, phonon-cpu, and voxcpm2-5090 without network access or model imports. A subset can be selected explicitly:

```sh
../.backends/beam/bin/python benchmark_suite.py \
  --case image-5090 --case voxcpm2-5090
```

Execution consumes Beam credits and requires applicable user authorization. The flag records that approval; it does not grant it or impose a provider spending cap:

```sh
../.backends/beam/bin/python benchmark_suite.py \
  --execute --approved-max-usd 3 \
  --case image-5090 --case voxcpm2-5090 \
  --output-dir ../outputs/NEW-UNIQUE-DIRECTORY
```

Do not overwrite or blindly rerun a prior output directory. After a timeout or interruption, verify the previous remote outcome before retrying. The suite stops on a failure; it does not retry automatically.

## Dependencies and fixes

- Python 3.12, Beam CLI 0.2.211 / beta9 0.1.268.
- PyTorch is pinned to 2.9.1, whose Linux PyPI wheel uses CUDA 12.8. Unrestricted newer Torch selected CUDA 13, incompatible with a tested Beam host's driver. No driver or security setting was changed.
- Image runtime: torchvision 0.24.1, diffusers 0.42.1 and sdnq 0.2.8, plus the declared tokenizer/model dependencies. A C++ compiler is installed in the remote image for Torch/SDNQ kernels.
- Diffusers 0.42.1 `blocks.init_pipeline` does not accept `revision` or `token`. The recipe uses the concrete pipeline constructor with those parameters and checks required components after loading.
- Phonon runtime: ptts 0.6.0.
- VoxCPM2 runtime: voxcpm 2.0.3, torch/torchaudio 2.9.1, torchcodec 0.8.1, FFmpeg and libsndfile.
- No Hugging Face token is required for these public checkpoints. No new credential or Beam secret was created.

## Measurement and safety checks

The E2E timer starts before CLI subprocess dispatch and stops after local media/receipt validation. Build/cache lookup, upload, queue/container startup, model download/load, inference, transfer and writes are included when they occur. E2E time is not billable time.

Receipts retain GPU identity, package/checkpoint versions, model load and generation durations, and output hashes. Image dimensions and WAV sample payloads are checked. The hardware guard refuses a different GPU instead of treating it as the requested model.

Remote task limits are 600 seconds for GPU work and 300 seconds for Phonon, with no automatic retries. The client has an additional 1,800-second deadline covering build and queueing. Neither is a provider dollar cap. Timeout/interruption is recorded as an uncertain remote outcome. Summary writes are atomic and SDK stage timings are enabled.

Offline checks:

```sh
../.backends/beam/bin/python -m unittest test_plan test_suite -v
```

## Sources

- https://www.beam.cloud/pricing
- https://docs.beam.cloud/v2/resources/pricing-and-billing
- https://pytorch.org/get-started/previous-versions/
- https://github.com/meta-pytorch/torchcodec
- https://huggingface.co/OzzyGT/Flux_3_Image_Klein_sdnq_dynamic_4bit
- https://huggingface.co/docs/diffusers/v0.42.1/api/pipelines/flux3
- https://huggingface.co/gradium/phonon-31m-en
- https://pypi.org/project/ptts/0.6.0/
- https://huggingface.co/openbmb/VoxCPM2
- https://pypi.org/project/voxcpm/2.0.3/
