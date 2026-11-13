"""Existing-mesh texturing with cached TRELLIS components and checked geometry."""
import copy
import hashlib
import json
from pathlib import Path
import time
import sys


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def load(image_pipeline,weights):
    """Reuse approved image/texture weights without constructing a remover."""
    from trellis2 import models
    from trellis2.pipelines import samplers
    from trellis2.pipelines.trellis2_texturing import Trellis2TexturingPipeline
    weights=Path(weights)
    config_path=weights/'texturing_pipeline.json'
    if not config_path.is_file():raise RuntimeError('Cached TRELLIS texturing configuration is missing; no implicit download')
    config=json.loads(config_path.read_text())['args']
    encoder=weights/config['models']['shape_slat_encoder']
    if not encoder.with_suffix('.json').is_file() or not encoder.with_suffix('.safetensors').is_file():
        raise RuntimeError('Cached shape encoder is missing; no implicit download')
    selected={key:image_pipeline.models[key] for key in ('tex_slat_decoder','tex_slat_flow_model_512','tex_slat_flow_model_1024')}
    selected['shape_slat_encoder']=models.from_pretrained(str(encoder))
    sampler=config['tex_slat_sampler']
    pipeline=Trellis2TexturingPipeline(models=selected,
        tex_slat_sampler=getattr(samplers,sampler['name'])(**sampler['args']),tex_slat_sampler_params=sampler['params'],
        shape_slat_normalization=config['shape_slat_normalization'],tex_slat_normalization=config['tex_slat_normalization'],
        image_cond_model=image_pipeline.image_cond_model,rembg_model=None,low_vram=True)
    pipeline.cuda()
    # Native extensions can terminate the process before Python can report an
    # exception. Record each stage in the worker log for a useful failure trace.
    for name in ('encode_shape_slat','sample_tex_slat','decode_tex_slat','postprocess_mesh'):
        original=getattr(pipeline,name)
        def stage(*args,_name=name,_original=original,**kwargs):
            print('TRELLIS texture stage: '+_name,flush=True,file=sys.stderr)
            value=_original(*args,**kwargs)
            print('TRELLIS texture complete: '+_name,flush=True,file=sys.stderr)
            return value
        setattr(pipeline,name,stage)
    if pipeline.rembg_model is not None:raise RuntimeError('Texturing must not construct a background remover')
    return pipeline


def world_source(scene):
    import numpy as np
    import trimesh
    objects=[];owners=[]
    for node in scene.graph.nodes_geometry:
        matrix,geometry=scene.graph[node]
        if abs(np.linalg.det(matrix[:3,:3]))<1e-12:raise ValueError('Bake singular mesh transforms before texturing')
        mesh=scene.geometry[geometry].copy();mesh.apply_transform(matrix)
        if not len(mesh.faces):continue
        objects.append(mesh);owners.extend([node]*len(mesh.faces))
    if not objects:raise ValueError('No static triangle geometry to texture')
    combined=trimesh.util.concatenate(objects)
    source_face_owners(combined,owners)
    return combined,owners


def source_face_owners(source,owners):
    """Allow duplicate faces within a node; refuse ambiguous node ownership."""
    import numpy as np
    _,position_ids=np.unique(np.asarray(source.vertices),axis=0,return_inverse=True)
    node_by_face={}
    for face,node in zip(position_ids[np.asarray(source.faces)],owners):
        key=tuple(sorted(int(value) for value in face))
        if key in node_by_face and node_by_face[key]!=node:
            raise ValueError('Coincident source triangles belong to different nodes; separate them before texturing')
        node_by_face[key]=node
    return node_by_face


