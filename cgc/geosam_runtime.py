"""Start GeoSAM2 in the isolated geometry environment."""
import json
import os
from pathlib import Path
import subprocess


def load():
    env=os.environ.copy();env.pop('PYTHONPATH',None)
    env.update(PATH='/opt/skinenv/bin:'+env.get('PATH',''),OPENCV_IO_ENABLE_OPENEXR='1',MAX_JOBS='2',OMP_NUM_THREADS='2',
               TORCH_EXTENSIONS_DIR='/tmp/cgc-geosam-extensions')
    process=subprocess.Popen(['/opt/skinenv/bin/python',str(Path(__file__).with_name('geosam_session.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env)
    line=process.stdout.readline()
    if not line:raise RuntimeError('GeoSAM2 initialization exited with code '+str(process.wait())+'; inspect remote logs')
    ready=json.loads(line)
    if not ready.get('ready'):raise RuntimeError('GeoSAM2 initialization failed: '+str(ready))
    process.cgc_device=ready['device'];process.cgc_provenance=ready['provenance'];process.cgc_versions=ready['versions']
    return process
