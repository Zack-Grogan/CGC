"""Isolated Beam SDK transport for resident queue workers."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

CPU_PROFILES=('phonon','gem-motion-convert','geosam2-render','mesh-split')
COLLECTION_ATTEMPTS=4
COLLECTION_BACKOFF_SECONDS=(1,2,4)
COLLECTION_TRANSFER_TIMEOUT=180
COLLECTION_BUDGET_SECONDS=600


def file_checksum(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def write_tracking(path, value):
    """Commit provider identity before another process can observe the record."""
    path=Path(path)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.'+path.name+'-',delete=False) as stream:
        temporary=Path(stream.name)
        json.dump(value,stream)
        stream.flush();os.fsync(stream.fileno())
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def _download_artifact(beam, request_id, name, directory, deadline, attempts, checksum=None):
    """Retry only a Beam volume read; corrupt bytes are not a retryable result."""
    if not name or name in ('.','..') or Path(name).name!=name:
        raise RuntimeError('Invalid remote output filename')
    local=Path(directory)/name
    command=[beam,'cp',f'beam://cgc-results/{request_id}/{name}',name]
    for attempt in range(COLLECTION_ATTEMPTS):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Artifact collection time budget exhausted: '+name)
        # A failed CLI call can leave partial bytes. Never use them as a cache.
        local.unlink(missing_ok=True)
        verified=False
        try:
            try:
                subprocess.run(command,check=True,cwd=directory,timeout=min(COLLECTION_TRANSFER_TIMEOUT,remaining))
                if not local.is_file():raise subprocess.CalledProcessError(1,command,stderr='Download produced no file')
            except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
                attempts.append({'name':name,'attempt':attempt+1,'status':'transfer_failed'})
                if attempt+1==COLLECTION_ATTEMPTS:
                    raise RuntimeError(f'Artifact download failed after {COLLECTION_ATTEMPTS} attempts: {name}') from error
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Artifact collection time budget exhausted: '+name) from error
                time.sleep(min(COLLECTION_BACKOFF_SECONDS[attempt],remaining))
                continue
            if checksum is not None and file_checksum(local)!=checksum:
                attempts.append({'name':name,'attempt':attempt+1,'status':'integrity_failed'})
                raise RuntimeError('Artifact digest mismatch; refusing automatic retry: '+name)
            attempts.append({'name':name,'attempt':attempt+1,'status':'verified' if checksum else 'downloaded'})
            verified=True
            return local
        finally:
            # Keep only a successful download. TemporaryDirectory removes that
            # copy when collection finishes or another artifact fails.
            if not verified:local.unlink(missing_ok=True)


def _publish_artifact(source, target, checksum):
    """Publish verified bytes without replacing any different existing bytes."""
    if target.exists():
        if file_checksum(target)!=checksum:raise RuntimeError('Local artifact collision: '+str(target))
        return
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False,prefix='.cgc-download-') as stream:
            temporary=Path(stream.name)
            with source.open('rb') as incoming:shutil.copyfileobj(incoming,stream)
            stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,target)
        except FileExistsError:
            if file_checksum(target)!=checksum:raise RuntimeError('Local artifact collision: '+str(target))
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def collect_results(beam, request_id, output, record):
    """Collect one known completed task; this function cannot submit inference."""
    output=Path(output);record=Path(record)
    tracking=json.loads(record.read_text())
    attempts=[]
    policy={'attempts_per_artifact':COLLECTION_ATTEMPTS,'backoff_seconds':list(COLLECTION_BACKOFF_SECONDS),
            'transfer_timeout_seconds':COLLECTION_TRANSFER_TIMEOUT,'budget_seconds':COLLECTION_BUDGET_SECONDS}
    tracking['collection']={'status':'collection_pending','policy':policy}
    write_tracking(record,tracking)
    try:
        deadline=time.monotonic()+COLLECTION_BUDGET_SECONDS
        with tempfile.TemporaryDirectory(prefix='cgc-collect-') as directory:
            result=_download_artifact(beam,request_id,'result.json',directory,deadline,attempts)
            report=json.loads(result.read_text())
            main_name=Path(report['file']).name
            if not main_name or main_name in ('.','..'):raise RuntimeError('Invalid remote output filename')
            artifacts=[(main_name,report['sha256'],output)]
            targets={output}
            for item in report.get('files',[]):
                name=item['name']
                if not name or name in ('.','..') or Path(name).name!=name:raise RuntimeError('Invalid remote output filename')
                if name==main_name:
                    if item['sha256']!=report['sha256']:raise RuntimeError('Conflicting main artifact digests')
                    continue
                target=output.with_name(output.stem+name[len('output'):] if name.startswith('output') else output.stem+'.'+name)
                if target in targets or target in (record,Path(str(output)+'.result.json')):
                    raise RuntimeError('Conflicting remote artifact destinations: '+str(target))
                targets.add(target);artifacts.append((name,item['sha256'],target))
            # Refuse collisions before publication, including a late sidecar.
            for name,checksum,target in artifacts:
                if target.exists() and file_checksum(target)!=checksum:raise RuntimeError('Local artifact collision: '+str(target))
            downloaded=[]
            for name,checksum,target in artifacts:
                downloaded.append((_download_artifact(beam,request_id,name,directory,deadline,attempts,checksum),target,checksum))
            for local,target,checksum in downloaded:_publish_artifact(local,target,checksum)
            tracking['collection']={'status':'completed','policy':policy,'attempts':attempts}
            report['execution']=tracking
            write_tracking(Path(str(output)+'.result.json'),report)
            write_tracking(record,tracking)
            return report
    except BaseException as error:
        # Keep provider COMPLETE and identity intact. remote.run maps that to
        # collection_pending, so recovery collects this task instead of paying again.
        tracking['collection']={'status':'collection_pending','policy':policy,'attempts':attempts,'error':str(error)}
        write_tracking(record,tracking)
        raise


def stage_references(paths):
    """Upload explicit content-addressed files outside the bounded task message."""
    if not paths:return []
    from beam import Volume
    from beta9.config import get_config_context
    from beta9.channel import ServiceClient
    from beta9.clients.volume import StatPathRequest
    volume=Volume(name='cgc-inputs',mount_path='./inputs')
    if not volume.get_or_create():raise RuntimeError('Could not prepare the private input volume')
    descriptors=[]
    cli=str(Path(sys.executable).with_name('beam'))
    with ServiceClient(config=get_config_context()) as service,tempfile.TemporaryDirectory(prefix='cgc-input-upload-') as directory:
        folder=Path(directory).resolve();(folder/'.beamignore').write_text('__pycache__/\n')
        for filename in paths:
            source=Path(filename).resolve();digest=hashlib.sha256()
            with source.open('rb') as stream:
                for block in iter(lambda:stream.read(8*1024*1024),b''):digest.update(block)
            checksum=digest.hexdigest();size=source.stat().st_size;name=checksum+source.suffix.lower()
            snapshot_root=(Path(os.environ.get('CGC_STATE_DIR',Path(__file__).resolve().parents[1]/'.cgc'))/'inputs').resolve()
            if source.parent==snapshot_root and len(source.stem)==64 and all(c in '0123456789abcdef' for c in source.stem) and source.stem!=checksum:
                raise RuntimeError('Queued input snapshot changed after admission: '+source.name)
            remote='cgc-inputs/'+name
            existing=service.volume.stat_path(StatPathRequest(path=remote))
            if not existing.ok or existing.path_info.size!=size:
                staged=folder/name
                if not staged.exists():
                    try:os.link(source,staged)
                    except OSError:shutil.copyfile(source,staged)
                subprocess.run([cli,'cp',staged.name,'beam://'+remote],cwd=folder,check=True,timeout=1800)
                uploaded=service.volume.stat_path(StatPathRequest(path=remote))
                if not uploaded.ok or uploaded.path_info.size!=size:raise RuntimeError('Input upload was not confirmed: '+name)
            descriptors.append({'name':name,'sha256':checksum,'bytes':size})
    return descriptors


FAILED_TASK_STATUSES = frozenset(('ERROR', 'FAILED', 'TIMEOUT', 'CANCELLED'))


def retire_failed_worker(details, task_id):
    """Stop only the provider-identified container of a confirmed terminal failure."""
    status = details.get('status', '').upper()
    if status not in FAILED_TASK_STATUSES:
        raise ValueError('Worker retirement requires a confirmed terminal failed task')
    container = details.get('container_id')
    result = {'task_id': task_id, 'provider_status': status, 'container_id': container,
              'policy': 'retire terminal failed GPU worker; never retry the paid request'}
    if not container:
        return {**result, 'status': 'unresolved', 'error': 'Provider did not identify the failed container'}
    try:
        stopped = subprocess.run([str(Path(sys.executable).with_name('beam')), 'container', 'stop', container],
                                 capture_output=True, text=True, timeout=30)
        message = (stopped.stdout or '')+(stopped.stderr or '')
        if stopped.returncode and 'not found' not in message.lower():
            return {**result, 'status': 'failed', 'error': message[-2000:]}
        return {**result, 'status': 'retired'}
    except (OSError, subprocess.SubprocessError) as error:
        return {**result, 'status': 'failed', 'error': str(error)[:2000]}


def acquire_gpu(profile, token, runtime_id, current_task_id=None):
    import fcntl
    import requests
    state=Path(os.environ.get('CGC_STATE_DIR',Path(__file__).resolve().parents[1]/'.cgc')).resolve()
    state.mkdir(parents=True,exist_ok=True)
    lock=(state/'gpu.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX)
    lease=state/'gpu-session.json'
    try:
        if lease.exists():
            previous=json.loads(lease.read_text())
            r=requests.get('https://api.beam.cloud/v2/task/'+previous['task_id']+'/',headers={'Authorization':'Bearer '+token},timeout=30)
            r.raise_for_status()
            data=r.json()
            own_recovery=bool(current_task_id and previous['task_id']==current_task_id)
            if data['status'].upper() not in ('COMPLETE','COMPLETED','ERROR','FAILED','TIMEOUT','CANCELLED') and not own_recovery:
                raise RuntimeError('Previous GPU task is still active or uncertain: '+previous['task_id'])
            container=data.get('container_id')
            if data['status'].upper() in FAILED_TASK_STATUSES:
                retirement = previous.get('worker_retirement', {})
                already_retired = retirement.get('status') == 'retired' and retirement.get('task_id') == previous['task_id'] and (not container or retirement.get('container_id') == container)
                if not already_retired:
                    retirement = retire_failed_worker(data, previous['task_id'])
                    previous['worker_retirement'] = retirement
                    write_tracking(lease, previous)
                if retirement.get('status') != 'retired':
                    raise RuntimeError('Prior failed GPU worker must be retired before dispatch: '+json.dumps(retirement))
            elif not own_recovery and (previous['profile']!=profile or previous.get('runtime_id')!=runtime_id) and container:
                stopped=subprocess.run([str(Path(sys.executable).with_name('beam')),'container','stop',container],capture_output=True,text=True)
                if stopped.returncode and 'not found' not in (stopped.stdout+stopped.stderr).lower():
                    raise RuntimeError('Could not release prior GPU worker: '+stopped.stderr)
    except BaseException:
        lock.close()
        raise
    return lock,lease


def cancel_task(plan):
    import beam
    import requests
    from beta9.config import get_config_context
    from beta9.channel import ServiceClient
    from beta9.clients.taskqueue import TaskQueueServiceStub,TaskQueueLengthRequest,TaskQueuePopRequest
    output=Path(plan['output'])
    tracking=json.loads(Path(str(output)+'.remote.json').read_text())
    task_id=tracking.get('task_id')
    if not task_id:
        raise RuntimeError('Submission outcome unknown; no task ID to cancel')
    context=get_config_context()
    headers={'Authorization':'Bearer '+context.token}
    beam_cli=str(Path(sys.executable).with_name('beam'))
    response=requests.get('https://api.beam.cloud/v2/task/'+task_id+'/',headers=headers,timeout=30)
    response.raise_for_status()
    before=response.json()
    if before['status'].upper() not in ('COMPLETE','COMPLETED','ERROR','FAILED','TIMEOUT','CANCELLED'):
        subprocess.run([beam_cli,'task','stop',task_id],check=True,stdout=subprocess.DEVNULL)
    response=requests.get('https://api.beam.cloud/v2/task/'+task_id+'/',headers=headers,timeout=30)
    response.raise_for_status()
    after=response.json()
    status=after['status'].upper()
    if status not in ('COMPLETE','COMPLETED','ERROR','FAILED','TIMEOUT','CANCELLED'):
        raise RuntimeError('Provider cancellation has not reached a terminal state')
    stub_id=after['stub']['id']
    tasks=json.loads(subprocess.check_output([beam_cli,'task','list','--filter','stub-id='+stub_id,'--format','json'],text=True))
    terminal=tasks and all(t['status'].upper() in ('COMPLETE','COMPLETED','ERROR','FAILED','TIMEOUT','CANCELLED') for t in tasks)
    if terminal:
        # Cancelled inputs can remain queued if startup failed before the worker
        # reached Pop. The owner-checked Pop discards terminal inputs server-side.
        with ServiceClient(config=context) as service:
            api=TaskQueueServiceStub(service.channel)
            length=api.task_queue_length(TaskQueueLengthRequest(stub_id=stub_id)).length
            if length:
                popped=api.task_queue_pop(TaskQueuePopRequest(stub_id=stub_id,container_id='cgc-cancelled-cleanup'))
                if popped.ok:
                    raise RuntimeError('Unexpected live task while cleaning a cancelled queue')
        containers=json.loads(subprocess.check_output([beam_cli,'container','list','--format','json'],text=True))
        for container in containers:
            if container.get('stub_id')==stub_id:
                subprocess.run([beam_cli,'container','stop',container['container_id']],check=True,stdout=subprocess.DEVNULL)
    return {'task_id':task_id,'status':status,'cancelled_queue_cleanup':bool(terminal)}


def main():
    # Staging is process-local during normal execution. Restore it on every
    # exit so embedded controller calls and recovery checks remain reusable.
    original_directory=os.open('.',os.O_RDONLY)
    original_path=list(sys.path)
    try:
        return _main()
    finally:
        try:os.fchdir(original_directory)
        finally:
            os.close(original_directory)
            sys.path[:]=original_path


def _main():
    # Avoid shadowing stdlib queue with the sibling cgc/queue.py.
    sys.path = [p for p in sys.path if Path(p or os.getcwd()).resolve() != Path(__file__).parent.resolve()]
    # Keep an explicit queue override stable when staging changes the cwd.
    os.environ['CGC_STATE_DIR']=str(Path(os.environ.get('CGC_STATE_DIR',Path(__file__).resolve().parents[1]/'.cgc')).expanduser().resolve())
    args = argparse.ArgumentParser()
    args.add_argument('--plan')
    args.add_argument('--cooldown', action='store_true')
    args.add_argument('--cancel', action='store_true')
    args.add_argument('--build-only', action='store_true')
    args.add_argument('--status-only', action='store_true')
    parsed = args.parse_args()
    if parsed.cooldown:
        import beam
        from beta9.config import get_config_context
        lock,lease=acquire_gpu('cooldown',get_config_context().token,'cooldown')
        with lock:
            if lease.exists():
                closed=lease.parent/'closed-gpu-sessions'
                closed.mkdir(exist_ok=True)
                lease.rename(closed/(str(time.time_ns())+'.json'))
        print(json.dumps({'gpu':'released'}))
        return
    if not parsed.plan:
        args.error('--plan is required')
    plan = json.loads(parsed.plan)
    if parsed.cancel:
        print(json.dumps(cancel_task(plan)))
        return
    output = Path(plan['output'])
    record = Path(str(output) + '.remote.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    if parsed.status_only:
        import beam
        from beta9.config import get_config_context
        import requests
        tracking=json.loads(record.read_text())
        if not tracking.get('task_id'):
            print(json.dumps({'status':'REJECTED' if tracking.get('not_submitted') else 'UNKNOWN'}))
            return
        response=requests.get('https://api.beam.cloud/v2/task/'+tracking['task_id']+'/',headers={'Authorization':'Bearer '+get_config_context().token},timeout=30)
        response.raise_for_status()
        print(json.dumps({'status':response.json()['status']}))
        return
    # CPU collection and manual recovery need the same per-output exclusion as GPU
    # jobs. Status/cancellation intentionally remain able to inspect a running job.
    import fcntl
    from contextlib import ExitStack
    with ExitStack() as execution:
        execution_lock=execution.enter_context(Path(str(output)+'.remote.lock').open('a'))
        fcntl.flock(execution_lock,fcntl.LOCK_EX)
        request = dict(plan['parameters'])
        request.pop('source_paths',None)
        profile = plan['model']
        request.update(prompt=plan['prompt'], seed=plan['seed'])
        references = request.pop('references', [])
        if request.get('reference'):
            references.append(request.pop('reference'))
        import uuid
        request['id'] = uuid.uuid4().hex
        from beam import Image, Volume, task_queue, QueueDepthAutoscaler
        from beta9.config import get_config_context
        import requests
        previous=json.loads(record.read_text()) if record.exists() else {}
        if previous and not previous.get('task_id') and not previous.get('not_submitted'):
            raise RuntimeError('Submission outcome unknown; do not resubmit. Request '+previous['request_id'])
        if not previous.get('task_id'):
            try:request['input_files']=stage_references(references)
            except Exception as error:
                write_tracking(record,{'request_id':request['id'],'profile':profile,'status':'REJECTED','not_submitted':True,'error':'Input preparation failed: '+str(error)})
                raise
        with tempfile.TemporaryDirectory(prefix='cgc-worker-') as folder:
            folder = Path(folder).resolve()
            shutil.copyfile(Path(__file__).with_name('remote_worker.py'), folder / 'remote_worker.py')
            shutil.copyfile(Path(__file__).with_name('media.py'),folder/'remote_media.py')
            shutil.copyfile(Path(__file__).with_name('motion.py'),folder/'remote_motion.py')
            if profile == 'kimodo-soma-rp-v1.2':
                for name in ('kimodo_assets.py','kimodo_session.py','kimodo_runtime.py'):
                    shutil.copyfile(Path(__file__).with_name(name),folder/name)
            if profile == 'tokenrig':
                for name in ('skintokens_assets.py','skintokens_session.py','skintokens_runtime.py','skintokens_patch.py'):
                    shutil.copyfile(Path(__file__).with_name(name),folder/name)
            if profile == 'gem-x-native77':
                for name in ('gem_assets.py','gem_session.py','gem_runtime.py'):
                    shutil.copyfile(Path(__file__).with_name(name),folder/name)
            if profile == 'gem-motion-convert':
                for name in ('gem_assets.py','gem_bridge.py','gem_runtime.py'):
                    shutil.copyfile(Path(__file__).with_name(name),folder/name)
            if profile == 'geosam2':
                for name in ('geosam_session.py','geosam_runtime.py'):
                    shutil.copyfile(Path(__file__).with_name(name),folder/name)
                shutil.copyfile(Path(__file__).with_name('segmentation.py'),folder/'remote_segmentation.py')
            if profile == 'geosam2-render':
                shutil.copyfile(Path(__file__).with_name('geosam_render.py'),folder/'geosam_render.py')
            if profile == 'audio2face3d':
                for name in ('a2f_session.py','a2f_runtime.py'):
                    shutil.copyfile(Path(__file__).with_name(name),folder/name)
                shutil.copyfile(Path(__file__).with_name('face.py'),folder/'remote_face.py')
            if profile in ('mesh-split','holopart'):
                name='mesh_split.py' if profile=='mesh-split' else 'holopart_session.py'
                shutil.copyfile(Path(__file__).with_name(name),folder/name)
                shutil.copyfile(Path(__file__).with_name('mesh_runtime.py'),folder/'mesh_runtime.py')
                if profile=='holopart':shutil.copyfile(Path(__file__).with_name('glb_replace.py'),folder/'glb_replace.py')
            if profile == 'trellis2':
                repo = Path(os.environ.get('CGC_3DLAB_ROOT',Path(__file__).resolve().parents[2]/'image-to-3dlab')).resolve()
                for name in ('scripts','image_to_3dlab','audit'):
                    shutil.copytree(repo/name,folder/name,ignore=shutil.ignore_patterns('__pycache__'))
                generator=folder/'scripts/trellis_cuda_generate.py'
                text=generator.read_text()
                anchor='glb.export(str(output), extension_webp=True)'
                if text.count(anchor)!=1:
                    raise RuntimeError('TRELLIS export anchor changed; refusing an unverified patch')
                generator.write_text(text.replace(anchor,'glb.export(str(output), extension_webp=False)').replace('map_location="cpu", weights_only=False','map_location="cpu", weights_only=True'))
                for name in ('trellis_runtime.py','trellis_session.py','trellis_texture.py'):
                    shutil.copyfile(Path(__file__).with_name(name),folder/name)
            (folder / '.beamignore').write_text('__pycache__/\n*.pyc\n')
            os.chdir(folder)
            sys.path.insert(0, str(folder))
            import remote_worker
            packages = {
                'mesh-split': [],
                'holopart': [],
                'audio2face3d': [],
                'geosam2-render': [],
                'gem-motion-convert': [],
                'geosam2': [],
                'gem-x-native77': [],
                'tokenrig': [],
                'kimodo-soma-rp-v1.2': [],
                'trellis2': ['huggingface_hub==0.36.0', 'uv==0.9.9'],
                'ace-step-1.5-base': ['git+https://github.com/ace-step/ACE-Step-1.5.git@ca1e85fe9430179831e6bc6be790c332190a3866'],
                'ace-step-1.5-turbo': ['git+https://github.com/ace-step/ACE-Step-1.5.git'],
                'phonon': ['ptts==0.6.0', 'huggingface_hub>=1,<2'],
                'voxcpm2': ['voxcpm==2.0.3', 'torch==2.9.1', 'torchaudio==2.9.1', 'soundfile'],
                'qwen-image-2.1': ['torch==2.9.1', 'git+https://github.com/huggingface/diffusers.git@0905b667fe3f37f43b6ef9c6e05ad20636206938', 'transformers>=5.17', 'accelerate', 'Pillow', 'sentencepiece'],
                'qwen-image-2.1-turbo': ['torch==2.9.1', 'git+https://github.com/huggingface/diffusers.git@0905b667fe3f37f43b6ef9c6e05ad20636206938', 'transformers>=5.17', 'accelerate', 'Pillow', 'sentencepiece'],
                'moss-sfx-v2': ['torch==2.9.1', 'git+https://github.com/OpenMOSS/MOSS-TTS.git#subdirectory=moss_soundeffect_v2'],
            }
            image = Image(python_version='python3.12', python_packages=packages[profile]).add_commands(['apt-get update && apt-get install -y git ffmpeg libsndfile1'])
            if profile == 'trellis2':
                image = Image(python_version='python3.12',base_image='nvidia/cuda:12.8.1-devel-ubuntu22.04',python_packages=packages[profile]).add_commands(['apt-get update && apt-get install -y git libgl1 libglib2.0-0 libegl1 libopengl0'])
            elif profile == 'voxcpm2':
                image = Image(python_version='python3.12',image_id='01d319bea780aa3c')
            elif profile == 'moss-sfx-v2':
                image = Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:01d319bea780aa3c',python_packages=['torch==2.9.1','torchaudio==2.9.1','numpy==1.26.4','einops==0.8.2','Pillow==12.2.0','safetensors==0.7.0','transformers==4.57.1','diffusers==0.37.1','ftfy==6.3.1','soundfile==0.13.1','imageio==2.37.3','descript-audiotools==0.7.2'])
                image = image.add_commands(['uv-b9 pip install --python "$(command -v python3.12)" --no-deps git+https://github.com/OpenMOSS/MOSS-TTS.git@934d6826b084c46a0d033402174d5f8ac4ed2519#subdirectory=moss_soundeffect_v2'])
            elif profile.startswith('ace-step-1.5'):
                image = Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:01d319bea780aa3c',python_packages=['torch==2.9.1','torchvision==0.24.1','torchaudio==2.9.1','transformers==4.57.3','diffusers==0.37.1','accelerate==1.13.0','scipy','loguru','einops','vector-quantize-pytorch','numba','matplotlib','peft','pytorch-wavelets','PyWavelets','toml','diskcache','modelscope','typer-slim'])
                image = image.add_commands(['git clone https://github.com/ace-step/ACE-Step-1.5.git /opt/acestep && cd /opt/acestep && git checkout ca1e85fe9430179831e6bc6be790c332190a3866 && uv-b9 pip install --python "$(command -v python3.12)" --no-deps .'])
            published={'qwen-image-2.1':'2aab938767d0827f','qwen-image-2.1-turbo':'2aab938767d0827f','moss-sfx-v2':'4ca48cb6b3111e72','ace-step-1.5-turbo':'7595713f760145fb','ace-step-1.5-base':'7595713f760145fb','trellis2':'e93dbb1f7ca0ad1c'}
            if profile in published:
                image=Image(python_version='python3.12',image_id=published[profile])
            if profile.startswith('qwen'):
                image=Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:2aab938767d0827f',python_packages=['torch==2.9.1','torchvision==0.24.1'])
            if profile == 'kimodo-soma-rp-v1.2':
                # Import by file: this SDK subprocess intentionally excludes cgc/.
                import importlib.util
                spec=importlib.util.spec_from_file_location('kimodo_image',Path(__file__).with_name('kimodo_image.py'))
                recipe=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recipe)
                image=recipe.image()
            if profile == 'tokenrig':
                import importlib.util
                spec=importlib.util.spec_from_file_location('skintokens_image',Path(__file__).with_name('skintokens_image.py'))
                recipe=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recipe)
                image=recipe.image()
            if profile in ('gem-x-native77','gem-motion-convert'):
                import importlib.util
                spec=importlib.util.spec_from_file_location('gem_image',Path(__file__).with_name('gem_image.py'))
                recipe=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recipe)
                image=recipe.image()
            if profile in ('geosam2','geosam2-render','mesh-split'):
                import importlib.util
                spec=importlib.util.spec_from_file_location('geosam_image',Path(__file__).with_name('geosam_image.py'))
                recipe=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recipe)
                image=recipe.image()
            if profile == 'holopart':
                import importlib.util
                spec=importlib.util.spec_from_file_location('holopart_image',Path(__file__).with_name('holopart_image.py'))
                recipe=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recipe)
                image=recipe.image()
            if profile == 'audio2face3d':
                import importlib.util
                spec=importlib.util.spec_from_file_location('audio2face_image',Path(__file__).with_name('audio2face_image.py'))
                recipe=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recipe)
                image=recipe.worker_image()
            if parsed.build_only:
                built = image.build()
                if not built.success:
                    raise RuntimeError('Image build failed')
                print(json.dumps({'profile':profile,'image_id':built.image_id}))
                return
            config_path=Path(os.environ.get('CGC_STATE_DIR',Path(__file__).resolve().parents[1]/'.cgc'))/'config.json'
            configuration=json.loads(config_path.read_text()) if config_path.exists() else {}
            warm_seconds=int(os.environ.get('CGC_KEEP_WARM_SECONDS',configuration.get('keep_warm_seconds',60)))
            if not 0<=warm_seconds<=3600:
                raise ValueError('Keep-warm duration must be 0 through 3600 seconds')
            worker_env={'CGC_PROFILE':profile,'HF_HUB_DISABLE_TELEMETRY':'1','TORCHDYNAMO_DISABLE':'1' if profile=='moss-sfx-v2' else '0','PYTHONPATH':'/usr/local/lib/python3.12/site-packages:/usr/local/lib/python3.12/dist-packages:/usr/lib/python3.12/site-packages:/usr/lib/python3.12/dist-packages'}
            remote = task_queue(name='cgc-resident-' + profile, cpu=8 if profile=='geosam2-render' else 2, memory='64Gi' if profile.startswith('qwen') else '16Gi' if profile in ('gem-motion-convert','geosam2-render','mesh-split') else '32Gi' if profile != 'phonon' else '4Gi', gpu='' if profile in CPU_PROFILES else 'RTX4090' if profile in ('trellis2','kimodo-soma-rp-v1.2','tokenrig','gem-x-native77','geosam2','audio2face3d','holopart') else 'RTX5090', image=image, workers=1, retries=0, timeout=1800, keep_warm_seconds=warm_seconds,
                on_start=remote_worker.load_model, env=worker_env,
                volumes=[Volume(name='cgc-models', mount_path='./models'), Volume(name='cgc-results', mount_path='./results'),Volume(name='cgc-inputs',mount_path='./inputs')]+([Volume(name='assetfurnace-trellis-models',mount_path='./trellis_models')] if profile == 'trellis2' else []), autoscaler=QueueDepthAutoscaler(min_containers=0,max_containers=1,tasks_per_container=1))(remote_worker.generate)
            token = get_config_context().token
            gpu_lock = None
            lease = None
            content=hashlib.sha256(profile.encode()+str(image.image_id).encode()+str(warm_seconds).encode()+Path(__file__).read_bytes())
            for source in sorted(folder.rglob('*.py')):
                content.update(str(source.relative_to(folder)).encode())
                content.update(source.read_bytes())
            runtime_id=content.hexdigest()
            if profile not in CPU_PROFILES and not parsed.build_only:
                gpu_lock,lease = acquire_gpu(profile,token,runtime_id,current_task_id=previous.get('task_id'))
                execution.enter_context(gpu_lock)
            if record.exists() and not previous.get('not_submitted'):
                tracking = json.loads(record.read_text())
                task_id = tracking.get('task_id')
                if not task_id:
                    raise RuntimeError('Submission outcome unknown; do not resubmit. Request '+tracking['request_id'])
                request['id'] = tracking['request_id']
            else:
                write_tracking(record,{'request_id':request['id'],'profile':profile,'status':'dispatching'})
                task = remote.put(request=request)
                if not task:
                    raise RuntimeError('Beam rejected task submission')
                task_id = task.id
                write_tracking(record,{'task_id':task_id,'request_id':request['id'],'profile':profile,'worker_bundle_sha256':runtime_id,'image_id':image.image_id})
            if lease is not None:
                # Reconstruct a lease if the host died after recording the paid task
                # but before recording its GPU container ownership.
                tracked=json.loads(record.read_text())
                write_tracking(lease,{'task_id':task_id,'profile':tracked.get('profile',profile),'runtime_id':tracked.get('worker_bundle_sha256') or runtime_id})
            token = get_config_context().token
            deadline = time.monotonic()+2400
            while True:
                response = requests.get('https://api.beam.cloud/v2/task/' + task_id + '/', headers={'Authorization':'Bearer '+token}, timeout=30)
                response.raise_for_status()
                details = response.json()
                status = details['status'].upper()
                tracking=json.loads(record.read_text())
                tracking['status']=status
                if details.get('container_id'):tracking['container_id']=details['container_id']
                if details.get('stub',{}).get('id'):tracking['stub_id']=details['stub']['id']
                write_tracking(record,tracking)
                if status in ('COMPLETE','COMPLETED'):
                    break
                if status in FAILED_TASK_STATUSES:
                    if profile not in CPU_PROFILES:
                        retirement = retire_failed_worker(details, task_id)
                        tracking['worker_retirement'] = retirement
                        write_tracking(record, tracking)
                        if lease is not None:
                            leased = json.loads(lease.read_text())
                            leased['worker_retirement'] = retirement
                            write_tracking(lease, leased)
                    stub=details.get('stub',{}).get('id')
                    if stub:
                        try:subprocess.run([str(Path(sys.executable).with_name('beam')),'logs','--stub-id',stub,'--tail','150'],timeout=30,check=False)
                        except Exception:pass
                    raise RuntimeError('Beam task ended: '+status+'; task '+task_id)
                if time.monotonic()>deadline:
                    raise TimeoutError('Remote task outcome unknown: '+task_id)
                time.sleep(3)
            beam = str(Path(sys.executable).with_name('beam'))
            print(json.dumps(collect_results(beam,request['id'],output,record)))


if __name__ == '__main__':
    main()
