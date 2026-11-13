"""Pure plans: argument validation, predictable outputs, no imports/downloads."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import secrets

from .catalog import ASPECTS, DEFAULTS, IMAGE_BINARIES, IMAGE_REPOS, MODELS, RESTRICTED, STYLES

ROOT = Path(__file__).resolve().parent.parent

class UserError(Exception):
    pass

@dataclass
class Plan:
    operation: str
    model: str
    backend: str
    command: list[str]
    output: str
    prompt: str
    seed: int | None
    download: bool
    warnings: list[str]
    parameters: dict

    def to_dict(self):
        return asdict(self)


def dimensions(aspect: str, size: int, width=None, height=None, multiple=16):
    if (width is None) != (height is None):
        raise UserError("Set both --width and --height, or use --aspect and --size.")
    if width is not None:
        if any(type(n) is not int or not 256 <= n <= 2048 or n % multiple for n in (width, height)):
            raise UserError(f"Width and height must be multiples of {multiple} between 256 and 2048.")
        return width, height
    if aspect not in ASPECTS:
        raise UserError(f"Unknown aspect {aspect!r}. Choose: {', '.join(ASPECTS)}")
    if type(size) is not int or size not in (512, 768, 1024, 1536, 2048):
        raise UserError("Size must be 512, 768, 1024, 1536, or 2048 (long edge).")
    w, h = ASPECTS[aspect]
    scale = size / max(w, h)
    return max(256, round(w * scale / multiple) * multiple), max(256, round(h * scale / multiple) * multiple)


def existing_file(value, label):
    p = Path(value).expanduser().resolve()
    if not p.is_file() or not p.stat().st_size:
        raise UserError(f"{label} must be an existing, nonempty file: {p}")
    return str(p)


def build_plan(operation: str, options: dict, root: Path = ROOT) -> Plan:
    if options.get("backend") == "local" and (operation.startswith(("audio.music", "model.", "motion.")) or operation == "audio.sfx"):
        raise UserError("This operation requires Beam; --backend local cannot run it. Select --backend beam explicitly.")
    if options.get("backend") == "beam" or operation.startswith(("audio.music", "model.", "motion.")) or operation == "audio.sfx":
        from .remote import plan as remote_plan
        return remote_plan(operation, options)
    if operation not in DEFAULTS:
        raise UserError(f"Unsupported operation: {operation}")
    opts = dict(options)
    for field in ("prompt", "model", "output", "style", "aspect", "transcript", "language", "voice", "direction", "backend"):
        if opts.get(field) is not None and not isinstance(opts[field], str):
            raise UserError(f"{field} must be a string.")
    for field in ("steps", "size", "width", "height", "seed"):
        if opts.get(field) is not None and type(opts[field]) is not int:
            raise UserError(f"{field} must be an integer.")
    if opts.get("speed") is not None and (type(opts["speed"]) not in (int, float)):
        raise UserError("speed must be numeric.")
    model_key = opts.get("model") or DEFAULTS[operation]
    if model_key not in MODELS:
        raise UserError(f"Unknown model {model_key!r}. Run cgc models.")
    model = MODELS[model_key]
    target = opts.get("backend") or "auto"
    if target not in ("auto", "local", "beam"):
        raise UserError("Backend must be auto, local, or beam.")
    remote = model.backend == "audio" and model_key in ("phonon", "voxcpm2") and target != "local"
    if target == "beam" and not remote:
        raise UserError(f"Beam audio supports Phonon and VoxCPM2, not {model_key}. Use --backend local.")
    if operation not in model.capabilities:
        raise UserError(f"{model_key} supports {', '.join(model.capabilities)}, not {operation}.")
    if model.backend == "image":
        irrelevant = ("voice", "language", "direction", "speed", "transcript")
    else:
        irrelevant = ("style", "aspect", "size", "width", "height", "steps")
        if operation != "audio.clone":
            irrelevant += ("reference", "transcript")
    for field in irrelevant:
        if opts.get(field) is not None:
            raise UserError(f"{field} is not supported for {operation}.")
    prompt = opts.get("prompt", "").strip()
    if not prompt:
        raise UserError("Provide a nonempty prompt or speech text.")
    suffix = ".png" if model.backend == "image" else ".wav"
    name = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    output = Path(opts.get("output") or root / "outputs" / (name + suffix)).expanduser().resolve()
    if output.suffix != suffix:
        raise UserError(f"Output must end in {suffix}.")
    if any(p.exists() for p in (output, output.with_suffix(output.suffix + ".json"), output.with_suffix(output.suffix + ".log"), output.with_suffix(output.suffix + ".beam.json"))):
        raise UserError(f"Output or its manifest already exists. Choose a new path: {output}")
    seed = opts.get("seed")
    if model.backend == "image":
        if seed is None:
            seed = secrets.randbelow(2**32)
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise UserError("Seed must be an integer from 0 to 4294967295.")
    elif seed is not None:
        raise UserError("MLX Audio 0.6.4 CLI does not expose a seed. Omit seed for audio jobs.")
    bindir = root / ".backends" / model.backend / "bin"
    warnings = []
    params = {"original_prompt": prompt, "license_acknowledged": bool(opts.get("accept_license"))}
    if model_key in RESTRICTED:
        warnings.append(f"Restricted weights: {model.license}. Review {model.source}. Execution requires --accept-license; this flag does not grant a license.")
    if model.weights_gb >= 7:
        warnings.append("Large checkpoint for 16 GB unified memory; may swap or fail. Start at 512, close other GPU-heavy apps, and benchmark before production.")
    if model.backend == "image":
        style = opts.get("style") or "raw"
        if style not in STYLES:
            raise UserError(f"Unknown style {style!r}. Run cgc styles.")
        prompt = STYLES[style] + prompt
        w, h = dimensions(opts.get("aspect") or "square", opts.get("size") if opts.get("size") is not None else 1024,
                          opts.get("width"), opts.get("height"), 32 if model_key.startswith("qwen-image") else 16)
        steps = opts.get("steps") if opts.get("steps") is not None else model.steps
        if not isinstance(steps, int) or not 1 <= steps <= 100:
            raise UserError("Steps must be between 1 and 100.")
        binary = IMAGE_BINARIES[model_key]
        if operation == "image.edit" and not binary.endswith("-edit"):
            binary += "-edit"
        cmd = [str(bindir / binary), "--model", IMAGE_REPOS[model_key], "--base-model", model.model_id, "--prompt", prompt,
               "--width", str(w), "--height", str(h), "--steps", str(steps),
               "--seed", str(seed), "--output", str(output), "--low-ram"]
        refs = opts.get("reference") or []
        if isinstance(refs, str):
            refs = [refs]
        target_image = opts.get('input')
        if target_image:
            if operation != 'image.edit':
                raise UserError('--input is an edit target; use --reference for generation.')
            refs = [target_image, *refs]
        if operation == "image.edit" or refs:
            if not refs:
                raise UserError("Image edit requires at least one --reference image.")
            refs = [existing_file(p, "Reference image") for p in refs]
            if len(refs) > 4:
                raise UserError("Use up to four reference images to bound memory on this Mac.")
            if not binary.endswith('-edit'):
                cmd[0] += '-edit'
            cmd += ["--image-paths", *refs]
        params.update(style=style, width=w, height=h, steps=steps, quantization=4, references=refs)
        if model_key == "qwen-image-2.1-turbo" and max(w, h) < 1024:
            warnings.append("Qwen 2.1 Turbo recommends 1024+ for quality; smaller smoke tests can show grid artifacts.")
        if w * h > 1024 * 1024:
            warnings.append("Large image: may exceed comfortable memory on a 16 GB Mac. Start at 768.")
    else:
        cmd = [str(bindir / "python"), "-m", "mlx_audio.tts.generate", "--model", model.model_id,
               "--text", prompt, "--output_path", str(output.parent), "--file_prefix", output.stem,
               "--audio_format", "wav", "--join_audio"]
        language = opts.get("language") or ("a" if model_key == "kokoro" else "English")
        if model_key in ("voxcpm2", "phonon"):
            if opts.get("language"):
                raise UserError(f"{model_key} does not expose language selection in this adapter.")
            language = "English checkpoint" if model_key == "phonon" else "auto from text"
        else:
            cmd += ["--lang_code", language]
        direction = opts.get("direction")
        if direction is not None:
            direction = direction.strip()
            if not direction:
                raise UserError("Voice direction must not be blank.")
        voice = opts.get("voice")
        speed = opts.get("speed")
        if operation == "audio.clone":
            if not opts.get("consent"):
                raise UserError("Voice cloning requires --consent: use your own voice or a speaker who authorized it.")
            if not opts.get("reference"):
                raise UserError("Voice clone requires --reference AUDIO and --transcript 'exact words'.")
            reference = existing_file(opts["reference"], "Voice reference")
            transcript = (opts.get("transcript") or "").strip()
            if not transcript:
                raise UserError("Provide --transcript with the exact reference words. This avoids an automatic transcription-model download.")
            if voice:
                raise UserError("Cloning uses the reference voice, not --voice.")
            cmd += ["--ref_audio", reference, "--ref_text", transcript]
            params.update(reference=reference, reference_transcript=transcript, speaker_consent=True)
        elif operation == "audio.design":
            if not direction:
                raise UserError("Voice design requires --direction describing the voice and delivery.")
            if voice:
                raise UserError("Voice design uses --direction, not a preset --voice.")
        else:
            voice = voice or ("af_heart" if model_key == "kokoro" else "default" if model_key == "phonon" else "Ryan")
            cmd += ["--voice", voice]
            params["voice"] = voice
        if direction:
            if model_key not in ("qwen3-voice", "qwen3-design", "voxcpm2"):
                raise UserError(f"{model_key} does not support CGC --direction. Use qwen3-voice, qwen3-design, or voxcpm2.")
            cmd += ["--instruct", direction]
            params["direction"] = direction
        if speed is not None:
            if model_key != "kokoro":
                raise UserError("--speed is supported only by the Kokoro adapter; use delivery direction for Qwen CustomVoice.")
            if not 0.5 <= speed <= 2:
                raise UserError("Speed must be between 0.5 and 2.0.")
            cmd += ["--speed", str(speed)]
            params["speed"] = speed
        if opts.get("metrics"):
            cmd.append("--verbose")
        params["language"] = language
        params["metrics"] = bool(opts.get("metrics"))
        if remote:
            if len(prompt) > 2000 or any(len(opts.get(key) or "") > 2000 for key in ("direction", "transcript")):
                raise UserError("Beam audio text, direction, and transcript are each limited to 2000 characters per job.")
            if model_key == "phonon" and voice != "default":
                raise UserError("Beam Phonon supports --voice default. For existing local voice embeddings use --backend local.")
            cmd = [str(root / ".backends/beam/bin/python"), str(ROOT / "cgc/beam_audio.py"),
                   "--model", model_key, "--operation", operation, "--text", prompt, "--output", str(output)]
            if direction:
                cmd += ["--direction", direction]
            if operation == "audio.clone":
                cmd += ["--reference", reference, "--transcript", transcript, "--consent"]
            params.update(execution_backend="beam", provider="Beam", gpu="RTX5090" if model_key == "voxcpm2" else None,
                          remote_model="openbmb/VoxCPM2" if model_key == "voxcpm2" else model.model_id,
                          remote_precision="BF16" if model_key == "voxcpm2" else "Q8",
                          remote_timeout_seconds=600 if model_key == "voxcpm2" else 300,
                          client_timeout_seconds=1800, automatic_retries=0)
            warnings.append("Runs on paid Beam credits: text/direction and any clone reference/transcript are sent to Beam. Public weights download in the remote worker; --download applies only to local models. No automatic retry or local fallback.")
            warnings.append("Remote runtime/precision differs from local MLX. Logs and receipts retain prompts/transcripts locally and may appear in Beam task data.")
        else:
            params["execution_backend"] = "local"
            warnings.append("Audio generation is local. Prompts, reference paths, and transcripts are recorded in the local run manifest.")
    return Plan(operation, model_key, "beam" if remote else model.backend, cmd, str(output), prompt, seed,
                bool(opts.get("download")), warnings, params)
