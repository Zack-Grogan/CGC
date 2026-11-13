"""Deterministic animation delivery. Models remain remote; Blender handles derivatives."""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile

ENGINES=('portable','bevy','godot','unity','unreal')
NOTES={
 'portable':'Load animation.glb. Bind the named clip to this exact compatible skeleton. Loop playback and root-motion consumption belong to the application.',
 'bevy':'Load the named Gltf animation into an AnimationGraph and attach it to the spawned AnimationPlayer. Configure repeating playback explicitly. Consume root movement in application code as required.',
 'godot':'Import animation.glb and select its clip in AnimationPlayer/AnimationTree. Set loop mode and the root-motion track explicitly in the importer/AnimationTree.',
 'unity':'Import animation.fbx. Start with Generic rig to retain the authored hierarchy; Humanoid requires a reviewed Avatar mapping. Set clip loop and Root Transform/Apply Root Motion options in the importer/controller.',
 'unreal':'Import animation.fbx as Skeletal Mesh + animation or bind it to the matching Skeleton. Enable root motion on the animation/controller only when intended. Review Blender FBX import against the UE pipeline version.',
}

def _sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def _doc(path):
 data=Path(path).read_bytes()
 if len(data)<28 or struct.unpack_from('<4sII',data)!=(b'glTF',2,len(data)):raise ValueError('Supply an embedded GLB 2.0 file')
 length,kind=struct.unpack_from('<II',data,12)
 if kind!=0x4e4f534a:raise ValueError('Missing GLB document')
 doc=json.loads(data[20:20+length])
 if len(doc.get('buffers',[]))!=1 or doc['buffers'][0].get('uri'):raise ValueError('Embed GLB buffers before animation processing')
 if any('uri' in image and not image['uri'].startswith('data:') for image in doc.get('images',[])):raise ValueError('Embed GLB image resources before animation processing')
 return doc

def _clip_name(value):
 if not isinstance(value,str) or not value.strip() or len(value)>128 or any(c in value for c in '/\\\x00'):raise ValueError('Clip name must be nonempty, at most 128 characters, without path separators')
 return value

def _channels(path):
 with zipfile.ZipFile(path) as archive:
  data=archive.read('channel_names.npy')
 if data[:8]!=b'\x93NUMPY\x01\x00':raise ValueError('Expected NPY v1 channel names')
 length=int.from_bytes(data[8:10],'little');header=ast.literal_eval(data[10:10+length].decode().strip())
 dtype=header['descr']
 if not isinstance(dtype,str) or not dtype.startswith('<U') or header['fortran_order'] or len(header['shape'])!=1:raise ValueError('Expected fixed Unicode face channel names')
 width=int(dtype[2:])*4;payload=data[10+length:]
 if len(payload)!=width*header['shape'][0]:raise ValueError('Truncated channel names')
 names=[payload[i:i+width].decode('utf-32-le').rstrip('\x00') for i in range(0,len(payload),width)]
 if len(names)!=68 or any(not name for name in names):raise ValueError('Expected 68 named SDK Mark channels')
 if len(names)!=len(set(names)):raise ValueError('Duplicate face channel names')
 return names

def validate_face_mapping(rig,weights,mapping):
 from .face import inspect
 inspect(weights);names=_channels(weights);doc=_doc(rig)
 spec=json.loads(Path(mapping).read_text());rules=spec.get('channels');ignored=spec.get('ignore_channels',[])
 if spec.get('format')!='cgc.face-map/1' or not isinstance(rules,dict) or not isinstance(ignored,list):raise ValueError('Use a cgc.face-map/1 object with channels and explicit ignore_channels')
 if any(not isinstance(name,str) for name in ignored):raise ValueError('Ignored channels must be names')
 if set(rules)&set(ignored) or set(rules)|set(ignored)!=set(names):raise ValueError('Every source channel must be mapped once or explicitly ignored')
 if not rules:raise ValueError('Map at least one facial channel')
 if len(ignored)!=len(set(ignored)):raise ValueError('Duplicate ignored channel')
 if len({rule.get('node') for rule in rules.values() if isinstance(rule,dict)})!=1:raise ValueError('Map one morph mesh per clip; split mappings explicitly')
 destinations=set()
 for channel,rule in rules.items():
  if not isinstance(rule,dict) or set(rule)-{'node','target','scale','offset'}:raise ValueError('Invalid facial mapping rule: '+channel)
  matches=[node for node in doc.get('nodes',[]) if node.get('name')==rule.get('node')]
  if len(matches)!=1 or 'mesh' not in matches[0]:raise ValueError('Mapping node must identify one mesh: '+str(rule.get('node')))
  mesh=doc['meshes'][matches[0]['mesh']];targets=mesh.get('extras',{}).get('targetNames',[])
  if targets.count(rule.get('target'))!=1 or any(len(p.get('targets',[]))!=len(targets) for p in mesh['primitives']):raise ValueError('Mapping requires an existing, uniquely named morph target: '+str(rule.get('target')))
  key=(rule['node'],rule['target'])
  if key in destinations:raise ValueError('Multiple channels cannot implicitly combine into one morph target')
  destinations.add(key)
  for field,default in [('scale',1.),('offset',0.)]:
   value=rule.get(field,default)
   if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Facial scale/offset must be finite')
 return {'channels':names,'mapped':len(rules),'explicitly_ignored':len(ignored),'mapping':spec}

