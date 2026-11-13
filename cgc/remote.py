"""Validated, file-based requests for remote generation and result collection."""
import json
import math
import struct
from pathlib import Path
import secrets
import time
import subprocess
from .planning import ROOT, Plan, UserError, existing_file, dimensions
from .catalog import STYLES

PROFILES = {
    'mesh-split': ('model.split',),
    'holopart': ('model.complete',),
    'audio2face3d': ('audio.face',),
    'geosam2-render': ('model.views',),
    'gem-motion-convert': ('motion.convert',),
    'geosam2': ('model.segment',),
    'gem-x-native77': ('motion.extract',),
    'tokenrig': ('model.rig','model.skin'),
    'kimodo-soma-rp-v1.2': ('motion.generate',),
    'qwen-image-2.1': ('image.generate','image.edit'),
    'qwen-image-2.1-turbo': ('image.generate','image.edit'),
    'trellis2': ('model.generate','model.texture'),
    'moss-sfx-v2': ('audio.sfx',),
    'phonon': ('audio.speak',),
    'voxcpm2': ('audio.design','audio.clone'),
    'ace-step-1.5-turbo': ('audio.music','audio.music.generate','audio.music.cover','audio.music.repaint'),
    'ace-step-1.5-base': ('audio.music','audio.music.generate','audio.music.cover','audio.music.repaint','audio.music.extract','audio.music.layer','audio.music.complete'),
}
DEFAULT = {'image.generate':'qwen-image-2.1-turbo','image.edit':'qwen-image-2.1-turbo','model.generate':'trellis2','audio.sfx':'moss-sfx-v2','audio.speak':'phonon','audio.design':'voxcpm2','audio.clone':'voxcpm2'}
DEFAULT.update({'audio.face':'audio2face3d','model.views':'geosam2-render','model.segment':'geosam2','model.split':'mesh-split','model.complete':'holopart',
                'model.rig':'tokenrig','model.skin':'tokenrig','model.texture':'trellis2','motion.generate':'kimodo-soma-rp-v1.2','motion.extract':'gem-x-native77','motion.convert':'gem-motion-convert'})


CATALOG = {
    'mesh-split': ('VAST-AI/GeoSAM2', 'Trimesh component terms; deterministic format adapter', 'CPU'),
    'holopart': ('VAST-AI/HoloPart', 'MIT model + component terms; scikit-image extraction', 'RTX4090'),
    'audio2face3d': ('nvidia/Audio2Face-3D-v3.0', 'Audio2Face-3D model terms + MIT SDK', 'RTX4090'),
    'geosam2-render': ('VAST-AI/GeoSAM2', 'Apache-2.0 renderer + Blender component terms', 'CPU'),
    'gem-motion-convert': ('nvidia/SOMA-X', 'Apache-2.0 SOMA assets', 'CPU'),
    'geosam2': ('VAST-AI/GeoSAM2', 'Apache-2.0', 'RTX4090'),
    'gem-x-native77': ('nvidia/GEM-X', 'OpenMDW model terms + Apache-2.0 SOMA assets', 'RTX4090'),
    'tokenrig': ('VAST-AI/SkinTokens', 'MIT + Qwen configuration component', 'RTX4090'),
    'kimodo-soma-rp-v1.2': ('nvidia/Kimodo-SOMA-RP-v1.2', 'NVIDIA Open Model + Llama 3 + LLM2Vec adapter terms', 'RTX4090'),
    'qwen-image-2.1': ('Qwen/Qwen-Image-2.1', 'Qwen Research License', 'RTX5090'),
    'qwen-image-2.1-turbo': ('Qwen/Qwen-Image-2.1-Turbo', 'Qwen Research License', 'RTX5090'),
    'trellis2': ('microsoft/TRELLIS.2-4B', 'MIT + component terms in provenance', 'RTX4090'),
    'moss-sfx-v2': ('OpenMOSS-Team/MOSS-SoundEffect-v2.0', 'Apache-2.0', 'RTX5090'),
    'phonon': ('gradium/phonon-31m-en', 'Apache-2.0', 'CPU'),
    'voxcpm2': ('openbmb/VoxCPM2', 'Apache-2.0', 'RTX5090'),
    'ace-step-1.5-turbo': ('ACE-Step/Ace-Step1.5', 'MIT', 'RTX5090'),
    'ace-step-1.5-base': ('ACE-Step/acestep-v15-base', 'MIT + shared component records', 'RTX5090'),
}


