"""Isolated backend setup and offline-first, receipt-backed execution."""
from datetime import datetime, timezone
import json
import hashlib
import struct
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
import wave
import tempfile

from . import __version__
from .catalog import IMAGE_REPOS, MODELS, RESTRICTED
from .planning import ROOT, Plan, UserError

PACKAGES = {"image": ["mflux==0.24.0"], "audio": ["mlx-audio==0.6.4", "requests==2.34.2"],
            "beam": ["beam-client==0.2.211", "beta9==0.1.268"],
            "kokoro": ["mlx-audio==0.6.4", "requests==2.34.2", "misaki[en]==0.9.4"]}


def environment(download=False):
    env = os.environ.copy()
    env.update(HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", TOKENIZERS_PARALLELISM="false")
    if download:
        env.pop("HF_HUB_OFFLINE", None)
        env.pop("TRANSFORMERS_OFFLINE", None)
    else:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


def setup_commands(backend, root=ROOT):
    if backend not in PACKAGES:
        raise UserError("Backend must be image, audio, kokoro, or beam.")
    target = root / ".backends" / ("audio" if backend == "kokoro" else backend)
    cmds = []
    if not (target / "bin/python").exists():
        cmds.append(["uv", "venv", "--python", "3.12", str(target)])
    cmds.append(["uv", "pip", "install", "--python", str(target / "bin/python"), *PACKAGES[backend]])
    return cmds


def setup(backend, root=ROOT):
    if backend != "beam" and (platform.system() != "Darwin" or platform.machine() != "arm64"):
        raise UserError("The MLX backends require Apple silicon macOS. Plans and tests work elsewhere.")
    if not shutil.which("uv"):
        raise UserError("Install uv from https://docs.astral.sh/uv/getting-started/installation/ then retry.")
    free = shutil.disk_usage(root).free / 2**30
    if free < 4:
        raise UserError(f"Only {free:.1f} GiB free; keep at least 4 GiB free before backend setup.")
    for cmd in setup_commands(backend, root):
        result = subprocess.run(cmd, check=False)
        if result.returncode:
            raise UserError(f"Backend setup stopped (exit {result.returncode}). No model weights requested.")


def doctor(root=ROOT):
    backends = {}
    for name, package in (("image", "mflux"), ("audio", "mlx-audio"), ("beam", "beam-client")):
        python = root / ".backends" / name / "bin/python"
        info = {"installed": python.exists(), "path": str(python)}
        if python.exists():
            try:
                result = subprocess.run([str(python), "-c", f"import importlib.metadata; print(importlib.metadata.version({package!r}))"],
                                        capture_output=True, text=True, timeout=15)
                info["package_version"] = result.stdout.strip() if result.returncode == 0 else "unavailable"
                info["installed"] = result.returncode == 0
            except (subprocess.TimeoutExpired, OSError) as exc:
                info.update(installed=False, package_version="unavailable", error=str(exc))
        backends[name] = info
    tools={}
    for name,flag in (('node','--version'),('ffmpeg','-version'),('ffprobe','-version'),('blender','--version')):
        executable=shutil.which(name)
        if name=='blender' and not executable and Path('/Applications/Blender.app/Contents/MacOS/Blender').is_file():executable='/Applications/Blender.app/Contents/MacOS/Blender'
        item={'installed':bool(executable),'path':executable}
        if executable:
            try:
                result=subprocess.run([executable,flag],capture_output=True,text=True,timeout=15)
                item['version']=(result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else 'unavailable'
                item['installed']=result.returncode==0
            except (OSError,subprocess.TimeoutExpired):item.update(installed=False,version='unavailable')
        tools[name]=item
    validator=Path(root)/'.backends/gltf-validator/node_modules/gltf-validator/package.json'
    tools['gltf-validator']={'installed':validator.is_file(),'path':str(validator.parent)}
    if validator.is_file():tools['gltf-validator']['version']=json.loads(validator.read_text()).get('version')
    media=Path(root)/'.backends/media/bin/python'
    tools['media-processing']={'installed':media.is_file(),'path':str(media),'downloads_model_weights':False}
    return {"cgc_version": __version__, "root": str(root), "platform": platform.system(),
            "architecture": platform.machine(), "mlx_compatible_host": platform.system() == "Darwin" and platform.machine() == "arm64",
            "free_disk_gib": round(shutil.disk_usage(root).free / 2**30, 2), "uv_available": bool(shutil.which("uv")),
            "backends": backends, "tools":tools, "inference_checked_by_doctor": False,
            "note": "Backend presence does not establish model availability or quality. See outputs/*.json for run results."}


def preflight(plan: Plan, root=ROOT):
    if plan.backend == "remote":
        if not (root / ".backends/beam/bin/python").is_file():
            raise UserError("Missing Beam client. Run cgc setup beam first.")
        if plan.model.startswith("qwen") and not plan.parameters.get("license_acknowledged"):
            raise UserError("Qwen execution requires --accept-license for your intended use")
        return
    if plan.backend != "beam" and (platform.system() != "Darwin" or platform.machine() != "arm64"):
        raise UserError("MLX generation requires Apple silicon macOS. Use --dry-run to inspect this plan.")
    if plan.model in RESTRICTED and not plan.parameters.get("license_acknowledged"):
        raise UserError(f"{plan.model} has restricted weight terms. Review {MODELS[plan.model].source} and pass --accept-license only if your intended use is permitted. The flag does not grant rights.")
    executable = Path(plan.command[0])
    if not executable.is_file():
        raise UserError(f"Missing {plan.backend} backend. Run cgc setup {plan.backend} first (packages only).")
    output = Path(plan.output)
    if any(p.exists() for p in (output, output.with_suffix(output.suffix + ".json"), output.with_suffix(output.suffix + ".log"), output.with_suffix(output.suffix + ".beam.json"))):
        raise UserError(f"Refusing to overwrite output or manifest: {output}")
    probe = output.parent
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free / 2**30
    minimum = 0.25 if plan.backend == "beam" else 4.0
    if plan.download and plan.backend != "beam":
        minimum += MODELS[plan.model].weights_gb * 1.3
    if free < minimum:
        raise UserError(f"Only {free:.1f} GiB free near output; allow approximately {minimum:.1f} GiB for this run including a reserve.")
    if plan.backend == "beam":
        if plan.parameters.get("reference"):
            from .beam_audio_worker import wav_info
            reference = Path(plan.parameters["reference"])
            if reference.stat().st_size > 8 * 1024 * 1024:
                raise UserError("Beam reference must be at most 8 MiB; use --backend local for other audio formats.")
            try:
                if wav_info(reference.read_bytes())["duration_seconds"] > 60:
                    raise ValueError("Reference must be at most 60 seconds.")
            except (ValueError, EOFError, wave.Error) as exc:
                raise UserError(f"Beam reference requires a complete mono/stereo PCM16 WAV: {exc}") from exc
        return
    # Weights usually live on a different volume than an explicitly chosen output.
    cache = Path(os.environ.get("HF_HUB_CACHE", os.environ.get("HUGGINGFACE_HUB_CACHE", "")))
    if not str(cache) or str(cache) == ".":
        cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"
    while not cache.exists():
        cache = cache.parent
    cache_free = shutil.disk_usage(cache).free / 2**30
    if plan.download and cache_free < minimum:
        raise UserError(f"Only {cache_free:.1f} GiB free on model-cache volume; approximately {minimum:.1f} GiB needed.")


def validate_output(path: Path):
    if path.suffix == '.npz':
        import zipfile
        with zipfile.ZipFile(path) as archive:
            segmented='labels.npy' in archive.namelist()
            facial='weights.npy' in archive.namelist() and 'times.npy' in archive.namelist()
        if segmented:
            from .segmentation import inspect
        elif facial:
            from .face import inspect
        else:
            from .motion import inspect
        inspect(path)
        return
    if path.suffix == '.glb':
        from .media import inspect
        inspect(path)
        return
    if not path.is_file() or path.stat().st_size < 32:
        raise UserError("Backend did not produce the requested media file. Its exit code alone is not proof of success.")
    if path.suffix.lower() == ".png":
        with path.open("rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                raise UserError("Backend output does not have a valid PNG signature.")
    if path.suffix.lower() == ".wav":
        # IEEE-float WAV is valid but unsupported by the Python stdlib wave reader.
        with path.open("rb") as f:
            header = f.read(12)
        if header[:4] not in (b"RIFF", b"RF64") or header[8:12] != b"WAVE":
            raise UserError("Backend output does not have a valid WAV header.")


def cached_model_identity(model_key):
    repo = IMAGE_REPOS.get(model_key, MODELS[model_key].model_id)
    cache = Path(os.environ.get("HF_HUB_CACHE", os.environ.get("HUGGINGFACE_HUB_CACHE", "")))
    if str(cache) == ".":
        cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"
    ref = cache / ("models--" + repo.replace("/", "--")) / "refs/main"
    try:
        revision = ref.read_text().strip()
    except OSError:
        revision = None
    return {"repository": repo, "cached_main_revision": revision}


def artifact_info(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    info = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    with path.open("rb") as f:
        head = f.read(32)
        if path.suffix == ".png" and head[12:16] == b"IHDR":
            info.update(width=struct.unpack(">I", head[16:20])[0], height=struct.unpack(">I", head[20:24])[0])
        elif path.suffix == ".wav" and head[:4] == b"RIFF":
            f.seek(12)
            byte_rate, data_size = None, None
            for _ in range(128):
                header = f.read(8)
                if len(header) < 8:
                    break
                kind, size = header[:4], struct.unpack("<I", header[4:])[0]
                if kind == b"fmt " and size >= 16:
                    payload = f.read(16)
                    if len(payload) < 16:
                        break
                    codec, channels, sample_rate, byte_rate, _, bits = struct.unpack("<HHIIHH", payload)
                    info.update(sample_rate=sample_rate, channels=channels, bits_per_sample=bits, wav_format=codec)
                    f.seek(size - 16 + size % 2, 1)
                else:
                    if kind == b"data":
                        data_size = size
                    f.seek(size + size % 2, 1)
                if byte_rate and data_size is not None:
                    info["duration_seconds"] = round(data_size / byte_rate, 4)
                    break
    return info


def run(plan: Plan, root=ROOT, quiet=False):
    if plan.backend == "remote":
        from .remote import run as remote_run
        return remote_run(plan)
    preflight(plan, root)
    output = Path(plan.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = output.with_suffix(output.suffix + ".json")
    log = output.with_suffix(output.suffix + ".log")
    receipt = {"schema_version": 1, "cgc_version": __version__, "started_at": datetime.now(timezone.utc).isoformat(),
               "status": "running", "plan": plan.to_dict(), "model_details": MODELS[plan.model].to_dict(), "log": str(log)}
    # Exclusive creation prevents concurrent runs from racing to the same output.
    with manifest.open("x") as f:
        json.dump(receipt, f, indent=2)
    start = time.monotonic()
    try:
        with log.open("x") as f:
            if plan.backend == "beam":
                # Bound the client wait as well as the server execution. Timeout or
                # interruption does not prove that the remote task was cancelled.
                result = subprocess.run(plan.command, env=environment(True), stdout=f,
                                        stderr=subprocess.STDOUT, timeout=1800, check=False)
                code = result.returncode
            else:
                code = _run_local(plan, f, quiet)
        receipt["backend_exit_code"] = code
        if code:
            raise UserError(f"Backend exited {code}. See {log}")
        validate_output(output)
        receipt.update(status="completed", output_bytes=output.stat().st_size, artifact=artifact_info(output))
        references = plan.parameters.get("references", [])
        if plan.parameters.get("reference"):
            references = [*references, plan.parameters["reference"]]
        receipt["parent_assets"] = [artifact_info(Path(p)) for p in references]
        if plan.backend == "beam":
            remote = json.loads(output.with_suffix(output.suffix + ".beam.json").read_text())
            if remote["artifact"]["sha256"] != receipt["artifact"]["sha256"]:
                raise UserError("Beam output digest does not match the remote receipt.")
            receipt["remote"] = remote
            receipt["model_snapshot"] = {"repository": remote["model_repository"], "revision": remote["model_revision"]}
            receipt["model_details"] = {
                "id": plan.model, "backend": "beam", "model_id": remote["model_repository"],
                "precision": remote["precision"], "license": MODELS[plan.model].license,
                "source": "https://huggingface.co/" + remote["model_repository"],
                "name": "VoxCPM2 · Beam BF16" if plan.model == "voxcpm2" else "Phonon 31M English · Beam Q8",
            }
        else:
            receipt["model_snapshot"] = cached_model_identity(plan.model)
    except BaseException as exc:
        receipt.update(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed", error=str(exc))
        if plan.backend == "beam":
            receipt.update(status="remote_outcome_unknown", remote_outcome="Check Beam task/container status before any retry; client failure does not establish remote termination.")
        if isinstance(exc, subprocess.TimeoutExpired):
            raise UserError("Beam client timed out; remote outcome is unknown. Check task status before retrying.") from exc
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - start, 3)
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        with tempfile.NamedTemporaryFile(mode="w", dir=manifest.parent, prefix=".cgc-receipt-", delete=False) as temp:
            json.dump(receipt, temp, indent=2)
            temp.write("\n")
        os.replace(temp.name, manifest)
    return receipt


def _run_local(plan, f, quiet):
    proc = subprocess.Popen(plan.command, env=environment(plan.download), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")
    try:
        for line in proc.stdout:
            f.write(line)
            f.flush()
            if not quiet:
                print(line, end="", flush=True)
        code = proc.wait()
    except BaseException:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise
    finally:
        proc.stdout.close()
    return code

def history(root=ROOT, limit=10):
    output_dir = root / "outputs"
    rows = []
    for p in sorted(output_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text())
            if (isinstance(data, dict) and data.get("schema_version") == 1
                    and isinstance(data.get("status"), str) and isinstance(data.get("plan"), dict)
                    and all(isinstance(data["plan"].get(k), str) for k in ("operation", "model", "output"))):
                rows.append(data)
        except (OSError, ValueError):
            continue
        if len(rows) >= limit:
            break
    return rows
