"""Load the existing test scene, render a 12-frame loop; no assets, addons or network."""
import bpy,json,math,time
from pathlib import Path
root=Path(__file__).resolve().parent.parent
out=root/'outputs'
frames=out/'benchmark-blender-motion-frames'
report=out/'benchmark-blender-motion.report.json'
if frames.exists() or report.exists():raise RuntimeError('Motion outputs already exist; refusing overwrite.')
frames.mkdir()
scene=bpy.context.scene
obj=bpy.data.objects['Original procedural ring']
scene.frame_start=1;scene.frame_end=12;scene.render.fps=12
obj.rotation_euler.z=0
obj.keyframe_insert(data_path='rotation_euler',frame=1)
obj.rotation_euler.z=2*math.pi
obj.keyframe_insert(data_path='rotation_euler',frame=13)
scene.render.filepath=str(frames/'frame_')
scene.render.image_settings.file_format='PNG'
start=time.monotonic()
bpy.ops.render.render(animation=True)
files=sorted(frames.glob('frame_*.png'))
result={'status':'completed' if len(files)==12 else 'failed','blender_version':bpy.app.version_string,'engine':scene.render.engine,'frames':len(files),'width':320,'height':320,'fps':12,'duration_seconds':1,'render_seconds':round(time.monotonic()-start,3),'frames_directory':str(frames)}
report.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
