"""Resident Kimodo process with an isolated Transformers environment."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def main():
    protocol = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from kimodo_assets import prepare
        from kimodo import load_model
        from kimodo.model.llm2vec.llm2vec_wrapper import LLM2VecEncoder
        from kimodo.exports.motion_io import save_kimodo_npz
        from kimodo.tools import seed_everything
        torch.set_num_threads(2)
        if not torch.cuda.is_available():
            raise RuntimeError('Kimodo requires the selected remote CUDA worker')
        properties = torch.cuda.get_device_properties(0)
        print('Kimodo CUDA device: '+properties.name, file=sys.stderr, flush=True)
        if torch.cuda.get_device_capability(0)[0] < 8 or properties.total_memory < 20*1024**3:
            raise RuntimeError('Kimodo requires BF16 CUDA support and at least 20 GiB VRAM: '+properties.name)
        mntp, supervised, motion, provenance = prepare(Path.cwd()/'models/kimodo')
        encoder = LLM2VecEncoder(str(mntp), str(supervised), 'bfloat16', 4096, device='cuda')
        expected = '<|start_header_id|>user<|end_header_id|>\n\nprobe<|eot_id|>'
        if encoder.model.prepare_for_tokenization('probe') != expected:
            raise RuntimeError('LLM2Vec Llama prompt format changed')
        checkpoints = Path.cwd()/'models/kimodo/checkpoints'
        checkpoints.mkdir(parents=True, exist_ok=True)
        selected = checkpoints/'Kimodo-SOMA-RP-v1.2'
        if not selected.exists():
            selected.symlink_to(motion, target_is_directory=True)
        if selected.resolve() != motion.resolve():
            raise RuntimeError('Unexpected cached Kimodo checkpoint')
        os.environ['CHECKPOINT_DIR'] = str(checkpoints)
        model = load_model('Kimodo-SOMA-RP-v1.2', device='cuda', text_encoder=encoder)
    import importlib.metadata
    versions = {name: importlib.metadata.version(name) for name in ('torch','transformers','peft','kimodo')}
    protocol.write(json.dumps({'ready': True, 'device': torch.cuda.get_device_name(0), 'provenance': provenance, 'versions': versions})+'\n')
    protocol.flush()
    for line in sys.stdin:
        try:
            task = json.loads(line)
            started = time.monotonic()
            with contextlib.redirect_stdout(sys.stderr), torch.inference_mode():
                seed_everything(task['seed'])
                output = model([task['prompt']], [int(task['duration']*model.fps)], num_samples=1,
                               num_denoising_steps=task['steps'], multi_prompt=True,
                               post_processing=True, return_numpy=True)
                single = {key: (value[0] if hasattr(value, 'shape') and len(value.shape)>0 and value.shape[0]==1 else value) for key, value in output.items()}
                save_kimodo_npz(task['output'], single)
            answer = {'ok': True, 'fps': float(model.fps), 'generation_seconds': time.monotonic()-started,
                      'peak_cuda_bytes': int(torch.cuda.max_memory_allocated())}
        except Exception:
            answer = {'ok': False, 'error': traceback.format_exc()}
        protocol.write(json.dumps(answer)+'\n')
        protocol.flush()


if __name__ == '__main__':
    main()