def _run(mode,source,output_dir,engine='portable',name='Action',blender=None,**options):
 from .game_assets import find_blender
 source=Path(source).expanduser().resolve(strict=True);output=Path(output_dir).expanduser().resolve()
 if engine not in ENGINES:raise ValueError('Unknown engine profile')
 _clip_name(name);doc=_doc(source)
 if output.exists():raise ValueError('Select a new output directory; existing packages are preserved')
 if mode=='retarget':
  if not doc.get('skins') or doc.get('animations'):raise ValueError('Retarget to a clean skinned bind GLB without existing animations')
  from .motion import inspect
  options['motion']=str(Path(options['motion']).expanduser().resolve(strict=True));inspect(options['motion'])
  speed=options.get('speed',1.);spread=options.get('arm_spread',0.)
  if type(speed) not in (int,float) or not math.isfinite(speed) or not .1<=speed<=4:raise ValueError('Speed must be finite, 0.1 through 4')
  if type(spread) not in (int,float) or not math.isfinite(spread) or not -30<=spread<=45:raise ValueError('Arm spread must be finite, -30 through 45 degrees')
  repo=Path(os.environ.get('CGC_3DLAB_ROOT',Path(__file__).resolve().parents[2]/'image-to-3dlab')).resolve()
  script=repo/'scripts/kimodo_retarget.py';helper=repo/'scripts/arm_clearance.py'
  if not script.is_file() or not helper.is_file():raise ValueError('Set CGC_3DLAB_ROOT to the qualified image-to-3dlab checkout')
 elif mode=='face':
  if doc.get('animations'):raise ValueError('Apply face weights to a clean compatible morph GLB; combine body/face clips explicitly later')
  options['weights']=str(Path(options['weights']).resolve(strict=True));options['mapping']=str(Path(options['mapping']).resolve(strict=True))
  validate_face_mapping(source,options['weights'],options['mapping'])
 elif mode=='prepare':
  if not doc.get('animations'):raise ValueError('Input contains no animation clips')
  clips=[item.get('name') for item in doc['animations']]
  if len(clips)>1 and options.get('clip') is None:raise ValueError('Select an exact --clip name for a multi-clip source: '+str(clips))
  if options.get('clip') is not None and clips.count(options['clip'])!=1:raise ValueError('Source clip name must identify exactly one GLB animation: '+str(clips))
 else:raise ValueError('Unknown animation operation')
 output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='.cgc-animation-',dir=output.parent) as temporary:
  stage=Path(temporary);shutil.copyfile(source,stage/'source.glb');sources={'source.glb':_sha(source)}
  if _sha(stage/'source.glb')!=sources['source.glb']:raise ValueError('Source changed during snapshot')
  job=dict(mode=mode,input=str(stage/'source.glb'),output=str(stage),engine=engine,name=name,**options)
  for key in ('motion','weights','mapping'):
   if job.get(key):
    old=Path(job[key]);target=stage/('source-'+key+old.suffix);shutil.copyfile(old,target)
    sources[target.name]=_sha(old)
    if _sha(target)!=sources[target.name]:raise ValueError('Input changed during snapshot: '+key)
    job[key]=str(target)
  if mode=='retarget':
   vendor=stage/'retarget-source';vendor.mkdir()
   for item in (script,helper):shutil.copyfile(item,vendor/item.name);sources[str((vendor/item.name).relative_to(stage))]=_sha(item)
   job['retarget_script']=str(vendor/script.name)
  (stage/'job.json').write_text(json.dumps(job))
  driver=Path(__file__).with_name('animation_assets_blender.py')
  try:
   with (stage/'blender.log').open('w') as log:
    result=subprocess.run([find_blender(blender),'--background','--factory-startup','--python',str(driver),'--','--job',str(stage/'job.json')],stdout=log,stderr=subprocess.STDOUT,timeout=1800,check=False)
  except subprocess.TimeoutExpired as exc:
   failed=output.parent/(output.name+'.failed-'+stage.name.rsplit('-',1)[-1]);os.rename(stage,failed)
   raise RuntimeError('Local Blender timed out; inspect '+str(failed/'blender.log')) from exc
  if result.returncode or not (stage/'animation-report.json').exists():
   failed=output.parent/(output.name+'.failed-'+stage.name.rsplit('-',1)[-1]);os.rename(stage,failed)
   raise RuntimeError('Animation package did not finish; inspect '+str(failed/'blender.log'))
  from .standards import validate
  validations=[]
  for artifact in sorted(stage.glob('*.glb')):
   checked=validate(artifact,stage/(artifact.stem+'.validation.json'))
   validations.append({'file':artifact.name,'status':checked['status'],'errors':checked['errors'],'warnings':checked['warnings']})
  validation=next(item for item in validations if item['file']=='animation.glb')
  if any(item['status']!='passed' for item in validations):
   failed=output.parent/(output.name+'.failed-'+stage.name.rsplit('-',1)[-1]);os.rename(stage,failed)
   raise RuntimeError('Animation GLB did not pass standards validation; inspect '+str(failed))
  report=json.loads((stage/'animation-report.json').read_text());(stage/'job.json').unlink()
  for path in stage.glob('source*'):
   if path.is_file() and path.name in sources and _sha(path)!=sources[path.name]:raise RuntimeError('Snapshot was modified during processing')
  manifest={'format':'cgc.animation-package/1','mode':mode,'clip_name':name,'engine':engine,'primary':'animation.fbx' if engine in ('unity','unreal') else 'animation.glb','sources':sources,
   'originals_retained_exact':True,'import_notes':NOTES[engine],'report':report,'standards':{'status':validation['status'],'errors':validation['errors'],'warnings':validation['warnings'],'artifacts':validations},
   'worker_sha256':_sha(driver),
   'limits':['No animated decimation or bone reparenting is performed.','Loop/root-motion flags do not configure an engine controller automatically.','FBX material fidelity and target-editor import require separate review.','Numerically valid motion and readback do not prove convincing acting, contact, or deformation.'],
   'files':[{'path':str(p.relative_to(stage)),'sha256':_sha(p),'bytes':p.stat().st_size} for p in sorted(stage.rglob('*')) if p.is_file()]}
  (stage/'animation-package.json').write_text(json.dumps(manifest,indent=2));os.rename(stage,output)
 return {'status':'completed','package':str(output),'manifest':str(output/'animation-package.json'),'primary':str(output/manifest['primary']),'clip_name':name,'report':report}

