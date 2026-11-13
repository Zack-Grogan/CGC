#!/usr/bin/env python3
"""Recheck the saved media-finishing fixtures without changing their sources."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, default=ROOT / 'outputs/media-finishing')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    folder = args.fixtures.resolve()
    receipts = []
    for path in sorted(folder.glob('*.quality.json')):
        report = json.loads(path.read_text())
        assert report['status'] == 'completed', f'Incomplete receipt: {path}'
        output = report['output']
        assert digest(output['path']) == output['sha256'], f'Output changed: {output["path"]}'
        sources = []
        if 'source' in report:
            sources.append(report['source'])
        sources.extend(value for value in report.get('channel_mapping', {}).values() if 'path' in value)
        for source in sources:
            assert digest(source['path']) == source['sha256'], f'Source changed: {source["path"]}'
        receipts.append({'receipt': str(path), 'operation': report['operation'],
                         'output': output['path'], 'output_sha256': output['sha256'],
                         'source_hashes_unchanged': True})
    assert len(receipts) >= 10, 'Expected the real audio, color, and material fixtures'

    pixel_check = '''import json,sys
from pathlib import Path
import numpy as np
from PIL import Image
p=Path(sys.argv[1])
s=np.asarray(Image.open(p/'trellis-metallic-roughness-source.png').convert('RGB'))
o=np.asarray(Image.open(p/'trellis-orm.png').convert('RGB'))
u=np.asarray(Image.open(p/'trellis-metallic-smoothness.png').convert('RGBA'))
assert np.all(o[:,:,0]==255) and np.array_equal(o[:,:,1],s[:,:,1]) and np.array_equal(o[:,:,2],s[:,:,2])
assert np.array_equal(u[:,:,0],s[:,:,2]) and np.all(u[:,:,1:3]==0) and np.array_equal(u[:,:,3],255-s[:,:,1])
c=Image.open(p/'display-p3-converted-srgb.png')
assert c.size==(2,2) and c.info.get('icc_profile') and np.all(np.asarray(c.getchannel('A'))==128)
print(json.dumps({'status':'passed','pixels_verified':int(s.shape[0]*s.shape[1]),'icc_conversion_alpha_unchanged':True}))
'''
    pixels = subprocess.run([str(ROOT / '.backends/media/bin/python'), '-c', pixel_check, str(folder)],
                            text=True, capture_output=True, check=True)
    tests = subprocess.run([sys.executable, '-W', 'error::ResourceWarning', '-m', 'unittest',
                            'discover', '-s', 'tests', '-p', 'test_media_quality.py', '-v'],
                           cwd=ROOT, text=True, capture_output=True)
    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert 'ResourceWarning' not in tests.stderr and 'Exception ignored' not in tests.stderr, tests.stderr
    bevy_path = folder / 'bevy-audio-decode.log'
    bevy = [json.loads(line) for line in bevy_path.read_text().splitlines() if line.startswith('{')]
    assert len(bevy) == 3 and all(value['status'] == 'passed' for value in bevy), 'Bevy decode evidence is missing'
    report = {
        'status': 'passed', 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'receipts_rechecked': receipts, 'channel_and_icc_recheck': json.loads(pixels.stdout),
        'unit_tests': {'status': 'passed', 'resource_warning_policy': 'error', 'log': tests.stdout + tests.stderr},
        'bevy_decode_evidence': {'log': str(bevy_path), 'sha256': digest(bevy_path), 'results': bevy},
        'limits': ['Technical checks do not rate artistic quality, acting, composition, or perceptual loop continuity.',
                   'Bevy decoder evidence does not establish a Unity, Unreal, or Godot application import.',
                   'High-precision image transforms and HDR/EXR finishing require another verified tool.',
                   'Acceptance rechecks saved provider outputs; it does not rerun generation models.'],
    }
    rendered = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        with args.output.open('x') as output:
            output.write(rendered + '\n')
    print(rendered)


if __name__ == '__main__':
    main()
