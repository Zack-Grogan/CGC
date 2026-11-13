"""Run with Blender --background --python scripts/blender_smoke.py. No addons/assets/network."""
import bpy
import json
import math
from mathutils import Vector
from pathlib import Path
import time

root = Path(__file__).resolve().parent.parent
out = root / 'outputs'
out.mkdir(exist_ok=True)
png = out / 'benchmark-blender-eevee.png'
blend = out / 'benchmark-blender-eevee.blend'
report = out / 'benchmark-blender-eevee.report.json'
if any(p.exists() for p in (png, blend, report)):
    raise RuntimeError('Smoke-test outputs exist; choose fresh paths rather than overwrite.')
start=time.monotonic()
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene
for engine in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
    try:
        scene.render.engine=engine
        break
    except TypeError:
        continue
else:
    raise RuntimeError('No Eevee engine available in this Blender build.')
scene.render.resolution_x=320
scene.render.resolution_y=320
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.filepath=str(png)
scene.world=bpy.data.worlds.new('Studio World')
scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(0.7,0.75,0.9,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=0.35

def material(name,color,roughness=0.3):
    m=bpy.data.materials.new(name);m.use_nodes=True
    bsdf=m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=roughness
    return m
blue=material('Cobalt glaze',(0.016,0.055,0.42),0.2)
floor=material('Warm limestone',(0.7,0.64,0.52),0.7)
bpy.ops.mesh.primitive_torus_add(major_radius=0.75,minor_radius=0.25,major_segments=48,minor_segments=24,location=(0,0,1),rotation=(math.pi/2,0,0))
obj=bpy.context.object;obj.name='Original procedural ring';obj.data.materials.append(blue)
for poly in obj.data.polygons:poly.use_smooth=True
bpy.ops.mesh.primitive_cylinder_add(vertices=64,radius=1.2,depth=0.3,location=(0,0,0.15))
obj=bpy.context.object;obj.name='Stone plinth';obj.data.materials.append(floor)
bevel=obj.modifiers.new('Soft edge','BEVEL');bevel.width=.04;bevel.segments=3
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-0.01))
bpy.context.object.data.materials.append(floor)
bpy.ops.object.light_add(type='AREA',location=(-3,-4,5));light=bpy.context.object;light.data.energy=600;light.data.shape='DISK';light.data.size=4
light.rotation_euler=(Vector((0,0,0.8))-light.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(3,-5,2.8));camera=bpy.context.object
camera.rotation_euler=(Vector((0,0,0.8))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.lens=50;scene.camera=camera
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.render.render(write_still=True)
result={'blender_version':bpy.app.version_string,'engine':scene.render.engine,'elapsed_seconds':round(time.monotonic()-start,3),'width':320,'height':320,'image':str(png),'scene':str(blend),'status':'completed'}
report.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
