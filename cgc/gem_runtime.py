"""Start GEM-X in its pinned Torch environment and retain its process."""
import json
import os
from pathlib import Path
import subprocess


def load(script='gem_session.py'):
    env=os.environ.copy();env.pop('PYTHONPATH',None)
    libraries=sorted(Path('/opt/gemenv/lib/python3.12/site-packages/nvidia').glob('*/lib'))
    env['LD_LIBRARY_PATH']=':'.join(str(path) for path in libraries)+':'+env.get('LD_LIBRARY_PATH','')
    process=subprocess.Popen(['/opt/gemenv/bin/python',str(Path(__file__).with_name(script))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env)
    line=process.stdout.readline()
    if not line:raise RuntimeError('GEM-X initialization exited with code '+str(process.wait())+'; inspect remote logs')
    ready=json.loads(line)
    if not ready.get('ready'):raise RuntimeError('GEM-X initialization failed: '+str(ready))
    process.cgc_device=ready['device'];process.cgc_provenance=ready['provenance'];process.cgc_versions=ready.get('versions',{})
    return process
