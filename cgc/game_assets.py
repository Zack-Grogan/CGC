"""Deterministic static game-asset packaging; the original is never overwritten."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib

PROFILES={
 'portable': {'primary':'lod0.glb','format':'glTF 2.0','import':'Load lod0.glb. Choose separate LOD files explicitly. Collision meshes are proxies, not engine physics objects.'},
 'bevy': {'primary':'lod0.glb','format':'glTF 2.0','import':'Load GltfAssetLabel::Scene(0) from lod0.glb. Select separate LOD handles in application code. Create colliders explicitly with the physics library.'},
 'godot': {'primary':'lod0.glb','format':'glTF 2.0','import':'Import lod0.glb as a scene. Godot can generate its own mesh LODs; avoid double-applying LOD systems. collision.glb uses -convcolonly suffixes for Godot collision import.'},
 'unity': {'primary':'asset.fbx','format':'FBX derivative + original glTF','import':'Import asset.fbx. Assign separate LOD renderers to an LODGroup and attach reviewed convex MeshColliders. Rebuild PBR material mappings from materials.json; FBX conversion is not a PBR fidelity guarantee.'},
 'unreal': {'primary':'asset.fbx','format':'FBX derivative + original glTF','import':'Import asset.fbx as static meshes, without Combine Meshes. UCX_<render name>_00 proxies are included when collision=convex. Separate lodN.fbx files can be imported as LOD levels. Rebuild materials from materials.json.'},
}

def _sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def _read(path):
 data=Path(path).read_bytes()
 if len(data)<28 or struct.unpack_from('<4sII',data)!=(b'glTF',2,len(data)):raise ValueError('Expected a valid GLB 2.0 file')
 n,kind=struct.unpack_from('<II',data,12)
 if kind!=0x4e4f534a or 20+n+8>len(data):raise ValueError('Invalid GLB JSON chunk')
 doc=json.loads(data[20:20+n]);size,kind=struct.unpack_from('<II',data,20+n)
 if kind!=0x004e4942 or 28+n+size!=len(data):raise ValueError('Expected one GLB binary chunk')
 if len(doc.get('buffers',[]))!=1 or doc['buffers'][0].get('uri'):raise ValueError('Use a GLB with one embedded buffer')
 if not doc.get('scenes') or not 0<=doc.get('scene',0)<len(doc['scenes']):raise ValueError('Asset packaging requires a defined default scene')
 for image in doc.get('images',[]):
  if 'uri' in image and not image['uri'].startswith('data:'):raise ValueError('Embed external image files before packaging')
 return doc,data[28+n:]

def inspect_asset(path,required_nodes=()):
 from .media import inspect
 path=Path(path).expanduser().resolve(strict=True);doc,_=_read(path)
 result=inspect(path)
 active=set();pending=list(doc.get('scenes',[{}])[doc.get('scene',0)].get('nodes',[]))
 while pending:
  index=pending.pop()
  if index in active:continue
  if type(index) is not int or not 0<=index<len(doc.get('nodes',[])):raise ValueError('Invalid scene node reference')
  active.add(index);pending.extend(doc['nodes'][index].get('children',[]))
 names=[doc['nodes'][index].get('name') for index in active]
 result['active_scene_node_count']=len(active)
 required=[{'name':name,'matches':names.count(name),'status':'passed' if names.count(name)==1 else 'failed'} for name in required_nodes]
 result['required_nodes']=required;result['status']='failed' if any(row['matches']!=1 for row in required) else 'inspected'
 result.update(path=str(path),format='glTF 2.0',coordinate_contract={'up':'+Y','front':'+Z','handedness':'right','linear_unit':'meter'},
  mesh_nodes=[{'name':node.get('name',f'node_{i}'),'mesh':node['mesh']} for i,node in enumerate(doc.get('nodes',[])) if 'mesh'in node],
  required_extensions=doc.get('extensionsRequired',[]),used_extensions=doc.get('extensionsUsed',[]),
  morph_target_primitives=sum(bool(p.get('targets')) for m in doc.get('meshes',[]) for p in m['primitives']),
  warnings=['The glTF unit convention does not prove that the author modeled the asset at the intended real-world size.','Accessor bounds are not a posed/deformed mesh quality check.'])
 return result

def _scale_glb(source,destination,scale,yaw_degrees=0.):
 if scale==1 and yaw_degrees==0:shutil.copyfile(source,destination);return
 doc,binary=_read(source)
 for scene in doc.get('scenes',[]):
  import math
  half=math.radians(yaw_degrees)/2
  node={'name':'CGC_units_and_facing','children':scene.get('nodes',[]),'scale':[scale,scale,scale],'rotation':[0,math.sin(half),0,math.cos(half)]}
  doc.setdefault('nodes',[]).append(node);scene['nodes']=[len(doc['nodes'])-1]
 encoded=json.dumps(doc,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4)
 destination.write_bytes(struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(binary))+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary)

def _material_manifest(source,out):
 doc,binary=_read(source);images=[];(out/'textures').mkdir()
 for index,image in enumerate(doc.get('images',[])):
  if 'bufferView' not in image:
   images.append({'index':index,'embedded_data_uri':True});continue
  view=doc['bufferViews'][image['bufferView']];start=view.get('byteOffset',0)
  suffix={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','image/ktx2':'.ktx2'}.get(image.get('mimeType'),'.bin')
  target=out/'textures'/f'image_{index:03d}{suffix}';target.write_bytes(binary[start:start+view['byteLength']])
  images.append({'index':index,'path':str(target.relative_to(out)),'mime_type':image.get('mimeType'),'sha256':_sha(target)})
 result={'materials':doc.get('materials',[]),'textures':doc.get('textures',[]),'samplers':doc.get('samplers',[]),'images':images,
 'channel_contract':{'base_color':'sRGB; alpha is coverage/opacity according to alphaMode','emissive':'sRGB','normal':'linear data, tangent-space +Y','metallic_roughness':'linear data; roughness=G, metallic=B','occlusion':'linear data; occlusion=R'},
 'engine_mapping_notes':['Unity metallic/smoothness workflows require metallic in R and smoothness (1 - roughness) in A; do not assign the original glTF packed map without conversion.','Unreal material normal settings may require Flip Green Channel when using a DirectX tangent-normal convention.','FBX does not preserve every glTF PBR material or extension. The original GLB and maps are authoritative.']}
 (out/'materials.json').write_text(json.dumps(result,indent=2));return result

def find_blender(value=None):
 found=value or os.environ.get('CGC_BLENDER') or shutil.which('blender')
 if found:found=shutil.which(found) or found
 if not found and Path('/Applications/Blender.app/Contents/MacOS/Blender').is_file():found='/Applications/Blender.app/Contents/MacOS/Blender'
 if not found:raise ValueError('Set --blender or CGC_BLENDER to the Blender executable')
 return str(Path(found).expanduser().resolve(strict=True))

def prepare_asset(source,output_dir,engine='portable',lod_ratios=(.5,.25),collision='none',meters_per_unit=1.,blender=None,required_nodes=(),yaw_degrees=0.,min_component_triangles=32,collision_nodes=(),exclude_collision_nodes=()):
 import math
 source=Path(source).expanduser().resolve(strict=True);output=Path(output_dir).expanduser().resolve()
 if engine not in PROFILES or collision not in ('none','convex'):raise ValueError('Unknown engine profile or collision method')
 if type(meters_per_unit) not in (float,int) or not math.isfinite(meters_per_unit) or not .000001<=meters_per_unit<=1000000:raise ValueError('meters_per_unit must be finite and positive')
 if type(yaw_degrees) not in (int,float) or not math.isfinite(yaw_degrees):raise ValueError('Yaw must be finite')
 if type(min_component_triangles) is not int or min_component_triangles<0:raise ValueError('Minimum component triangle count must be a nonnegative integer')
 ratios=list(lod_ratios)
 if len(ratios)>5 or any(type(r) not in (float,int) or not math.isfinite(r) or not 0<r<1 for r in ratios) or any(a<=b for a,b in zip([1.,*ratios],ratios)):raise ValueError('LOD ratios must decrease strictly from below 1; at most five derivatives')
 info=inspect_asset(source,required_nodes)
 if info['status']=='failed':raise ValueError('Required node/socket names must exist exactly once: '+str(info['required_nodes']))
 if collision=='none' and (collision_nodes or exclude_collision_nodes):raise ValueError('Use collision=convex with collision node selection')
 mesh_names=[row['name'] for row in info['mesh_nodes']]
 for name in [*collision_nodes,*exclude_collision_nodes]:
  if mesh_names.count(name)!=1:raise ValueError('Collision selection must name one source mesh node: '+name)
 if set(collision_nodes)&set(exclude_collision_nodes):raise ValueError('A collision node cannot be both included and excluded')
 processing=bool(ratios or collision!='none' or engine in ('unity','unreal'))
 if processing and (info['skins'] or info['animations'] or info['morph_target_primitives']):raise ValueError('LOD, collision and FBX finishing currently require static geometry without skins, animations, or morph targets; use no LODs/collision with a GLB profile to preserve an animated asset')
 if output.exists():raise ValueError('Select a new output directory; existing packages are preserved')
 output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='.cgc-asset-',dir=output.parent) as directory:
  stage=Path(directory);shutil.copyfile(source,stage/'source.glb')
  if _sha(stage/'source.glb')!=info['sha256']:raise RuntimeError('Source changed during snapshot; no package was published')
  _scale_glb(stage/'source.glb',stage/'lod0.glb',float(meters_per_unit),float(yaw_degrees));_material_manifest(stage/'source.glb',stage)
  report={}
  if processing:
   executable=find_blender(blender)
   job={'input':str(stage/'lod0.glb'),'output':str(stage),'engine':engine,'lod_ratios':ratios,'collision':collision,'min_component_triangles':min_component_triangles,'collision_nodes':list(collision_nodes),'exclude_collision_nodes':list(exclude_collision_nodes)}
   (stage/'job.json').write_text(json.dumps(job))
   script=Path(__file__).with_name('game_assets_blender.py')
   try:
    with (stage/'blender.log').open('w') as log:process=subprocess.run([executable,'--background','--factory-startup','--python',str(script),'--','--job',str(stage/'job.json')],stdout=log,stderr=subprocess.STDOUT,check=False,timeout=1800)
   except subprocess.TimeoutExpired as error:
    failed=output.parent/(output.name+'.failed-'+stage.name.rsplit('-',1)[-1]);_publish_directory(stage,failed)
    raise RuntimeError('Blender timed out; inspect '+str(failed/'blender.log')) from error
   if process.returncode or not (stage/'blender-report.json').is_file():
    failed=output.parent/(output.name+'.failed-'+stage.name.rsplit('-',1)[-1]);os.rename(stage,failed)
    raise RuntimeError('Blender did not finish the asset package; inspect '+str(failed/'blender.log'))
   report=json.loads((stage/'blender-report.json').read_text())
  (stage/'job.json').unlink(missing_ok=True)
  from .standards import validate
  validations=[]
  for asset in sorted(stage.glob('*.glb')):
   validation=validate(asset,stage/(asset.name+'.validation.json'))
   report_file=stage/(asset.name+'.validation.json')
   if report_file.exists():
    saved=json.loads(report_file.read_text());saved['source']=asset.name;report_file.write_text(json.dumps(saved,indent=2))
   validations.append({'file':asset.name,'status':validation['status'],'errors':validation['errors'],'warnings':validation['warnings']})
   if validation['status']!='passed':
    failed=output.parent/(output.name+'.failed-'+stage.name.rsplit('-',1)[-1]);os.rename(stage,failed)
    raise RuntimeError('The package failed glTF standards checks; inspect '+str(failed))
  files=[{'path':str(p.relative_to(stage)),'bytes':p.stat().st_size,'sha256':_sha(p)} for p in sorted(stage.rglob('*')) if p.is_file()]
  manifest={'format':'cgc.game-asset-package/1','engine':engine,'primary':PROFILES[engine]['primary'],'source_sha256':info['sha256'],'source_file':'source.glb','original_retained_exact':True,
   'meters_per_source_unit':meters_per_unit,'facing_yaw_degrees':yaw_degrees,'coordinate_contract':'GLB: right-handed, +Y up, front +Z, meters. FBX export handles axes; verify intended character/object facing in the engine.',
   'lod_policy':'Separate explicit files; engine selection/setup is required. LOD0 is never decimated.','min_component_triangles_for_decimation':min_component_triangles,'collision_policy':collision,'collision_nodes':list(collision_nodes),'exclude_collision_nodes':list(exclude_collision_nodes),'import_notes':PROFILES[engine]['import'],'source_inspection':info,'blender':report,'standards_validation':validations,'files':files,
   'limitations':['Generated LODs require silhouette, UV, normal and texture review at intended viewing distances.','Convex proxies fill concavities and may block doors or interiors. Review placement before use.','This package does not certify engine import, collision behavior, rig quality, or artistic quality.','No engine shader conversion can be assumed to reproduce all source PBR extensions.']}
  (stage/'asset-package.json').write_text(json.dumps(manifest,indent=2))
  _publish_directory(stage,output)
 return {'status':'completed','package':str(output),'manifest':str(output/'asset-package.json'),'primary':str(output/manifest['primary']),'source_sha256':info['sha256'],'source_preserved':_sha(source)==info['sha256'],'blender':report}


def _publish_directory(stage,output):
 """Atomic no-replace publication; never replace an existing directory."""
 import ctypes
 import sys
 if os.name=='nt':os.rename(stage,output);return
 library=ctypes.CDLL(None,use_errno=True)
 if sys.platform=='darwin':
  operation=library.renamex_np;operation.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];operation.restype=ctypes.c_int
  result=operation(os.fsencode(stage),os.fsencode(output),4)
 elif hasattr(library,'renameat2'):
  operation=library.renameat2;operation.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];operation.restype=ctypes.c_int
  result=operation(-100,os.fsencode(stage),-100,os.fsencode(output),1)
 else:raise RuntimeError('Atomic exclusive directory publication is unavailable on this platform')
 if result:
  error=ctypes.get_errno();raise OSError(error,os.strerror(error),str(output))


def _check_render_png(path,size):
 data=path.read_bytes()
 if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Renderer output is not PNG: '+path.name)
 offset=8;header=False;pixels=False;ended=False
 while offset<len(data):
  if offset+12>len(data):raise ValueError('Truncated PNG: '+path.name)
  length,kind=struct.unpack_from('>I4s',data,offset);end=offset+12+length
  if end>len(data):raise ValueError('Truncated PNG chunk: '+path.name)
  payload=data[offset+8:offset+8+length];crc=struct.unpack_from('>I',data,offset+8+length)[0]
  if zlib.crc32(kind+payload)&0xffffffff!=crc:raise ValueError('PNG checksum mismatch: '+path.name)
  if kind==b'IHDR':
   if header or length!=13 or struct.unpack_from('>II',payload)!=(size,size):raise ValueError('Unexpected render dimensions: '+path.name)
   header=True
  elif kind==b'IDAT':pixels=True
  elif kind==b'IEND':
   if length or end!=len(data):raise ValueError('Invalid PNG ending: '+path.name)
   ended=True
  offset=end
 if not header or not pixels or not ended:raise ValueError('Incomplete render PNG: '+path.name)


def render_asset(source,output_dir,size=512,blender=None,timeout=1800,light_scale=0.12,samples=24,clay=False):
 import math
 source=Path(source).expanduser().resolve(strict=True);output=Path(output_dir).expanduser().resolve()
 if type(size) is not int or not 256<=size<=4096:raise ValueError('Render size must be an integer from 256 through 4096')
 if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:raise ValueError('Render timeout must be positive and finite')
 if type(light_scale) not in (int,float) or not math.isfinite(light_scale) or not .001<=light_scale<=10:raise ValueError('Light scale must be finite and from 0.001 through 10')
 if type(samples) is not int or not 1<=samples<=512:raise ValueError('Render samples must be an integer from 1 through 512')
 info=inspect_asset(source)
 if output.exists():raise ValueError('Select a new output directory; existing reviews are preserved')
 executable=find_blender(blender);output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='.cgc-render-',dir=output.parent) as directory:
  stage=Path(directory)
  try:
   snapshot=stage/'source.glb';shutil.copyfile(source,snapshot)
   if _sha(snapshot)!=info['sha256']:raise RuntimeError('Source changed during snapshot')
   command=[executable,'--background','--factory-startup','--python',str(Path(__file__).with_name('asset_render_blender.py')),'--','--input',str(snapshot),'--output-dir',str(stage),'--size',str(size),'--light-scale',str(light_scale),'--samples',str(samples)]
   if clay:command.append('--clay')
   with (stage/'blender.log').open('w') as log:
    try:process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False,timeout=timeout)
    except subprocess.TimeoutExpired as error:raise RuntimeError('Blender review exceeded the '+str(timeout)+' second timeout') from error
   if process.returncode:raise RuntimeError('Blender review exited with code '+str(process.returncode))
   inspection=stage/'inspection.json'
   if not inspection.is_file():raise RuntimeError('Blender did not complete the review inspection')
   inspected=json.loads(inspection.read_text())
   if inspected.get('image_size')!=[size,size] or not inspected.get('meshes') or not inspected.get('triangles'):raise RuntimeError('Blender inspection is incomplete')
   for name in ('front','side','back','three-quarter'):_check_render_png(stage/(name+'.png'),size)
   if _sha(snapshot)!=info['sha256']:raise RuntimeError('Renderer changed the input snapshot')
   inspected['source']='source.glb';inspection.write_text(json.dumps(inspected,indent=2))
   artifacts=[{'path':p.name,'bytes':p.stat().st_size,'sha256':_sha(p)} for p in sorted(stage.iterdir()) if p.is_file()]
   report={'format':'cgc.asset-review/1','status':'completed','source':str(source),'source_sha256':info['sha256'],'snapshot':'source.glb','size':size,'light_scale':light_scale,'samples':samples,'material_mode':'clay' if clay else 'source PBR','views':['front','side','back','three-quarter'],'artifacts':artifacts,
    'inspection':'inspection.json','scope':'Local Blender default-pose review with fitted orthographic cameras and neutral studio lighting. Engine appearance, animation deformation and artistic approval remain separate.'}
   (stage/'render-review.json').write_text(json.dumps(report,indent=2))
   _publish_directory(stage,output)
  except Exception as error:
   if stage.exists():
    failed=output.parent/(output.name+'.failed-'+stage.name.rsplit('-',1)[-1])
    (stage/'failure.json').write_text(json.dumps({'status':'failed','error':str(error),'source':str(source),'source_sha256':info['sha256']},indent=2))
    _publish_directory(stage,failed)
    raise RuntimeError(str(error)+'; failed review retained at '+str(failed)) from error
   raise
 return {'status':'completed','review':str(output),'manifest':str(output/'render-review.json'),'source_sha256':info['sha256'],'source_preserved':_sha(source)==info['sha256'],'views':[str(output/(name+'.png')) for name in report['views']]}

def add_parser(subparsers):
 family=subparsers.add_parser('asset',help='Inspect and prepare portable game assets')
 verbs=family.add_subparsers(dest='action',required=True)
 review=verbs.add_parser('render');review.add_argument('--input',required=True);review.add_argument('--output-dir',required=True);review.add_argument('--size',type=int,default=512);review.add_argument('--blender');review.add_argument('--timeout',type=float,default=1800);review.add_argument('--json',action='store_true')
 review.add_argument('--light-scale',type=float,default=.12,help='Studio light energy multiplier; adjust for material response')
 review.add_argument('--samples',type=int,default=24,help='Cycles CPU samples, 1 through 512')
 review.add_argument('--clay',action='store_true',help='Review geometry with a neutral material override')
 clean=verbs.add_parser('clean',help='Remove exact degenerate static GLB triangles without changing retained samples')
 clean.add_argument('--input',required=True);clean.add_argument('--output','-o',required=True);clean.add_argument('--normalize-normals',action='store_true');clean.add_argument('--json',action='store_true')
 check=verbs.add_parser('inspect');check.add_argument('--input',required=True);check.add_argument('--json',action='store_true');check.add_argument('--require-node',action='append',default=[])
 prepare=verbs.add_parser('prepare');prepare.add_argument('--input',required=True);prepare.add_argument('--output-dir',required=True)
 prepare.add_argument('--engine',choices=tuple(PROFILES),default='portable');prepare.add_argument('--lod-ratios',default='0.5,0.25',help='Comma-separated decreasing ratios, or none')
 prepare.add_argument('--collision',choices=('none','convex'),default='none');prepare.add_argument('--meters-per-unit',type=float,default=1.);prepare.add_argument('--yaw-degrees',type=float,default=0.)
 prepare.add_argument('--collision-node',action='append',default=[]);prepare.add_argument('--exclude-collision-node',action='append',default=[])
 prepare.add_argument('--min-component-triangles',type=int,default=32)
 prepare.add_argument('--require-node',action='append',default=[])
 prepare.add_argument('--blender');prepare.add_argument('--json',action='store_true')
 return family

def handle(args):
 if args.action=='clean':
  from .mesh_clean import clean_asset
  return clean_asset(args.input,args.output,args.normalize_normals)
 if args.action=='render':return render_asset(args.input,args.output_dir,args.size,args.blender,args.timeout,args.light_scale,args.samples,args.clay)
 if args.action=='inspect':return inspect_asset(args.input,args.require_node)
 ratios=[] if args.lod_ratios.lower()=='none' else [float(value) for value in args.lod_ratios.split(',')]
 return prepare_asset(args.input,args.output_dir,args.engine,ratios,args.collision,args.meters_per_unit,args.blender,args.require_node,args.yaw_degrees,args.min_component_triangles,args.collision_node,args.exclude_collision_node)
