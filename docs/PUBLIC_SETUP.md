# Public checkout setup

CGC is maintained as a personal CLI tool. The source includes remote worker recipes and local finishing commands. It does not include credentials, model weights, backend environments, queue databases, or generated assets.

## Runtime requirements

- Install Python 3.11+ for the CLI and offline tests.
- Install uv for backend setup. Beam setup selects Python 3.12.
- Authenticate with your own Beam account through the Beam CLI.
- Review the applicable model terms before you use a model. Some operations require `--accept-license` or `--consent`.
- Install Blender for Blender-based rendering and asset processing. Other finishing tools have separate setup commands documented in the main README.

## Workspace-specific dependencies

Published Beam image IDs identify builds used by the original workspace. These IDs are not credentials and do not grant access. Another workspace may need to build equivalent images. Build recipes are retained in `cgc/remote_client.py`, `cgc/*_image.py`, and `beam/`. A source checkout alone does not establish that all remote profiles work in a new account.

TRELLIS integration expects an existing sibling `image-to-3dlab` runtime and approved weights. Set `CGC_3DLAB_ROOT` if that runtime is elsewhere. The repository does not provide that separate runtime or its weights.

Local MLX image and audio backends require Apple silicon macOS. Select them explicitly with `--backend local`.

## Local state and evidence

Keep one shared state directory for each Beam workspace/profile set. The default is `.cgc/` in the checkout. `CGC_STATE_DIR` selects another directory. Do not share output paths across independent queues.

Historical validation documents describe particular runs. References to `outputs/`, local paths, and private project documents identify evidence from the original setup. Those artifacts are not included in the public repository. Historical results do not establish current provider availability or output quality for other inputs.

## Offline checks

Run these commands from the repository root:

```sh
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s beam -p 'test_*.py' -q
```

These checks do not qualify a new cloud account. Remote acceptance runs consume credits and require separate execution.
