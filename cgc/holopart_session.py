"""Complete one selected part with HoloPart and retain all other geometry."""
import contextlib
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback

REVISION='29cdb1417121842c4c4d59b9d283cc734f8c3aec'


def main():
    protocol=sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import numpy as np
        import trimesh
        sys.path[:0]=['/opt/HoloPart','/opt/HoloPart/scripts']
        from holopart.pipelines.pipeline_holopart import HoloPartPipeline
        from holopart.inference_utils import hierarchical_extract_geometry
        from huggingface_hub import snapshot_download
        from glb_replace import read as read_glb,target_node,replace as replace_part
        torch.set_num_threads(2)
        if not torch.cuda.is_available():raise RuntimeError('HoloPart requires the remote CUDA profile')
        root=(Path.cwd()/'models/holopart').resolve()
        snapshot_download('VAST-AI/HoloPart',revision=REVISION,allow_patterns=['model_index.json','part_encoder/**','scheduler/**','transformer/**','vae/**'],local_dir=root)
        pipe=HoloPartPipeline.from_pretrained(str(root)).to('cuda',torch.float16)
        versions={name:importlib.metadata.version(name) for name in ('torch','diffusers','transformers','trimesh','scikit-image')}
    provenance={'revisions':{'VAST-AI/HoloPart':REVISION},'source_revision':'48dd632c9a7412e6688573bb4f153e0ade7e7325',
                'extraction':'Upstream hierarchical_extract_geometry with equal dense/final depths and scikit-image marching cubes','diso_used':False}
    protocol.write(json.dumps({'ready':True,'device':torch.cuda.get_device_name(0),'versions':versions,'provenance':provenance})+'\n');protocol.flush()
    for line in sys.stdin:
        try:
            task=json.loads(line);started=time.monotonic()
            with contextlib.redirect_stdout(sys.stderr),torch.inference_mode(),tempfile.TemporaryDirectory() as directory:
                np.random.seed(task['seed']);torch.manual_seed(task['seed'])
                source_document,_=read_glb(task['input']);target_node(source_document,task['part'])
                original=trimesh.load(task['input'],force='scene',process=False)
                world={};aliases={};selected_nodes=[]
                for node in original.graph.nodes_geometry:
                    transform,geometry=original.graph[node]
                    mesh=original.geometry[geometry].copy();mesh.apply_transform(transform)
                    world[node]=mesh;aliases.setdefault(geometry,[]).append(node)
                    ancestor=node
                    while ancestor is not None:
                        if ancestor==task['part']:
                            selected_nodes.append(node);break
                        ancestor=original.graph.transforms.parents.get(ancestor)
                selected=task['part']
                if not selected_nodes:
                    options=aliases.get(selected,[])
                    if len(options)!=1:raise ValueError('Select one geometry node from: '+str(sorted(world)))
                    selected_nodes=options
                target_mesh=trimesh.util.concatenate([world[name] for name in selected_nodes])
                rest_meshes=[mesh for name,mesh in world.items() if name not in selected_nodes]
                bounds=trimesh.util.concatenate(list(world.values())).bounds
                center=bounds.mean(axis=0);scale=1.8/float((bounds[1]-bounds[0]).max())
                context=trimesh.util.concatenate([target_mesh,*rest_meshes])
                context.apply_translation(-center);context.apply_scale(scale)
                target=target_mesh.copy();target.apply_translation(-center);target.apply_scale(scale)
                part_points,part_faces=target.sample(20480,return_index=True)
                whole_points,whole_faces=context.sample(20480,return_index=True)
                part_cond=torch.as_tensor(np.concatenate([part_points,target.face_normals[part_faces]],axis=1),dtype=torch.float32,device='cuda')
                part_center=(part_cond[:,:3].max(dim=0).values+part_cond[:,:3].min(dim=0).values)/2
                local_cond=part_cond.clone();local_cond[:,:3]-=part_center
                part_scale=float(local_cond[:,:3].abs().max()/(.95*.7));local_cond[:,:3]/=part_scale
                ownership=(whole_faces<len(target_mesh.faces)).astype(np.float32)
                whole_cond=torch.as_tensor(np.concatenate([whole_points,context.face_normals[whole_faces],ownership[:,None]],axis=1),dtype=torch.float32,device='cuda')
                latent=pipe(part_surface=part_cond[None],whole_surface=whole_cond[None],
                            part_local_surface=local_cond[None],num_inference_steps=task['steps'],guidance_scale=task.get('guidance_scale',3.5),
                            generator=torch.Generator('cuda').manual_seed(task['seed']),output_type='latent').samples
                def geometry(points):return pipe.vae.decode(latent,sampled_points=points,num_chunks=10000).sample
                depth=task['octree_depth']
                outputs=hierarchical_extract_geometry(geometry,torch.device('cuda'),bounds=(-1.05,-1.05,-1.05,1.05,1.05,1.05),dense_octree_depth=depth,hierarchical_octree_depth=depth)
                vertices,faces=outputs[0]
                if vertices is None or faces is None or not len(faces):raise RuntimeError('HoloPart did not reconstruct a surface')
                completed=trimesh.Trimesh(vertices=np.asarray(vertices,dtype=np.float32),faces=faces,process=False)
                completed.apply_scale(part_scale);completed.apply_translation(part_center.cpu().numpy())
                completed.apply_scale(1/scale);completed.apply_translation(center)
                if not np.isfinite(completed.vertices).all():raise RuntimeError('HoloPart produced nonfinite geometry')
                completed.visual.vertex_colors=[180,180,180,255]
                generated=Path(directory)/'replacement.glb';completed.export(generated)
                preserved=replace_part(task['input'],generated,task['part'],task['output'])
            answer={'ok':True,'part':selected,'source_part_nodes':selected_nodes,'source_part_faces':len(target_mesh.faces),'generated_part_faces':len(completed.faces),
                    'source_part_watertight':bool(target_mesh.is_watertight),'generated_part_watertight':bool(completed.is_watertight),
                    'unselected_parts_preserved':len(rest_meshes),'normalization_center':center.tolist(),'normalization_scale':scale,
                    'octree_depth':depth,'new_part_textures_preserved':False,'preservation':preserved,'generation_seconds':time.monotonic()-started,'peak_cuda_bytes':int(torch.cuda.max_memory_allocated())}
        except Exception:answer={'ok':False,'error':traceback.format_exc()}
        protocol.write(json.dumps(answer)+'\n');protocol.flush()


if __name__=='__main__':main()
