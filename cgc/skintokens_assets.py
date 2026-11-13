"""Download only the two TokenRig checkpoints and Qwen configuration files."""
import hashlib
import json
from pathlib import Path

REVISIONS = {'VAST-AI/SkinTokens':'79736cad0fd84de384d5eede659b4ebd24effe33',
             'Qwen/Qwen3-0.6B':'c1899de289a04d12100db370d81485cdf75e47ca'}
CHECKPOINTS = ['experiments/skin_vae_2_10_32768/last.ckpt',
               'experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt']


def prepare(root):
    from huggingface_hub import snapshot_download
    root=Path(root).resolve()
    snapshot_download('VAST-AI/SkinTokens',revision=REVISIONS['VAST-AI/SkinTokens'],allow_patterns=CHECKPOINTS,local_dir=root)
    snapshot_download('Qwen/Qwen3-0.6B',revision=REVISIONS['Qwen/Qwen3-0.6B'],
                      allow_patterns=['config.json','generation_config.json','tokenizer*','vocab.json','merges.txt','special_tokens_map.json'],
                      local_dir=root/'models/Qwen3-0.6B')
    hashes={}
    for name in CHECKPOINTS:
        digest=hashlib.sha256()
        with (root/name).open('rb') as source:
            for block in iter(lambda:source.read(8*1024*1024),b''):digest.update(block)
        hashes[name]=digest.hexdigest()
    receipt={'revisions':REVISIONS,'checkpoint_hashes':hashes,'qwen_weights_downloaded':False}
    (root/'provenance.json').write_text(json.dumps(receipt,indent=2))
    return root,receipt