def catalog():
    return [dict(id=key,name=key,backend='beam',capabilities=PROFILES[key],model_id=repo,license=license,device=device,source='https://huggingface.co/'+repo) for key,(repo,license,device) in CATALOG.items()]


def number(value, low, high, label, integer=False):
    if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise UserError(f'{label} must be {low} through {high}')
    return value


def plan(operation, opts):
    for key in ('model','prompt','input','output','direction','transcript','transcript_file','text_file','lyrics_file','key','language','track','tracks','from_latents','views','points','mask','labels','part','quality','negative_prompt'):
        if opts.get(key) is not None and not isinstance(opts[key],str):
            raise UserError(key+' must be a string')
    for key in ('seed','width','height','steps','texture_size','decimation_target','bpm'):
        if opts.get(key) is not None and type(opts[key]) is not int:
            raise UserError(key+' must be an integer')
    raw=opts.get('reference')
    if raw is not None and not isinstance(raw,str) and (not isinstance(raw,list) or any(not isinstance(p,str) for p in raw)):
        raise UserError('References must be local path strings')
    music = operation.startswith('audio.music')
    base_music=operation in ('audio.music.extract','audio.music.layer','audio.music.complete') or bool(opts.get('lyrics_file'))
    model = opts.get('model') or (('ace-step-1.5-base' if base_music else 'ace-step-1.5-turbo') if music else DEFAULT.get(operation))
    if operation not in PROFILES.get(model, ()):
        raise UserError(f'Unsupported remote model/operation: {model}/{operation}')
    from .quality_profiles import resolve
    try:opts,quality=resolve(model,opts,operation)
    except ValueError as error:raise UserError(str(error)) from error
    step_models={'qwen-image-2.1','qwen-image-2.1-turbo','moss-sfx-v2','ace-step-1.5-base','ace-step-1.5-turbo','voxcpm2','kimodo-soma-rp-v1.2','holopart'}
    if opts.get('steps') is not None and model not in step_models:raise UserError('Steps are not supported for '+model)
    guidance_models={'qwen-image-2.1','qwen-image-2.1-turbo','ace-step-1.5-base','voxcpm2','holopart'}
    if opts.get('guidance_scale') is not None and model not in guidance_models:raise UserError('Guidance scale is not supported for '+model)
    if opts.get('negative_prompt') is not None and not model.startswith('qwen-image-2.1'):raise UserError('Negative prompts are only exposed for Qwen Base')
    if opts.get('cfg_scale') is not None and model!='moss-sfx-v2':raise UserError('CFG scale is exposed for MOSS SFX only')
    if opts.get('num_beams') is not None and model!='tokenrig':raise UserError('Beam search is exposed for TokenRig only')
    prompt = opts.get('prompt') or ''
    if opts.get('text_file'):
        if prompt:
            raise UserError('Use text or --text-file, not both')
        prompt=Path(existing_file(opts['text_file'],'Text file')).read_text()
    prompt = prompt.strip()
    if not prompt and operation not in ('model.generate','model.texture','model.rig','model.skin','model.segment','model.split','model.views','motion.convert','audio.face') and not operation.endswith(('extract','complete')):
        raise UserError('A prompt is required')
    irrelevant=('voice','direction','speed','transcript','transcript_file') if music or operation=='audio.sfx' else ()
    for field in irrelevant:
        if opts.get(field) is not None:
            raise UserError(field+' is not supported for '+operation)
    if operation=='model.generate' and prompt:
        raise UserError('This TRELLIS adapter is conditioned by an image or saved latents, not a text prompt')
    refs = opts.get('reference') or []
    if isinstance(refs,str):
        refs=[refs]
    target=opts.get('input')
    params={'license_acknowledged':bool(opts.get('accept_license'))}
    warnings=[]
    if quality:
        params['quality_profile']=quality
        warnings.append('Quality profiles set native compute budgets; inspect the resulting content before admission.')
    if opts.get('guidance_scale') is not None:params['guidance_scale']=number(opts['guidance_scale'],0,20,'Guidance scale')
    if operation.startswith('image.'):
        if operation=='image.edit' and not target:
            raise UserError('Remote editing requires --input TARGET')
        if operation=='image.generate' and target:
            raise UserError('Use --reference for generation; --input identifies an edit target')
        if target:
            refs=[target,*refs]
        if len(refs)>10:
            raise UserError('At most ten conditioning images including target')
        from .quality_profiles import QWEN_CANVASES
        canvas=(opts.get('width'),opts.get('height'))
        w,h=canvas if canvas in QWEN_CANVASES else dimensions(opts.get('aspect') or 'square',opts.get('size') or 1024,opts.get('width'),opts.get('height'),32)
        params.update(width=w,height=h,transparent=bool(opts.get('transparent')),target_index=0 if target else None)
        guidance=params.get('guidance_scale',1.)
        negative=opts.get('negative_prompt')
        if model.endswith('turbo') and (guidance!=1 or negative is not None):raise UserError('Qwen Turbo retains CFG=1 and does not expose negative conditioning')
        if negative is not None and guidance<=1:raise UserError('Negative conditioning requires --guidance-scale greater than 1')
        if guidance>1 and negative is None:raise UserError('Guidance greater than 1 requires --negative-prompt, including an empty negative prompt')
        if negative is not None:params['negative_prompt']=negative
        prompt=STYLES.get(opts.get('style') or 'raw','')+prompt
        if params['transparent']:
            prompt='This is an RGBA image with transparency. '+prompt+'. The image has alpha channel and the background is transparent.'
        if target and len(refs)>1:
            prompt='Image 1 is the target to edit. Images 2 onward are supporting references. '+prompt
        if opts.get('steps') is not None:
            steps=number(opts['steps'],1,100,'Steps',True)
            if model.endswith('turbo') and steps!=8:
                raise UserError('Qwen Turbo uses its saved eight-step schedule')
            params['steps']=steps
    elif operation=='model.texture':
        if not target or len(refs)!=1 or prompt:raise UserError('Texturing requires --input STATIC.glb and one --reference cutout image without text')
        if opts.get('from_latents') or opts.get('decimation_target') is not None or opts.get('save_latents'):
            raise UserError('Existing-mesh texturing does not resample geometry, decimate, or save generation latents')
        source=existing_file(target,'Static mesh')
        if Path(source).suffix.lower()!='.glb':raise UserError('This texturing adapter accepts static GLB')
        from .media import inspect
        info=inspect(source)
        if info['skins'] or info['animations']:raise UserError('Texture static, unskinned geometry before rigging')
        from .texture_preflight import inspect_source
        try:params['source_preflight']=inspect_source(source)
        except (ValueError,KeyError,IndexError,TypeError,struct.error) as error:raise UserError(str(error)) from error
        refs=[source,*refs]
        params.update(texture=True,resolution=str(opts.get('resolution') if opts.get('resolution') is not None else '1024'),
                      texture_size=number(opts.get('texture_size') if opts.get('texture_size') is not None else 2048,512,4096,'Texture size',True))
        if params['resolution'] not in ('512','1024'):raise UserError('Texturing resolution must be 512 or 1024')
        warnings.append('Texturing replaces source materials and UV layout; world triangle geometry and node transforms are checked.')
    elif operation in ('model.split','model.complete'):
        if not target or prompt or refs:raise UserError('Geometry processing requires --input GLB without text or reference images')
        source=existing_file(target,'Static mesh')
        if Path(source).suffix.lower()!='.glb':raise UserError('This geometry adapter accepts GLB input')
        from .media import inspect
        info=inspect(source)
        if info['skins'] or info['animations']:raise UserError('Process static, unskinned geometry before rigging')
        refs=[source]
        if operation=='model.split':
            if not opts.get('labels'):raise UserError('Splitting requires --labels NPZ from segmentation')
            refs.append(existing_file(opts['labels'],'Face labels'))
            params['label']=number(opts.get('label') if opts.get('label') is not None else 1,1,1000000,'Part label',True)
        else:
            if not opts.get('part'):raise UserError('Completion requires --part GEOMETRY_NODE')
            params.update(part=opts['part'],steps=number(opts.get('steps') if opts.get('steps') is not None else 50,1,100,'Steps',True),
                          octree_depth=number(opts.get('octree_depth') if opts.get('octree_depth') is not None else 7,5,8,'Octree depth',True))
            warnings.append('The reconstructed part has new geometry and no original UVs or textures; unselected parts are retained.')
    elif operation=='audio.face':
        if not target or prompt or refs or opts.get('seed') is not None:raise UserError('Face animation requires --input WAV; it does not expose text, references, or a seed')
        if not opts.get('accept_license'):raise UserError('Audio2Face requires --accept-license for the selected model terms')
        refs=[existing_file(target,'Speech WAV')]
        if Path(refs[0]).suffix.lower()!='.wav':raise UserError('This face-animation adapter accepts WAV input')
        warnings.append('Weights target the SDK Mark skin and tongue basis; map them to a compatible facial rig before game playback.')
    elif operation=='model.views':
        if not target or prompt or refs:raise UserError('View preparation requires --input GLB without text or reference images')
        refs=[existing_file(target,'Mesh')]
        if Path(refs[0]).suffix.lower()!='.glb':raise UserError('GeoSAM2 view preparation accepts GLB')
        from .media import inspect
        info=inspect(refs[0])
        if info['skins'] or info['animations']:raise UserError('Prepare views from static, unskinned geometry before rigging')
    elif operation=='motion.convert':
        if not target or prompt or refs or opts.get('seed') is not None:raise UserError('Conversion requires --input GEM_PT without text, references, or a seed')
        refs=[existing_file(target,'GEM motion file')]
        if Path(refs[0]).suffix!='.pt':raise UserError('Expected a native GEM-X .pt prediction file')
    elif operation=='model.segment':
        if target or refs or prompt or not opts.get('views') or bool(opts.get('points'))==bool(opts.get('mask')):
            raise UserError('GeoSAM2 requires --views ZIP and exactly one --points JSON or --mask file')
        views=existing_file(opts['views'],'View package')
        import zipfile
        try:
            with zipfile.ZipFile(views) as archive:
                names=set(archive.namelist())
                if not {'meta.json','mesh.glb'}<=names:raise UserError('View package must contain meta.json and mesh.glb at its root')
                meta=json.loads(archive.read('meta.json'))
                if meta.get('image_size')!=[1024,1024]:raise UserError('Use cgc model views to prepare matching 1024px RGB/depth/normal views')
        except zipfile.BadZipFile as error:raise UserError('Views must be a ZIP file') from error
        source=existing_file(opts.get('points') or opts.get('mask'),'Point prompts or mask')
        suffix=Path(source).suffix.lower()
        if (opts.get('points') and suffix!='.json') or (opts.get('mask') and suffix not in ('.npy','.exr','.png','.webp','.jpg','.jpeg')):
            raise UserError('Use JSON point prompts or a native NPY/EXR/image mask')
        refs=[views,source]
        params.update(points=bool(opts.get('points')),prompt_suffix=suffix,view=number(opts.get('view') if opts.get('view') is not None else 0,0,11,'View index',True))
    elif operation=='motion.extract':
        if not target or refs or prompt or opts.get('seed') is not None:
            raise UserError('GEM-X requires --input VIDEO and does not expose text, reference images, or a generation seed')
        if not opts.get('accept_license'):raise UserError('GEM-X requires --accept-license for the selected model terms')
        refs=[existing_file(target,'Video')]
        duration=opts.get('duration')
        if duration is not None:number(duration,.1,60,'Clip duration')
        camera=opts.get('camera_mode') or 'background'
        if camera not in ('static','background'):raise UserError('Camera mode must be static or background')
        params.update(duration=duration,camera_mode=camera)
    elif operation in ('model.rig','model.skin'):
        if not target or refs or prompt:
            raise UserError('TokenRig requires --input GLB; it does not accept prompts or reference images')
        source=Path(existing_file(target,'Character GLB'))
        if source.suffix.lower()!='.glb':raise UserError('This TokenRig adapter accepts GLB input')
        from .media import inspect
        info=inspect(source)
        if operation=='model.skin' and not info['skins']:raise UserError('Skinning requires an existing skeleton in the input GLB')
        refs=[str(source)]
        params.update(use_skeleton=operation=='model.skin',transfer=True)
        params['num_beams']=number(opts.get('num_beams') if opts.get('num_beams') is not None else 10,1,20,'Beam search width',True)
        if operation=='model.skin':warnings.append('The native SkinTokens route rebuilds bone names and bind transforms; existing animations are not retained.')
    elif operation=='motion.generate':
        if refs or target:
            raise UserError('Kimodo motion generation accepts text; references are not supported')
        if not opts.get('accept_license'):
            raise UserError('Kimodo requires --accept-license for the motion, Llama, and adapter terms')
        params.update(duration=number(opts.get('duration') if opts.get('duration') is not None else 5,1,30,'Motion duration'),
                      steps=number(opts.get('steps') if opts.get('steps') is not None else 100,1,200,'Steps',True))
    elif operation=='model.generate':
        latent=opts.get('from_latents')
        if bool(latent)==bool(refs) or (refs and len(refs)!=1):
            raise UserError('Supply exactly one --reference image or --from-latents file')
        if latent:
            refs=[latent]
        if latent and opts.get('seed') is not None:raise UserError('Latent re-export does not use a generation seed')
        if latent and (opts.get('resolution') is not None or opts.get('save_latents')):
            raise UserError('Latent re-export keeps its sampled resolution and does not save new generation latents')
        params.update(from_latents=bool(latent),resolution=str(opts.get('resolution') if opts.get('resolution') is not None else '1024'),texture_size=opts.get('texture_size') if opts.get('texture_size') is not None else 2048,decimation_target=opts.get('decimation_target') if opts.get('decimation_target') is not None else 100000,save_latents=bool(opts.get('save_latents')))
        if params['resolution'] not in ('512','1024','1536'):
            raise UserError('TRELLIS resolution must be 512, 1024, or 1536')
        number(params['texture_size'],512,4096,'Texture size',True)
        number(params['decimation_target'],1000,1000000,'Decimation target',True)
        if latent:
            params.pop('resolution');params.pop('save_latents')
    elif operation=='audio.sfx':
        if refs or target:
            raise UserError('SFX backend accepts text, not reference/source conditioning')
        params['duration']=number(opts.get('duration') if opts.get('duration') is not None else 10,0.1,30,'SFX duration')
        if opts.get('steps') is not None:
            params['steps']=number(opts['steps'],1,200,'Steps',True)
        if opts.get('cfg_scale') is not None:params['cfg_scale']=number(opts['cfg_scale'],0,20,'SFX CFG scale')
    elif music:
        mode=operation.rsplit('.',1)[-1] if operation!='audio.music' else 'generate'
        params['music_task']={'generate':'text2music','layer':'lego'}.get(mode,mode)
        if mode!='generate' and not target:
            raise UserError('This music operation requires --input SOURCE.wav')
        if mode=='generate' and target:
            raise UserError('Use --reference for style guidance, or a source-audio music operation')
        if len(refs)>1:
            raise UserError('Music accepts one style-reference file')
        params['style_reference_index']=1 if target and refs else 0 if refs else None
        params['source_index']=0 if target else None
        refs=([target] if target else [])+refs
        lyrics=Path(existing_file(opts['lyrics_file'],'Lyrics')).read_text() if opts.get('lyrics_file') else ''
        if lyrics and opts.get('instrumental'):
            raise UserError('Supplied lyrics and --instrumental conflict')
        params.update(duration=number(opts.get('duration') if opts.get('duration') is not None else 30,10,600,'Music duration'),lyrics=lyrics,instrumental=bool(opts.get('instrumental')) or (mode=='generate' and not lyrics),bpm=opts.get('bpm'),key=opts.get('key') or '',language=opts.get('language') or 'unknown',track=opts.get('track'),tracks=opts.get('tracks'),start=opts.get('start') if opts.get('start') is not None else 0,end=opts.get('end') if opts.get('end') is not None else -1)
        if opts.get('steps') is not None:
            params['steps']=number(opts['steps'],1,100,'Music steps',True)
            if model.endswith('turbo') and params['steps']!=8:raise UserError('ACE Turbo uses its eight-step schedule')
        if params['bpm'] is not None:number(params['bpm'],30,300,'BPM',True)
        number(params['start'],0,600,'Source interval start')
        if params['end']!=-1:number(params['end'],0,600,'Source interval end')
        if mode in ('extract','layer') and not params['track']:
            raise UserError('Track operation requires --track')
        if mode=='complete' and not params['tracks']:
            raise UserError('Complete requires --tracks')
        allowed_tracks={'vocals','backing_vocals','drums','bass','guitar','keyboard','percussion','strings','synth','fx','brass','woodwinds'}
        if params['track'] and params['track'] not in allowed_tracks:
            raise UserError('Unsupported music track')
        if params['tracks'] and any(t.strip() not in allowed_tracks for t in params['tracks'].split(',')):
            raise UserError('Unsupported music completion track')
        if mode=='repaint' and (params['start']<0 or (params['end']!=-1 and params['end']<=params['start'])):
            raise UserError('Repaint needs a nonnegative start and an end after start')
    else:
        if opts.get('speed') is not None or opts.get('language') is not None:
            raise UserError('This speech adapter does not expose speed or language overrides')
        if model=='voxcpm2' and opts.get('voice') is not None:
            raise UserError('Use a reference or voice description, not a preset speaker for VoxCPM2')
        if operation=='audio.speak' and (refs or opts.get('direction') or opts.get('voice') not in (None,'default')):
            raise UserError('Phonon supports plain speech with its default voice')
        transcript=opts.get('transcript')
        if opts.get('transcript_file'):
            transcript=Path(existing_file(opts['transcript_file'],'Transcript')).read_text()
        if operation=='audio.clone' and (not opts.get('consent') or len(refs)!=1 or not transcript):
            raise UserError('Cloning requires one reference, exact transcript, and consent')
        if operation=='audio.design' and (not opts.get('direction') or refs):
            raise UserError('Design requires direction and no reference; use clone for references')
        if len(prompt)>2000 or len(transcript or '')>2000 or len(opts.get('direction') or '')>2000:
            raise UserError('Split speech inputs into at most 2000 characters per job')
        if operation=='audio.clone':
            from .beam_audio_worker import wav_info
            info=wav_info(Path(existing_file(refs[0],'Voice reference')).read_bytes())
            if info['duration_seconds']>60:
                raise UserError('Voice reference must be at most 60 seconds')
        params.update(direction=opts.get('direction'),transcript=transcript)
        if model=='voxcpm2' and opts.get('steps') is not None:params['steps']=number(opts['steps'],1,100,'Speech inference steps',True)
    params['references']=[existing_file(p,'Reference') for p in refs]
    suffix='.zip' if operation=='model.views' else '.pt' if operation=='motion.extract' else '.npz' if operation.startswith('motion.') or operation in ('model.segment','audio.face') else '.glb' if operation.startswith('model.') else '.png' if operation.startswith('image.') else '.wav'
    output=Path(opts.get('output') or ROOT/'outputs'/(secrets.token_hex(8)+suffix)).expanduser().resolve()
    if output.suffix!=suffix:
        raise UserError('Expected output suffix '+suffix)
    if any(Path(str(output)+s).exists() for s in ('','.json','.log','.remote.json','.result.json')):
        raise UserError('Output or run record already exists')
    if model in ('phonon','voxcpm2') and opts.get('seed') is not None:
        raise UserError('This speech adapter does not expose seeded generation')
    seed=opts.get('seed') if opts.get('seed') is not None else secrets.randbelow(2**32)
    number(seed,0,2**32-1,'Seed',True)
    return Plan(operation,model,'remote',[],str(output),prompt,seed,False,warnings,params)


