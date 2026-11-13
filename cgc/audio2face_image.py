"""Native Audio2Face SDK toolchain, separate from Torch generation images."""
SOURCE_REVISION='1ca0f02535ed774f5dbcd724a31cd486368dc783'
SDK_IMAGE='5a499e2c8aa621f2'
WORKER_IMAGE='8e4475aa40d2449a'


def image():
    from beam import Image
    version='10.13.3.9-1+cuda12.9'
    return Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:e93dbb1f7ca0ad1c').add_commands([
        "sed -i 's|http://mirrors.edge.kernel.org/ubuntu|http://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list",
        'apt-get update -qq && apt-get install -y git-lfs ninja-build '+' '.join(name+'='+version for name in ('libnvinfer10','libnvinfer-plugin10','libnvonnxparsers10','libnvinfer-headers-dev','libnvinfer-headers-plugin-dev','libnvinfer-dev','libnvinfer-plugin-dev','libnvonnxparsers-dev')),
        'uv-b9 pip install --python "$(command -v python3.12)" "cmake==3.31.6" "huggingface_hub==0.36.0"',
        'git clone https://github.com/NVIDIA/Audio2Face-3D-SDK.git /opt/audio2face && cd /opt/audio2face && git checkout '+SOURCE_REVISION,
        'cd /opt/audio2face && ./fetch_deps.sh release',
        'cd /opt/audio2face && cmake -S . -B /opt/a2f-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DTENSORRT_ROOT_DIR=/usr -DCUDAToolkit_ROOT=/usr/local/cuda && cmake --build /opt/a2f-build --parallel 4',
    ])


def worker_image(rebuild=False):
    import base64
    from pathlib import Path
    from beam import Image
    if not rebuild:return Image(python_version='python3.12',image_id=WORKER_IMAGE)
    code=base64.b64encode(Path(__file__).with_name('a2f_worker.cpp').read_bytes()).decode()
    cmake="\nadd_executable(cgc_a2f /opt/cgc_a2f.cpp)\ntarget_link_libraries(cgc_a2f PRIVATE audio2x CUDA::cudart nlohmann_json::nlohmann_json)\n"
    encoded=base64.b64encode(cmake.encode()).decode()
    return Image(python_version='python3.12',base_image='187248174200.dkr.ecr.us-east-1.amazonaws.com/prod/beta9-users:'+SDK_IMAGE).add_commands([
        'apt-get update -qq && apt-get install -y '+' '.join(name+'=10.13.3.9-1+cuda12.9' for name in ('libnvinfer-bin','libnvinfer-lean10','libnvinfer-vc-plugin10','libnvinfer-dispatch10')),
        'uv-b9 pip install --python "$(command -v python3.12)" "numpy==1.26.4" "scipy==1.15.3" "soundfile==0.13.1"',
        "python3.12 -c \"from pathlib import Path; import base64; Path('/opt/cgc_a2f.cpp').write_bytes(base64.b64decode('"+code+"')); p=Path('/opt/audio2face/CMakeLists.txt'); p.write_text(p.read_text()+base64.b64decode('"+encoded+"').decode())\"",
        'cmake -S /opt/audio2face -B /opt/a2f-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DTENSORRT_ROOT_DIR=/usr -DCUDAToolkit_ROOT=/usr/local/cuda && cmake --build /opt/a2f-build --target cgc_a2f --parallel 4',
        'test -x /usr/src/tensorrt/bin/trtexec && test -x /opt/a2f-build/cgc_a2f',
    ])
