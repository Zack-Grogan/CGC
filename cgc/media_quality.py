"""Measured media checks and deterministic finishing; no generation models."""
import argparse
import array
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IMAGE_PYTHON = ROOT / '.backends/media/bin/python'
AUDIO_SUFFIXES = {'.wav', '.ogg', '.mp3', '.flac', '.aif', '.aiff', '.opus'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tga', '.tif', '.tiff', '.bmp'}
PROFILES = {
    'master': {'suffix': '.wav', 'codec': 'pcm_f32le', 'sample_rate': None, 'channels': None, 'lossy': False},
    'game': {'suffix': '.wav', 'codec': 'pcm_s16le', 'sample_rate': 48000, 'channels': None, 'lossy': False},
    'spatial': {'suffix': '.wav', 'codec': 'pcm_s16le', 'sample_rate': 48000, 'channels': 1, 'lossy': False},
    'stream': {'suffix': '.ogg', 'codec': 'libvorbis', 'sample_rate': 48000, 'channels': None, 'lossy': True},
}


def _number(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be {low} through {high}')
    return value


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise ValueError(f'{name} is required; install the official FFmpeg tools and put them on PATH')
    return path


def _run(command, **options):
    result = subprocess.run(command, capture_output=True, text=True, timeout=options.pop('timeout', 600), **options)
    if result.returncode:
        raise ValueError(f'{Path(command[0]).name} failed: {(result.stderr or result.stdout)[-3000:]}')
    return result


def _source(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Input file does not exist: '+str(path))
    return path


def _hash(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def _probe(path):
    result = _run([_tool('ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)])
    return json.loads(result.stdout)


def _db(value):
    return 20*math.log10(value) if value > 0 else None


def _finite_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _loudness(path, *, target_lufs=-23., target_peak=-1., target_lra=11.):
    command = [_tool('ffmpeg'), '-hide_banner', '-nostdin', '-v', 'info', '-i', str(path), '-map', '0:a:0',
               '-af', f'loudnorm=I={target_lufs}:TP={target_peak}:LRA={target_lra}:print_format=json', '-f', 'null', '-']
    result = _run(command)
    matches = re.findall(r'\{\s*"input_i"[\s\S]*?\}', result.stderr)
    if not matches:
        raise ValueError('FFmpeg did not return loudness measurements')
    values = json.loads(matches[-1])
    return {'integrated_lufs': _finite_number(values.get('input_i')), 'true_peak_db': _finite_number(values.get('input_tp')),
            'loudness_range_lu': _finite_number(values.get('input_lra')), 'threshold_lufs': _finite_number(values.get('input_thresh')),
            'meter': 'FFmpeg loudnorm / EBU R128', 'raw': values}


def inspect_audio(path, *, silence_db=-60., edge_window_ms=10., loudness=True):
    """Decode every sample and report technical observations, without a quality rating."""
    path = _source(path)
    _number(silence_db, -120, -10, 'Silence threshold dBFS')
    _number(edge_window_ms, .1, 1000, 'Edge window milliseconds')
    streams = [stream for stream in _probe(path)['streams'] if stream['codec_type'] == 'audio']
    if not streams:
        raise ValueError('No audio stream')
    stream = streams[0]; channels = int(stream['channels']); rate = int(stream['sample_rate'])
    if not 1 <= channels <= 32 or rate <= 0:
        raise ValueError('Unsupported channel count or sample rate')
    window = max(1, round(rate*edge_window_ms/1000)); first = []; tail = deque(maxlen=window*channels)
    sums = [0.] * channels; squares = [0.] * channels; peaks = [0.] * channels
    count = nonfinite = over_range = full_scale = silent_frames = run = longest = leading = 0
    ever_audible = False; threshold = 10**(silence_db/20)
    command = [_tool('ffmpeg'), '-hide_banner', '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:a:0',
               '-vn', '-sn', '-dn', '-f', 'f32le', '-c:a', 'pcm_f32le', 'pipe:1']
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        pending = b''
        try:
            while block := process.stdout.read(256*1024):
                pending += block
                complete = len(pending)//(4*channels)*(4*channels)
                raw, pending = pending[:complete], pending[complete:]
                values = array.array('f'); values.frombytes(raw)
                if sys.byteorder != 'little': values.byteswap()
                if len(first) < window*channels:
                    first.extend(values[:window*channels-len(first)])
                tail.extend(values)
                for offset in range(0, len(values), channels):
                    frame_peak = 0.
                    for channel in range(channels):
                        value = values[offset+channel]; count += 1
                        if not math.isfinite(value):
                            nonfinite += 1; continue
                        magnitude = abs(value); frame_peak = max(frame_peak, magnitude)
                        sums[channel] += value; squares[channel] += value*value; peaks[channel] = max(peaks[channel], magnitude)
                        over_range += magnitude > 1.; full_scale += magnitude >= 32767/32768
                    if frame_peak <= threshold:
                        silent_frames += 1; run += 1; longest = max(longest, run)
                        if not ever_audible: leading += 1
                    else:
                        ever_audible = True; run = 0
            return_code = process.wait(timeout=30)
            if pending: raise ValueError('Audio decoder returned a partial frame')
            if return_code:
                errors.seek(0); raise ValueError('Audio decoding failed: '+errors.read().decode(errors='replace')[-2000:])
        finally:
            if process.poll() is None: process.kill(); process.wait()
            process.stdout.close()
    frames = count//channels
    if not frames: raise ValueError('Empty decoded audio')
    last = list(tail); edge_count = min(len(first), len(last))//channels
    jumps = [abs(last[-channels+c]-first[c]) for c in range(channels)]
    edge = []
    for channel in range(channels):
        beginning = first[channel:edge_count*channels:channels]; ending = last[-edge_count*channels+channel::channels]
        a = math.sqrt(sum(x*x for x in beginning)/len(beginning)) if all(math.isfinite(x) for x in beginning) else None
        b = math.sqrt(sum(x*x for x in ending)/len(ending)) if all(math.isfinite(x) for x in ending) else None
        edge.append({'channel': channel, 'start_rms': a, 'end_rms': b,
                     'rms_difference_db': 20*math.log10(a/b) if a and b else None})
    measurements = _loudness(path) if loudness and not nonfinite else None
    peak = max(peaks)
    return {'kind': 'audio', 'path': str(path), 'bytes': path.stat().st_size, 'sha256': _hash(path), 'decoded': True,
            'codec': stream.get('codec_name'), 'sample_format': stream.get('sample_fmt'), 'bits_per_sample': stream.get('bits_per_raw_sample') or stream.get('bits_per_sample'),
            'sample_rate': rate, 'channels': channels, 'frames': frames, 'duration': frames/rate, 'finite': nonfinite == 0,
            'nonfinite_samples': nonfinite, 'sample_peak': peak, 'sample_peak_dbfs': _db(peak), 'over_range_samples': over_range,
            'full_scale_samples': full_scale, 'rms_per_channel': [math.sqrt(value/frames) for value in squares], 'dc_per_channel': [value/frames for value in sums],
            'silence': {'threshold_dbfs': silence_db, 'fraction': silent_frames/frames, 'leading_seconds': leading/rate, 'trailing_seconds': run/rate, 'longest_seconds': longest/rate},
            'loop_seam': {'sample_jump_peak': max(jumps) if all(math.isfinite(x) for x in jumps) else None,
                          'sample_jump_dbfs': _db(max(jumps)) if all(math.isfinite(x) for x in jumps) else None,
                          'window_ms': edge_window_ms, 'channels': edge, 'limitation': 'Technical boundary measurements do not establish a musically or perceptually seamless loop'},
            'loudness': measurements}


def check_audio(report, *, peak_ceiling_db=-1., loop=False, seam_ceiling_db=-50., max_silence_fraction=None, allow_float_headroom=False):
    _number(peak_ceiling_db, -30, 0, 'True-peak ceiling')
    _number(seam_ceiling_db, -120, 0, 'Seam jump ceiling')
    findings = []
    def add(level, code, message): findings.append({'level': level, 'code': code, 'message': message})
    if not report['finite']: add('error', 'nonfinite_audio', 'Decoded audio contains nonfinite samples')
    if report['sample_peak'] == 0: add('error', 'silent_audio', 'Decoded audio is entirely silent')
    if report['over_range_samples']: add('warning' if allow_float_headroom else 'error', 'over_range_audio', 'Samples exceed full scale and can clip during integer encoding')
    true_peak = (report.get('loudness') or {}).get('true_peak_db')
    if true_peak is not None and true_peak > peak_ceiling_db+.15:
        add('warning', 'true_peak_headroom', f'Measured true peak {true_peak:.2f} dBTP exceeds the configured {peak_ceiling_db:.2f} dBTP ceiling')
    if report['full_scale_samples']: add('warning', 'full_scale_samples', 'Full-scale samples were found; this alone does not prove audible clipping')
    if max(abs(x) for x in report['dc_per_channel']) > .01: add('warning', 'dc_offset', 'Mean channel amplitude exceeds 0.01; inspect the DC offset')
    if max_silence_fraction is not None:
        _number(max_silence_fraction, 0, 1, 'Maximum silence fraction')
        if report['silence']['fraction'] > max_silence_fraction: add('warning', 'silence_fraction', 'Silence exceeds the configured fraction')
    if loop:
        jump = report['loop_seam']['sample_jump_dbfs']
        if jump is not None and jump > seam_ceiling_db: add('warning', 'loop_boundary_jump', 'The loop sample jump exceeds the configured threshold; audition the transition')
    return {'status': 'failed' if any(f['level'] == 'error' for f in findings) else 'review' if findings else 'passed',
            'findings': findings, 'policy': {'true_peak_ceiling_db': peak_ceiling_db, 'loop': loop, 'seam_jump_ceiling_dbfs': seam_ceiling_db, 'max_silence_fraction': max_silence_fraction},
            'limitation': 'A technical pass does not rate voice acting, music composition, semantic fit, or perceptual loop quality'}


def _destination(path, suffix=None):
    path = Path(path).expanduser().resolve()
    if suffix and path.suffix.lower() != suffix: raise ValueError('Expected output suffix '+suffix)
    if path.exists() or Path(str(path)+'.quality.json').exists(): raise ValueError('Output or quality receipt already exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def process_audio(source, output, *, profile='master', sample_rate=None, channels=None, trim_start=0., trim_end=None,
                  fade_in=0., fade_out=0., loop_crossfade=0., loop_curve='linear', lufs=None, peak_db=None, true_peak_db=-1., allow_dynamic=False):
    source = _source(source)
    if profile not in PROFILES: raise ValueError('Unknown audio profile')
    settings = PROFILES[profile]
    output = _destination(output, settings['suffix'])
    if source == output: raise ValueError('Source and output must differ')
    _number(trim_start, 0, 86400, 'Trim start'); _number(fade_in, 0, 60, 'Fade in'); _number(fade_out, 0, 60, 'Fade out'); _number(loop_crossfade, 0, 60, 'Loop crossfade')
    if trim_end is not None: _number(trim_end, trim_start+.000001, 86400, 'Trim end')
    if sample_rate is not None and (type(sample_rate) is not int or not 8000 <= sample_rate <= 192000): raise ValueError('Sample rate must be an integer from 8000 through 192000')
    if channels is not None and (type(channels) is not int or not 1 <= channels <= 8): raise ValueError('Channels must be 1 through 8')
    if lufs is not None: _number(lufs, -70, -5, 'Target LUFS')
    if peak_db is not None: _number(peak_db, -30, 0, 'Target true peak')
    _number(true_peak_db, -9, 0, 'True-peak ceiling')
    if lufs is not None and peak_db is not None: raise ValueError('Choose LUFS normalization or peak normalization')
    if loop_curve not in ('linear', 'equal-power'): raise ValueError('Loop curve must be linear or equal-power')
    before = inspect_audio(source, loudness=False)
    if not before['finite'] or not before['sample_peak']: raise ValueError('Finishing requires finite, non-silent audio')
    if trim_start >= before['duration'] or (trim_end is not None and trim_end > before['duration']+1/before['sample_rate']): raise ValueError('Trim range exceeds the decoded source duration')
    rate = sample_rate or settings['sample_rate'] or before['sample_rate']; channel_count = channels or settings['channels'] or before['channels']
    commands = []; notes = []; normalization = None; encoder_details={'implementation':'FFmpeg','codec':settings['codec']}
    def execute(arguments):
        command = [_tool('ffmpeg'), '-hide_banner', '-nostdin', '-v', 'error', '-n', *arguments]
        commands.append(command); return _run(command)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.cgc-media-') as directory:
        folder = Path(directory); prepared = folder/'prepared.wav'
        filters = []
        if trim_start or trim_end is not None: filters += [f'atrim=start={trim_start}'+(f':end={trim_end}' if trim_end is not None else ''), 'asetpts=PTS-STARTPTS']
        args = ['-i', str(source), '-map', '0:a:0', '-vn', '-sn', '-dn']
        if filters: args += ['-af', ','.join(filters)]
        execute([*args, '-ar', str(rate), '-ac', str(channel_count), '-c:a', 'pcm_f32le', str(prepared)])
        measured = inspect_audio(prepared, loudness=False)
        if loop_crossfade:
            overlap = round(loop_crossfade*rate); length = measured['frames']
            if overlap < 2 or overlap*2 >= length: raise ValueError('Crossfade must cover at least two samples and less than half the trimmed clip')
            curve = 'tri' if loop_curve == 'linear' else 'qsin'
            graph = (f'[0:a]asplit=3[b][t][h];[b]atrim=start_sample={overlap}:end_sample={length-overlap},asetpts=PTS-STARTPTS[body];'
                     f'[t]atrim=start_sample={length-overlap}:end_sample={length},asetpts=PTS-STARTPTS[tail];'
                     f'[h]atrim=start_sample=0:end_sample={overlap},asetpts=PTS-STARTPTS[head];'
                     f'[tail][head]acrossfade=ns={overlap}:c1={curve}:c2={curve}[blend];[body][blend]concat=n=2:v=0:a=1[out]')
            looped = folder/'looped.wav'; execute(['-i', str(prepared), '-filter_complex', graph, '-map', '[out]', '-c:a', 'pcm_f32le', str(looped)])
            prepared = looped; measured = inspect_audio(prepared, loudness=False)
            notes.append('Loop overlap shortens the clip and rotates its start; it does not establish musical or perceptual continuity')
        filters = []
        for value, direction in ((fade_in, 'in'), (fade_out, 'out')):
            if value > measured['duration']: raise ValueError('Fade duration exceeds the prepared clip')
            if value:
                length = max(1, round(value*rate)); start = 0 if direction == 'in' else measured['frames']-length
                filters.append(f'afade=t={direction}:ss={start}:ns={length}:curve=tri')
        if filters:
            faded = folder/'faded.wav'; execute(['-i', str(prepared), '-af', ','.join(filters), '-c:a', 'pcm_f32le', str(faded)]); prepared = faded
        prepared_report = inspect_audio(prepared)
        meter = prepared_report['loudness']; filters = []
        if peak_db is not None:
            if meter['true_peak_db'] is None: raise ValueError('Cannot measure true peak for this input')
            gain = peak_db-meter['true_peak_db']; filters = [f'volume={gain:.9f}dB']
            normalization = {'method': 'measured_true_peak_constant_gain', 'gain_db': gain, 'target_true_peak_db': peak_db}
        elif lufs is not None:
            if meter['integrated_lufs'] is None or meter['true_peak_db'] is None: raise ValueError('Integrated loudness is undefined for this clip; use explicit peak normalization or a longer clip')
            gain = lufs-meter['integrated_lufs']; predicted_peak = meter['true_peak_db']+gain
            if predicted_peak <= true_peak_db+.05:
                filters = [f'volume={gain:.9f}dB']; normalization = {'method': 'measured_lufs_constant_gain', 'gain_db': gain, 'target_lufs': lufs, 'true_peak_ceiling_db': true_peak_db}
            elif not allow_dynamic:
                raise ValueError('The LUFS target would exceed the true-peak ceiling with constant gain; lower the target or explicitly allow dynamic normalization')
            else:
                lra = min(50., max(11., meter['loudness_range_lu'] or 0.))
                raw = _loudness(prepared,target_lufs=lufs,target_peak=true_peak_db,target_lra=lra)['raw']
                filters = [f"loudnorm=I={lufs}:TP={true_peak_db}:LRA={lra}:measured_I={raw['input_i']}:measured_TP={raw['input_tp']}:measured_LRA={raw['input_lra']}:measured_thresh={raw['input_thresh']}:offset={raw['target_offset']}:linear=false"]
                normalization = {'method': 'two_pass_dynamic_loudnorm', 'target_lufs': lufs, 'true_peak_ceiling_db': true_peak_db, 'lra': lra, 'measurement_pass':raw}
                notes.append('Dynamic loudness normalization can alter transients and dynamics')
        if not filters and prepared_report['over_range_samples'] and settings['codec'] != 'pcm_f32le': raise ValueError('Normalize over-range float audio before integer or lossy delivery encoding')
        def encode(target,active_filters):
            nonlocal encoder_details
            if settings['codec']=='libvorbis':
                if not IMAGE_PYTHON.is_file():raise ValueError('Vorbis encoding requires the project backend; run cgc media setup')
                delivery=prepared
                if active_filters:
                    delivery=folder/(target.stem+'-normalized.wav')
                    execute(['-i',str(prepared),'-af',','.join(active_filters),'-ar',str(rate),'-ac',str(channel_count),'-c:a','pcm_f32le',str(delivery)])
                command=[str(IMAGE_PYTHON),str(Path(__file__).with_name('media_vorbis_worker.py')),str(delivery),str(target)]
                commands.append(command);encoder_details=json.loads(_run(command).stdout)
            else:
                active=[*active_filters,'aresample=dither_method=triangular'] if settings['codec']=='pcm_s16le' else active_filters
                arguments=['-i',str(prepared),'-map','0:a:0']
                if active:arguments+=['-af',','.join(active)]
                execute([*arguments,'-ar',str(rate),'-ac',str(channel_count),'-c:a',settings['codec'],str(target)])
        dynamic=bool(normalization and normalization['method']=='two_pass_dynamic_loudnorm')
        offset=float(normalization['measurement_pass']['target_offset']) if dynamic else 0.
        if dynamic:normalization['verified_attempts']=[]
        for attempt in range(3 if dynamic else 1):
            final=folder/(f'finished-{attempt}'+settings['suffix']);encode(final,filters)
            after=inspect_audio(final);actual_lufs=(after.get('loudness') or {}).get('integrated_lufs')
            if dynamic:normalization['verified_attempts'].append({'offset_db':offset,'integrated_lufs':actual_lufs,'true_peak_db':after['loudness']['true_peak_db']})
            if not dynamic or actual_lufs is None or abs(actual_lufs-lufs)<=.5:break
            offset=_number(offset+lufs-actual_lufs,-99,99,'Dynamic correction offset')
            raw=normalization['measurement_pass'];lra=normalization['lra']
            filters=[f"loudnorm=I={lufs}:TP={true_peak_db}:LRA={lra}:measured_I={raw['input_i']}:measured_TP={raw['input_tp']}:measured_LRA={raw['input_lra']}:measured_thresh={raw['input_thresh']}:offset={offset}:linear=false"]
        if not after['finite'] or after['sample_peak'] == 0: raise ValueError('The output failed decoding or finite/non-silent checks')
        if after['sample_rate'] != rate or after['channels'] != channel_count: raise ValueError('Output rate/channels differ from the requested settings')
        if after['over_range_samples'] and settings['codec'] != 'pcm_f32le': raise ValueError('Encoded output exceeds full scale')
        if lufs is not None and (actual_lufs is None or abs(actual_lufs-lufs)>.5): raise ValueError('Output loudness missed the target by more than 0.5 LU; no file was committed')
        ceiling = peak_db if peak_db is not None else true_peak_db
        checks = check_audio(after, peak_ceiling_db=ceiling, loop=bool(loop_crossfade), allow_float_headroom=settings['codec']=='pcm_f32le')
        if normalization and after['loudness']['true_peak_db'] is not None and after['loudness']['true_peak_db'] > ceiling+.3:
            raise ValueError('Encoded output exceeds the requested true-peak ceiling; no file was committed')
        if _hash(source) != before['sha256']: raise ValueError('Source changed during finishing')
        os.link(final, output)
    after['path'] = str(output)
    if channel_count != before['channels']: notes.append('Channel conversion changes the mix; audition spatial and phase behavior')
    if rate > before['sample_rate']: notes.append('Upsampling changes delivery format but does not recover source bandwidth')
    if settings['lossy']: notes.append('The delivery file is lossy; retain the original and a lossless master')
    report = {'status': 'completed', 'operation': 'media.audio', 'source': before, 'output': after, 'profile': profile, 'normalization': normalization,
              'requested':{'sample_rate':sample_rate,'channels':channels,'trim_start':trim_start,'trim_end':trim_end,'fade_in':fade_in,'fade_out':fade_out,'loop_crossfade':loop_crossfade,'loop_curve':loop_curve,'lufs':lufs,'peak_db':peak_db,'true_peak_db':true_peak_db,'allow_dynamic':allow_dynamic},
              'processing_order': ['trim', 'sample_rate_and_channels', 'loop_overlap', 'fades', 'normalization', 'delivery_encode'],
              'loop': {'crossfade_seconds': loop_crossfade, 'curve': loop_curve, 'playback_loop_start_frame': 0, 'playback_loop_end_frame_exclusive': after['frames'], 'sample_rate': rate, 'metadata_embedded': False},
              'checks': checks, 'notes': notes, 'commands': commands, 'encoder_details':encoder_details,'ffmpeg_version': _run([_tool('ffmpeg'), '-version']).stdout.splitlines()[0]}
    with Path(str(output)+'.quality.json').open('x') as receipt: json.dump(report, receipt, indent=2, allow_nan=False)
    return report


def setup_image_backend():
    uv = shutil.which('uv')
    if not uv: raise ValueError('uv is required for the project-scoped image backend')
    environment = ROOT/'.backends/media'
    if not IMAGE_PYTHON.exists(): _run([uv, 'venv', '--python', '3.13', str(environment)])
    packages=['Pillow==12.2.0','numpy==2.3.4','soundfile==0.13.1']
    _run([uv, 'pip', 'install', '--python', str(IMAGE_PYTHON), *packages])
    return {'status': 'installed', 'path': str(environment), 'packages': packages, 'models_downloaded': False}


def _image_request(request):
    if not IMAGE_PYTHON.is_file(): raise ValueError('Image finishing requires the project backend; run cgc media setup')
    result = _run([str(IMAGE_PYTHON), str(Path(__file__).with_name('media_image_worker.py')), '--request', json.dumps(request)], timeout=600)
    return json.loads(result.stdout)


def inspect_image(path, *, role='color'):
    return _image_request({'operation': 'inspect', 'source': str(_source(path)), 'role': role})


def process_image(source, output, **options):
    return _image_request({'operation': 'process', 'source': str(_source(source)), 'output': str(Path(output).expanduser().resolve()), **options})


def pack_image(output, **options):
    return _image_request({'operation':'pack','output':str(Path(output).expanduser().resolve()),**options})


def extract_channel(source,output, *, channel='r',invert=False):
    return _image_request({'operation':'channel','source':str(_source(source)),'output':str(Path(output).expanduser().resolve()),'channel':channel,'invert':invert})


def inspect_media(path, *, kind=None, role='color', **audio_options):
    path = _source(path)
    kind = kind or ('audio' if path.suffix.lower() in AUDIO_SUFFIXES else 'image' if path.suffix.lower() in IMAGE_SUFFIXES else None)
    if kind == 'audio': return inspect_audio(path, **audio_options)
    if kind == 'image': return inspect_image(path, role=role)
    raise ValueError('Choose --kind audio or image for this file')


def add_parser(subparsers):
    media = subparsers.add_parser('media', help='Inspect, check, and finish local audio/images without generation models')
    actions = media.add_subparsers(dest='media_action', required=True)
    for action in ('setup', 'inspect', 'check', 'audio', 'image', 'pack', 'channel'):
        command = actions.add_parser(action)
        command.add_argument('--json', action='store_true')
        if action == 'setup': continue
        if action == 'pack':
            command.add_argument('--output','-o',required=True)
            command.add_argument('--layout',choices=('orm','unity-metallic','unity-hdrp-mask'),required=True)
            for scalar in ('occlusion','roughness','metallic','detail'):
                command.add_argument('--'+scalar)
                command.add_argument('--'+scalar+'-channel',choices=('r','g','b','a'),default='r')
            continue
        command.add_argument('--input', required=True)
        if action == 'channel':
            command.add_argument('--output','-o',required=True)
            command.add_argument('--channel',choices=('r','g','b','a'),required=True)
            command.add_argument('--invert',action='store_true')
            continue
        if action in ('inspect', 'check'):
            command.add_argument('--kind', choices=('audio', 'image'))
            command.add_argument('--role', default='color')
            command.add_argument('--no-loudness', action='store_true')
            command.add_argument('--loop', action='store_true')
            command.add_argument('--peak-ceiling-db', type=float, default=-1.)
            command.add_argument('--seam-ceiling-db', type=float, default=-50.)
            command.add_argument('--max-silence-fraction', type=float)
            if action == 'check': command.add_argument('--strict',action='store_true',help='Treat review findings as a failed acceptance check')
        elif action == 'audio':
            command.add_argument('--output', '-o', required=True)
            command.add_argument('--profile', choices=tuple(PROFILES), default='master')
            command.add_argument('--sample-rate', type=int)
            command.add_argument('--channels', type=int)
            command.add_argument('--trim-start', type=float, default=0.)
            command.add_argument('--trim-end', type=float)
            command.add_argument('--fade-in', type=float, default=0.)
            command.add_argument('--fade-out', type=float, default=0.)
            command.add_argument('--loop-crossfade', type=float, default=0.)
            command.add_argument('--loop-curve', choices=('linear', 'equal-power'), default='linear')
            command.add_argument('--lufs', type=float)
            command.add_argument('--peak-db', type=float)
            command.add_argument('--true-peak-db', type=float, default=-1.)
            command.add_argument('--allow-dynamic', action='store_true')
        else:
            command.add_argument('--output', '-o', required=True)
            command.add_argument('--role', default='color')
            command.add_argument('--color-action', choices=('preserve', 'to-srgb'), default='preserve')
            command.add_argument('--assume-srgb', action='store_true')
            command.add_argument('--max-size', type=int)
            command.add_argument('--flip-green', action='store_true')
            command.add_argument('--strip-color-tags', action='store_true')
    return media


def handle(args):
    action = args.media_action
    if action == 'setup': return setup_image_backend()
    if action == 'pack':
        inputs={name:{'path':str(_source(getattr(args,name))),'channel':getattr(args,name+'_channel')} for name in ('occlusion','roughness','metallic','detail') if getattr(args,name)}
        return pack_image(args.output,layout=args.layout,inputs=inputs)
    if action == 'channel':return extract_channel(args.input,args.output,channel=args.channel,invert=args.invert)
    if action in ('inspect', 'check'):
        result = inspect_media(args.input, kind=args.kind, role=args.role, loudness=not args.no_loudness)
        if action == 'inspect': return result
        checks = check_audio(result, peak_ceiling_db=args.peak_ceiling_db, loop=args.loop, seam_ceiling_db=args.seam_ceiling_db, max_silence_fraction=args.max_silence_fraction) if result['kind'] == 'audio' else result['checks']
        if getattr(args,'strict',False) and checks['status']=='review':checks={**checks,'status':'failed','review_required':True,'strict':True}
        return {'status': checks['status'], 'media': result, 'checks': checks}
    if action == 'audio':
        keys = ('profile','sample_rate','channels','trim_start','trim_end','fade_in','fade_out','loop_crossfade','loop_curve','lufs','peak_db','true_peak_db','allow_dynamic')
        return process_audio(args.input, args.output, **{key:getattr(args,key) for key in keys})
    keys = ('role','color_action','assume_srgb','max_size','flip_green','strip_color_tags')
    return process_image(args.input, args.output, **{key:getattr(args,key) for key in keys})


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m cgc.media_quality')
    add_parser(parser.add_subparsers(dest='command', required=True))
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != 'media': arguments.insert(0, 'media')
    try:
        report = handle(parser.parse_args(arguments)); print(json.dumps(report, indent=2, allow_nan=False))
        return 2 if report.get('status') == 'failed' else 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status':'failed','error':str(error)})); return 2


if __name__ == '__main__': raise SystemExit(main())
