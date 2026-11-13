"""Render a GLB from four views with Blender; does not modify the source.

Run: blender --background --factory-startup --python scripts/render_model.py -- --input MODEL.glb --output-dir DIR
"""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

args=argparse.ArgumentParser()
args.add_argument('--input',type=Path,required=True)
args.add_argument('--output-dir',type=Path,required=True)
args.add_argument('--size',type=int,default=512)
args.add_argument('--light-scale',type=float,default=.12)
args.add_argument('--samples',type=int,default=24)
args.add_argument('--clay',action='store_true')
options=args.parse_args(sys.argv[sys.argv.index('--')+1:])
options.output_dir.mkdir(parents=True,exist_ok=True)
for name in ('front','side','back','three-quarter'):
    if (options.output_dir/(name+'.png')).exists():
        raise ValueError('Render output exists; select a new directory')
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(options.input.resolve()))
scene=bpy.context.scene;scene.frame_set(1);bpy.context.view_layer.update()
meshes=[o for o in scene.objects if o.type=='MESH']
deps=bpy.context.evaluated_depsgraph_get()
points=[o.matrix_world @ vertex.co for o in meshes for vertex in o.evaluated_get(deps).data.vertices]
if not points or any(not all(math.isfinite(value) for value in point) for point in points):raise ValueError('No finite imported mesh')
minimum=Vector([min(p[i] for p in points) for i in range(3)])
maximum=Vector([max(p[i] for p in points) for i in range(3)])
center=(minimum+maximum)/2
radius=max(maximum-minimum)/2
if radius<=0:raise ValueError('Mesh has no measurable extent')
scene=bpy.context.scene
scene.render.engine='CYCLES'
scene.cycles.samples=options.samples
scene.cycles.device='CPU'
scene.render.resolution_x=options.size
scene.render.resolution_y=options.size
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.world=bpy.data.worlds.new('Review lighting')
scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(0.2,0.2,0.2,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=0.6
for direction,energy in [((-2,-3,4),1200),((3,1,2),700)]:
    bpy.ops.object.light_add(type='AREA',location=center+Vector(direction)*radius)
    light=bpy.context.object
    light.data.energy=energy*radius*radius*options.light_scale
    light.data.shape='DISK';light.data.size=radius*3
    light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add()
camera=bpy.context.object
scene.camera=camera
camera.data.type='ORTHO'
camera.data.ortho_scale=radius*2.7
if options.clay:
    material=bpy.data.materials.new('CGC review clay override')
    material.use_nodes=True
    shader=material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value=(.18,.18,.18,1)
    shader.inputs['Metallic'].default_value=0
    shader.inputs['Roughness'].default_value=.72
    scene.view_layers[0].material_override=material
for name,angle in [('front',0),('side',math.pi/2),('back',math.pi),('three-quarter',math.pi/4)]:
    camera.location=center+Vector((math.sin(angle)*3,-math.cos(angle)*3,0.7))*radius
    camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str((options.output_dir/(name+'.png')).resolve())
    bpy.ops.render.render(write_still=True)
report={'source':str(options.input.resolve()),'blender_version':bpy.app.version_string,'frame':1,'render_engine':'Cycles CPU','samples':options.samples,'light_scale':options.light_scale,'material_mode':'clay' if options.clay else 'source PBR','image_size':[options.size,options.size],'review_scope':'Four fitted orthographic views of the default imported pose; not engine lighting or animation/deformation approval','meshes':len(meshes),'triangles':sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in meshes),'bounds_blender_min':list(minimum),'bounds_blender_max':list(maximum),'skins':sum(any(m.type=='ARMATURE' for m in o.modifiers) for o in meshes)}
(options.output_dir/'inspection.json').write_text(json.dumps(report,indent=2))
