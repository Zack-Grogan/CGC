#!/usr/bin/env python3
"""Plan-first Beam audio tests. No personal voice recording is uploaded."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time
import wave

PHONON_MODEL = 'gradium/phonon-31m-en'
VOX_MODEL = 'openbmb/VoxCPM2'
SPEECH = 'Three brands. Three completely different worlds. Welcome to Night Garden, where every detail tells a story. Take a breath, then imagine what comes next.'
REFERENCE_TEXT = 'Welcome to Night Garden. This is a clean synthetic voice reference for our local creative tools. Every small detail tells a bigger story.'
DIRECTION = 'A warm adult male narrator with a relaxed American accent, clear natural diction and a subtle smile. Conversational, not an exaggerated announcer.'
CLONE_TEXT = 'Three brands. Three completely different worlds. This new sentence uses our generated reference voice, not a real person.'
PACKAGES = {
    'phonon': ['ptts==0.6.0', 'huggingface_hub>=1,<2'],
    'voxcpm2': ['voxcpm==2.0.3', 'torch==2.9.1', 'torchaudio==2.9.1', 'torchcodec==0.8.1', 'soundfile>=0.13,<1'],
}


def plan(model='voxcpm2', gpu='RTX5090'):
    gpu = gpu if model == 'voxcpm2' else None
    memory = 16 if gpu else 4
    timeout = 600 if gpu else 300
    hourly = ({'RTX4090': 0.69, 'RTX5090': 1.09}[gpu] + 4 * 0.18972 + memory * 0.0198) if gpu else (4 * 0.05 + memory * 0.01)
    return {
        'status': 'not_run', 'provider': 'Beam', 'model': VOX_MODEL if gpu else PHONON_MODEL,
        'backend': 'PyTorch CUDA BF16' if gpu else 'ptts Rust CPU Q8',
        'gpu': gpu, 'sdk_cpu_cores': 2, 'host_memory_gib': memory,
        'timeout_seconds': timeout, 'retries': 0,
        'conservative_hourly_resource_usd': round(hourly, 5),
        'timeout_resource_estimate_usd': round(hourly * timeout / 3600, 5),
        'scope': ['voice design', 'clone the voice synthesized within the same remote job'] if gpu else ['plain English speech'],
        'recording_uploads': 'none; synthetic reference created inside the remote worker',
        'precision_note': 'Different runtime/precision from local MLX tests; not bit-equivalent.',
        'packages': PACKAGES[model],
        'billing_verified': False,
    }


def describe_wav(data):
    with wave.open(io.BytesIO(data), 'rb') as f:
        if f.getnframes() == 0 or f.getnchannels() != 1 or f.getframerate() <= 0:
            raise RuntimeError('Expected a nonempty mono WAV.')
        expected = f.getnframes() * f.getnchannels() * f.getsampwidth()
        if len(f.readframes(f.getnframes())) != expected:
            raise RuntimeError('Truncated WAV: sample payload does not match its header.')
        return {'sample_rate': f.getframerate(), 'channels': f.getnchannels(),
                'duration_seconds': f.getnframes() / f.getframerate(),
                'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def run_audio(model='voxcpm2', gpu='RTX5090'):
    started = time.monotonic()
    import importlib.metadata
    import tempfile
    from huggingface_hub import HfApi, snapshot_download
    stages = {}
    results = {}
    with tempfile.TemporaryDirectory(prefix='cgc-audio-') as tmp:
        root = Path(tmp)
        if model == 'phonon':
            import ptts
            revision = HfApi().model_info(PHONON_MODEL, token=False).sha
            stages['import_seconds'] = time.monotonic() - started
            load_started = time.monotonic()
            tts = ptts.TTS(f'hf://{PHONON_MODEL}@{revision}', lang='en', quant='q8')
            stages['model_download_and_load_seconds'] = time.monotonic() - load_started
            generation = time.monotonic()
            target = root / 'phonon-speech.wav'
            tts.save(str(target), SPEECH, voice='default')
            stages['speech_generation_seconds'] = time.monotonic() - generation
            results[target.name] = target.read_bytes()
            versions = {'ptts': importlib.metadata.version('ptts')}
            device = 'CPU'
        else:
            import soundfile as sf
            import torch
            from voxcpm import VoxCPM
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA unavailable; refusing a CPU fallback.')
            device = torch.cuda.get_device_name(0)
            if gpu.removeprefix('RTX') not in device.replace(' ', ''):
                raise RuntimeError(f'Expected {gpu}, received {device}.')
            stages['import_seconds'] = time.monotonic() - started
            load_started = time.monotonic()
            revision = HfApi().model_info(VOX_MODEL, token=False).sha
            folder = snapshot_download(VOX_MODEL, revision=revision, token=False)
            # No compiler warmup, denoiser or external text-normalization model.
            tts = VoxCPM.from_pretrained(folder, device='cuda', load_denoiser=False,
                                         optimize=False, local_files_only=True)
            torch.cuda.synchronize()
            stages['model_download_and_load_seconds'] = time.monotonic() - load_started
            torch.cuda.reset_peak_memory_stats()
            options = dict(cfg_value=2.0, inference_timesteps=10,
                           normalize=False, denoise=False, retry_badcase=False, max_len=256)
            generation = time.monotonic()
            design = tts.generate(text=f'({DIRECTION}){REFERENCE_TEXT}', **options)
            torch.cuda.synchronize()
            stages['voice_design_generation_seconds'] = time.monotonic() - generation
            reference = root / 'voxcpm2-design.wav'
            sf.write(str(reference), design, tts.tts_model.sample_rate, subtype='PCM_16')
            results[reference.name] = reference.read_bytes()
            generation = time.monotonic()
            clone = tts.generate(text=CLONE_TEXT, prompt_wav_path=str(reference),
                                 prompt_text=REFERENCE_TEXT, reference_wav_path=str(reference), **options)
            torch.cuda.synchronize()
            stages['synthetic_clone_generation_seconds'] = time.monotonic() - generation
            target = root / 'voxcpm2-clone.wav'
            sf.write(str(target), clone, tts.tts_model.sample_rate, subtype='PCM_16')
            results[target.name] = target.read_bytes()
            stages['peak_cuda_allocated_gib'] = torch.cuda.max_memory_allocated() / 2**30
            stages['peak_cuda_reserved_gib'] = torch.cuda.max_memory_reserved() / 2**30
            versions = {p: importlib.metadata.version(p) for p in ['voxcpm', 'torch', 'soundfile']}
            versions['cuda'] = torch.version.cuda
        artifacts = {name: describe_wav(data) for name, data in results.items()}
        report = {**plan(model, gpu), 'status': 'generated', 'model_revision': revision,
                  'device': device, 'stages': stages, 'versions': versions,
                  'artifacts': artifacts, 'handler_seconds': time.monotonic() - started,
                  'prompt': SPEECH if model == 'phonon' else REFERENCE_TEXT,
                  'voice_direction': DIRECTION if model == 'voxcpm2' else 'default',
                  'clone_target': CLONE_TEXT if model == 'voxcpm2' else None,
                  'comparison_warning': 'Synthetic clone input is generated on Beam, not the exact local reference. No equal-waveform claim.'}
        return {'files': results, 'report': report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=list(PACKAGES), default='voxcpm2')
    parser.add_argument('--gpu', choices=['RTX4090', 'RTX5090'], default='RTX5090')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-max-usd', type=float)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    config = plan(args.model, args.gpu)
    if not args.execute:
        print(json.dumps(config, indent=2)); return 0
    minimum = config['timeout_resource_estimate_usd'] * 1.25
    if args.approved_max_usd is None or not minimum <= args.approved_max_usd <= 3:
        parser.error(f'Recorded approval of at least ${minimum:.2f} and at most $3 is required. The flag does not grant permission.')
    os.chdir(Path(__file__).resolve().parent)
    output = (args.output_dir or Path(f'../outputs/beam-{args.model}')).resolve()
    if output.exists():
        parser.error('Use a new output directory; refusing to overwrite results.')
    from beam import Image, function
    image = Image(python_version='python3.12', python_packages=PACKAGES[args.model])
    if args.model == 'voxcpm2':
        image = image.add_commands([
            'apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 g++ && rm -rf /var/lib/apt/lists/*'
        ])
    remote = function(name=f'cgc-audio-{args.model}', cpu=2,
                      memory=f"{config['host_memory_gib']}Gi", gpu=config['gpu'] or '',
                      image=image,
                      timeout=config['timeout_seconds'], retries=0, headless=False,
                      env={'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
                           'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1', 'HF_HOME': '/tmp/hf-cgc',
                           'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '2'})(run_audio)
    result = remote.remote(model=args.model, gpu=args.gpu)
    if not isinstance(result, dict) or not isinstance(result.get('files'), dict):
        raise RuntimeError('No verified audio returned from Beam.')
    allowed = {'phonon-speech.wav'} if args.model == 'phonon' else {'voxcpm2-design.wav', 'voxcpm2-clone.wav'}
    if set(result['files']) != allowed:
        raise RuntimeError('Unexpected output filenames.')
    for name, data in result['files'].items():
        meta = describe_wav(data)
        if meta['sha256'] != result['report']['artifacts'][name]['sha256']:
            raise RuntimeError('Audio digest mismatch.')
    output.mkdir(parents=True, exist_ok=False)
    for name, data in result['files'].items():
        with (output / name).open('xb') as f: f.write(data)
    with (output / 'report.json').open('x') as f: json.dump(result['report'], f, indent=2)
    print(json.dumps({'output_dir': str(output), 'receipt': str(output / 'report.json')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
