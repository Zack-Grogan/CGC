"""Curated, source-checked adapters, not an exhaustive model leaderboard."""
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class Model:
    id: str
    name: str
    backend: str
    capabilities: tuple[str, ...]
    model_id: str
    license: str
    weights_gb: float
    notes: str
    source: str
    steps: int | None = None

    def to_dict(self):
        return asdict(self)

MODELS = {
    "klein": Model("klein", "FLUX.2 Klein 4B · 4-bit", "image",
        ("image.generate", "image.edit"), "flux2-klein-4b", "Apache-2.0", 4.62,
        "Recommended image/edit starting point for 16 GB. Distilled, 4 steps. Runtime RAM exceeds weights. Local inference not yet benchmarked.",
        "https://github.com/mflux-community/mflux/blob/main/src/mflux/models/flux2/README.md", 4),
    "z-image": Model("z-image", "Z-Image Turbo · 4-bit", "image",
        ("image.generate",), "z-image-turbo", "Apache-2.0", 5.90,
        "Alternative generator for photorealism and typography. 9 steps in MFLUX. Not an instruction-edit adapter.",
        "https://github.com/mflux-community/mflux/blob/main/src/mflux/models/z_image/README.md", 9),
    "kokoro": Model("kokoro", "Kokoro 82M · bf16", "audio", ("audio.speak",),
        "mlx-community/Kokoro-82M-bf16", "Apache-2.0", 0.36,
        "Lightweight preset-voice speech. Not voice cloning. First use may need auxiliary pronunciation assets.",
        "https://huggingface.co/mlx-community/Kokoro-82M-bf16"),
    "qwen3-clone": Model("qwen3-clone", "Qwen3-TTS 0.6B Base · 4-bit", "audio",
        ("audio.clone",), "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit", "Apache-2.0", 1.71,
        "Small cloning starting point. Requires reference recording and its exact transcript; no preset voice.",
        "https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"),
    "qwen3-clone-hq": Model("qwen3-clone-hq", "Qwen3-TTS 1.7B Base · 4-bit", "audio",
        ("audio.clone",), "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit", "Apache-2.0", 2.34,
        "Larger cloning candidate. Compare against 0.6B using your own reference; quality winner is unverified.",
        "https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit"),
    "qwen3-voice": Model("qwen3-voice", "Qwen3-TTS 1.7B CustomVoice · 4-bit", "audio",
        ("audio.speak",), "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit", "Apache-2.0", 2.31,
        "Preset voices with natural-language delivery direction. Separate weights from Base and VoiceDesign.",
        "https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit"),
    "qwen3-design": Model("qwen3-design", "Qwen3-TTS 1.7B VoiceDesign · 4-bit", "audio",
        ("audio.design",), "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit", "Apache-2.0", 2.31,
        "Describe a new voice and delivery. No reference recording or preset voice.",
        "https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit"),
}

MODELS["voxcpm2"] = Model("voxcpm2", "VoxCPM2 · 4-bit", "audio",
    ("audio.clone", "audio.design"), "mlx-community/VoxCPM2-4bit", "Apache-2.0", 2.30,
    "Tested locally for descriptive voice design and synthetic-reference cloning at 48 kHz. See benchmark report; not a blind quality winner.",
    "https://huggingface.co/mlx-community/VoxCPM2-4bit")

MODELS["phonon"] = Model("phonon", "Phonon 31M English", "audio", ("audio.speak",),
    "gradium/phonon-31m-en", "Apache-2.0", 0.25,
    "Tested: 10 seconds of intelligible English speech in 3.45 seconds on this M4. Voice is default or an embedding, not a Qwen voice name.",
    "https://huggingface.co/gradium/phonon-31m-en")

IMAGE_REPOS = {"klein": "mflux-community/flux2-klein-4b-mflux-q4",
               "z-image": "mflux-community/z-image-turbo-mflux-q4"}

