"""Keep GEM-X's detector, observation, Pose and Motion models resident."""
import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import traceback


def main():
    protocol=sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import onnxruntime as ort
        from gem_assets import prepare
        from gem.inference import body_video
        from gem.inference.inputs import load_mapping
        from gem.inference.postprocess import postprocess_motion_result
        from gem.motion.postprocess.api import SomaContactPostprocessor
        from gem.inference.serialization import save_predictions
        torch.set_num_threads(2)
        original_options=ort.SessionOptions
        def limited_options():
            options=original_options()
            options.intra_op_num_threads=2;options.inter_op_num_threads=1
            return options
        ort.SessionOptions=limited_options
        if not torch.cuda.is_available():raise RuntimeError('GEM-X requires the remote CUDA profile')
        root,provenance=prepare(Path.cwd()/'models/gem-x')
        config=load_mapping(root/'weights/body_video_native77.yaml')
        for section,name in [('pose','body_s240000.ckpt'),('observations','vitpose.pth'),('detector','yolox_humanart.onnx'),('motion','motion_native77_e774_s292175.ckpt')]:
            config[section]['checkpoint']=str(root/'weights'/name)
        config['motion']['stats']=str(root/'weights/motion_stats_raw.npz')
        config['pose']['batch_size']=1;config['observations']['batch_size']=1
        config['detector']['device']='cuda'
        config['camera']['mode']='static'
        cached={};load_counts={}
        def retain(name):
            original=getattr(body_video,name)
            def loader(*args,**kwargs):
                if name not in cached:
                    cached[name]=original(*args,**kwargs);load_counts[name]=1
                return cached[name]
            setattr(body_video,name,loader)
        for name in ('YOLOXONNX','load_native77_detector','load_pose_checkpoint','load_predictor'):retain(name)
        options=dict(config['detector']);checkpoint=options.pop('checkpoint')
        body_video.YOLOXONNX(checkpoint,**options)
        body_video.load_native77_detector(config['observations']['checkpoint'],release_id=config['observations']['release_id'],device='cuda',batch_size=1)
        body_video.load_pose_checkpoint(config['pose']['checkpoint'],body_video.body_release(config),device='cuda')
        body_video.load_predictor(config['motion']['checkpoint'],config['motion'],stats_path=config['motion']['stats'],device='cuda')
        processor=SomaContactPostprocessor(str(root/'soma'),device='cuda')
        versions={name:importlib.metadata.version(name) for name in ('torch','transformers','py-soma-x','gem','onnxruntime-gpu')}
    protocol.write(json.dumps({'ready':True,'device':torch.cuda.get_device_name(0),'provenance':provenance,'versions':versions})+'\n');protocol.flush()
    for line in sys.stdin:
        try:
            task=json.loads(line);started=time.monotonic()
            stages=[]
            def progress(message):
                stages.append({'stage':message,'at_seconds':time.monotonic()-started})
                print(message,file=sys.stderr,flush=True)
            with contextlib.redirect_stdout(sys.stderr),torch.inference_mode():
                config['camera']['mode']=task.get('camera_mode','background')
                result=body_video.run_body_video(task['input'],config,device='cuda',duration=task.get('duration'),progress=progress)
                progress('Applying contact and IK processing')
                result=postprocess_motion_result(result,soma_assets=str(root/'soma'),device='cuda',processor=processor)
                frames=int(torch.as_tensor(result['length']).reshape(-1)[0])
                for coordinates in ('incam','global'):
                    for name,value in result['pred_soma_params_'+coordinates].items():
                        if torch.is_tensor(value) and not torch.isfinite(value).all():raise RuntimeError('Nonfinite GEM-X output: '+coordinates+'/'+name)
                if not 1<=frames<=1800:raise RuntimeError('Invalid GEM-X motion frame count')
                save_predictions(result,task['output'])
            answer={'ok':True,'frames':frames,'fps':30,'camera_mode':config['camera']['mode'],'contact_postprocess':True,
                    'model_load_counts':load_counts,'stages':stages,'onnx_device':'cuda','onnx_cpu_threads':2,'generation_seconds':time.monotonic()-started,'peak_cuda_bytes':int(torch.cuda.max_memory_allocated())}
        except Exception:answer={'ok':False,'error':traceback.format_exc()}
        protocol.write(json.dumps(answer)+'\n');protocol.flush()


if __name__=='__main__':main()
