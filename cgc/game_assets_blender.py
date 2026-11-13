"""Blender worker for cgc asset prepare. Receives a local JSON job."""
import argparse
import json
import math
from pathlib import Path
import re
import sys
import bpy
import bmesh
from mathutils import Vector

parser=argparse.ArgumentParser();parser.add_argument('--job',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);job=json.loads(args.job.read_text());output=Path(job['output'])

def load():
 bpy.ops.wm.read_factory_settings(use_empty=True)
 bpy.context.scene.unit_settings.system='METRIC';bpy.context.scene.unit_settings.scale_length=1.
 bpy.ops.import_scene.gltf(filepath=job['input'])
 meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
 if not meshes:raise RuntimeError('No render geometry')
 for i,obj in enumerate(meshes):
  obj['cgc_source_node_name']=obj.name
  if job['engine']=='unreal':obj.name='CGC_'+re.sub('[^a-zA-Z0-9_]','_',obj.name)[:40]+f'_{i:03d}'
 return meshes

def triangles(meshes):return sum(sum(max(0,len(p.vertices)-2) for p in o.data.polygons) for o in meshes)
def bounds(meshes):
 points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices]
 if any(not all(math.isfinite(c) for c in p) for p in points):raise RuntimeError('Nonfinite vertex positions')
 return {'min':[min(p[i] for p in points) for i in range(3)],'max':[max(p[i] for p in points) for i in range(3)]}
def select(objects):
 bpy.ops.object.select_all(action='DESELECT')
 for obj in objects:obj.select_set(True)
 if objects:bpy.context.view_layer.objects.active=objects[0]
def export_glb(path,objects,keep_empties=True):
 select([*objects,*([o for o in bpy.context.scene.objects if o.type=='EMPTY'] if keep_empties else [])]);bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_animations=False)
def export_fbx(path,objects):
 select([*objects,*[o for o in bpy.context.scene.objects if o.type=='EMPTY']])
 unreal=job['engine']=='unreal'
 bpy.ops.export_scene.fbx(filepath=str(path),use_selection=True,object_types={'MESH','EMPTY'},bake_anim=False,add_leaf_bones=False,path_mode='COPY',embed_textures=True,
  global_scale=1.,apply_unit_scale=True,apply_scale_options='FBX_SCALE_UNITS',axis_forward='-Y' if unreal else '-Z',axis_up='Z' if unreal else 'Y')

base=load();baseline=triangles(base);base_bounds=bounds(base)
report={'blender_version':bpy.app.version_string,'base_triangles':baseline,'base_bounds_blender_m':base_bounds,'lods':[],'colliders':[],'fbx':[]}
for level,ratio in enumerate(job['lod_ratios'],1):
 meshes=load();skipped=[]
 for obj in meshes:
  before=triangles([obj])
  if before<=job.get('min_component_triangles',32):skipped.append(obj.name);continue
  bpy.context.view_layer.objects.active=obj
  modifier=obj.modifiers.new('CGC budget derivative','DECIMATE');modifier.ratio=ratio;modifier.use_collapse_triangulate=True
  bpy.ops.object.modifier_apply(modifier=modifier.name)
  if before and not obj.data.polygons:raise RuntimeError('Decimation removed a component')
 count=triangles(meshes)
 if not 0<count<=baseline:raise RuntimeError('Invalid LOD triangle count')
 export_glb(output/f'lod{level}.glb',meshes)
 entry={'level':level,'requested_ratio':ratio,'triangles':count,'actual_ratio':count/baseline,'bounds_blender_m':bounds(meshes),'small_components_retained':skipped,'path':f'lod{level}.glb'}
 if job['engine'] in ('unity','unreal'):
  export_fbx(output/f'lod{level}.fbx',meshes);entry['fbx']=f'lod{level}.fbx'
 report['lods'].append(entry)

