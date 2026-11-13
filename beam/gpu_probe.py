#!/usr/bin/env python3
"""Bounded GPU identity diagnostic using the already-published test image."""
import argparse
import json
import os
from pathlib import Path
import time

IMAGE_ID = '3b68a8c844bc9956'

def inspect_gpu(requested_gpu):
    import subprocess
    import torch
    rows = []
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        rows.append({'index': i, 'name': p.name, 'capability': list(torch.cuda.get_device_capability(i)),
                     'memory_gib': p.total_memory / 2**30})
    result = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
                            capture_output=True, text=True, timeout=10)
    return {'requested_gpu': requested_gpu, 'torch': str(torch.__version__), 'cuda': torch.version.cuda,
            'cuda_available': torch.cuda.is_available(), 'devices': rows,
            'nvidia_smi': result.stdout.strip(), 'nvidia_smi_error': result.stderr.strip()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--gpu', action='append', choices=['RTX4090', 'RTX5090'],
                        help='GPU to inspect; defaults to RTX5090 only. Repeat to request explicit alternatives.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    gpus = list(dict.fromkeys(args.gpu or ['RTX5090']))
    if not args.execute:
        print(json.dumps({'gpus': gpus, 'timeout_seconds_each': 60,
                          'image_id': IMAGE_ID, 'status': 'not_run'})); return
    if args.output.exists():
        raise RuntimeError('Refusing to overwrite an earlier diagnostic.')
    os.chdir(Path(__file__).resolve().parent)
    from beam import Image, function
    reports = []
    for gpu in gpus:
        remote = function(name=f'cgc-probe-{gpu.lower()}', cpu=1, memory='4Gi', gpu=gpu, gpu_count=1,
                          image=Image.from_id(IMAGE_ID), timeout=60, retries=0, headless=False)(inspect_gpu)
        start = time.perf_counter()
        report = remote.remote(requested_gpu=gpu)
        report['cli_elapsed_seconds'] = time.perf_counter() - start
        reports.append(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(reports, indent=2))
        print(json.dumps(report), flush=True)

if __name__ == '__main__':
    main()
