# CGC 0.2.0 acceptance record

CGC 0.4.1 adds explicit degenerate-triangle cleanup, bounded artifact-download retries and configurable Blender material/clay reviews. The [real Dominion visual test](DOMINION_VISUAL_VALIDATION.md) rejected all four raw reconstructions; its separately recorded manual repair remains an approximate starting point. Technical validation does not establish visual approval.

CGC 0.4.0 added native compute profiles, official glTF validation, source-preserving engine packages, animation delivery, measured media finishing, and queue recovery fixes. See [the creative toolbox guide](CREATIVE_TOOLBOX.md) for current commands and limits. Its historical consolidated verification record is `outputs/quality-upgrade/acceptance.json`.

CGC 0.3.0 added the six remote enhancement routes and content-addressed input transport. See [the enhancement setup and acceptance guide](ENHANCEMENT_SETUP.md). The original 0.2.0 acceptance record follows.

Verified on 2026-11-11 local time (2026-11-12 UTC). The installed `cgc` command works outside the checkout. Codex drives the CLI using local input and output paths.

## Delivered and exercised

- Qwen Image 2.1 Base and Turbo on Beam: text generation, generation with references, target editing with supporting references, and validated RGBA output.
- TRELLIS.2: image to textured GLB, saved generation latents, and decode/bake/export from saved latents. The new exports use standard textures that Bevy can load.
- Character audio: Phonon speech and VoxCPM2 voice design, reference-conditioned lines, and delivery controls. Three corrected character lines matched independent transcription.
- MOSS-SoundEffect v2: one-shot effects, ambience, and a generic nonverbal effort sound.
- ACE-Step 1.5: instrumental and supplied-lyrics generation, style-reference generation, cover, repaint, track extraction, layer generation, and arrangement completion. Base is the default for supplied lyrics; the qualified English vocal example used `--language en`.
- Durable local queue: bulk import, input snapshots, output reservations, background dispatch, status/wait, pause/resume, cancel/retry, retained-result collection, and configurable idle warming.

The machine-readable evidence is [queue-e2e-acceptance.json](../outputs/queue-e2e-acceptance.json). It contains 30 completed logical jobs, their local media hashes, model/component revisions, package versions, actual hardware, provider task IDs, timings, and worker sessions. Two additional logical jobs were deliberately cancelled before inference: one in the local backlog and one already submitted to Beam. These are logical-job counts, not total paid attempts; debugging and rejected auditions remain in the logs and attempt history.

## Reliability checks

- Imported 10,000 jobs without allocating GPUs. Replayed rows did not create duplicates.
- Verified queued cancellation without an output or inference submission.
- Exercised running cancellation and explicit retry after a confirmed provider outcome. Provider-pending cancellation also drains terminal queue entries and releases idle startup containers, preventing cancelled failed-startup requests from restarting workers.
- Restarted the controller during a real 3D job. Recovery collected the same provider task without submitting inference again.
- Temporarily moved a generated provenance sidecar, then restored it from retained Beam files without repeating inference. Original and restored hashes matched.
- Verified the installed CLI from `/tmp`, including relative output resolution and access to the same project queue.
- Released the idle GPU session. The final Beam container inventory was empty.

Warm model reuse was recorded for all GPU model families. Examples include two Qwen Turbo images in one worker, three SFX jobs in one worker, and three 3D reconstructions plus a latent re-export in one TRELLIS worker. Direct CPU speech acceptance samples also reused one Phonon instance.

## Actual game-file checks

The generated crate GLB passed StarFall's native Bevy 0.20.1 import and three-view capture check without an extra texture conversion. The original Iron Sovereign import regression check still passed.

The StarFall inspection manifest now accepts an explicit emissive-material count; its default remains three for the existing Iron Sovereign asset. A decoder example checks generated audio using the same Bevy version. It passed ten WAV/OGG files covering speech, SFX, music, and music source operations. This validates file compatibility; it does not add gameplay audio behavior.

Evidence:

- [Native crate import](../outputs/starfall-native-crate-captures/bevy-import.json)
- [Original asset regression](../outputs/starfall-original-regression/bevy-import.json)
- [Audio decoder checks](../outputs/starfall-final-audio-check.log)
- [Blender review](../outputs/queue-edited-crate-review/inspection.json)
- [Active-job restart](../outputs/restart-active-acceptance.json)
- [Sidecar recovery](../outputs/sidecar-recovery-acceptance.json)

## Measured processing times

These small acceptance samples exclude provider queueing, model loading, and local collection. They are not a controlled model ranking or a production throughput guarantee.

| Case | Processing time |
| --- | ---: |
| Phonon short speech | 0.7–0.8 s |
| VoxCPM2 designed reference | 1.5 s |
| Corrected reference-conditioned character lines | 2.9–5.4 s |
| MOSS SFX, 2–6 seconds of audio | 12.9–16.0 s |
| Qwen Turbo, 1024 square, text generation | 46.9–60.4 s |
| Qwen Base, 1024 square, 40 steps | 69.2 s |
| Qwen reference-guided generation / target edit | 88.0 / 117.5 s |
| TRELLIS first 512 crate in a loaded worker | 82.6 s |
| Subsequent 512 crate reconstructions | 24.6–25.8 s |
| Saved-latent decode/export | 9.6 s |
| ACE-Step Turbo, 15-second instrumental | 4.9 s |
| ACE-Step Base, 30-second vocal example | 4.7 s |

Initial loading is separate. For example, the first Base checkpoint download/load took 312.6 seconds; the tested TRELLIS runtime restore/load took about 223 seconds. A cached download is distinct from a resident model. Session IDs and call counters establish actual reuse.

## Validation and output scope

The final checks passed: 90 core Python tests, 20 Beam offline tests, compilation checks, native imports, audio decoding, and StarFall Clippy with warnings denied.

Earlier character auditions spoke their direction text, and the initial short Turbo vocal audition did not pass the lyric transcription check. Those candidates have rejected QA sidecars. The corrected character path uses the model's reference-only control mode, and all intended words matched independent ASR. The clearer Base vocal example contained both supplied lyric phrases, with musical repetition. Successful media decoding alone is not a quality verdict.

Generated meshes remain editable reconstruction drafts: rigs, skin weights, collision, sockets, separated moving parts, and interiors require their own authoring work. Music generation and extraction do not guarantee exact stem reconstruction, synchronization, or seamless loops. Model-specific license records remain attached; CLI acknowledgments do not grant rights.
