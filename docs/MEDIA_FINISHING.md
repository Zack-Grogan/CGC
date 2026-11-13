# Measured media finishing

CGC can inspect and finish generated audio and raster images without loading a generation model. The original file remains the master. Every completed derivative has a `.quality.json` receipt with source/output hashes, measurements, processing choices, and software versions. Existing outputs and receipts are refused.

## Setup

```sh
cgc media setup
```

This installs Pillow/LittleCMS, NumPy, and SoundFile into the project `.backends/media` environment. It downloads no model weights. The host also needs the official `ffmpeg` and `ffprobe` commands on `PATH`. Vorbis uses the pinned libsndfile backend because an FFmpeg build may omit `libvorbis`.

## Inspect and accept files

```sh
cgc media inspect --input ./voice.wav --json
cgc media check --input ./ambience.wav --loop --seam-ceiling-db -50 --json
cgc media check --input ./albedo.png --role base-color --strict --json
```

Audio inspection decodes every sample. It reports finite values, sample peaks, measured true peak and integrated loudness, per-channel RMS/DC, and configurable silence observations. Full-scale samples are reported as a clipping risk, not proof of audible distortion.

Loop inspection measures the last-to-first sample jump and edge-window level difference. A technical pass does not establish musical phase, matching room tone, a natural repeating action, or perceptual continuity. Audition the result.

Checks return `passed`, `review`, or `failed`. `--strict` changes review findings into a failed acceptance result. Thresholds are project policy choices. There is no universal game LUFS target or seam threshold.

## Audio processing

```sh
cgc media audio --input ./voice.wav --profile game \
  --fade-in 0.005 --fade-out 0.01 --lufs -18 -o ./voice-game.wav
cgc media audio --input ./ambience.wav --profile master \
  --loop-crossfade 0.5 --peak-db -3 -o ./ambience-loop-master.wav
cgc media audio --input ./ambience-loop-master.wav --profile stream \
  --peak-db -3 -o ./ambience-delivery.ogg
```

The example loudness and peak values are explicit delivery choices, not recommendations for every asset. A game's final mix can clip even when individual sources have headroom.

| Profile | Output | Rate and channels | Intended use |
| --- | --- | --- | --- |
| `master` | Float32 WAV | Preserve source rate/channels | Editable processing derivative; retain the source for original precision |
| `game` | PCM16 WAV with triangular dither | 48 kHz; preserve channels | Conservative interchange delivery |
| `spatial` | PCM16 WAV with triangular dither | 48 kHz mono | Explicit mono downmix for spatial emitters |
| `stream` | Vorbis OGG | 48 kHz; preserve channels | Lossy streaming delivery where the engine/importer supports it |

Use `--sample-rate` and `--channels` to override those choices. Upsampling does not recover missing source bandwidth. Mono conversion can change stereo imaging and phase behavior.

The processing order is trim, rate/channels, optional loop overlap, fades, normalization, and delivery encoding. Normalization measures the processed clip first. LUFS normalization uses constant gain when that can meet the true-peak ceiling. If it cannot, CGC stops. `--allow-dynamic` explicitly permits a measured `loudnorm` transform that can alter transients and dynamics. CGC verifies each result and permits at most three offset-refinement attempts, each from the same lossless prepared source. Short effects may have undefined integrated loudness; use an explicit peak target or an appropriate longer measurement context.

The optional loop overlap combines the tail and head, rotates the playback start, and shortens the clip by the overlap duration. Linear and equal-power curves are available. The output receipt records exact playback frame bounds; it does not claim embedded loop metadata or configure an engine's playback loop switch.

The delivery file is decoded and measured after encoding. Lossy coding can move peaks. CGC refuses a normalized output that exceeds its configured tolerance. Review warnings remain visible in the receipt.

## Image and texture processing

```sh
cgc media inspect --input ./albedo.png --role base-color --json
cgc media image --input ./albedo.png --role base-color \
  --color-action to-srgb --assume-srgb --max-size 2048 -o ./albedo-delivery.png
cgc media image --input ./normal.png --role normal \
  --max-size 1024 --flip-green -o ./normal-converted.png
```

`--assume-srgb` is required when an untagged color image needs an sRGB interpretation. It is an assumption about source samples, not color recovery. Embedded ICC conversion uses LittleCMS. Color resizing uses linear-light samples and premultiplied-alpha filtering, then writes straight-alpha PNG output. The alpha channel is retained separately from the color transform.