MODELS.update({
    "qwen-image-2.1": Model("qwen-image-2.1", "Qwen Image 2.1 · 4-bit", "image",
        ("image.generate", "image.edit"), "qwen-image-2.1", "Qwen Image Research License (restricted)", 10.64,
        "User-requested candidate; heavy for 16 GB. Use the vision-capable edit pipeline even for text-only generation. Not an unrestricted commercial default.",
        "https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE", 40),
    "qwen-image-2.1-turbo": Model("qwen-image-2.1-turbo", "Qwen Image 2.1 Turbo · 4-bit", "image",
        ("image.generate", "image.edit"), "qwen-image-2.1-turbo", "Qwen Image Research License (restricted)", 9.96,
        "Distilled Qwen candidate; heavy for 16 GB. License and output-use restrictions require review.",
        "https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/LICENSE", 8),
    "flux3": Model("flux3", "FLUX.3 Image Klein · 4-bit", "image",
        ("image.generate", "image.edit"), "flux3-image-klein", "FLUX Kommunity License (restricted)", 5.33,
        "Tested locally at 512/1024 pixels for generation and 512 for reference edits. Precise material edits still need review. Check commercial conditions before company use.",
        "https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md", 16),
    "fibo2": Model("fibo2", "FIBO 2.0 Dev · 4-bit", "image",
        ("image.generate", "image.edit"), "fibo2", "BRIA noncommercial default; separate commercial license", 7.20,
        "User-requested FIBO generation/edit candidate. 50 steps, substantial memory; company use needs the appropriate BRIA agreement.",
        "https://huggingface.co/briaai/Fibo-2.0-dev", 50),
    "fibo2-edit": Model("fibo2-edit", "FIBO 2.0 Edit Turbo · 4-bit", "image",
        ("image.edit",), "fibo2-edit-turbo", "BRIA noncommercial default; separate commercial license", 7.20,
        "Four-step edit-only candidate. Generation is intentionally not exposed because official Turbo capability is editing.",
        "https://huggingface.co/briaai/Fibo-2.0-edit-turbo", 4),
})
IMAGE_REPOS.update({
    "qwen-image-2.1": "mflux-community/qwen-image-2-1-mflux-q4",
    "qwen-image-2.1-turbo": "mflux-community/qwen-image-2-1-turbo-mflux-q4",
    "flux3": "mflux-community/flux-3-image-klein-mflux-q4",
    "fibo2": "mflux-community/fibo-2-0-dev-mflux-q4",
    "fibo2-edit": "mflux-community/fibo-2-0-edit-turbo-mflux-q4",
})
RESTRICTED = {"qwen-image-2.1", "qwen-image-2.1-turbo", "flux3", "fibo2", "fibo2-edit"}
IMAGE_BINARIES = {"klein": "mflux-generate-flux2", "z-image": "mflux-generate-z-image-turbo",
                  "flux3": "mflux-generate-flux3", "fibo2": "mflux-generate-fibo2", "fibo2-edit": "mflux-generate-fibo2",
                  "qwen-image-2.1": "mflux-generate-qwen-2.1-edit", "qwen-image-2.1-turbo": "mflux-generate-qwen-2.1-edit"}

STYLES = {
    "raw": "",
    "editorial": "Art-directed editorial photography, thoughtful composition, tactile detail, restrained color palette. ",
    "cinematic": "Cinematic still, motivated lighting, deliberate lens choice, atmospheric depth, refined color grade. ",
    "product": "Premium product campaign, sculptural studio lighting, tactile materials, intentional negative space, crisp detail. ",
    "playful": "Playful art direction, expressive shapes, unexpected color relationships, clear visual idea, charming handcrafted detail. ",
    "interface": "Inventive high-fidelity website concept, distinctive typography and layout, strong hierarchy, polished interaction design presented as a static concept. ",
}
ASPECTS = {"square": (1, 1), "landscape": (16, 9), "portrait": (9, 16),
           "social": (4, 5), "wide": (21, 9), "1:1": (1, 1), "16:9": (16, 9),
           "9:16": (9, 16), "4:5": (4, 5), "3:2": (3, 2), "2:3": (2, 3)}
DEFAULTS = {"image.generate": "flux3", "image.edit": "flux3", "audio.speak": "phonon",
            "audio.clone": "voxcpm2", "audio.design": "voxcpm2"}
