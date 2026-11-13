"""SkinTokens uses Python 3.11 for the published bpy and attention wheels."""
SOURCE_REVISION = '273b691d35989d71cd17ff2895fdc735097b92d1'
PUBLISHED_IMAGE = 'ebdbcd99b119c29e'


def image(rebuild=False):
    from beam import Image
    if not rebuild:return Image(python_version='python3.12',image_id=PUBLISHED_IMAGE)
    return Image(
        python_version='python3.12',
        base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:e93dbb1f7ca0ad1c',
    ).add_commands([
        'apt-get update -qq && apt-get install -y -qq libgl1 libglib2.0-0 libgomp1 libxrender1 libxi6 libxfixes3 libxkbcommon0 libsm6',
        'git clone https://github.com/VAST-AI-Research/SkinTokens.git /opt/SkinTokens && cd /opt/SkinTokens && git checkout '+SOURCE_REVISION,
        'uv-b9 venv --python 3.11 --python-preference only-managed /opt/skinenv',
        'uv-b9 pip install --python /opt/skinenv/bin/python "torch==2.8.0" "torchvision==0.23.0" "torchaudio==2.8.0" "transformers==4.57.3" "diffusers==0.37.1" "numpy==1.26.4" "bpy==4.5.3" python-box einops omegaconf lightning addict fast-simplification trimesh "open3d==0.19.0" huggingface_hub "gradio==6.8.0" bottle tornado',
        'uv-b9 pip install --python /opt/skinenv/bin/python --no-deps https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3%2Bcu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl',
        'cd /opt/SkinTokens && env -u PYTHONPATH /opt/skinenv/bin/python -c "import bpy, flash_attn, transformers; print(bpy.app.version_string)"',
    ])
