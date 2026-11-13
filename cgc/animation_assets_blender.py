"""Blender implementation for deterministic CGC animation packages."""
import argparse
import json
import math
from pathlib import Path
import runpy
import sys
import bpy
import numpy as np

parser=argparse.ArgumentParser();parser.add_argument('--job',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);job=json.loads(args.job.read_text());output=Path(job['output'])

def reset():
 bpy.ops.wm.read_factory_settings(use_empty=True)
 bpy.context.scene.unit_settings.system='METRIC';bpy.context.scene.unit_settings.scale_length=1.

def fcurves(action):
 if hasattr(action,'fcurves'):return list(action.fcurves)
 curves=[]
 for layer in action.layers:
  for strip in layer.strips:
   if hasattr(strip,'channelbag'):
    for slot in action.slots:
     bag=strip.channelbag(slot)
     if bag:curves.extend(bag.fcurves)
 return curves

def active_action(arm,source_clip=None):
 actions=[]
 bound=arm.animation_data.action if arm.animation_data else None
 for action in bpy.data.actions:
  if (source_clip is not None and action.name==source_clip) or (source_clip is None and (action==bound if bound else any(curve.data_path.startswith('pose.bones[') for curve in fcurves(action)))):actions.append(action)
 if len(actions)!=1:raise RuntimeError('Select exactly one source clip; available: '+str([a.name for a in bpy.data.actions]))
 action=actions[0]
 arm.animation_data_create()
 for track in arm.animation_data.nla_tracks:track.mute=True
 arm.animation_data.action=action
 if action.slots:
  if len(action.slots)!=1:raise RuntimeError('Multi-slot source actions need an explicit authored binding; automatic rebinding is disabled')
  arm.animation_data.action_slot=action.slots[0]
 return action

def sample_scene(action,arm=None,fractions=None,frame_range=None):
 start,end=frame_range or action.frame_range;scene=bpy.context.scene
 if end<=start:raise RuntimeError('Clip has no positive duration')
 samples=[]
 if fractions is None:fractions=[float((frame-start)/(end-start)) for frame in np.unique(np.round(np.linspace(start,end,9)))]
 for alpha in fractions:
  frame=float(start+(end-start)*alpha);scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update()
  entry={'fraction':float(alpha)}
  if arm:
   entry['bones']={bone.name:list(arm.matrix_world@bone.head) for bone in arm.pose.bones}
   entry['rotations']={bone.name:list((arm.matrix_world@bone.matrix).to_quaternion().normalized()) for bone in arm.pose.bones}
  deps=bpy.context.evaluated_depsgraph_get();points=[];morph={}
  for obj in scene.objects:
   if obj.type!='MESH':continue
   evaluated=obj.evaluated_get(deps)
   points.extend(obj.matrix_world@v.co for v in evaluated.data.vertices)
   if obj.data.shape_keys:morph[obj.name]={key.name:float(key.value) for key in obj.data.shape_keys.key_blocks if key.name!='Basis'}
  if not points or any(not all(math.isfinite(c) for c in p) for p in points):raise RuntimeError('Nonfinite or empty evaluated geometry')
  entry['bounds']={'min':[min(p[i] for p in points) for i in range(3)],'max':[max(p[i] for p in points) for i in range(3)]};entry['morph_values']=morph;samples.append(entry)
 report={'fps':scene.render.fps/scene.render.fps_base,'frame_start':float(start),'frame_end':float(end),'duration_seconds':float((end-start)*scene.render.fps_base/scene.render.fps),'samples':samples}
 if arm:
  roots=[bone.name for bone in arm.data.bones if bone.parent is None]
  report['bones']=[bone.name for bone in arm.data.bones];report['root_bones']=roots
  report['bone_parents']={bone.name:bone.parent.name if bone.parent else None for bone in arm.data.bones}
  if len(roots)==1:
   delta=np.asarray(samples[-1]['bones'][roots[0]])-samples[0]['bones'][roots[0]]
   report['root_end_displacement_blender_m']=delta.tolist();report['root_horizontal_displacement_m']=float(np.linalg.norm(delta[:2]))
  from mathutils import Quaternion
  report['endpoint_bone_rotation_gap_radians']=max(Quaternion(samples[0]['rotations'][name]).rotation_difference(Quaternion(samples[-1]['rotations'][name])).angle for name in report['bones'])
 return report

