"""Separate GEM-X runtime for its Torch and Transformers requirements."""
SOURCE_REVISION='4aef1452e5df171deff4f293c08e643eb450981e'
PUBLISHED_IMAGE='2c38e60265ea55df'


def image(rebuild=False):
    from beam import Image
    if not rebuild:return Image(python_version='python3.12',image_id=PUBLISHED_IMAGE)
    return Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:e93dbb1f7ca0ad1c').add_commands([
        "sed -i 's|http://mirrors.edge.kernel.org/ubuntu|http://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list && apt-get update -qq && apt-get install -y -qq ffmpeg",
        'git clone https://github.com/NVlabs/GEM-X.git /opt/GEM-X && cd /opt/GEM-X && git checkout '+SOURCE_REVISION,
        'uv-b9 venv --python "$(command -v python3.12)" /opt/gemenv',
        'uv-b9 pip install --python /opt/gemenv/bin/python "torch==2.10.0" "torchvision==0.25.0" "torchaudio==2.10.0" "transformers==5.3.0" "py-soma-x==0.3.3" "numpy==1.26.4" "scipy>=1.11,<2" "einops>=0.8,<1" "pillow>=10,<13" "opencv-python-headless==4.11.0.86" "omegaconf==2.3.0" "onnxruntime-gpu==1.23.2"',
        'uv-b9 pip install --python /opt/gemenv/bin/python --no-deps /opt/GEM-X',
        'env -u PYTHONPATH /opt/gemenv/bin/python -c "import gem,torch; import soma; print(torch.__version__)"',
    ])