def retarget(rig,motion,output_dir,engine='portable',name='Action',loop='none',root_motion='keep',speed=1.,stiff_fingers=False,arm_spread=0.,blender=None):
 if loop not in ('none','cycle','whole') or root_motion not in ('keep','in-place'):raise ValueError('Unknown loop or root-motion policy')
 return _run('retarget',rig,output_dir,engine,name,blender,motion=motion,loop=loop,root_motion=root_motion,speed=speed,stiff_fingers=stiff_fingers,arm_spread=arm_spread)

def prepare(source,output_dir,engine='portable',name='Action',clip=None,blender=None):return _run('prepare',source,output_dir,engine,name,blender,clip=clip)

def apply_face(rig,weights,mapping,output_dir,engine='portable',name='Dialogue',blender=None):return _run('face',rig,output_dir,engine,name,blender,weights=weights,mapping=mapping)

def add_parser(subparsers):
 group=subparsers.add_parser('animation',help='Retarget, name and deliver existing skeletal or mapped morph animation')
 verbs=group.add_subparsers(dest='action',required=True)
 for action in ('retarget','prepare','face'):
  command=verbs.add_parser(action);command.add_argument('--input',required=True,help='Compatible GLB rig or animated GLB')
  command.add_argument('--output-dir',required=True);command.add_argument('--engine',choices=ENGINES,default='portable');command.add_argument('--name',default='Dialogue' if action=='face' else 'Action');command.add_argument('--blender');command.add_argument('--json',action='store_true')
  if action=='retarget':
   command.add_argument('--motion',required=True);command.add_argument('--loop',choices=('none','cycle','whole'),default='none');command.add_argument('--root-motion',choices=('keep','in-place'),default='keep');command.add_argument('--speed',type=float,default=1.);command.add_argument('--stiff-fingers',action='store_true');command.add_argument('--arm-spread',type=float,default=0.)
  elif action=='prepare':command.add_argument('--clip',help='Exact source animation name; required if more than one clip exists')
  else:command.add_argument('--weights',required=True);command.add_argument('--mapping',required=True)
 return group

def handle(args):
 from .planning import UserError
 try:
  if args.action=='retarget':return retarget(args.input,args.motion,args.output_dir,args.engine,args.name,args.loop,args.root_motion,args.speed,args.stiff_fingers,args.arm_spread,args.blender)
  if args.action=='prepare':return prepare(args.input,args.output_dir,args.engine,args.name,args.clip,args.blender)
  return apply_face(args.input,args.weights,args.mapping,args.output_dir,args.engine,args.name,args.blender)
 except RuntimeError as exc:
  raise UserError(str(exc)) from exc
