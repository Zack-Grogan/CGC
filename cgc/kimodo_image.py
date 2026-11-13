"""Isolated upstream Kimodo environment; Beam keeps its own dependencies."""
SOURCE_REVISION = 'e1c219c99b4b94ba48be1fb6a1cbc64ecee4c954'
PUBLISHED_IMAGE = 'f19b3bbc2b365d99'


def image(rebuild=False):
    from beam import Image
    if not rebuild:
        return Image(python_version='python3.12', image_id=PUBLISHED_IMAGE)
    return Image(python_version='python3.12', base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:7595713f760145fb').add_commands([
        'apt-get update -qq && apt-get install -y -qq cmake',
        'git clone https://github.com/nv-tlabs/kimodo.git /opt/kimodo && cd /opt/kimodo && git checkout '+SOURCE_REVISION,
        'uv-b9 venv --python "$(command -v python3.12)" --system-site-packages /opt/kimodoenv',
        "printf '/usr/local/lib/python3.12/site-packages\\n/usr/local/lib/python3.12/dist-packages\\n' > /opt/kimodoenv/lib/python3.12/site-packages/cgc-system.pth",
        'uv-b9 pip install --python /opt/kimodoenv/bin/python "torch==2.9.1" "torchvision==0.24.1" "torchaudio==2.9.1" "numpy==1.26.4" "transformers==5.1.0" "peft==0.18.1" "hydra-core==1.3.2" "omegaconf==2.3.0" "gradio_client==2.0.0" einops scipy',
        'uv-b9 pip install --python /opt/kimodoenv/bin/python --no-deps /opt/kimodo',
        'env -u PYTHONPATH /opt/kimodoenv/bin/python -c "from kimodo import load_model; from kimodo.model.llm2vec.llm2vec_wrapper import LLM2VecEncoder; print(1)"',
    ])
