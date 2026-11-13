# Qwen memory controls and failed-worker containment

The StarFall prototype campaign exposed two different failure layers. A 2048-square Qwen Base image exhausted GPU memory during VAE decoding after earlier wide images had succeeded. Later requests then failed in the text encoder within seconds. Retaining an exception-interrupted VAE/offload state let one failed job affect subsequent jobs.

## Native memory controls

CGC now calls the pinned VAE's `enable_tiling()` with 256-pixel sample tiles and 192-pixel strides, plus `enable_slicing()`. The requested canvas, model, inference steps, seed, and conditioning stay unchanged. Spatial tiling addresses image-size activation pressure. Slicing operates across the batch dimension and does not itself solve a single-image spatial decode peak.

These APIs were checked in Diffusers revision `0905b667fe3f37f43b6ef9c6e05ad20636206938`. The implementation supports tiled encoding and decoding, with overlap blending. Tiling can change pixels and needs image review; it is not a visual-quality certificate. See the pinned [Qwen21 VAE](https://github.com/huggingface/diffusers/blob/0905b667fe3f37f43b6ef9c6e05ad20636206938/src/diffusers/models/autoencoders/autoencoder_kl_qwenimage21.py) and [AutoencoderMixin slicing API](https://github.com/huggingface/diffusers/blob/0905b667fe3f37f43b6ef9c6e05ad20636206938/src/diffusers/models/autoencoders/vae.py).

Successful receipts include `memory_controls`: tiling/slicing settings, tile dimensions and strides, the Diffusers revision, and `canvas_reduced: false`. Existing successful warm sessions still reuse their loaded models.

## Failure containment

The pinned pipeline frees model hooks at its successful return. An exception before that line bypasses the call. VAE feature caches also need explicit clearing after an interrupted decode. CGC now quarantines a failed Qwen session before cleanup. It then attempts VAE feature-cache clearing, pipeline hook/offload reset, and release of unreferenced CUDA cache. Cleanup errors do not replace the original failure. The pipeline reference is removed, and that resident session refuses further inference. The worker writes `failure.json` with request/task/session identity, cleanup results, and `retry_performed: false`.

The successful-return hook behavior and offload reset were checked in the pinned [Qwen pipeline](https://github.com/huggingface/diffusers/blob/0905b667fe3f37f43b6ef9c6e05ad20636206938/src/diffusers/pipelines/qwenimage21/pipeline_qwenimage21.py) and [pipeline hook implementation](https://github.com/huggingface/diffusers/blob/0905b667fe3f37f43b6ef9c6e05ad20636206938/src/diffusers/pipelines/pipeline_utils.py).

Once Beam confirms a GPU task is terminal with `ERROR`, `FAILED`, `TIMEOUT`, or `CANCELLED`, the client stops that task's provider-identified container. It records `worker_retirement`, container ID, task ID, and status in the task record and GPU lease. The failed provider identity and prior output/run records remain available.

If the local controller exits before retirement, the next GPU admission checks the old task. A terminal failure requires retirement even when the next task uses the same model and code. Successful same-model workers retain normal bounded warm reuse. Active or uncertain provider work is not stopped by the failed-task path. If retirement cannot be confirmed, new dispatch and cooldown are refused rather than reusing uncertain model state or discarding its lease.

No failed generation is retried automatically. A new paid attempt still requires the existing confirmed-failure retry path. Changing a canvas or model to avoid memory pressure is a separate explicit decision.

## Verification boundary

`tests/test_qwen_memory_recovery.py` checks native call signatures/settings, unchanged canvas controls, interrupted VAE cache/offload cleanup, preservation of the original OOM, failed-session refusal, successful warm reuse, exact terminal-container retirement, blocked admission after failed retirement, and controller recovery without a second paid submission.

The seven focused recovery tests and nine existing queue reliability tests passed without GPUs. The pinned-source API audit and source hashes are under `outputs/starfall-prototype-set-v1/runtime-recovery-research/`. The full 2048-square marine path still requires the root-controlled live qualification; these offline tests do not establish its latency, peak VRAM, or resulting image quality.
