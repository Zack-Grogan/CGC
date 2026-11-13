"""Self-contained Beam handler. Only this source file is staged for upload."""
import hashlib
import io
import re
from pathlib import Path
import time
import wave

MODELS = {
    'phonon': ('gradium/phonon-31m-en', '92741c5b07d085ff840e26fea8ce43110b87852f'),
    'voxcpm2': ('openbmb/VoxCPM2', '32279effe8c19989596f05d353d1447f51d9e915'),
}
PACKAGES = {
    'phonon': ['ptts==0.6.0', 'huggingface_hub>=1,<2'],
    'voxcpm2': ['voxcpm==2.0.3', 'torch==2.9.1', 'torchaudio==2.9.1', 'torchcodec==0.8.1', 'soundfile>=0.13,<1'],
}
IMAGES = {'phonon': '59258f158b6ae337', 'voxcpm2': '01d319bea780aa3c'}


def wav_info(data):
    if not isinstance(data, bytes) or len(data) > 8 * 1024 * 1024:
        raise ValueError('Expected WAV bytes, at most 8 MiB.')
    with wave.open(io.BytesIO(data), 'rb') as f:
        if not f.getnframes() or f.getnchannels() not in (1, 2) or f.getsampwidth() != 2:
            raise ValueError('Expected nonempty mono/stereo PCM16 WAV.')
        if len(f.readframes(f.getnframes())) != f.getnframes() * f.getnchannels() * f.getsampwidth():
            raise ValueError('Truncated WAV sample payload.')
        return {'sample_rate': f.getframerate(), 'channels': f.getnchannels(),
                'duration_seconds': f.getnframes() / f.getframerate(),
                'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def resources(model):
    return {'cpu': 2, 'memory': '4Gi' if model == 'phonon' else '16Gi',
            'gpu': '' if model == 'phonon' else 'RTX5090',
            'timeout': 300 if model == 'phonon' else 600}


def validate_request(request):
    model, operation, text = request.get('model'), request.get('operation'), request.get('text')
    if model not in MODELS or not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Unsupported model or text length (1 to 2000 characters).')
    if (model == 'phonon' and operation != 'audio.speak') or (model == 'voxcpm2' and operation not in ('audio.design', 'audio.clone')):
        raise ValueError('Unsupported operation for selected model.')
    for key in ('direction', 'transcript'):
        value = request.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 2000):
            raise ValueError(f'{key} must be nonblank and at most 2000 characters.')
    if operation != 'audio.clone' and (request.get('reference_bytes') is not None or request.get('transcript') is not None):
        raise ValueError('Reference audio/transcript are supported only by cloning.')
    if model == 'phonon' and request.get('direction'):
        raise ValueError('Phonon does not support voice direction.')
    if operation == 'audio.design' and not request.get('direction'):
        raise ValueError('Voice design requires direction.')
    if operation == 'audio.clone':
        if not request.get('speaker_consent') or not request.get('transcript'):
            raise ValueError('Clone requires speaker consent and reference transcript.')
        if wav_info(request.get('reference_bytes'))['duration_seconds'] > 60:
            raise ValueError('Reference must be at most 60 seconds.')


