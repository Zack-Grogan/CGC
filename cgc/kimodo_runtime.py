"""Start and retain Kimodo's isolated inference process."""
import json
import os
from pathlib import Path
import subprocess


def load():
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['TEXT_ENCODER_MODE'] = 'local'
    process = subprocess.Popen(['/opt/kimodoenv/bin/python', str(Path(__file__).with_name('kimodo_session.py'))],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    line = process.stdout.readline()
    if not line:
        status = process.wait()
        raise RuntimeError('Kimodo initialization process exited with code '+str(status)+'; inspect remote logs')
    ready = json.loads(line)
    if not ready.get('ready'):
        raise RuntimeError('Kimodo initialization failed: '+str(ready))
    process.cgc_device = ready['device']
    process.cgc_provenance = ready['provenance']
    process.cgc_versions = ready['versions']
    return process
