"""Resident TokenRig inference and Blender transfer server."""
import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def main():
    protocol=sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import numpy as np
        import random
        from skintokens_assets import prepare, CHECKPOINTS
        if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
        device=torch.cuda.get_device_name(0)
        if '4090' not in device:raise RuntimeError('Initial FlashAttention qualification requires RTX4090, received '+device)
        torch.set_num_threads(2)
        root,provenance=prepare(Path.cwd()/'models/skintokens')
        source=Path('/opt/SkinTokens')
        from skintokens_patch import patch
        provenance['runtime_patch']=patch(source)
        for name in ('experiments','models'):
            target=source/name
            if not target.exists():target.symlink_to(root/name,target_is_directory=True)
            if target.resolve()!=(root/name).resolve():raise RuntimeError('Unexpected SkinTokens asset path: '+name)
        os.chdir(source)
        sys.path.insert(0,str(source))
        os.environ['HF_HUB_OFFLINE']='1'
        import demo
        server=subprocess.Popen([sys.executable,'bpy_server.py'],stdout=sys.stderr,stderr=sys.stderr)
        demo.wait_for_bpy_server(timeout=90)
        checkpoint=str(root/CHECKPOINTS[1])
        demo.load_model(checkpoint,None)
        versions={name:importlib.metadata.version(name) for name in ('torch','transformers','bpy','flash-attn')}
    protocol.write(json.dumps({'ready':True,'device':device,'provenance':provenance,'versions':versions})+'\n');protocol.flush()
    try:
        for line in sys.stdin:
            try:
                task=json.loads(line);started=time.monotonic()
                with contextlib.redirect_stdout(sys.stderr):
                    torch.manual_seed(task['seed']);np.random.seed(task['seed']);random.seed(task['seed'])
                    outputs=demo.run_rig([Path(task['input'])],5,.95,1.0,2.0,task.get('num_beams',10),task['use_skeleton'],True,False,[Path(task['output'])],checkpoint,None)
                    if len(outputs)!=1 or not Path(outputs[0]).is_file():raise RuntimeError('TokenRig did not export a GLB')
                answer={'ok':True,'generation_seconds':time.monotonic()-started,'peak_cuda_bytes':int(torch.cuda.max_memory_allocated()),'transfer':True,'use_skeleton':task['use_skeleton']}
            except Exception:answer={'ok':False,'error':traceback.format_exc()}
            protocol.write(json.dumps(answer)+'\n');protocol.flush()
    finally:
        server.terminate()


if __name__=='__main__':main()
