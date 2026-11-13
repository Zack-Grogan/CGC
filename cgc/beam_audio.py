"""Isolated Beam client. Importing this module performs no network or SDK work."""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=('phonon', 'voxcpm2'), required=True)
    parser.add_argument('--operation', choices=('audio.speak', 'audio.design', 'audio.clone'), required=True)
    parser.add_argument('--text', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--direction')
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--transcript')
    parser.add_argument('--consent', action='store_true')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if args.reference:
        args.reference = args.reference.resolve()
    report_path = output.with_suffix(output.suffix + '.beam.json')
    if output.exists() or report_path.exists():
        parser.error('Refusing to overwrite output or Beam report.')
    request = {'model': args.model, 'operation': args.operation, 'text': args.text,
               'direction': args.direction, 'transcript': args.transcript,
               'speaker_consent': args.consent}
    # An explicit allowlist staging directory prevents uploading the user's checkout,
    # .env, credentials, outputs, or any unrelated source/reference files.
    worker = Path(__file__).with_name('beam_audio_worker.py')
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='cgc-beam-client-') as tmp:
        tmp = str(Path(tmp).resolve())
        previous_module = sys.modules.pop('beam_audio_worker', None)
        shutil.copyfile(worker, Path(tmp) / 'beam_audio_worker.py')
        (Path(tmp) / '.beamignore').write_text('*\n!beam_audio_worker.py\n')
        original_cwd = Path.cwd()
        sys.path.insert(0, tmp)
        try:
            os.chdir(tmp)
            module = importlib.import_module('beam_audio_worker')
            if args.reference:
                if args.reference.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('Reference must be at most 8 MiB.')
                request['reference_bytes'] = args.reference.read_bytes()
                if module.wav_info(request['reference_bytes'])['duration_seconds'] > 60:
                    raise ValueError('Reference must be at most 60 seconds.')
            module.validate_request(request)
            from beam import Image, function
            config = module.resources(args.model)
            # Exact already-published images from the verified recipe. No persistent
            # endpoint, volumes, secrets, retries, or idle keep-alive are created.
            remote = function(name=f'cgc-cli-audio-{args.model}', image=Image(image_id=module.IMAGES[args.model], python_version='python3.12'),
                              **config, retries=0, headless=False,
                              env={'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
                                   'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1', 'HF_HOME': '/tmp/hf-cgc',
                                   'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '2'})(module.generate)
            result = remote.remote(request=request)
            if not isinstance(result, dict) or not isinstance(result.get('report'), dict):
                raise RuntimeError('No verified audio returned from Beam.')
            info = module.wav_info(result.get('audio'))
            if info != result['report']['artifact']:
                raise RuntimeError('Returned audio does not match remote digest or WAV metadata.')
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as f:
                f.write(result['audio'])
            report = result['report']
            report['client_seconds'] = time.monotonic() - started
            report['reference_upload'] = args.reference is not None
            with report_path.open('x') as f:
                json.dump(report, f, indent=2)
            print(json.dumps({'output': str(output), 'report': str(report_path), 'client_seconds': report['client_seconds']}))
        finally:
            os.chdir(original_cwd)
            sys.path.remove(tmp)
            sys.modules.pop('beam_audio_worker', None)
            if previous_module is not None:
                sys.modules['beam_audio_worker'] = previous_module
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