meshes=load();colliders=[]
if job['collision']=='convex':
 report['collider_skips']=[]
 for index,obj in enumerate(meshes):
  source_name=obj.get('cgc_source_node_name',obj.name)
  if (job.get('collision_nodes') and source_name not in job['collision_nodes']) or source_name in job.get('exclude_collision_nodes',[]):
   report['collider_skips'].append({'mesh':source_name,'reason':'Excluded by caller collision selection'});continue
  source=bmesh.new();source.from_mesh(obj.data)
  bmesh.ops.remove_doubles(source,verts=list(source.verts),dist=1e-6)
  unseen={v for v in source.verts if v.link_faces};components=[]
  while unseen:
   first=unseen.pop();stack=[first];part={first}
   while stack:
    vertex=stack.pop()
    for edge in vertex.link_edges:
     other=edge.other_vert(vertex)
     if other in unseen:unseen.remove(other);part.add(other);stack.append(other)
   components.append([v.co.copy() for v in part])
  source.free()
  components.sort(key=lambda points:tuple(round(sum(point[axis] for point in points)/len(points),8) for axis in range(3)))
  for component,points in enumerate(components):
   bm=bmesh.new()
   for point in points:bm.verts.new(point)
   bm.verts.ensure_lookup_table()
   if len(points)<4:
    report['collider_skips'].append({'mesh':obj.name,'component':component,'reason':'Fewer than four vertices'});bm.free();continue
   result=bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
   unused=list({v for v in result.get('geom_interior',[])+result.get('geom_unused',[]) if isinstance(v,bmesh.types.BMVert) and v.is_valid})
   if unused:bmesh.ops.delete(bm,geom=unused,context='VERTS')
   bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
   volume=abs(bm.calc_volume(signed=True))
   if len(bm.faces)<4 or any(not edge.is_manifold for edge in bm.edges) or volume<=1e-12:
    report['collider_skips'].append({'mesh':obj.name,'component':component,'reason':'Coplanar or non-volume hull; author a slab/primitive if collision is needed'});bm.free();continue
   data=bpy.data.meshes.new('Collision_'+obj.name);bm.to_mesh(data);bm.free()
   suffix=f'_{component:02d}'
   name='UCX_'+obj.name+suffix if job['engine']=='unreal' else obj.name+suffix+'-convcolonly' if job['engine']=='godot' else 'COL_'+obj.name+suffix
   collider=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(collider);collider.matrix_world=obj.matrix_world.copy();colliders.append(collider)
   report['colliders'].append({'name':name,'render_mesh':obj.name,'source_node':source_name,'component':component,'vertices':len(data.vertices),'triangles':triangles([collider]),'local_volume':volume,'world_volume_m3':volume*abs(obj.matrix_world.to_3x3().determinant()),'closed_manifold':True,'shape':'convex hull'})
 if not colliders:raise RuntimeError('No closed convex collision volume could be generated')
 export_glb(output/'collision.glb',colliders,keep_empties=False)
if job['engine'] in ('unity','unreal'):
 export_fbx(output/'asset.fbx',meshes+colliders if job['engine']=='unreal' else meshes)
 report['fbx'].append('asset.fbx')
 if colliders and job['engine']=='unity':export_fbx(output/'collision.fbx',colliders);report['fbx'].append('collision.fbx')
 # Verify the exported FBX can be read by the same Blender build. This is not an engine import test.
 bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.fbx(filepath=str(output/'asset.fbx'))
 imported=[o for o in bpy.context.scene.objects if o.type=='MESH' and not o.name.startswith('UCX_')]
 if not imported or triangles(imported)==0:raise RuntimeError('FBX roundtrip lost geometry')
 report['fbx_roundtrip']={'reader':'Blender '+bpy.app.version_string,'triangles':triangles(imported),'bounds_blender_m':bounds(imported),'engine_import_verified':False}
(output/'blender-report.json').write_text(json.dumps(report,indent=2))
print('CGC_ASSET_PACKAGE_COMPLETED')
