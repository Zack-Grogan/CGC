# CGC game-audio suite

Status: implemented operation contracts. Codex drives choices through commands and local files. Actual Beam results, qualified profiles, and verification limits are recorded in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## 1. Character voices

Use the existing three speech operations. Character use does not require a separate `character generator` model or command.

| Operation | Input files and instructions | Result |
| --- | --- | --- |
| `audio design` | Sample words plus a description of voice identity | A candidate reference WAV. |
| `audio clone` | New words, selected reference WAV, its transcript, optional delivery direction | New speech conditioned on that reference. |
| `audio speak` | Words plus a supported preset where the selected backend provides one | Speech using the model's supported preset. |

VoxCPM2 is the starting backend because CGC has already exercised it on Beam. Its upstream API supports design descriptions and reference-conditioned speech with delivery guidance. Keep the pinned version's exact mapping and reject unsupported controls. [VoxCPM2 source](https://github.com/OpenBMB/VoxCPM).

Evaluate Qwen3-TTS when comparing identity stability, emotion, pronunciation, or languages. Its VoiceDesign, Base cloning, and CustomVoice presets use separate checkpoints and methods; they are not one interchangeable checkpoint. The official examples also show designing a sample and reusing it for cloning. [Qwen3-TTS source](https://github.com/QwenLM/Qwen3-TTS).

A character's local files can be:

```text
voices/mechanic/
  reference.wav
  reference.txt
  voice.json
  lines.ndjson
  lines/
    greeting.wav
    warning.wav
    combat-callout.wav
```

`voice.json` is an optional local record of the selected model revision, reference hash, identity description, and settings. It is ordinary data for Codex or job-file expansion, not an agent/persona service. `reference.txt` contains the exact words in the reference WAV. Keep dialogue text separate from delivery instructions. Add file-reading conveniences such as `--text-file` and `--transcript-file` without changing the model operation.

Design several candidates, listen, and retain one reference. Reuse that file for later lines instead of running voice design afresh for every sentence. Keep stable identity traits in the reference; vary performance through supported direction. Inspect identity across calm speech, urgent callouts, whispers, names, numbers, and longer sentences. Seeds can improve traceability where supported, but do not guarantee voice identity or identical output across runtime changes.

Build dialogue as per-line queue entries with speaker references and output paths. Codex can combine the resulting WAVs using an explicit timing/mix script or FFmpeg. This supplies controllable multi-character scenes without claiming that a single TTS call performs a complete cast. A native dialogue model would be a separate qualified adapter.

Include breaths, laughs, grunts, pain efforts, and creature calls in the audition set. Do not claim that writing `[grunt]` makes a speech model reliably produce a nonverbal performance. Generic non-speech sounds can use the SFX backend; identity-matched character efforts require an actual successful test or an explicitly selected additional model/recording route.

Usage:

```sh
cgc audio design "Docking systems checked. Ready when you are." \
  --model voxcpm2 --direction "Adult frontier mechanic, low warm voice, restrained rasp" \
  -o ./voices/mechanic/reference.wav

cgc audio clone "Get clear of the airlock!" --model voxcpm2 \
  --reference ./voices/mechanic/reference.wav \
  --transcript "Docking systems checked. Ready when you are." \
  --direction "Urgent shouted warning, same speaker" --consent \
  -o ./voices/mechanic/lines/warning.wav
```

The source reference may be a generated voice or another authorized recording. Preserve CGC's existing reference/transcript/consent checks. Qualify speaker continuity by listening; a valid WAV and correct transcript do not prove it.

## 2. Sound effects and ambience

First candidate: `OpenMOSS-Team/MOSS-SoundEffect-v2.0`, from the MOSS-TTS repository's dedicated `moss_soundeffect_v2` implementation. It generates non-speech sounds from text and accepts duration in seconds. The published range extends to 30 seconds. The documented CUDA API exposes `seconds`, inference steps, and guidance; qualify the exact revision and GPU memory before deployment. [Model card and API example](https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0).

Command:

```sh
cgc audio sfx "Heavy powered hatch opens, pneumatic hiss, short metallic stop, isolated" \
  --model moss-sfx-v2 --duration 4 -o ./audio/sfx/hatch-open.wav
```

One-shots, ambience beds, interfaces, machinery, fictional weapons, footsteps, impacts, and creature sounds are prompt categories of this operation. They are not separate model tools. `--count` produces alternative takes with individual receipts and files.

Do not add `--reference` or `--input` to this backend unless its actual implementation supports the requested conditioning or transformation. Do not inherit speech's 2,000-character limits, PCM16 reference rules, or token caps as if they were universal audio-model requirements.

Test transient clarity, leading silence, duration, noise, unwanted speech/music, and repetition. The model's first-call compilation cost must be separated from warm inference. Retain compilation/model state across jobs where compatible. Ambience longer than the qualified limit requires explicit assembly or a different profile; do not imply an unbounded duration input.

## 3. Music

First candidate: ACE-Step 1.5 on CUDA. Start with a pinned Turbo profile for generation, then qualify the Base profile for the operations that require it. These are qualified deployment profiles, not measured quality winners. Keep any optional music language-model component explicit in the worker profile, weight list, memory use, and timings. It is part of the music backend, not a custom CGC orchestrator. [ACE-Step project](https://github.com/ace-step/ACE-Step-1.5).

The adapter must keep style-reference audio separate from source audio that is being transformed:

| Proposed CLI operation | Actual ACE-Step mapping |
| --- | --- |
| `audio music generate PROMPT` | `text2music`; prompt becomes `caption`. |
| `generate --instrumental` / `--lyrics-file` | Instrumental setting or supplied `lyrics`; reject conflicting requests. |
| `generate --reference STYLE.wav` | `reference_audio`, when supported by the qualified profile/task. |
| `audio music cover --input SONG.wav` | `cover` with `src_audio`. |
| `audio music repaint --input SONG.wav --start S --end E` | `repaint` with source audio and a time interval. |
| `audio music extract --input MIX.wav --track vocals` | Base-only `extract` with its track instruction. |
| `audio music layer --input BACKING.wav --track strings` | Base-only `lego` task. |
| `audio music complete --input PARTIAL.wav --tracks drums,bass` | Base-only `complete` task. |

These mappings come from the [official inference specification](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/main/docs/en/INFERENCE.md). Reject unsupported operation/checkpoint pairs rather than silently changing models. Generated extraction or accompaniment does not guarantee exact source reconstruction or phase-aligned game stems.

Expose duration, seed, BPM, key, language, and generation controls only where supported. Record requested metadata separately from measured output: requesting a tempo or duration does not validate it. Generation returns a mix; do not label it isolated stems. Keep raw model output and processed game files separate.

Usage:

```sh
cgc audio music generate "Tense industrial orbital combat, restrained percussion, dark synths" \
  --model ace-step-1.5-turbo --instrumental --duration 60 \
  -o ./audio/music/orbital-combat.wav
```

Start qualification with short cues, then test longer tracks within the real worker timeout and memory budget. Include instrumentals, supplied lyrics, a style reference, and the source-audio operations above. Verify the Base-only cases on the Base worker. A full music suite requires those adapters and tests; naming the commands in this plan does not provide them.

## 4. Game-audio processing and checks

Codex can use FFmpeg or reusable audio scripts for trim, fade, gain/loudness adjustment, resampling, channel conversion, mix assembly, and runtime encoding. These are deterministic processing operations, not generation capabilities. Preserve original model output and record the processing command in a sidecar.

Choose mono/stereo, sample rate, and format from the intended game role; do not silently downmix a music bed or spatialize stereo ambience. Keep a lossless master and derive runtime encodings separately. Decode the actual encoded file during validation, not just its WAV source.

A prompt asking for a loop does not establish a seamless loop. For ambience/music loops, record loop bounds and audition the repeated boundary. Verify any crossfade or bar-aligned cut against the generated audio. Related combat/exploration arrangements are not automatically synchronized adaptive-music stems.

Every queue result must include actual sample rate, channels, sample count/duration, digest, model and component revisions, parameters, and timing. Check complete decoding, finite samples, unintended silence, clipping, and truncation. Speech also needs intelligibility/pronunciation checks; SFX and music need listening against their briefs. Apply loudness targets per asset class rather than one blanket target for every sound.

## 5. Required completion set

- One reusable character voice with multiple dialogue lines and delivery variants, plus an explicit result for the nonverbal audition cases.
- SFX one-shots and ambience with alternative takes and the requested local file outputs.
- Instrumental and supplied-lyrics music, style-reference generation, and qualified source-edit/stem operations on their required profiles.
- Real Beam runs with repeated jobs using the loaded model, followed by validated local collection and queue restart recovery.
- At least one StarFall sound playback/import test using the actual runtime encoding. Production mixing, music synchronization, and final casting remain creative/runtime checks, not consequences of a successful generation exit code.

SFX and music are included in CGC 0.2.0. Pinned builds and actual Beam output checks passed; new checkpoints or expanded profiles need their own qualification.
