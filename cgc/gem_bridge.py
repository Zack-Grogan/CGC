"""Convert GEM parameters to a checked SOMA77 motion package for retargeting."""
import contextlib
import json
from pathlib import Path
import sys
import traceback


def convert(source,destination,body):
    import torch
    import numpy as np
    from gem.motion.frontend.joint_sets import SOMA77_JOINT_NAMES
    allowed=[bytes,bytearray,np.core.multiarray._reconstruct,np.core.multiarray.scalar,np.ndarray,np.dtype,
             *(type(np.dtype(kind)) for kind in ('float16','float32','float64','int32','int64','bool'))]
    with torch.serialization.safe_globals(allowed):
        result=torch.load(source,map_location='cpu',weights_only=True,mmap=True)
    if result.get('format')!='gem_body_video_predictions_v1':raise ValueError('Expected a native GEM-X body-video prediction')
    parameters=result['pred_soma_params_global']
    matrix_pose=parameters['body_pose'].shape[-2:]==(3,3)
    output=body(**parameters,pose2rot=not matrix_pose,return_joints_only=False)
    neutral=dict(parameters)
    for name in ('global_orient','body_pose'):
        value=parameters[name]
        neutral[name]=torch.eye(3).expand_as(value).clone() if matrix_pose else torch.zeros_like(value)
    neutral['transl']=torch.zeros_like(parameters['transl'])
    rest=body(**neutral,pose2rot=not matrix_pose,return_joints_only=False)
    joints=output['joints'][0].detach().numpy()
    bind_joints=rest['joints'][0].detach().numpy()
    transforms=output['transforms'][0].detach().numpy()
    bind_transforms=rest['transforms'][0].detach().numpy()
    if transforms.shape[-3]==78:
        transforms=transforms[:,1:];bind_transforms=bind_transforms[:,1:]
    if transforms.shape[-3]!=77:raise ValueError('Unexpected SOMA transform count')
    parents=np.asarray(body.runtime.output_joint_parent_ids.cpu().tolist()[1:],dtype=np.int64)-1
    if len(parents)!=77 or parents[0]!=-1 or any(parent<0 or parent>=i for i,parent in enumerate(parents[1:],1)):
        raise ValueError('Unexpected SOMA hierarchy')
    def rotations(value):
        u,_,vh=np.linalg.svd(value[...,:3,:3].astype(np.float64))
        r=u@vh
        bad=np.linalg.det(r)<0
        u[bad,:,2]*=-1
        return u@vh
    posed_rotation=rotations(transforms);bind_rotation=rotations(bind_transforms)
    candidates={'runtime_rotation':posed_rotation,'runtime_times_inverse_bind':posed_rotation@bind_rotation.swapaxes(-1,-2)}
    errors={}
    for name,rotation in candidates.items():
        reconstructed=np.zeros_like(joints);reconstructed[:,0]=joints[:,0]
        for index in range(1,77):
            parent=parents[index]
            reconstructed[:,index]=reconstructed[:,parent]+np.einsum('tij,tj->ti',rotation[:,parent],bind_joints[:,index]-bind_joints[:,parent])
        errors[name]=float(np.linalg.norm(reconstructed-joints,axis=-1).max())
    selected=min(errors,key=errors.get)
    if errors[selected]>.01:raise ValueError('SOMA-to-retarget rotation convention failed FK validation: '+str(errors))
    global_rotation=candidates[selected]
    local_rotation=global_rotation.copy()
    for index in range(1,77):local_rotation[:,index]=global_rotation[:,parents[index]].swapaxes(-1,-2)@global_rotation[:,index]
    np.savez_compressed(destination,posed_joints=joints.astype(np.float32),global_rot_mats=global_rotation.astype(np.float32),
                        local_rot_mats=local_rotation.astype(np.float32),root_positions=joints[:,0].astype(np.float32),joint_names=np.asarray(SOMA77_JOINT_NAMES),parents=parents)
    return {'frames':len(joints),'fps':30,'coordinates':'Y-up meters','rotation_convention':selected,'fk_errors_meters':errors,
            'source_format':result.get('format'),'source_postprocessed':bool(result.get('postprocessing'))}


def main():
    protocol=sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from gem.common.soma import SomaFixedGs1BodyAdapter,SomaRuntimeConfig
        from huggingface_hub import snapshot_download
        from gem_assets import REVISIONS,SOMA
        torch.set_num_threads(2)
        root=(Path.cwd()/'models/gem-x/soma').resolve()
        snapshot_download('nvidia/SOMA-X',revision=REVISIONS['nvidia/SOMA-X'],allow_patterns=SOMA,local_dir=root)
        body=SomaFixedGs1BodyAdapter(SomaRuntimeConfig(data_root=str(root),device='cpu',mode='torch',lod='xlo',apply_correctives=False))
        import importlib.metadata
        versions={name:importlib.metadata.version(name) for name in ('torch','gem','py-soma-x','numpy')}
    protocol.write(json.dumps({'ready':True,'device':'CPU','versions':versions,'provenance':{'revisions':{'nvidia/SOMA-X':REVISIONS['nvidia/SOMA-X']}}})+'\n');protocol.flush()
    for line in sys.stdin:
        try:
            task=json.loads(line)
            with contextlib.redirect_stdout(sys.stderr),torch.inference_mode():answer=dict(convert(task['input'],task['output'],body),ok=True)
        except Exception:answer={'ok':False,'error':traceback.format_exc()}
        protocol.write(json.dumps(answer)+'\n');protocol.flush()


if __name__=='__main__':main()
