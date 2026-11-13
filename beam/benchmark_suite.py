#!/usr/bin/env python3
"""Time each CLI subprocess through validated local completion. Plan-only by default."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

import flux3_smoke
import audio_smoke

CLIENT_TIMEOUT_SECONDS = 1800
ROOT = Path(__file__).resolve().parent
CASES = {
    'image-4090': {'script': 'flux3_smoke.py', 'args': ['--gpu', 'RTX4090'], 'config': flux3_smoke.plan('RTX4090')},
    'image-5090': {'script': 'flux3_smoke.py', 'args': ['--gpu', 'RTX5090'], 'config': flux3_smoke.plan('RTX5090')},
    'phonon-cpu': {'script': 'audio_smoke.py', 'args': ['--model', 'phonon'], 'config': audio_smoke.plan('phonon')},
    'voxcpm2-5090': {'script': 'audio_smoke.py', 'args': ['--model', 'voxcpm2', '--gpu', 'RTX5090'], 'config': audio_smoke.plan('voxcpm2', 'RTX5090')},
    'voxcpm2-4090': {'script': 'audio_smoke.py', 'args': ['--model', 'voxcpm2', '--gpu', 'RTX4090'], 'config': audio_smoke.plan('voxcpm2', 'RTX4090')},
}

DEFAULT_CASES = ['image-5090', 'phonon-cpu', 'voxcpm2-5090']

def suite_plan(names=None):
    names = names or DEFAULT_CASES
    configs = {name: CASES[name]['config'] for name in names}
    estimate = sum(p['conservative_hourly_resource_usd'] * p['timeout_seconds'] / 3600 for p in configs.values())
    return {'status': 'not_run', 'cases': configs,
            'combined_timeout_resource_estimate_usd': round(estimate, 5),
            'suggested_approval_usd': 3,
            'metric': 'Monotonic duration from CLI subprocess dispatch until successful process exit and local artifact/receipt validation.',
            'includes': ['CLI startup', 'image build or cache lookup', 'upload', 'queue and container startup',
                         'model download and load', 'generation', 'output transfer', 'local writes and validation'],
            'initialization': 'First invocation of each recipe; no persistent model cache. Provider container-image cache may be reused and is not called a warm model.',
            'billing': 'E2E time is not billable time. GPU/CPU allocation time must be checked in Beam; timeout is not a monetary cap.',
            'permissions': 'Execution requires approved combined Beam budget, authorized API access; public model checkpoints do not require any credentials. No secrets are created or transmitted by setup.'}


def validate_receipt(receipt_path):
    report = json.loads(receipt_path.read_text())
    if report.get('status') != 'generated':
        raise RuntimeError('Receipt does not say generated.')
    if 'image_sha256' in report:
        image = receipt_path.with_suffix('')
        blob = image.read_bytes()
        if not blob.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Image is not a PNG.')
        if hashlib.sha256(blob).hexdigest() != report['image_sha256']:
            raise RuntimeError('PNG digest mismatch.')
        if tuple(int.from_bytes(blob[i:i+4], 'big') for i in (16, 20)) != (1024, 1024):
            raise RuntimeError('PNG dimensions differ from the requested 1024x1024.')
    else:
        for name, meta in report['artifacts'].items():
            path = receipt_path.parent / name
            if path.parent != receipt_path.parent or Path(name).name != name:
                raise RuntimeError('Invalid artifact name.')
            blob = path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != meta['sha256']:
                raise RuntimeError('WAV digest mismatch.')
            actual = audio_smoke.describe_wav(blob)
            for key in ['sample_rate', 'channels', 'duration_seconds', 'bytes']:
                if actual[key] != meta[key]:
                    raise RuntimeError(f'WAV {key} differs from its receipt.')
    return report


def save_summary(path, summary):
    """Replace the state atomically so interruption cannot truncate prior evidence."""
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(summary, indent=2) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-max-usd', type=float)
    parser.add_argument('--case', action='append', choices=list(CASES))
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--client-timeout', type=float, default=CLIENT_TIMEOUT_SECONDS,
                        help='Wall-clock seconds per CLI, including build and queue. Not a billing cap.')
    args = parser.parse_args()
    if args.client_timeout <= 0:
        parser.error('--client-timeout must be positive.')
    names = list(dict.fromkeys(args.case or DEFAULT_CASES))
    proposal = suite_plan(names)
    if not args.execute:
        print(json.dumps(proposal, indent=2)); return 0
    if args.approved_max_usd is None or not proposal['combined_timeout_resource_estimate_usd'] * 1.25 <= args.approved_max_usd <= 3:
        parser.error('Provide the recorded combined approval, sufficient for the selected cases and no more than $3. This flag does not authorize spending.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    destination = (args.output_dir or ROOT.parent / 'outputs' / f'beam-suite-{stamp}').resolve()
    destination.mkdir(parents=True, exist_ok=False)
    summary = {**proposal, 'status': 'running', 'approved_max_usd': args.approved_max_usd,
               'client_timeout_seconds': args.client_timeout, 'results': []}
    summary_path = destination / 'summary.json'
    revision = None
    image_versions = None
    for name in names:
        case = CASES[name]
        command = [sys.executable, str(ROOT / case['script']), *case['args'], '--execute',
                   '--approved-max-usd', str(args.approved_max_usd)]
        if name.startswith('image-'):
            target = destination / f'{name}.png'
            receipt = target.with_suffix('.png.json')
            command += ['--output', str(target)]
            if revision:
                command += ['--model-revision', revision]
        else:
            target = destination / name
            receipt = target / 'report.json'
            command += ['--output-dir', str(target)]
        log = destination / f'{name}.log'
        row = {'case': name, 'command': command, 'started_at': datetime.now(timezone.utc).isoformat(),
               'status': 'running', 'log': str(log), 'receipt': str(receipt)}
        summary['results'].append(row)
        save_summary(summary_path, summary)
        started = time.perf_counter()
        try:
            with log.open('x') as stream:
                process = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                         timeout=args.client_timeout,
                                         env={**os.environ, 'PYTHONUNBUFFERED': '1', 'BETA9_SDK_TIMINGS': '1'})
            row['cli_process_seconds'] = time.perf_counter() - started
            row['return_code'] = process.returncode
            if process.returncode:
                raise RuntimeError(f'CLI failed with exit {process.returncode}; inspect the log. No automatic retry.')
            report = validate_receipt(receipt)
            row['command_to_validated_completion_seconds'] = time.perf_counter() - started
            row['finished_at'] = datetime.now(timezone.utc).isoformat()
            row['handler_seconds'] = report['handler_seconds']
            row['status'] = 'completed'
            row['actual_bill_usd'] = None
            row['bill_verification_required'] = True
            if name.startswith('image-'):
                revision = report['model_revision']
                if image_versions is not None and image_versions != report['versions']:
                    row['warning'] = 'Package versions differ between GPU runs. Comparison is not controlled.'
                image_versions = report['versions']
        except (Exception, KeyboardInterrupt) as exc:
            status = ('client_timed_out' if isinstance(exc, subprocess.TimeoutExpired) else
                      'client_interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            row.update(status=status, error=str(exc) or type(exc).__name__,
                       elapsed_until_failure_seconds=time.perf_counter() - started,
                       finished_at=datetime.now(timezone.utc).isoformat(),
                       remote_state_verification_required=True,
                       retry_warning='Client termination does not prove remote termination. Verify Beam task/container/build state before rerunning.')
            summary['status'] = status
            save_summary(summary_path, summary)
            print(json.dumps({'status': status, 'summary': str(summary_path), 'error': row['error']}, indent=2))
            return 1
        save_summary(summary_path, summary)
    summary['status'] = 'completed_pending_billing_and_media_review'
    save_summary(summary_path, summary)
    print(json.dumps({'status': summary['status'], 'summary': str(summary_path)}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
