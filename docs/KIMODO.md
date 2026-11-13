# Kimodo motion generation

CGC uses `nvidia/Kimodo-SOMA-RP-v1.2` on Beam. The CLI accepts a text prompt and writes a local SOMA77 NPZ file. It uses the existing CGC queue.

```sh
cgc motion generate "A person walks forward at a steady pace." \
  --duration 4 --steps 100 --seed 42 --accept-license -o ./walk.npz
cgc motion generate "A person stands in a relaxed idle stance." \
  --duration 4 --seed 43 --count 4 --output-dir ./idle-candidates \
  --accept-license --enqueue --json
```

Duration is 1–30 seconds at 30 frames per second. The default is 5 seconds and 100 denoising steps. Each job has its own seed, local output path, receipt, and provider task record. Existing files are preserved. Use `cgc jobs wait JOB_ID --json` to wait for collection.

The worker retains the text encoder and motion model between jobs. It uses an isolated Python environment so Kimodo's Transformers dependency does not change the other generation environments.

CGC requests an RTX 4090. The worker accepts a compatible provider assignment with BF16 support and at least 20 GiB VRAM. Each receipt records the actual GPU.

## Llama weight source

The text encoder uses these components:

| Component | Repository | Pinned revision |
| --- | --- | --- |
| Base weights | `NousResearch/Meta-Llama-3-8B-Instruct` | `53346005fb0ef11d3b6a83b12c895cca40156b6c` |
| MNTP adapter and tokenizer | `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp` | `31474e395ada192e8ed1586db6be79fb3b70c9c0` |
| Supervised adapter | `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised` | `baa8ebf04a1c2500e61288e7dad65e8ae42601a7` |
| Motion checkpoint | `nvidia/Kimodo-SOMA-RP-v1.2` | `0e3c89024d896064b6851201373f7834784a386b` |

All four published weight-shard hashes in the Nous mirror match the corresponding original Meta shards. Beam also verified the downloaded bytes against those hashes. See the [metadata comparison](../outputs/enhancements/kimodo-mirror-comparison.json) and [remote cache receipt](../outputs/enhancements/kimodo-encoder-cache.json).

CGC makes a derived copy of the MNTP adapter configuration. It changes only `base_model_name_or_path` to the pinned Nous weights. It preserves both adapters, the MNTP tokenizer, and LLM2Vec's Llama 3 prompt formatting. The prompt-format identifier remains `meta-llama/Meta-Llama-3-8B-Instruct`; the receipt separately records the actual Nous weight source. No access to the gated Meta repository is required for this route.

`--accept-license` acknowledges the intended use of the motion checkpoint, Llama 3 weights, and adapter components. The mirror retains the Llama terms. See the [Nous model card](https://huggingface.co/NousResearch/Meta-Llama-3-8B-Instruct) and [Kimodo source](https://github.com/nv-tlabs/kimodo).

## Output checks

CGC checks the SOMA77 array shapes, finite positions, and proper rotation matrices before it marks the local job complete. It writes an additional `.motion.json` file with the encoder sources, actual runtime versions, frame rate, and GPU-memory measurement.

An NPZ contains motion on the source skeleton. It must be retargeted to the character rig before game playback. The existing image-to-3dlab retargeter supplies that processing step. Character deformation, foot contact, and loop quality require separate checks on the target rig.

Source is pinned at `e1c219c99b4b94ba48be1fb6a1cbc64ecee4c954`. The published Beam image is `f19b3bbc2b365d99`; its build recipe is in `cgc/kimodo_image.py`.

## End-to-end acceptance

The [acceptance record](../outputs/enhancements/kimodo-e2e.json) covers two four-second generations, idle and walk, on an actual RTX 4090. Both contain 120 SOMA77 frames. They share one resident session with call counters 1 and 2 and one model load. Worker generation times were 2.29 and 1.98 seconds; these exclude queueing, startup, and collection. The measured initial load was 287.51 seconds, including remote weight verification and encoder initialization. Peak allocated CUDA memory was 16.39 GB.

Both clips were retargeted to a separate copy of StarFall's Dominion marine. The copy removes one unweighted wrapper root; its rest-pose vertex change was below `1e-6`. The original assets were preserved. Loop processing reduced the exported clips to selected cycles; the walk also removes horizontal root travel.

Blender checks passed for normalized weights, influence limits, finite evaluated vertices, and bounded deformation. StarFall's Bevy 0.20.1 test evaluated each exported animation through 120 frames and confirmed moving, finite character-node transforms. These checks qualify this existing rig and the motion handoff. They do not qualify new TokenRig rigs or every possible character.

To run a Python CLI helper inside Blender, use the argument adapter:

```sh
blender --background --python scripts/blender_python.py -- \
  ../image-to-3dlab/scripts/kimodo_retarget.py \
  --rig ./compatible-rig.glb --motion ./walk.npz --out ./walk.glb --loop --in-place
```
