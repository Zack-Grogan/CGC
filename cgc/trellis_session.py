"""Resident TRELLIS subprocess in its qualified CUDA environment; JSON lines on stdout."""
import contextlib
import faulthandler
import json
import os
from pathlib import Path
import sys
import traceback


def reserve_protocol():
    """Keep JSON separate from native libraries that write directly to fd 1."""
    sys.stdout.flush()
    protocol=os.fdopen(os.dup(sys.stdout.fileno()),'w',buffering=1)
    os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    return protocol


def main():
    faulthandler.enable()
    protocol=reserve_protocol()
    root = Path('/tmp/assetfurnace')
    os.chdir(root)
    sys.path[:0] = [str(root), str(root / 'scripts')]
    import trellis_cuda_generate as generator
    import bootstrap_trellis_cuda as boot
    from image_to_3dlab.provenance import validate_run_policy
    validate_run_policy('trellis2', 'game', 'private', False, model_identity='microsoft/TRELLIS.2-4B')
    with contextlib.redirect_stdout(sys.stderr):
        pipeline = generator.load_pipeline(boot.VENDOR)
    generator.load_pipeline = lambda *args, **kwargs: pipeline
    texture_pipeline=None
    print(json.dumps({'ready': True}), flush=True,file=protocol)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if request.get('texture'):
                    import trellis_texture
                    if texture_pipeline is None:
                        texture_pipeline=trellis_texture.load(pipeline,Path('/tmp/assetfurnace/weights/trellis'))
                    trellis_texture.run(texture_pipeline,generator,request['source'],request['reference'],request['output'],
                        request['seed'],request['resolution'],request['texture_size'])
                elif request.get('from_latents'):
                    generator.generate_from_latents(Path(request['source']), Path(request['output']), boot.VENDOR,
                        decimation_target=request['decimation_target'], texture_size=request['texture_size'])
                else:
                    generator.generate(Path(request['source']), Path(request['output']), boot.VENDOR,
                        seed=request['seed'], resolution=str(request['resolution']), decimation_target=request['decimation_target'],
                        texture_size=request['texture_size'], save_latents=request.get('save_latents', False))
            print(json.dumps({'ok':True}), flush=True,file=protocol)
        except Exception:
            print(json.dumps({'error':traceback.format_exc()}), flush=True,file=protocol)


if __name__ == '__main__':
    main()
