"""Selected GEM-X Native77 motion assets, excluding optional hand models."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

REVISIONS={'nvidia/GEM-X':'b111f2dcf3ebcf57965fd53499cb645dfa5ba25c',
           'nvidia/SOMA-X':'d281db2d01553f7230c56e764cec00fe27ef23f7'}
WEIGHTS=['body_s240000.ckpt','body_config.json','vitpose.pth','motion_native77_e774_s292175.ckpt','motion_stats_raw.npz','body_video_native77.yaml']
SOMA=['SOMA_neutral.npz','SOMA_template_rig.usda','SOMA_procedural_transforms.json','correctives_model.pt']
DETECTOR='https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_x_8xb8-300e_humanart-a39d44ed.zip'


def prepare(root):
    from huggingface_hub import snapshot_download
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    weights=root/'weights';soma=root/'soma'
    snapshot_download('nvidia/GEM-X',revision=REVISIONS['nvidia/GEM-X'],allow_patterns=WEIGHTS,local_dir=weights)
    snapshot_download('nvidia/SOMA-X',revision=REVISIONS['nvidia/SOMA-X'],allow_patterns=SOMA,local_dir=soma)
    detector=weights/'yolox_humanart.onnx'
    if not detector.exists():
        bundle=root/'yolox_humanart.zip'
        urllib.request.urlretrieve(DETECTOR,bundle)
        with zipfile.ZipFile(bundle) as archive:
            matches=[name for name in archive.namelist() if name.endswith('/end2end.onnx')]
            if len(matches)!=1:raise RuntimeError('Unexpected detector archive')
            with archive.open(matches[0]) as source,detector.open('wb') as target:shutil.copyfileobj(source,target)
    hashes={}
    for path in [*(weights/name for name in WEIGHTS),*(soma/name for name in SOMA),detector]:
        digest=hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda:source.read(8*1024*1024),b''):digest.update(block)
        hashes[str(path.relative_to(root))]=digest.hexdigest()
    receipt={'revisions':REVISIONS,'soma_asset_tag':'v0.3.3','detector_source':DETECTOR,'files':hashes,'hand_models_downloaded':False}
    (root/'provenance.json').write_text(json.dumps(receipt,indent=2))
    return root,receipt
