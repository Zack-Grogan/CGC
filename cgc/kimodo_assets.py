"""Pinned Kimodo encoder assets with a verified public Llama weight source."""
import hashlib
import json
from pathlib import Path
import shutil

REVISIONS = {
    'NousResearch/Meta-Llama-3-8B-Instruct': '53346005fb0ef11d3b6a83b12c895cca40156b6c',
    'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp': '31474e395ada192e8ed1586db6be79fb3b70c9c0',
    'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised': 'baa8ebf04a1c2500e61288e7dad65e8ae42601a7',
    'nvidia/Kimodo-SOMA-RP-v1.2': '0e3c89024d896064b6851201373f7834784a386b',
}
MIRROR = 'NousResearch/Meta-Llama-3-8B-Instruct'
MNTP = 'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp'
SUPERVISED = MNTP+'-supervised'
MOTION = 'nvidia/Kimodo-SOMA-RP-v1.2'
CANONICAL = 'meta-llama/Meta-Llama-3-8B-Instruct'
WEIGHT_HASHES = {
    'model-00001-of-00004.safetensors': 'd8cf9c4d0dd972e1a2131bfe656235ee98221679711a3beef6d46dadf0f20b5c',
    'model-00002-of-00004.safetensors': '8d4782b4a69ef03845159ce1a15e272aadaaf134dc138d68f616098e8531729c',
    'model-00003-of-00004.safetensors': '3acdd690e65c24f42a24581b8467af98bd3ca357444580f8012aacd2bd607921',
    'model-00004-of-00004.safetensors': '67e9ad31c8c32abf3a55ee7fc7217b3ecb35fd3c74d98a5bd233e0e4d6964f46',
}


def derive_mntp(source, base, destination):
    """Keep MNTP weights and tokenizer; redirect only its base-weight path."""
    source, base, destination = map(Path, (source, base, destination))
    config = json.loads((source/'config.json').read_text())
    adapter = json.loads((source/'adapter_config.json').read_text())
    if config.get('_name_or_path') != CANONICAL or adapter.get('base_model_name_or_path') != CANONICAL:
        raise ValueError('Unexpected MNTP base or prompt-format identity')
    shutil.copytree(source, destination, dirs_exist_ok=True)
    adapter['base_model_name_or_path'] = str(base.resolve())
    (destination/'adapter_config.json').write_text(json.dumps(adapter, indent=2))
    return destination


def prepare(root):
    from huggingface_hub import snapshot_download
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    paths = {repo: Path(snapshot_download(repo, revision=revision, ignore_patterns=['original/**','*.pth'])) for repo, revision in REVISIONS.items()}
    # Verify actual bytes on the remote host, not only public metadata.
    for name, expected in WEIGHT_HASHES.items():
        digest = hashlib.sha256()
        with (paths[MIRROR]/name).open('rb') as stream:
            for block in iter(lambda: stream.read(8*1024*1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError('Mirror weight digest mismatch: '+name)
    derived = derive_mntp(paths[MNTP], paths[MIRROR], root/'mntp-with-nous-base')
    receipt = {'revisions': REVISIONS, 'base_weight_source': MIRROR, 'prompt_format': CANONICAL,
               'weight_hashes': WEIGHT_HASHES, 'downloaded_weight_hashes_verified': True,
               'adapter_override': {'base_model_name_or_path': str(paths[MIRROR])}}
    (root/'encoder-provenance.json').write_text(json.dumps(receipt, indent=2))
    return derived, paths[SUPERVISED], paths[MOTION], receipt