Numeric texture roles use linear filtering without display gamma. Normal vectors are renormalized after resizing. Green inversion is explicit; the tool does not infer a universal normal convention from the target engine name. Use the convention required by the selected importer and shader.

Lossless PNG copying preserves the source bytes when no transformation is requested. Original PNG color chunks are retained for a preserving conversion. `--strip-color-tags` is available only for explicitly numeric roles and retains numeric samples.

High-bit-depth PNGs can be copied or have color metadata removed without changing their pixel payload. This worker refuses high-precision resizing and color transforms that Pillow would reduce to 8-bit precision. HDR/EXR and arbitrary high-precision color work still need a verified high-precision tool. The inspector labels its 8-bit display-decode measurements accordingly.

## Explicit channel packing

glTF stores roughness in green and metallic in blue. Unity shader layouts can differ. The packer copies scalar samples without ICC conversion, gamma processing, or implicit resizing.

```sh
cgc media pack --layout orm \
  --roughness ./gltf-mr.png --roughness-channel g \
  --metallic ./gltf-mr.png --metallic-channel b -o ./orm.png
cgc media pack --layout unity-metallic \
  --roughness ./gltf-mr.png --roughness-channel g \
  --metallic ./gltf-mr.png --metallic-channel b -o ./metallic-smoothness.png
cgc media channel --input ./metallic-smoothness.png --channel a \
  --invert -o ./roughness.png
```

| Layout | R | G | B | A |
| --- | --- | --- | --- | --- |
| `orm` | Occlusion, default 1 | Roughness, default 1 | Metallic, default 0 | Not written |
| `unity-metallic` | Metallic | 0 | 0 | `1 - roughness` |
| `unity-hdrp-mask` | Metallic | Occlusion | Detail mask, default 1 | `1 - roughness` |

Provide `--occlusion`, `--roughness`, `--metallic`, or `--detail`, with the corresponding `--NAME-channel` when needed. Dimensions must match. The initial packer supports 8-bit data and refuses implicit high-bit-depth reduction. Import packed outputs as linear/non-color data. A custom shader or glTF importer may already handle conversion; use the layout that the actual shader expects.

## Verified evidence

[The acceptance artifact](../outputs/media-finishing/acceptance.json) records real generated files and exact-value fixtures. The CGC voice was delivered as 48 kHz PCM16 with measured loudness. A generated 15-second cue became a 14.5-second overlap loop and a Vorbis delivery. StarFall's Bevy 0.20.1 decoder accepted the PCM16 WAV, float WAV, and OGG files. No Unity, Unreal, or Godot application import is claimed by this media test.

The image tests cover linear-light averaging, transparent-color bleed prevention, explicit normal conversion, high-precision refusal/copy behavior, ICC conversion, and exact channel layouts. The actual TRELLIS material map was repacked for ORM and Unity metallic/smoothness with every pixel checked.

## Primary research

- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html): measured loudness, constant/dynamic normalization, sample-based fades, and overlap curves.
- [SoundFile documentation](https://python-soundfile.readthedocs.io/en/latest/) and [libsndfile command API](https://libsndfile.github.io/libsndfile/command.html): available formats and explicit compression control.
- [Pillow ImageCms](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html): ICC transforms through LittleCMS.
- [PNG specification](https://www.w3.org/TR/png-3/): color declarations and alpha semantics.
- [glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html): color/data texture interpretation, channel assignments, and straight alpha.
- [Unity metallic shader properties](https://docs.unity.com/en-us/engine/6000.0/manual/materials-and-shaders/built-in/shader-built-in-configure-properties/standard-shader-material-parameter-metallic) and [HDRP mask maps](https://docs.unity.cn/Packages/com.unity.render-pipelines.high-definition%4012.1/manual/Mask-Map-and-Detail-Map.html): shader-specific packing.
- [Godot audio importing](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_audio_samples.html), [Unity audio import settings](https://docs.unity.com/en-us/engine/6000.0/manual/audio/reference/class-audio-clip), and [Unreal audio importing](https://dev.epicgames.com/documentation/unreal-engine/importing-audio-files): format and importer tradeoffs. These support interchange guidance, not a universal mastering target.
