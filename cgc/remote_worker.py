"""Beam generation worker; imports model libraries only inside the remote container."""
import base64
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


def image_controls(profile,request):
    controls={}
    if not profile.endswith('turbo'):controls['num_inference_steps']=request.get('steps',40)
    if 'guidance_scale' in request:controls['true_cfg_scale']=request['guidance_scale']
    if 'negative_prompt' in request:controls['negative_prompt']=request['negative_prompt']
    return controls


def effective_controls(profile,request):
    defaults={
        'qwen-image-2.1':{'steps':40,'guidance_scale':1.},
        'qwen-image-2.1-turbo':{'steps':8,'guidance_scale':1.,'sampling_schedule':'checkpoint sigmas'},
        'moss-sfx-v2':{'steps':100,'cfg_scale':4.},
        'voxcpm2':{'steps':10,'guidance_scale':2.},
        'ace-step-1.5-base':{'steps':32,'guidance_scale':7.},
        'ace-step-1.5-turbo':{'steps':8},
        'tokenrig':{'num_beams':10},
        'holopart':{'steps':50,'guidance_scale':3.5,'octree_depth':7},
        'kimodo-soma-rp-v1.2':{'steps':100},
    }
    result=dict(defaults.get(profile,{}))
    fields=('width','height','steps','guidance_scale','cfg_scale','resolution','texture_size','decimation_target','num_beams','octree_depth','duration','from_latents','save_latents')
    result.update({key:request[key] for key in fields if key in request})
    if 'negative_prompt' in request:result['negative_prompt']=request['negative_prompt']
    return result


def configure_qwen_memory(pipe):
    """Use the pinned AutoencoderKLQwenImage21 spatial and batch adapters."""
    pipe.vae.enable_tiling(tile_sample_min_height=256, tile_sample_min_width=256,
                           tile_sample_stride_height=192, tile_sample_stride_width=192)
    pipe.vae.enable_slicing()
    return {'vae_tiling': True, 'vae_slicing': True, 'tile_sample_height': 256,
            'tile_sample_width': 256, 'tile_stride_height': 192, 'tile_stride_width': 192,
            'canvas_reduced': False, 'diffusers_revision': '0905b667fe3f37f43b6ef9c6e05ad20636206938'}


def quarantine_qwen_failure(state, error):
    """Never reuse an exception-interrupted offload chain or VAE feature cache."""
    import gc
    state['unhealthy'] = {'type': type(error).__name__, 'error': str(error)[:2000]}
    cleanup = []
    pipe = state.get('pipe')
    for name, operation in (('vae_feature_cache', lambda: pipe.vae.clear_cache()),
                            ('model_offload_hooks', lambda: pipe.maybe_free_model_hooks())):
        try:
            if pipe is not None:
                operation()
            cleanup.append({'operation': name, 'status': 'completed' if pipe is not None else 'not_loaded'})
        except Exception as cleanup_error:
            cleanup.append({'operation': name, 'status': 'failed', 'error': str(cleanup_error)[:1000]})
    # The provider marks this attempt terminal before the client retires its
    # exact container. Do not reload a model or retry the paid request here.
    state['pipe'] = None
    try:
        import torch
        gc.collect()
        torch.cuda.empty_cache()
        cleanup.append({'operation': 'unreferenced_cuda_cache', 'status': 'completed'})
    except Exception as cleanup_error:
        cleanup.append({'operation': 'unreferenced_cuda_cache', 'status': 'failed', 'error': str(cleanup_error)[:1000]})
    state['failure_cleanup'] = cleanup
    return cleanup


def load_model():
    try:
        return _load_model()
    except Exception:
        import traceback
        error=traceback.format_exc()
        print(error,flush=True)
        return {"initialization_error":error}