reset();mode=job['mode'];face_report=None
if mode=='retarget':
 module=runpy.run_path(job['retarget_script'],run_name='cgc_native_retarget')
 with np.load(job['motion'],allow_pickle=False) as data:
  if 'joint_names'in data.files and data['joint_names'].tolist()!=module['SOMA77']:raise RuntimeError('Motion joint-name order differs from the retargeter')
 sys.path.insert(0,str(Path(job['retarget_script']).parent))
 command=[job['retarget_script'],'--rig',job['input'],'--motion',job['motion'],'--out',str(output/'native-retarget.glb'),'--speed',str(job['speed']),'--arm-spread',str(job['arm_spread'])]
 if job['loop']!='none':command.append('--loop')
 if job['loop']=='whole':command.append('--keep-whole')
 if job['root_motion']=='in-place':command.append('--in-place')
 if job['stiff_fingers']:command.append('--stiff-fingers')
 sys.argv=command;module['main']()
 arms=[obj for obj in bpy.context.scene.objects if obj.type=='ARMATURE']
 if len(arms)!=1:raise RuntimeError('Retarget output must have one armature')
 arm=arms[0];action=active_action(arm)
elif mode=='prepare':
 bpy.context.scene.render.fps=60
 bpy.ops.import_scene.gltf(filepath=job['input'])
 arms=[obj for obj in bpy.context.scene.objects if obj.type=='ARMATURE']
 if len(arms)!=1:raise RuntimeError('Prepare currently supports one skeletal armature; use face for explicit morph animation')
 arm=arms[0];action=active_action(arm,job.get('clip'))
else:
 bpy.context.scene.render.fps=60
 bpy.ops.import_scene.gltf(filepath=job['input'])
 spec=json.loads(Path(job['mapping']).read_text())
 with np.load(job['weights'],allow_pickle=False) as data:
  names=data['channel_names'].tolist();times=data['times'];weights=data['weights']
 owners=[]
 for column,name in enumerate(names):
  if name in spec.get('ignore_channels',[]):continue
  rule=spec['channels'][name];obj=bpy.data.objects.get(rule['node'])
  if obj is None or obj.type!='MESH' or not obj.data.shape_keys:raise RuntimeError('Mapped node has no shape keys: '+rule['node'])
  key=obj.data.shape_keys.key_blocks.get(rule['target'])
  if key is None:raise RuntimeError('Mapped morph target is missing: '+rule['target'])
  values=weights[:,column]*rule.get('scale',1.)+rule.get('offset',0.)
  if not np.isfinite(values).all() or values.min()<-10 or values.max()>10:raise RuntimeError('Mapped shape values exceed Blender supported range')
  for timestamp,value in zip(times,values):key.value=float(value);key.keyframe_insert('value',frame=1+float(timestamp)*60)
  owner=obj.data.shape_keys
  if owner not in owners:owners.append(owner)
 if len(owners)!=1:raise RuntimeError('This face adapter currently exports one mapped morph mesh per clip; split mappings explicitly')
 action=owners[0].animation_data.action
 for curve in fcurves(action):
  for key in curve.keyframe_points:key.interpolation='LINEAR'
 arm=None;face_report={'basis':'Explicit user mapping; no new morph targets','mapped_channels':len(spec['channels']),'ignored_channels':len(spec.get('ignore_channels',[])),'input_times':[float(times[0]),float(times[-1])],'baked_fps':60}

# Keep this derivative to exactly one selected clip. Source snapshots remain unchanged.
for other in list(bpy.data.actions):
 if other!=action:bpy.data.actions.remove(other)
