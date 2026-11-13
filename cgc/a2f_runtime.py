"""Start and retain the native Audio2Face executor via its Python adapter."""
import json
import os
from pathlib import Path
import subprocess
import sys


def load():
    process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('a2f_session.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=os.environ.copy())
    line=process.stdout.readline()
    if not line:raise RuntimeError('Audio2Face initialization exited with code '+str(process.wait())+'; inspect remote logs')
    ready=json.loads(line)
    if not ready.get('ready'):raise RuntimeError('Audio2Face initialization failed: '+str(ready))
    process.cgc_device=ready['device'];process.cgc_provenance=ready['provenance'];process.cgc_versions=ready['versions']
    return process
