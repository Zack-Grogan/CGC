"""Render native GeoSAM2 views with the pinned Blender 4.0 CPU runtime."""
import importlib.util
import json
import hashlib
import sys
from pathlib import Path


def main():
    import bpy
    source,destination=sys.argv[sys.argv.index('--')+1:]
    path=Path('/opt/GeoSAM2/geosam2_render.py')
    spec=importlib.util.spec_from_file_location('geosam_renderer',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    def cpu_render():
        scene=bpy.context.scene
        scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=8
        scene.render.threads_mode='FIXED';scene.render.threads=8
    module.eevee_init=cpu_render
    if not module.process(str(Path(source).resolve()),'glb',str(Path(destination).resolve())):
        # The upstream function returns None after a successful write.
        if not (Path(destination)/'meta.json').is_file():raise RuntimeError('GeoSAM2 renderer did not write metadata')
    from bpy_extras.object_utils import world_to_camera_view
    from PIL import Image
    # Invisible RGB values in Blender's lossy WebP can contain unrelated pixels.
    # SAM consumes RGB, so composite them onto black while retaining alpha masks.
    for path in Path(destination).glob('color_*.webp'):
        with Image.open(path) as raw:
            image=raw.convert('RGBA');alpha=image.getchannel('A')
            mask=alpha.point(lambda value:255 if value else 0)
            rgb=Image.composite(image.convert('RGB'),Image.new('RGB',image.size),mask)
            rgb.putalpha(alpha);rgb.save(path,format='WEBP',lossless=True,exact=True)
    metadata_path=Path(destination)/'meta.json'
    metadata=json.loads(metadata_path.read_text())
    scale=metadata['scaling_factor']
    # Upstream inference translates before scaling; rendering does the reverse.
    metadata['renderer_translation']=metadata['translation']
    metadata['translation']=[value/scale for value in metadata['translation']]
    metadata['translation_space']='before_scaling'
    metadata['source_sha256']=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    metadata['cgc_format']='geosam_views_v1'
    metadata['renderer']='Blender 4.0.2, Cycles CPU, 8 samples'
    metadata['image_size']=[module.RESOLUTION,module.RESOLUTION]
    metadata_path.write_text(json.dumps(metadata,indent=2))
    scene=bpy.context.scene
    meshes=[obj for obj in scene.objects if obj.type=='MESH']
    rows=[]
    for index in range(12):
        scene.frame_set(index)
        points=[world_to_camera_view(scene,scene.camera,obj.matrix_world@vertex.co) for obj in meshes for vertex in obj.data.vertices]
        rows.append({'view':index,'minimum':[min(p[i] for p in points) for i in range(3)],'maximum':[max(p[i] for p in points) for i in range(3)]})
    (Path(destination)/'render_audit.json').write_text(json.dumps(rows,indent=2))


if __name__=='__main__':main()