action.name=job['name'];start,end=action.frame_range;scene=bpy.context.scene
scene.frame_start=math.floor(start);scene.frame_end=math.ceil(end)
scene.frame_set(scene.frame_start)
before=sample_scene(action,arm,frame_range=(scene.frame_start,scene.frame_end))
before['authored_frame_range']=[float(start),float(end)]
before['timing_padding_seconds']=[float((start-scene.frame_start)*scene.render.fps_base/scene.render.fps),float((scene.frame_end-end)*scene.render.fps_base/scene.render.fps)]
report={'blender_version':bpy.app.version_string,'clip_name':job['name'],'mode':mode,'loop_policy':job.get('loop','source clip'),'root_motion':job.get('root_motion','source clip'),'bone_reparenting':False,'animated_decimation':False,'source_evaluation':before,'face_mapping':face_report,'engine_import_verified':False}
bpy.ops.wm.save_as_mainfile(filepath=str(output/'animation.blend'))
bpy.ops.export_scene.gltf(filepath=str(output/'animation.glb'),export_format='GLB',export_animations=True,export_animation_mode='ACTIONS',export_nla_strips=False,export_force_sampling=True,export_frame_range=True,export_morph_animation=True)
# FBX contains exactly this action, no automatically selected NLA clips or leaf bones.
if job['engine'] in ('unity','unreal'):
 unreal=job['engine']=='unreal'
 bpy.ops.export_scene.fbx(filepath=str(output/'animation.fbx'),object_types={'ARMATURE','MESH','EMPTY'},add_leaf_bones=False,use_armature_deform_only=False,use_mesh_modifiers=False,
  bake_anim=True,bake_anim_use_all_bones=True,bake_anim_use_nla_strips=False,bake_anim_use_all_actions=False,bake_anim_step=1.,bake_anim_simplify_factor=0.,
  global_scale=1.,apply_unit_scale=True,apply_scale_options='FBX_SCALE_UNITS',axis_forward='-Y' if unreal else '-Z',axis_up='Z' if unreal else 'Y',path_mode='COPY',embed_textures=True)
 had_arm=arm is not None
 bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.fbx(filepath=str(output/'animation.fbx'))
 arms=[obj for obj in bpy.context.scene.objects if obj.type=='ARMATURE']
 if had_arm:
  if len(arms)!=1:raise RuntimeError('FBX readback lost its armature')
  imported=arms[0];read_action=active_action(imported);after=sample_scene(read_action,imported,[sample['fraction'] for sample in before['samples']])
  if set(before['bones'])!=set(after['bones']):raise RuntimeError('FBX readback changed the bone-name set')
  if before['bone_parents']!=after['bone_parents']:raise RuntimeError('FBX readback changed bone parenting')
  if abs(before['duration_seconds']-after['duration_seconds'])>1e-4:raise RuntimeError('FBX readback changed clip duration')
  error=max(float(np.linalg.norm(np.asarray(a['bones'][name])-b['bones'][name])) for a,b in zip(before['samples'],after['samples']) for name in before['bones'])
  (output/'fbx-probe.json').write_text(json.dumps({'before':before,'after':after,'maximum_joint_error_m':error},indent=2))
  if error>.005:raise RuntimeError('FBX readback joint-position error exceeds 5mm: '+str(error))
  report['fbx_readback']={'reader':'Blender '+bpy.app.version_string,'bone_names_preserved':True,'bone_parents_preserved':True,'maximum_sampled_joint_error_m':error,'duration_seconds':after['duration_seconds'],'engine_editor_verified':False}
 else:
  meshes=[obj for obj in bpy.context.scene.objects if obj.type=='MESH' and obj.data.shape_keys]
  if len(meshes)!=1:raise RuntimeError('FBX readback lost mapped morph targets')
  keys=set(meshes[0].data.shape_keys.key_blocks.keys());expected=set(spec['channels'][name]['target'] for name in spec['channels'])
  if not expected<=keys:raise RuntimeError('FBX readback lost a named mapped morph target')
  actions=list(bpy.data.actions)
  if not actions:raise RuntimeError('FBX readback lost morph animation')
  read_action=meshes[0].data.shape_keys.animation_data.action
  after=sample_scene(read_action,fractions=[sample['fraction'] for sample in before['samples']])
  error=max(abs(a['morph_values'][next(iter(a['morph_values']))][name]-b['morph_values'][meshes[0].name][name]) for a,b in zip(before['samples'],after['samples']) for name in expected)
  if error>1e-4:raise RuntimeError('FBX readback changed morph animation values: '+str(error))
  (output/'fbx-probe.json').write_text(json.dumps({'before':before,'after':after,'maximum_morph_weight_error':error},indent=2))
  report['fbx_readback']={'reader':'Blender '+bpy.app.version_string,'mapped_targets_present':True,'maximum_sampled_morph_weight_error':error,'duration_seconds':after['duration_seconds'],'engine_editor_verified':False}
report['glb_animation_names']=[]
import struct
raw=(output/'animation.glb').read_bytes();length=struct.unpack_from('<I',raw,12)[0];document=json.loads(raw[20:20+length]);report['glb_animation_names']=[item.get('name') for item in document.get('animations',[])]
if report['glb_animation_names']!=[job['name']]:raise RuntimeError('GLB export did not retain exactly the named clip: '+str(report['glb_animation_names']))
(output/'animation-report.json').write_text(json.dumps(report,indent=2))
print('CGC_ANIMATION_COMPLETED')
