"""HoloPart with native marching cubes and compiled nearest-neighbor kernels."""
SOURCE_REVISION='48dd632c9a7412e6688573bb4f153e0ade7e7325'
PUBLISHED_IMAGE='52c3093c3b5b6610'


def image(rebuild=False):
    from beam import Image
    if not rebuild:return Image(python_version='python3.12',image_id=PUBLISHED_IMAGE)
    return Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:167105b2045892fe').add_commands([
        'git clone https://github.com/VAST-AI-Research/HoloPart.git /opt/HoloPart && cd /opt/HoloPart && git checkout '+SOURCE_REVISION,
        'uv-b9 pip install --python /opt/skinenv/bin/python pymeshlab "scikit-image<0.26" jaxtyping "typeguard<3" peft setuptools wheel',
        'uv-b9 pip install --python /opt/skinenv/bin/python --no-deps https://data.pyg.org/whl/torch-2.8.0%2Bcu128/torch_cluster-1.6.3%2Bpt28cu128-cp311-cp311-linux_x86_64.whl',
        "python3.12 -c \"from pathlib import Path; p=Path('/opt/HoloPart/holopart/inference_utils.py'); s=p.read_text(); assert s.count('from diso import DiffDMC')==1; assert s.count('        dmc = DiffDMC')==1; s=s.replace('from diso import DiffDMC',''); s=s.replace('        dmc = DiffDMC','        from diso import DiffDMC'+chr(10)+'        dmc = DiffDMC'); p.write_text(s)\"",
        'cd /opt/HoloPart && env -u PYTHONPATH /opt/skinenv/bin/python -c "import torch_cluster,pymeshlab; from holopart.pipelines.pipeline_holopart import HoloPartPipeline; print(1)"',
    ])