def _load_model():
    os.environ['HF_HOME'] = str((Path.cwd() / 'models/hf').resolve())
    profile = os.environ['CGC_PROFILE']
    if profile == 'moss-sfx-v2':
        os.environ['TORCHDYNAMO_DISABLE']='1'
    started = time.monotonic()
    revisions = {}
    device = 'CPU'
    memory_controls = {}
    if profile not in ('phonon', 'trellis2', 'kimodo-soma-rp-v1.2', 'tokenrig', 'gem-x-native77', 'geosam2','gem-motion-convert','geosam2-render','audio2face3d','mesh-split','holopart'):
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; refusing CPU fallback')
        device = torch.cuda.get_device_name(0)
        if '5090' not in device.replace(' ', ''):
            raise RuntimeError('Expected RTX5090, received ' + device)
    if profile in ('mesh-split','holopart'):
        from mesh_runtime import load
        pipe=load('mesh_split.py' if profile=='mesh-split' else 'holopart_session.py')
        repo='VAST-AI/HoloPart' if profile=='holopart' else 'VAST-AI/GeoSAM2';device=pipe.cgc_device
        revisions.update(pipe.cgc_provenance.get('revisions',{}))
    elif profile == 'audio2face3d':
        from a2f_runtime import load
        pipe=load();repo='nvidia/Audio2Face-3D-v3.0';device=pipe.cgc_device
        revisions.update(pipe.cgc_provenance['revisions'])
    elif profile == 'geosam2-render':
        pipe=None;repo='VAST-AI/GeoSAM2';device='CPU'
        revisions['source/GeoSAM2']='b5de23c60ab487d407b623d394a1614f9714761c'
    elif profile == 'gem-motion-convert':
        from gem_runtime import load
        pipe=load('gem_bridge.py');repo='nvidia/SOMA-X';device='CPU'
        revisions.update(pipe.cgc_provenance['revisions'])
    elif profile == 'geosam2':
        from geosam_runtime import load
        pipe=load();repo='VAST-AI/GeoSAM2';device=pipe.cgc_device
        revisions.update(pipe.cgc_provenance['revisions'])
    elif profile == 'gem-x-native77':
        from gem_runtime import load
        pipe=load();repo='nvidia/GEM-X';device=pipe.cgc_device
        revisions.update(pipe.cgc_provenance['revisions'])
    elif profile == 'tokenrig':
        from skintokens_runtime import load
        pipe=load();repo='VAST-AI/SkinTokens';device=pipe.cgc_device
        revisions.update(pipe.cgc_provenance['revisions'])
    elif profile == 'kimodo-soma-rp-v1.2':
        from kimodo_runtime import load
        pipe = load()
        repo = 'nvidia/Kimodo-SOMA-RP-v1.2'
        device = pipe.cgc_device
        revisions.update(pipe.cgc_provenance['revisions'])
    elif profile == 'trellis2':
        from trellis_runtime import load
        pipe = load()
        repo = 'microsoft/TRELLIS.2-4B'
        device = pipe.cgc_device
    elif profile.startswith('qwen'):
        from diffusers import QwenImage21Pipeline
        repo = 'Qwen/Qwen-Image-2.1' + ('-Turbo' if profile.endswith('turbo') else '')
        revision = 'fc13ba1986fcb905854dc8de2f52eee395f49b5b' if profile.endswith('turbo') else 'd26bb61231c349cf6b7896fa83353113880e1ba3'
        revisions[repo] = revision
        pipe = QwenImage21Pipeline.from_pretrained(repo, revision=revision, torch_dtype=torch.bfloat16, cache_dir=os.environ['HF_HOME'])
        memory_controls = configure_qwen_memory(pipe)
        pipe.enable_model_cpu_offload()
    elif profile == 'moss-sfx-v2':
        from moss_soundeffect_v2 import MossSoundEffectPipeline
        repo = 'OpenMOSS-Team/MOSS-SoundEffect-v2.0'
        revisions[repo] = 'e35df4d82fbe87fcd5d14e5d100e349c0c3c076d'
        pipe = MossSoundEffectPipeline.from_pretrained(repo, revision=revisions[repo], torch_dtype=torch.bfloat16, device='cuda')
    elif profile.startswith('ace-step-1.5'):
        from acestep.handler import AceStepHandler
        repo = 'ACE-Step/Ace-Step1.5'
        from huggingface_hub import snapshot_download
        checkpoints = (Path.cwd()/'models/ace-checkpoints').resolve()
        revisions[repo] = '19671f406d603126926c1b7e2adc169acbcade22'
        snapshot_download(repo,revision=revisions[repo],local_dir=str(checkpoints),allow_patterns=['vae/**','Qwen3-Embedding-0.6B/**','acestep-v15-turbo/**','config.json'])
        config='acestep-v15-base' if profile.endswith('base') else 'acestep-v15-turbo'
        if profile.endswith('base'):
            base_repo='ACE-Step/acestep-v15-base'
            revisions[base_repo]='e432212fec32b8965a14ffa57ae653438d6abd14'
            snapshot_download(base_repo,revision=revisions[base_repo],local_dir=str(checkpoints/config))
        os.environ['ACESTEP_CHECKPOINTS_DIR']=str(checkpoints)
        from acestep import model_downloader
        model_downloader.MAIN_MODEL_COMPONENTS=['acestep-v15-turbo','vae','Qwen3-Embedding-0.6B']
        pipe = AceStepHandler()
        message,ok=pipe.initialize_service(project_root='/tmp/acestep',config_path=config,device='cuda',compile_model=False,quantization=None)
        if not ok:
            raise RuntimeError(message)
    elif profile == 'voxcpm2':
        from voxcpm import VoxCPM
        repo = 'openbmb/VoxCPM2'
        from huggingface_hub import snapshot_download
        revisions[repo]='32279effe8c19989596f05d353d1447f51d9e915'
        local=snapshot_download(repo,revision=revisions[repo])
        pipe = VoxCPM.from_pretrained(local,device='cuda',load_denoiser=False,optimize=False)
    elif profile == 'phonon':
        import ptts
        repo = 'gradium/phonon-31m-en'
        revisions[repo]='92741c5b07d085ff840e26fea8ce43110b87852f'
        pipe = ptts.TTS('hf://' + repo+'@'+revisions[repo], lang='en', quant='q8')
    else:
        raise ValueError('Unimplemented remote profile: ' + profile)
    return {'memory_controls':memory_controls,'revisions':revisions,'device': device, 'pipe': pipe, 'repo': repo, 'session': uuid.uuid4().hex, 'load_seconds': time.monotonic()-started, 'calls': 0}