def restore_scene(scene,source,textured,owners,center,scale):
    """Recover original positions and each node's transform after native UV unwrap."""
    import numpy as np
    from scipy.spatial import cKDTree
    from collections import Counter,defaultdict
    source_positions,position_ids=np.unique(np.asarray(source.vertices),axis=0,return_inverse=True)
    source_triangles=position_ids[np.asarray(source.faces)]
    def key(face):
        face=tuple(int(value) for value in face)
        return min(face,face[1:]+face[:1],face[2:]+face[:2])
    node_by_face=source_face_owners(source,owners)
    restored=np.asarray(textured.vertices)/scale+center
    distances,matched=cKDTree(source_positions).query(restored)
    tolerance=max(float(np.ptp(source_positions,axis=0).max())*2e-5,1e-7)
    if not np.isfinite(restored).all() or float(distances.max())>tolerance:
        raise RuntimeError('Native texturing changed the source surface positions')
    textured_triangles=matched[np.asarray(textured.faces)]
    if Counter(key(face) for face in textured_triangles)!=Counter(key(face) for face in source_triangles):
        raise RuntimeError('Native texturing changed the source triangles')
    # Float32 normalization/denormalization can drift. Snap back only after the
    # one-to-one surface check, using the exact original world positions.
    textured.vertices=source_positions[matched]
    grouped=defaultdict(list)
    for index,face in enumerate(textured_triangles):grouped[node_by_face[tuple(sorted(int(value) for value in face))]].append(index)
    result=scene.copy()
    for node,indices in grouped.items():
        matrix,_=scene.graph[node]
        part=textured.submesh([indices],append=True,repair=False)
        part.apply_transform(np.linalg.inv(matrix))
        geometry='cgc_textured_'+node
        while geometry in result.geometry:geometry+='_'
        result.geometry[geometry]=part
        parent=scene.graph.transforms.parents.get(node,scene.graph.base_frame)
        local,_=scene.graph.get(node,frame_from=parent)
        result.graph.update(frame_to=node,frame_from=parent,matrix=local,geometry=geometry)
    used={result.graph[node][1] for node in result.graph.nodes_geometry}
    for name in list(result.geometry):
        if name not in used:result.geometry.pop(name)
    return result,{'source_faces':len(source.faces),'output_faces':len(textured.faces),'nodes_preserved':len(grouped),
        'world_position_max_before_restore':float(distances.max()),'world_geometry_restored':True,'node_transforms_preserved':True,
        'uvs_rebuilt':True,'source_materials_replaced':True}


def run(pipeline,generator,source,reference,output,seed,resolution,texture_size):
    import numpy as np
    import trimesh
    from PIL import Image
    started=time.monotonic()
    scene=trimesh.load(source,force='scene',process=False)
    mesh,owners=world_source(scene)
    vertices=np.asarray(mesh.vertices);center=(vertices.min(axis=0)+vertices.max(axis=0))/2
    extent=float(np.ptp(vertices,axis=0).max())
    if extent<=0:raise ValueError('Source mesh has no measurable extent')
    scale=.99999/extent
    prepared,matte_model=generator.prepare_image(Path(reference),Path(output),force_matte=False,allow_uncut=False)
    with Image.open(prepared) as opened:image=opened.convert('RGBA')
    alpha=np.asarray(image)[:,:,3]
    if not np.any(alpha<255) or not np.any(alpha>0):raise RuntimeError('Texturing requires a prepared cutout with foreground and alpha')
    textured=pipeline.run(mesh.copy(),image,seed=seed,resolution=int(resolution),texture_size=texture_size,preprocess_image=True)
    result,audit=restore_scene(scene,mesh,textured,owners,center,scale)
    result.export(output,extension_webp=False)
    report={'operation':'model.texture','source_mesh_sha256':digest(source),'reference_sha256':digest(reference),
        'geometry':audit,'seed':seed,'resolution':int(resolution),'texture_size':texture_size,'matte_model':matte_model,
        'bria_loaded':False,'geometry_preservation':'World triangle positions and node transforms checked; UV seams may duplicate vertices',
        'generation_seconds':time.monotonic()-started}
    Path(output).with_suffix('.texture.json').write_text(json.dumps(report,indent=2))
    return report
