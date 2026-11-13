#!/usr/bin/env python3
"""Plan by default; explicitly approved execution runs one short Beam GPU task."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time

MODEL = "OzzyGT/Flux_3_Image_Klein_sdnq_dynamic_4bit"
VARIANT = "sdnq-int4"
PROMPT = 'A sculptural cobalt-blue ceramic watering can with a single curved handle and a long narrow spout, centered on a pale warm stone plinth. Quiet premium studio photograph, soft daylight from the left, plain ivory background, accurate tactile glazed ceramic, a single object, no text, no extra props.'
SEED = 6101
TIMEOUT_SECONDS = 600
# Conservative: budget SDK cpu=2 as 2 physical cores / 4 vCPU.
GPU_RATES = {"RTX4090": 0.69, "RTX5090": 1.09}
HOURLY_BUDGET_USD = GPU_RATES["RTX5090"] + 4 * 0.18972 + 32 * 0.0198
PACKAGES = [
    "torch==2.9.1", "torchvision==0.24.1", "diffusers==0.42.1", "transformers>=4.57,<6",
    "accelerate>=1.10,<2", "huggingface_hub>=1,<2", "Pillow>=11,<14",
    "safetensors>=0.6,<1", "sentencepiece>=0.2,<1", "sdnq==0.2.8",
]


def plan(gpu: str = "RTX5090") -> dict:
    hourly = GPU_RATES[gpu] + 4 * 0.18972 + 32 * 0.0198
    return {
        "status": "not_run", "provider": "Beam", "gpu": gpu,
        "gpu_count": 1, "sdk_cpu_cores": 2, "host_memory_gib": 32,
        "timeout_seconds": TIMEOUT_SECONDS, "retries": 0,
        "deployment": "one-shot function, no endpoint or persistent volume",
        "model": MODEL, "variant": VARIANT,
        "precision_note": "Public CUDA SDNQ INT4 transformer/text encoder; not bit-equivalent to Mac MLX Q4.",
        "prompt_upsampling": "disabled for the exact same Mac comparison prompt",
        "prompt": PROMPT, "seed": SEED, "width": 1024, "height": 1024, "steps": 16,
        "conservative_hourly_resource_usd": round(hourly, 5),
        "ten_minute_resource_estimate_usd": round(hourly / 6, 5),
        "cost_warning": "Task timeout is not a provider-enforced billing cap. No top-up or subscription purchase.",
        "required_before_execution": [
            "User approval of Beam usage spending limit and this CUDA comparison",
            "Authorized network access to the Beam API",
            "Public model uses no credentials; same existing FLUX Kommunity terms",
            "Review current Beam resource rates, available balance and GPU availability",
        ],
        "packages": PACKAGES,
    }


def run_inference(gpu: str = "RTX5090", model_revision: str | None = None) -> dict:
    """Remote handler. Imports and model downloads happen on the GPU worker only."""
    started = time.monotonic()
    import importlib.metadata
    import torch
    import sdnq  # Register the public quantization loader.
    from diffusers import ModularPipeline
    from huggingface_hub import HfApi

    import_seconds = time.monotonic() - started
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Refusing a CPU fallback.")
    properties = torch.cuda.get_device_properties(0)
    capability = torch.cuda.get_device_capability(0)
    print("CGC GPU identity: " + json.dumps({"requested": gpu, "actual": properties.name,
                                           "capability": capability, "cuda": torch.version.cuda}), flush=True)
    if gpu.removeprefix("RTX") not in properties.name.replace(" ", ""):
        raise RuntimeError(f"Requested {gpu}, but received {properties.name} (SM {capability}).")
    if capability < (8, 9):
        raise RuntimeError(f"Unexpected capability {capability} for {properties.name}.")
    if gpu == "RTX5090" and tuple(map(int, torch.version.cuda.split(".")[:2])) < (12, 8):
        raise RuntimeError("RTX5090 requires a Blackwell-compatible PyTorch CUDA 12.8+ build.")
    load_started = time.monotonic()
    revision = model_revision or HfApi().model_info(MODEL, token=False).sha
    if not revision:
        raise RuntimeError("Could not resolve a concrete model revision.")
    # Remove the separate 9B prompt model before loading any pipeline weights.
    # A comparison smoke test must use the same exact caption as the Mac run.
    original = ModularPipeline.from_pretrained(MODEL, revision=revision, token=False)
    blocks = original.blocks
    if "prompt_upsampler" in blocks.sub_blocks:
        blocks.sub_blocks.pop("prompt_upsampler")
    # init_pipeline does not accept revision/token in Diffusers 0.42.1.
    # Rebuild the same pipeline class so both configuration and components stay pinned.
    pipe = type(original)(blocks=blocks, pretrained_model_name_or_path=MODEL,
                          revision=revision, token=False)
    pipe.load_components(dtype={"vae": torch.float32, "default": torch.bfloat16},
                         revision=revision, token=False)
    missing = [name for name in ("text_encoder", "tokenizer", "transformer", "vae")
               if getattr(pipe, name, None) is None]
    if missing:
        raise RuntimeError(f"Required components failed to load: {missing}")
    pipe.to("cuda")
    torch.cuda.synchronize()
    load_seconds = time.monotonic() - load_started
    torch.cuda.reset_peak_memory_stats()
    generated = time.monotonic()
    image = pipe(prompt=PROMPT, width=1024, height=1024, num_inference_steps=16,
                 generator=torch.Generator(device="cpu").manual_seed(SEED), output="images")[0]
    torch.cuda.synchronize()
    generation_seconds = time.monotonic() - generated
    if image.size != (1024, 1024):
        raise RuntimeError(f"Unexpected output dimensions: {image.size}")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    report = {
        **plan(gpu), "status": "generated", "model_revision": revision,
        "import_seconds": import_seconds, "cuda_version": torch.version.cuda,
        "gpu_name": properties.name, "gpu_total_gib": properties.total_memory / 2**30,
        "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
        "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
        "load_and_download_seconds": load_seconds,
        "load_timing_note": "Excludes Python imports; includes checkpoint resolution, download, loading and CUDA transfer.",
        "generation_seconds": generation_seconds,
        "handler_seconds": time.monotonic() - started,
        "image_sha256": hashlib.sha256(png).hexdigest(),
        "versions": {p: importlib.metadata.version(p) for p in
                     ["torch", "diffusers", "transformers", "accelerate", "huggingface_hub", "Pillow", "sdnq"]},
        "billing_verified": False,
    }
    return {"png": png, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", choices=list(GPU_RATES), default="RTX5090")
    parser.add_argument("--model-revision", help="Optional immutable checkpoint commit used by both GPU tests")
    parser.add_argument("--execute", action="store_true", help="Spend approved Beam credits; otherwise only print a plan")
    parser.add_argument("--approved-max-usd", type=float)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(plan(args.gpu), indent=2))
        return 0
    if args.approved_max_usd is None or not 0.5 <= args.approved_max_usd <= 3.0:
        parser.error("This one-shot recipe requires a recorded Beam approval between $0.50 and $3.00. This flag does not itself grant permission.")
    # Beam syncs the working directory. Restrict it to this isolated recipe folder.
    os.chdir(Path(__file__).resolve().parent)
    output = (args.output or Path(f"../outputs/beam-flux3-sdnq4-{args.gpu.lower()}-1024.png")).resolve()
    receipt = output.with_suffix(output.suffix + ".json")
    if output.exists() or receipt.exists():
        parser.error("Refusing to overwrite an existing image or receipt.")
    from beam import Image, function
    image = Image(python_version="python3.12", python_packages=PACKAGES).add_commands([
        "apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*"
    ])
    remote = function(
        name=f"cgc-flux3-sdnq4-{args.gpu.lower()}", cpu=2, memory="32Gi", gpu=args.gpu, gpu_count=1,
        image=image, timeout=TIMEOUT_SECONDS, retries=0,
        env={"HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
             "TOKENIZERS_PARALLELISM": "false", "HF_HOME": "/tmp/hf-cgc", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"},
        headless=False,
    )(run_inference)
    result = remote.remote(gpu=args.gpu, model_revision=args.model_revision)
    if not isinstance(result, dict) or not isinstance(result.get("png"), bytes):
        raise RuntimeError("No verified PNG returned from Beam.")
    png = result["png"]
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Remote output has no PNG signature.")
    if hashlib.sha256(png).hexdigest() != result["report"]["image_sha256"]:
        raise RuntimeError("Image digest mismatch.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as file:
        file.write(png)
    with receipt.open("x") as file:
        json.dump(result["report"], file, indent=2)
    print(json.dumps({"image": str(output), "receipt": str(receipt)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
