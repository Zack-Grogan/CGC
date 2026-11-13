"""Restore the already approved, verified TRELLIS CUDA runtime without new weights."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def load():
    source = Path.cwd()
    models = (source / 'trellis_models').resolve()
    root = Path('/tmp/assetfurnace')
    root.mkdir(exist_ok=True)
    for name in ('scripts','image_to_3dlab','audit'):
        shutil.copytree(source / name, root / name, dirs_exist_ok=True)
    sys.path[:0] = [str(root),str(root/'scripts')]
    import bootstrap_trellis_cuda as boot
    os.chdir(root)
    route, why, tag = boot.detect()
    capability = boot.host.compute_capability()
    gpu_name=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True).strip()
    if '4090' not in gpu_name:
        raise RuntimeError('Qualified TRELLIS profile requires RTX4090; received '+gpu_name)
    if route is None or capability != '89':
        raise RuntimeError('Qualified TRELLIS runtime requires RTX4090 SM89: '+str(why))
    archive = models/'runtime/trellis-89.tar'
    if not archive.is_file():
        raise RuntimeError('Approved TRELLIS runtime archive is missing; no implicit bootstrap')
    shutil.copyfile(archive, '/tmp/cgc-trellis-runtime.tar')
    boot.VENDOR.parent.mkdir(parents=True,exist_ok=True)
    def safe_filter(member,destination):
        if member.issym() and os.path.isabs(member.linkname):
            target=Path(member.linkname)
            target.relative_to(boot.VENDOR)
            member.linkname=os.path.relpath(target,Path(destination)/Path(member.name).parent)
        return tarfile.data_filter(member,destination)
    with tarfile.open('/tmp/cgc-trellis-runtime.tar') as tar:
        tar.extractall(boot.VENDOR,filter=safe_filter)
    receipt=json.loads((models/'trellis-weights-ready.json').read_text())
    components={r['component']:r for r in receipt['components']}
    def cached(name):
        return models/Path(components[name]['path']).relative_to('/volumes/models')
    assembled=root/'weights/trellis'
    shutil.copytree(cached('microsoft/TRELLIS.2-4B'),assembled,dirs_exist_ok=True)
    encoder=root/'weights/encoder'
    shutil.copytree(cached(boot.GATED),encoder,dirs_exist_ok=True)
    decoder=root/'weights/decoder'
    shutil.copytree(cached('microsoft/TRELLIS-image-large'),decoder,dirs_exist_ok=True)
    config=json.loads((assembled/'pipeline.json').read_text())
    config['args']['image_cond_model']['args']['model_name']=str(encoder)
    config['args']['models']['sparse_structure_decoder']=str(decoder/'ckpts/ss_dec_conv3d_16l8_fp16')
    (assembled/'pipeline.json').write_text(json.dumps(config))
    env=os.environ.copy()
    env.update(I2L_TRELLIS_MODEL_PATH=str(assembled), HF_HOME=str(models/'huggingface'), U2NET_HOME=str(models/'u2net'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    process=subprocess.Popen([str(boot.venv_python()),str(source/'trellis_session.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env)
    ready=json.loads(process.stdout.readline())
    if not ready.get('ready'):
        raise RuntimeError('TRELLIS session failed to load')
    os.chdir(source)
    process.cgc_device=gpu_name
    return process