def run(plan, recover=False):
    from .runtime import validate_output, artifact_info
    output=Path(plan.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    receipt=Path(str(output)+'.json')
    report_path=Path(str(output)+'.result.json')
    if recover and output.exists() and report_path.exists():
        import hashlib
        report=json.loads(report_path.read_text())
        if hashlib.sha256(output.read_bytes()).hexdigest()!=report['sha256']:
            raise UserError('Existing output does not match remote digest')
        complete=True
        main_name=Path(report['file']).name
        for item in report.get('files',[]):
            name=item['name']
            if Path(name).name!=name:
                raise UserError('Invalid remote result filename')
            target=output if name==main_name else output.with_name(output.stem+name[len('output'):] if name.startswith('output') else output.stem+'.'+name)
            if not target.exists():
                complete=False
            elif hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:
                raise UserError('Existing sidecar does not match remote digest: '+str(target))
        if complete:
            validate_output(output)
            result={'status':'completed','plan':plan.to_dict(),'artifact':artifact_info(output),'remote':report}
            receipt.write_text(json.dumps(result,indent=2))
            return result
    if not recover and (output.exists() or receipt.exists()):
        raise UserError('Output or receipt exists')
    if recover and not Path(str(output)+'.remote.json').exists():
        raise UserError('No provider task record; refusing to resubmit an uncertain job')
    started=time.monotonic()
    result={'status':'running','plan':plan.to_dict()}
    receipt.write_text(json.dumps(result,indent=2))
    try:
        with Path(str(output)+'.log').open('a' if recover else 'x') as log:
            subprocess.run([str(ROOT/'.backends/beam/bin/python'),str(ROOT/'cgc/remote_client.py'),'--plan',json.dumps(plan.to_dict())],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=7200)
        validate_output(output)
        result.update(status='completed',artifact=artifact_info(output),remote=json.loads(Path(str(output)+'.result.json').read_text()))
    except BaseException as exc:
        tracking_path=Path(str(output)+'.remote.json')
        tracking=json.loads(tracking_path.read_text()) if tracking_path.exists() else {}
        status=tracking.get('status','UNKNOWN').upper()
        local_status={'ERROR':'failed','FAILED':'failed','TIMEOUT':'failed','REJECTED':'failed','CANCELLED':'cancelled','COMPLETE':'collection_pending','COMPLETED':'collection_pending'}.get(status,'remote_outcome_unknown')
        result.update(status=local_status,error=str(exc))
        raise UserError(f'Remote execution failed; inspect {output}.log and provider task record before retrying') from exc
    finally:
        result['local_seconds']=time.monotonic()-started
        receipt.write_text(json.dumps(result,indent=2))
    return result
