"""Render a GLB animation as a fixed-camera video for motion-capture qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys
import bpy
from mathutils import Vector

parser=argparse.ArgumentParser()
parser.add_argument('--input',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--action',default='walk_test')
parser.add_argument('--frames',type=int,default=60)
parser.add_argument('--fps',type=int,default=30)
options=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
options.output_dir.mkdir(parents=True,exist_ok=True)
if any(options.output_dir.iterdir()):raise RuntimeError('Select an empty output directory')
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene;scene.render.fps=options.fps
bpy.ops.import_scene.gltf(filepath=str(options.input.resolve()))
arm=next(o for o in scene.objects if o.type=='ARMATURE')
actions=[a for a in bpy.data.actions if options.action in a.name]
if len(actions)!=1:raise RuntimeError('Expected one matching action: '+str([a.name for a in bpy.data.actions]))
action=actions[0]
for track in arm.animation_data.nla_tracks:track.mute=True
arm.animation_data.action=action
if action.slots:arm.animation_data.action_slot=action.slots[0]
start,end=action.frame_range
scene.frame_set(int(start));bpy.context.view_layer.update()
meshes=[o for o in scene.objects if o.type=='MESH']
points=[o.matrix_world@Vector(p) for o in meshes for p in o.bound_box]
minimum=Vector([min(p[i] for p in points) for i in range(3)])
maximum=Vector([max(p[i] for p in points) for i in range(3)])
center=(minimum+maximum)/2;height=maximum.z-minimum.z
scene.render.engine='CYCLES';scene.cycles.samples=8
scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.world=bpy.data.worlds.new('Motion reference lighting');scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.12,.15,.18,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.6
bpy.ops.object.light_add(type='AREA',location=center+Vector((-2,-3,4))*height)
light=bpy.context.object;light.data.energy=1200*height*height;light.data.size=height*3
light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=center+Vector((.4,-1.6,.3))*height)
camera=bpy.context.object;camera.data.lens=50;camera.data.sensor_width=36
camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler();scene.camera=camera
reference=[]
for index in range(options.frames):
    frame=start+(index % max(1,int(end-start)))
    scene.frame_set(int(frame))
    reference.append({'frame':index,'source_frame':float(frame),'joints_blender':{p.name:list(arm.matrix_world@p.head) for p in arm.pose.bones}})
    scene.render.filepath=str((options.output_dir/f'frame-{index:04d}.png').resolve())
    bpy.ops.render.render(write_still=True)
output=options.output_dir/'input.mp4'
subprocess.run([shutil.which('ffmpeg') or 'ffmpeg','-hide_banner','-loglevel','error','-framerate',str(options.fps),'-i',str((options.output_dir/'frame-%04d.png').resolve()),'-c:v','libx264','-pix_fmt','yuv420p','-crf','18',str(output.resolve())],check=True)
focal=512*50/36
report={'source':str(options.input.resolve()),'source_sha256':hashlib.sha256(options.input.read_bytes()).hexdigest(),'action':action.name,'frames':options.frames,'fps':options.fps,'camera_mode':'static','intrinsics':[[focal,0,256],[0,focal,256],[0,0,1]],'camera_to_world_blender':[list(row) for row in camera.matrix_world],'reference':reference}
(options.output_dir/'reference.json').write_text(json.dumps(report,indent=2))
