"""Cache a GPU-specific TensorRT engine and retain the native face executor."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

REVISION='b74132732fd9a9d29b237bec193ded64c9745e91'
NETWORK_SHA='db47c2701ca849de443c9e9f25657210f829a74fc458ee6fed603a8a501253a8'


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def response(process):
    for line in process.stdout:
        if line.startswith('CGC_A2F_JSON '):return json.loads(line[len('CGC_A2F_JSON '):])
        print(line,file=sys.stderr,end='',flush=True)
    raise RuntimeError('Audio2Face native worker exited with code '+str(process.wait()))


def main():
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from huggingface_hub import snapshot_download
    cache=(Path.cwd()/'models/audio2face-v3').resolve()
    snapshot_download('nvidia/Audio2Face-3D-v3.0',revision=REVISION,allow_patterns=['*.npz','*.json','network.onnx'],local_dir=cache)
    if digest(cache/'network.onnx')!=NETWORK_SHA:raise RuntimeError('Audio2Face network digest mismatch')
    device=subprocess.check_output(['nvidia-smi','--query-gpu=name,compute_cap,driver_version','--format=csv,noheader'],text=True).strip()
    key=hashlib.sha256((NETWORK_SHA+device+'trt10.13.3.9-batch1').encode()).hexdigest()[:24]
    engines=(Path.cwd()/'models/audio2face-engines').resolve();engines.mkdir(parents=True,exist_ok=True)
    stored=engines/(key+'.trt');receipt_path=engines/(key+'.json')
    local=Path(tempfile.mkdtemp(prefix='cgc-a2f-runtime-'))
    for path in cache.iterdir():
        if path.is_file() and path.name!='network.onnx' and path.suffix in ('.npz','.json'):shutil.copyfile(path,local/path.name)
    engine=local/'network.trt'
    if stored.exists() and receipt_path.exists():
        receipt=json.loads(receipt_path.read_text());shutil.copyfile(stored,engine)
        if digest(engine)!=receipt['sha256']:raise RuntimeError('Cached Audio2Face engine digest mismatch')
    else:
        onnx=local/'network.onnx';shutil.copyfile(cache/'network.onnx',onnx)
        info=json.loads((cache/'trt_info.json').read_text())
        shapes=[value.replace('{MAX_BATCH_SIZE}','1').replace('{OPT_BATCH_SIZE}','1') for value in info['trt_build_param']['batch']]
        command=['/usr/src/tensorrt/bin/trtexec','--onnx='+str(onnx),'--saveEngine='+str(engine),'--skipInference','--builderOptimizationLevel=3','--memPoolSize=workspace:2048',*shapes]
        subprocess.run(command,stdout=sys.stderr,stderr=sys.stderr,check=True)
        if not engine.is_file():raise RuntimeError('TensorRT did not write an engine')
        receipt={'network_sha256':NETWORK_SHA,'device':device,'TensorRT':'10.13.3.9','batch_size':1,'sha256':digest(engine)}
        temporary=stored.with_suffix('.uploading');shutil.copyfile(engine,temporary);temporary.replace(stored)
        receipt_path.write_text(json.dumps(receipt,indent=2))
    process=subprocess.Popen(['/opt/a2f-build/cgc_a2f',str(local/'model.json')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    ready=response(process)
    if not ready.get('ready'):raise RuntimeError('Audio2Face initialization failed: '+str(ready))
    names=[]
    for component in ('skin','tongue'):
        with np.load(local/f'bs_{component}_Mark.npz',allow_pickle=False) as data:
            poses=[value.decode() for value in data['poseNames']]
            if poses[0].lower()!='neutral':raise RuntimeError('Unexpected blendshape basis')
            names.extend(component+'/'+name for name in poses[1:])
    if len(names)!=ready['weights']:raise RuntimeError('Blendshape names do not match native output order')
    provenance={'revisions':{'nvidia/Audio2Face-3D-v3.0':REVISION},'sdk_revision':'1ca0f02535ed774f5dbcd724a31cd486368dc783',
                'worker_source_sha256':digest('/opt/cgc_a2f.cpp'),'network_sha256':NETWORK_SHA,'engine':receipt,'identity':'Mark','emotion':'Model default; no Audio2Emotion inference'}
    versions={name:importlib.metadata.version(name) for name in ('numpy','scipy','soundfile')};versions['TensorRT']='10.13.3.9'
    print(json.dumps({'ready':True,'device':device,'provenance':provenance,'versions':versions}),flush=True)
    for line in sys.stdin:
        try:
            task=json.loads(line);started=time.monotonic()
            samples,rate=sf.read(task['input'],dtype='float32',always_2d=True)
            if not samples.size or not np.isfinite(samples).all() or len(samples)/rate>60:raise ValueError('Face animation requires finite audio of at most 60 seconds')
            mono=samples.mean(axis=1);target_rate=ready['sample_rate']
            if rate!=target_rate:
                factor=math.gcd(rate,target_rate);mono=resample_poly(mono,target_rate//factor,rate//factor).astype(np.float32)
            with tempfile.TemporaryDirectory() as directory:
                raw=Path(directory)/'samples.f32';mono.astype('<f4').tofile(raw)
                target=Path(directory)/'frames.json'
                process.stdin.write(json.dumps({'samples':str(raw),'output':str(target)})+'\n');process.stdin.flush()
                status=response(process)
                if not status.get('ok'):raise RuntimeError(status.get('error','Native face inference failed'))
                result=json.loads(target.read_text());weights=np.asarray(result['weights'],dtype=np.float32)
                times=np.asarray(result['timestamps'],dtype=np.float64)/result['sample_rate']
                if weights.shape!=(len(times),len(names)) or not np.isfinite(weights).all():raise RuntimeError('Invalid blendshape output')
                np.savez_compressed(task['output'],weights=weights,times=times,channel_names=np.asarray(names),identity=np.asarray('Mark'))
            answer={'ok':True,'frames':len(times),'channels':len(names),'fps':ready['fps_numerator']/ready['fps_denominator'],'input_duration':len(samples)/rate,
                    'time_start':float(times[0]),'time_end':float(times[-1]),'generation_seconds':time.monotonic()-started,'identity':'Mark','basis':'SDK Mark skin and tongue blendshapes'}
        except Exception:answer={'ok':False,'error':traceback.format_exc()}
        print(json.dumps(answer),flush=True)
    process.terminate()


if __name__=='__main__':main()
