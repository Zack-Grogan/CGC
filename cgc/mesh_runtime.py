"""Start deterministic geometry processing in the isolated geometry runtime."""
import json
import os
from pathlib import Path
import subprocess


def load(script):
    env=os.environ.copy();env.pop('PYTHONPATH',None)
    process=subprocess.Popen(['/opt/skinenv/bin/python',str(Path(__file__).with_name(script))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env)
    line=process.stdout.readline()
    if not line:raise RuntimeError('Geometry worker exited with code '+str(process.wait())+'; inspect remote logs')
    ready=json.loads(line)
    if not ready.get('ready'):raise RuntimeError('Geometry worker initialization failed: '+str(ready))
    process.cgc_device=ready['device'];process.cgc_provenance=ready['provenance'];process.cgc_versions=ready.get('versions',{})
    return process
