# Adding a model responsibly

1. Verify the current **released** backend source and exact console entry point. Main-branch documentation can differ from the installed release.
2. Verify the actual downloadable checkpoint, base-model alias, quantization format and original weight license. Community conversion metadata does not replace original terms.
3. Add a `Model` in `cgc/catalog.py`, supported operation names, realistic weight footprint, source link and candid memory caveat. Image repositories and console entry points are separately mapped.
4. Add argument translation in `cgc/planning.py`. Do not pass free-form shell fragments. `command` is always a list executed without a shell.
5. Add unit tests for command construction and unsupported combinations. Keep imports lazy and no downloads in help, doctor or planning.
6. Run a real 512-pixel image/edit or short speech test only after dependencies, storage, license and asset-download permission are satisfied. Record package/model revision, peak memory, elapsed time and qualitative results before calling it verified.
7. Add a new backend/environment if dependencies conflict. Do not silently turn a local model option into a hosted API.

The current audio family covers speech/voice generation, not music or sound effects. ACE-Step 1.5 and MOSS-SoundEffect require different adapters and resource evaluation; their command schemas must not be guessed from the speech module.

Native ChatGPT image generation is an optional separate creative workflow, not an installed or callable CGC backend. Do not claim CGC can access an unavailable private ChatGPT API.