def generate(context, request):
    state = context.on_start_value
    if state.get('unhealthy'):
        raise RuntimeError('Resident Qwen session is quarantined after a failed task; a fresh provider worker is required')
    try:
        return _generate(context, request)
    except Exception as error:
        if os.environ.get('CGC_PROFILE', '').startswith('qwen'):
            cleanup = quarantine_qwen_failure(state, error)
            job_id = request.get('id', '')
            if isinstance(job_id, str) and job_id.isalnum():
                destination = Path.cwd()/'results'/job_id
                try:
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination/'failure.json').write_text(json.dumps({'status': 'failed', 'session': state.get('session'),
                        'task_id': os.environ.get('TASK_ID'), 'request_id': job_id,
                        'failure': state['unhealthy'], 'cleanup': cleanup, 'retry_performed': False}, indent=2))
                except OSError:
                    pass
        raise


def _generate(context, request):
    import tempfile
    state = context.on_start_value
    if state.get('initialization_error'):
        raise RuntimeError(state['initialization_error'])
    state['calls'] += 1
    profile = os.environ['CGC_PROFILE']
    started = time.monotonic()
    job_id = request['id']
    if not job_id.isalnum():
        raise ValueError('Invalid job ID')
    destination = (Path.cwd() / 'results') / job_id
    destination.mkdir(parents=True, exist_ok=True)
    manifest = destination / 'result.json'
    if manifest.exists():
        return json.loads(manifest.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        references = []
        import shutil
        input_root=(Path.cwd()/'inputs').resolve()
        for index,item in enumerate(request.get('input_files',[])):
            name=item['name']
            if Path(name).name!=name or not name.startswith(item['sha256']):raise ValueError('Invalid input descriptor')
            source=(input_root/name).resolve();source.relative_to(input_root)
            target=Path(tmp)/(f'reference-{index}'+source.suffix)
            shutil.copyfile(source,target)
            checksum=hashlib.sha256()
            with target.open('rb') as stream:
                for block in iter(lambda:stream.read(8*1024*1024),b''):checksum.update(block)
            if target.stat().st_size!=item['bytes'] or checksum.hexdigest()!=item['sha256']:raise ValueError('Uploaded input digest mismatch')
            references.append(target)
        for index, encoded in enumerate(request.get('files', [])):
            path = Path(tmp) / (f'reference-{index}'+('.glb' if index==0 else '.npz') if profile in ('mesh-split','holopart') else f'reference-{index}.wav' if profile=='audio2face3d' else f'reference-{index}.pt' if profile=='gem-motion-convert' else f'reference-{index}'+('.zip' if index==0 else request['prompt_suffix']) if profile=='geosam2' else f'reference-{index}.glb' if profile in ('tokenrig','geosam2-render') else f'reference-{index}.mp4' if profile=='gem-x-native77' else f'reference-{index}')
            path.write_bytes(base64.b64decode(encoded, validate=True))
            references.append(path)
        if profile in ('mesh-split','holopart'):
            output=destination/'output.glb'
            task=dict(input=str(references[0]),output=str(output))
            if profile=='mesh-split':task.update(labels=str(references[1]),label=request['label'])
            else:task.update(part=request['part'],seed=request['seed'],steps=request['steps'],octree_depth=request['octree_depth'],guidance_scale=request.get('guidance_scale',3.5))
            state['pipe'].stdin.write(json.dumps(task)+'\n');state['pipe'].stdin.flush()
            answer=json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):raise RuntimeError(answer.get('error','Geometry child exited'))
            (destination/'output.geometry.json').write_text(json.dumps(dict(answer,provenance=state['pipe'].cgc_provenance),indent=2))
        elif profile == 'audio2face3d':
            output=destination/'output.npz'
            state['pipe'].stdin.write(json.dumps(dict(input=str(references[0]),output=str(output)))+'\n');state['pipe'].stdin.flush()
            answer=json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):raise RuntimeError(answer.get('error','Audio2Face child exited'))
            (destination/'output.face.json').write_text(json.dumps(dict(answer,provenance=state['pipe'].cgc_provenance),indent=2))
        elif profile == 'geosam2-render':
            import subprocess,sys,zipfile
            views=Path(tmp)/'views'
            env=os.environ.copy();env.pop('PYTHONPATH',None);env.update(RESOLUTION='1024',RENDER_SAMPLES='8')
            subprocess.run(['/opt/blender40/blender','-b','-P',str(Path.cwd()/'geosam_render.py'),'--',str(references[0]),str(views)],env=env,check=True)
            metadata=json.loads((views/'meta.json').read_text())
            if metadata.get('image_size')!=[1024,1024]:raise RuntimeError('Renderer did not produce the native GeoSAM2 view size')
            audit=json.loads((views/'render_audit.json').read_text())
            if any(min(row['minimum'][:2])<0 or max(row['maximum'][:2])>1 for row in audit):raise RuntimeError('Mesh is clipped by a rendered camera')
            output=destination/'output.zip'
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
                for path in views.iterdir():
                    if path.is_file():archive.write(path,path.name)
        elif profile == 'gem-motion-convert':
            output=destination/'output.npz'
            state['pipe'].stdin.write(json.dumps(dict(input=str(references[0]),output=str(output)))+'\n');state['pipe'].stdin.flush()
            answer=json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):raise RuntimeError(answer.get('error','GEM converter exited'))
            (destination/'output.conversion.json').write_text(json.dumps(dict(answer,provenance=state['pipe'].cgc_provenance),indent=2))
        elif profile == 'geosam2':
            output=destination/'output.npz'
            state['pipe'].stdin.write(json.dumps(dict(views=str(references[0]),prompt_file=str(references[1]),output=str(output),points=request['points'],view=request['view'],seed=request['seed']))+'\n');state['pipe'].stdin.flush()
            answer=json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):raise RuntimeError(answer.get('error','GeoSAM2 child exited'))
            (destination/'output.segmentation.json').write_text(json.dumps(dict(answer,provenance=state['pipe'].cgc_provenance),indent=2))
        elif profile == 'gem-x-native77':
            output=destination/'output.pt'
            state['pipe'].stdin.write(json.dumps(dict(input=str(references[0]),output=str(output),camera_mode=request['camera_mode'],duration=request.get('duration')))+'\n');state['pipe'].stdin.flush()
            answer=json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):raise RuntimeError(answer.get('error','GEM-X child exited'))
            (destination/'output.motion.json').write_text(json.dumps(dict(answer,provenance=state['pipe'].cgc_provenance),indent=2))
        elif profile == 'tokenrig':
            output=destination/'output.glb'
            state['pipe'].stdin.write(json.dumps(dict(input=str(references[0]),output=str(output),seed=request['seed'],use_skeleton=request['use_skeleton'],num_beams=request.get('num_beams',10)))+'\n');state['pipe'].stdin.flush()
            answer=json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):raise RuntimeError(answer.get('error','TokenRig child exited'))
            (destination/'output.rig.json').write_text(json.dumps(dict(answer,provenance=state['pipe'].cgc_provenance),indent=2))
        elif profile == 'kimodo-soma-rp-v1.2':
            output = destination / 'output.npz'
            state['pipe'].stdin.write(json.dumps(dict(output=str(output), prompt=request['prompt'], seed=request['seed'], duration=request['duration'], steps=request['steps']))+'\n')
            state['pipe'].stdin.flush()
            answer = json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):
                raise RuntimeError(answer.get('error','Kimodo child exited'))
            (destination/'output.motion.json').write_text(json.dumps(dict(answer, encoder=state['pipe'].cgc_provenance),indent=2))
        elif profile == 'trellis2':
            output = destination / 'output.glb'
            task = dict(source=str(references[0]), output=str(output), seed=request['seed'], resolution=request.get('resolution',1024), decimation_target=request.get('decimation_target',100000), texture_size=request.get('texture_size',2048), save_latents=request.get('save_latents',False), from_latents=request.get('from_latents',False))
            if request.get('texture'):task.update(texture=True,reference=str(references[1]))
            state['pipe'].stdin.write(json.dumps(task)+'\n')
            state['pipe'].stdin.flush()
            answer = json.loads(state['pipe'].stdout.readline())
            if not answer.get('ok'):
                raise RuntimeError(answer.get('error','TRELLIS child exited'))
        elif profile.startswith('qwen'):
            import torch
            from PIL import Image
            kwargs = dict(prompt=request['prompt'], width=request.get('width',1024), height=request.get('height',1024), generator=torch.Generator('cpu').manual_seed(request['seed']))
            if references:
                kwargs['image'] = [Image.open(p).convert('RGBA') for p in references]
            kwargs.update(image_controls(profile,request))
            output = destination / 'output.png'
            image = state['pipe'](**kwargs).images[0]
            if request.get('transparent') and ('A' not in image.getbands() or image.getchannel('A').getextrema()[0] == 255 or image.getchannel('A').getextrema()[1] == 0):
                raise ValueError('Model did not produce requested transparency')
            image.save(output)
        elif profile == 'moss-sfx-v2':
            audio = state['pipe'](prompt=request['prompt'], seconds=request['duration'], num_inference_steps=request.get('steps',100), cfg_scale=request.get('cfg_scale',4.0),seed=request['seed'])
            output = destination / 'output.wav'
            import soundfile as sf
            sf.write(str(output),audio[0].detach().float().cpu().numpy().T,state['pipe'].sample_rate,subtype='PCM_16')
        elif profile.startswith('ace-step-1.5'):
            from acestep.inference import GenerationParams, GenerationConfig, generate_music
            kwargs=dict(inference_steps=request.get('steps',32 if profile.endswith('base') else 8),task_type=request.get('music_task','text2music'),caption=request['prompt'],lyrics=request.get('lyrics',''),instrumental=request.get('instrumental',True),duration=request.get('duration',30),thinking=False,use_cot_metas=False,use_cot_caption=False,use_cot_lyrics=False,use_cot_language=False,seed=request['seed'],bpm=request.get('bpm'),keyscale=request.get('key',''),vocal_language=request.get('language','unknown'))
            if profile.endswith('base') and 'guidance_scale' in request:kwargs['guidance_scale']=request['guidance_scale']
            if request.get('style_reference_index') is not None:
                kwargs['reference_audio']=str(references[request['style_reference_index']])
            if request.get('source_index') is not None:
                kwargs['src_audio']=str(references[request['source_index']])
            mode=kwargs['task_type']
            track=request.get('track')
            if mode=='extract': kwargs['instruction']=f'Extract the {track} track from the audio:'
            if mode=='lego': kwargs['instruction']=f'Generate the {track} track based on the audio context:'
            if mode=='complete': kwargs['instruction']=f"Complete the input track with {request['tracks']}:"
            if mode=='repaint': kwargs.update(repainting_start=request.get('start',0),repainting_end=request.get('end',-1))
            params=GenerationParams(**kwargs)
            result = generate_music(state['pipe'], None, params, GenerationConfig(batch_size=1,audio_format='wav',use_random_seed=False,seeds=[request['seed']]), save_dir=str(destination))
            if not result.success:
                raise RuntimeError(result.error)
            output = Path(result.audios[0]['path'])
        elif profile == 'phonon':
            output = destination / 'output.wav'
            state['pipe'].save(str(output), request['prompt'], voice='default')
        else:
            import soundfile as sf
            output = destination / 'output.wav'
            text = request['prompt']
            if request.get('direction'):
                text = '(' + request['direction'] + ')' + text
            kwargs = dict(text=text, max_len=512, normalize=False, denoise=False, retry_badcase=False,inference_timesteps=request.get('steps',10),cfg_value=request.get('guidance_scale',2.))
            if references:
                kwargs['reference_wav_path']=str(references[0])
                if not request.get('direction'):
                    kwargs.update(prompt_wav_path=str(references[0]),prompt_text=request['transcript'])
            import re
            clean_text = re.sub(r'\s+', ' ', text)
            tts_model = state['pipe'].tts_model
            token_cap = min(512, int(len(tts_model.text_tokenizer(clean_text))*6.0+10))
            sample_cap = token_cap * tts_model.patch_size * tts_model._decode_chunk_size
            audio = state['pipe'].generate(**kwargs)
            if len(audio) >= sample_cap:
                raise RuntimeError('Speech reached token cap; split the line')
            sf.write(str(output), audio, state['pipe'].tts_model.sample_rate, subtype='PCM_16')
    files = [{'name':p.name, 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in destination.iterdir() if p.is_file() and p.name != 'result.json']
    from remote_media import inspect
    metadata=inspect(output)
    if profile == 'tokenrig' and not metadata.get('skins'):
        raise ValueError('TokenRig output has no skin')
    if profile == 'geosam2':
        from remote_segmentation import inspect as inspect_segmentation
        metadata.update(inspect_segmentation(output))
    if profile == 'audio2face3d':
        from remote_face import inspect as inspect_face
        metadata.update(inspect_face(output))
    if profile in ('kimodo-soma-rp-v1.2','gem-motion-convert'):
        from remote_motion import inspect as inspect_motion
        metadata.update(inspect_motion(output))
    import importlib.metadata
    versions={}
    for package in ('torch','diffusers','transformers','voxcpm','ptts','moss-soundeffect-v2','ace-step'):
        try: versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: pass
    if profile in ('kimodo-soma-rp-v1.2','tokenrig','gem-x-native77','geosam2','gem-motion-convert','audio2face3d','mesh-split','holopart'):
        versions.update(state['pipe'].cgc_versions)
    report = {'media':metadata,'seed_used':profile.startswith('qwen') or (profile=='trellis2' and not request.get('from_latents')) or profile in ('moss-sfx-v2','kimodo-soma-rp-v1.2','tokenrig','geosam2','holopart') or profile.startswith('ace-step'),'versions':versions,'revisions':state['revisions'],'files':files, 'device':state['device'], 'file': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'repository': state['repo'], 'session': state['session'], 'model_load_count': 1, 'session_call': state['calls'], 'load_seconds': state['load_seconds'], 'generation_seconds': time.monotonic()-started, 'task_id': os.environ.get('TASK_ID')}
    report['memory_controls']=state.get('memory_controls',{})
    report['quality_profile']=request.get('quality_profile')
    fields=('width','height','steps','guidance_scale','cfg_scale','resolution','texture_size','decimation_target','num_beams','octree_depth','duration','from_latents','save_latents')
    report['requested_controls']={key:request[key] for key in fields if key in request}
    report['effective_controls']=effective_controls(profile,request)
    manifest.write_text(json.dumps(report, indent=2))
    return report

# The Beam SDK error path expects a decorated handler's retry policy. This
# module is staged as a plain callable, so supply the same no-retry policy.
from types import SimpleNamespace
generate.parent = SimpleNamespace(retry_for=[])
