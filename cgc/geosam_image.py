"""GeoSAM2 inference and a pinned Blender renderer for its native view format."""
SOURCE_REVISION='b5de23c60ab487d407b623d394a1614f9714761c'
PUBLISHED_IMAGE='167105b2045892fe'


def image(rebuild=False):
    from beam import Image
    if not rebuild:return Image(python_version='python3.12',image_id=PUBLISHED_IMAGE)
    return Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:ebdbcd99b119c29e').add_commands([
        "sed -i 's|http://mirrors.edge.kernel.org/ubuntu|http://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list && apt-get update -qq && apt-get install -y -qq libglu1-mesa libxxf86vm1",
        'git clone https://github.com/VAST-AI-Research/GeoSAM2.git /opt/GeoSAM2 && cd /opt/GeoSAM2 && git checkout '+SOURCE_REVISION,
        'uv-b9 pip install --python /opt/skinenv/bin/python "hydra-core==1.3.2" iopath "opencv-python-headless==4.11.0.86" pandas ninja setuptools wheel',
        'GEOSAM2_BUILD_CUDA=0 uv-b9 pip install --python /opt/skinenv/bin/python --no-deps --no-build-isolation /opt/GeoSAM2',
        'curl -fL https://ftp.halifax.rwth-aachen.de/blender/release/Blender4.0/blender-4.0.2-linux-x64.tar.xz -o /tmp/cgc-blender.tar.xz && echo 5583a5588736da8858c522ef17fff5d73be59c47a6fe91ad29c6f3263e22086a /tmp/cgc-blender.tar.xz | sha256sum -c - && tar -xJf /tmp/cgc-blender.tar.xz -C /opt && mv /opt/blender-4.0.2-linux-x64 /opt/blender40 && rm /tmp/cgc-blender.tar.xz',
        "python3.12 -c \"import glob,subprocess; p=glob.glob('/opt/blender40/4.0/python/bin/python3.*')[0]; subprocess.run(['uv-b9','pip','install','--python',p,'--target','/opt/blender40/4.0/python/lib/'+p.rsplit('/',1)[-1]+'/site-packages','Pillow==12.2.0'],check=True)\"",
        'env -u PYTHONPATH /opt/skinenv/bin/python -c "from sam2.build_sam import build_sam2_video_predictor_geosam2; print(1)"',
    ])