def generate(request):
    import os
    print(f"CGC Beam task ID: {os.getenv('TASK_ID', 'unknown')}", flush=True)
    started = time.monotonic()
    import importlib.metadata
    import tempfile
    validate_request(request)
    model, operation, text = request['model'], request['operation'], request['text']
    repo, revision = MODELS[model]
    stages = {}
    with tempfile.TemporaryDirectory(prefix='cgc-audio-') as tmp:
        target = Path(tmp) / 'output.wav'
        if model == 'phonon':
            import ptts
            stages['import_seconds'] = time.monotonic() - started
            tick = time.monotonic()
            tts = ptts.TTS(f'hf://{repo}@{revision}', lang='en', quant='q8')
            stages['model_download_and_load_seconds'] = time.monotonic() - tick
            tick = time.monotonic()
            tts.save(str(target), text, voice='default')
            stages['generation_seconds'] = time.monotonic() - tick
            versions = {'ptts': importlib.metadata.version('ptts')}
            device = 'CPU'
            precision = 'ptts Rust CPU Q8'
        else:
            import soundfile as sf
            import torch
            from huggingface_hub import snapshot_download
            from voxcpm import VoxCPM
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA unavailable; no CPU fallback.')
            device = torch.cuda.get_device_name(0)
            print(f'Requested RTX5090; actual {device}', flush=True)
            if '5090' not in device.replace(' ', ''):
                raise RuntimeError(f'Expected RTX5090, received {device}; refusing inference.')
            stages['import_seconds'] = time.monotonic() - started
            tick = time.monotonic()
            folder = snapshot_download(repo, revision=revision, token=False)
            tts = VoxCPM.from_pretrained(folder, device='cuda', load_denoiser=False,
                                         optimize=False, local_files_only=True)
            torch.cuda.synchronize()
            stages['model_download_and_load_seconds'] = time.monotonic() - tick
            torch.cuda.reset_peak_memory_stats()
            kwargs = dict(cfg_value=2.0, inference_timesteps=10, normalize=False,
                          denoise=False, retry_badcase=False, max_len=512)
            if operation == 'audio.clone':
                if not request.get('speaker_consent') or not (request.get('transcript') or '').strip():
                    raise ValueError('Clone requires speaker consent and reference transcript.')
                reference = request.get('reference_bytes')
                if wav_info(reference)['duration_seconds'] > 60:
                    raise ValueError('Reference must be at most 60 seconds.')
                ref = Path(tmp) / 'reference.wav'
                ref.write_bytes(reference)
                kwargs.update(prompt_wav_path=str(ref), reference_wav_path=str(ref), prompt_text=request['transcript'])
            elif not (request.get('direction') or '').strip():
                raise ValueError('Voice design requires direction.')
            if request.get('direction'):
                text = f"({request['direction']}){text}"
            clean_text = re.sub(r'\s+', ' ', text.replace('\n', ' '))
            effective_token_cap = min(kwargs['max_len'], int(len(tts.tts_model.text_tokenizer(clean_text)) * 6.0 + 10))
            sample_cap = effective_token_cap * tts.tts_model.patch_size * tts.tts_model._decode_chunk_size
            tick = time.monotonic()
            audio = tts.generate(text=text, **kwargs)
            torch.cuda.synchronize()
            stages['generation_seconds'] = time.monotonic() - tick
            # Pinned VoxCPM2 emits 4 audio-codec frames per token, 1920
            # samples each. Hitting max_len does not raise upstream: reject a
            # potentially truncated utterance instead of calling it completed.
            if len(audio) >= sample_cap:
                raise RuntimeError('Speech reached the generation length cap and may be incomplete. Split the script into shorter jobs.')
            stages['generation_token_cap'] = effective_token_cap
            sf.write(str(target), audio, tts.tts_model.sample_rate, subtype='PCM_16')
            stages['peak_cuda_allocated_gib'] = torch.cuda.max_memory_allocated() / 2**30
            stages['peak_cuda_reserved_gib'] = torch.cuda.max_memory_reserved() / 2**30
            versions = {p: importlib.metadata.version(p) for p in ('voxcpm', 'torch', 'soundfile')}
            versions['cuda'] = str(torch.version.cuda)
            precision = 'PyTorch CUDA BF16'
        data = target.read_bytes()
        info = wav_info(data)
        return {'audio': data, 'report': {
            'provider': 'Beam', 'task_id': os.getenv('TASK_ID'), 'model_repository': repo, 'model_revision': revision,
            'precision': precision, 'device': device, 'resources': resources(model),
            'stages': stages, 'versions': versions, 'artifact': info,
            'handler_seconds': time.monotonic() - started,
            'actual_bill_usd': None, 'retries': 0,
            'comparison_note': 'Different runtime and precision from local MLX. No bit-equivalence claim.',
        }}
