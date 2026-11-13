"""Resident point/mask prompting and multiview GeoSAM2 face-label inference."""
import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import zipfile


def unpack(source,destination):
    with zipfile.ZipFile(source) as archive:
        if sum(item.file_size for item in archive.infolist())>1024**3:raise ValueError('View package is too large')
        for item in archive.infolist():
            path=(destination/item.filename).resolve()
            path.relative_to(destination.resolve())
            if (item.external_attr>>16)&0o170000==0o120000:raise ValueError('View package contains a symlink')
        archive.extractall(destination)


def main():
    protocol=sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import numpy as np
        sys.path.insert(0,'/opt/GeoSAM2')
        from sam2.build_sam import build_sam2_video_predictor_geosam2
        from sam2.automatic_mask_generator_geosam2 import SAM2AutomaticMaskGenerator
        import single_view_point_prompt_infer as points
        import inference
        from huggingface_hub import snapshot_download
        revision='ba92f5f50418f2fe9af1078448b63176df13b1ee'
        root=(Path.cwd()/'models/geosam2').resolve()
        snapshot_download('VAST-AI/GeoSAM2',revision=revision,allow_patterns=['geosam2.pt'],local_dir=root)
        torch.set_num_threads(2)
        if not torch.cuda.is_available():raise RuntimeError('GeoSAM2 requires the remote CUDA profile')
        predictor=build_sam2_video_predictor_geosam2('configs/geosam2.yaml',str(root/'geosam2.pt'),device='cuda')
        generator=SAM2AutomaticMaskGenerator(model=predictor,points_per_side=64,points_per_batch=128,pred_iou_thresh=.7,stability_score_thresh=.7,stability_score_offset=.7,crop_n_layers=0,box_nms_thresh=.7,crop_n_points_downscale_factor=2,min_mask_region_area=25.,use_m2m=True)
        versions={name:importlib.metadata.version(name) for name in ('torch','transformers','geosam2','trimesh')}
    protocol.write(json.dumps({'ready':True,'device':torch.cuda.get_device_name(0),'versions':versions,'provenance':{'revisions':{'VAST-AI/GeoSAM2':revision},'source_revision':'b5de23c60ab487d407b623d394a1614f9714761c'}})+'\n');protocol.flush()
    for line in sys.stdin:
        try:
            task=json.loads(line);started=time.monotonic()
            with tempfile.TemporaryDirectory() as temporary,contextlib.redirect_stdout(sys.stderr),torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                torch.manual_seed(task['seed']);np.random.seed(task['seed'])
                root=Path(temporary);views=root/'views';views.mkdir()
                unpack(task['views'],views)
                for index in range(12):
                    for prefix,suffix in [('color','.webp'),('normal','.webp'),('depth','.exr')]:
                        if not (views/f'{prefix}_{index:04d}{suffix}').is_file():raise ValueError('Incomplete multiview package')
                if not (views/'mesh.glb').is_file():raise ValueError('Views must include their source mesh.glb')
                view=task['view'];mask=Path(task['prompt_file'])
                if task['points']:
                    prompts=points.load_prompts(str(mask));_,frame_prompts=points.choose_frame_prompts(prompts,view)
                    state=predictor.init_state(video_path=str(views),video_id_list=[view]);predictor.reset_state(state)
                    for obj_id,(coords,labels) in points.group_obj_prompts(frame_prompts).items():
                        predictor.add_new_points_or_box(inference_state=state,frame_idx=0,obj_id=obj_id,points=coords,labels=labels)
                    segmentation={}
                    for frame,ids,logits in predictor.propagate_in_video_v2(state,start_frame_idx=0):
                        segmentation[frame]={int(obj): (logits[i]>0).cpu().numpy().squeeze() for i,obj in enumerate(ids)}
                    rgb=points.load_rgb(str(views),view)
                    label_map=np.zeros(rgb.shape[:2],dtype=np.int32)
                    for obj_id,selected in segmentation[0].items():label_map[selected]=obj_id
                    mask=root/'mask.npy';np.save(mask,label_map)
                    points.save_outputs(label_map,rgb,str(Path(task['output']).parent),view)
                data=inference.read_data(str(views),mask_path=str(mask),mask_view=view)
                canonical=data['mesh_vanilla']
                result=inference.segment_with_mask_prompts(predictor,generator,data,opposite_auto_segmentation=False,enable_postprocess=False,output_dir=str(root/'native-output'),start_frames=[view],start_to_seed_views={view:[view]})
                native_labels=result['face_label'].cpu().numpy().astype(np.int32)
                labels=np.where(native_labels==999,0,native_labels).astype(np.int32)
                if len(labels)!=len(canonical.faces) or not np.any(labels>0):raise RuntimeError('GeoSAM2 selected no mesh faces')
                import hashlib
                source_hash=hashlib.sha256((views/'mesh.glb').read_bytes()).hexdigest()
                legend=[{'label':index+1,'input_key':list(key)} for index,(key,_) in enumerate(sorted(inference.extract_mask_segments(str(mask)),key=lambda item:item[0]))]
                np.savez_compressed(task['output'],labels=labels,native_labels=native_labels,vertices=np.asarray(canonical.vertices,dtype=np.float32),faces=np.asarray(canonical.faces,dtype=np.int64),source_sha256=np.asarray(source_hash))
            answer={'ok':True,'faces':len(labels),'selected_faces':int(np.count_nonzero(labels)),'labels':np.unique(labels).tolist(),'label_legend':legend,'native_background_label':999,'output_background_or_unobserved_label':0,'source_sha256':source_hash,'face_index_space':'Included canonical vertices/faces; not original GLB primitive indices','postprocess':False,'generation_seconds':time.monotonic()-started,'peak_cuda_bytes':int(torch.cuda.max_memory_allocated())}
        except Exception:answer={'ok':False,'error':traceback.format_exc()}
        protocol.write(json.dumps(answer)+'\n');protocol.flush()


if __name__=='__main__':main()
