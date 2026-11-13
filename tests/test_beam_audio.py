import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

from cgc.beam_audio import main as beam_main
from cgc.beam_audio_worker import MODELS, wav_info, validate_request
from cgc.cli import main
from cgc.planning import UserError, build_plan
from cgc.runtime import preflight, run, setup_commands


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000)
        f.writeframes(b'\x01\x00' * 2400)
    return stream.getvalue()


class BeamPlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def plan(self, operation='audio.speak', **opts):
        return build_plan(operation, {'prompt': 'Hello world.', **opts}, self.root)

    def test_default_speech_is_remote(self):
        p = self.plan()
        self.assertEqual(p.backend, 'beam'); self.assertEqual(p.model, 'phonon')
        self.assertIn('/beam/bin/python', p.command[0]); self.assertIn('--text', p.command)
        self.assertIn('sends', ' '.join(p.warnings).lower().replace('are sent', 'sends'))
        self.assertFalse((self.root / 'outputs').exists())

    def test_design_default_is_5090(self):
        p = self.plan('audio.design', direction='Warm adult narrator')
        self.assertEqual(p.backend, 'beam'); self.assertEqual(p.parameters['gpu'], 'RTX5090')
        self.assertEqual(p.parameters['remote_precision'], 'BF16')

    def test_local_override_preserves_mlx(self):
        p = self.plan(backend='local')
        self.assertEqual(p.backend, 'audio'); self.assertIn('mlx_audio.tts.generate', p.command)
        self.assertNotIn('Beam', ' '.join(p.warnings))

    def test_other_audio_models_remain_local(self):
        p = self.plan(model='kokoro')
        self.assertEqual(p.backend, 'audio')
        with self.assertRaises(UserError): self.plan(model='kokoro', backend='beam')

    def test_remote_phonon_does_not_silently_ignore_voice(self):
        with self.assertRaises(UserError): self.plan(voice='custom.npy')
        self.assertEqual(self.plan(voice='custom.npy', backend='local').backend, 'audio')

    def test_blank_direction_rejected_before_launch(self):
        with self.assertRaises(UserError): self.plan('audio.design', direction='   ')

    def test_length_and_backend_validation(self):
        for opts in ({'prompt': 'a' * 2001}, {'backend': 'bogus'}, {'backend': 10}):
            with self.assertRaises(UserError): self.plan(**opts)

    def test_remote_clone_consent_and_reference(self):
        ref = self.root / 'ref.wav'; ref.write_bytes(wav_bytes())
        with self.assertRaises(UserError): self.plan('audio.clone', reference=str(ref), transcript='Hello')
        p = self.plan('audio.clone', reference=str(ref), transcript='Hello', consent=True)
        self.assertIn('--consent', p.command); self.assertIn(str(ref.resolve()), p.command)

    def test_beam_receipt_collision(self):
        out = self.root / 'old.wav'; out.with_suffix('.wav.beam.json').write_text('{}')
        with self.assertRaises(UserError): self.plan(output=str(out))

    def test_setup_is_pinned_and_not_model_download(self):
        cmds = setup_commands('beam', self.root)
        self.assertIn('beam-client==0.2.211', cmds[-1]); self.assertIn('beta9==0.1.268', cmds[-1])

    def test_batch_local_override(self):
        brief = self.root / 'brief.json'
        brief.write_text(json.dumps({'version': 1, 'jobs': [{'operation': 'audio.speak', 'prompt': 'Hello'}]}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['batch', str(brief), '--backend', 'local', '--dry-run', '--json'])
        self.assertEqual(code, 0); self.assertEqual(json.loads(out.getvalue())[0]['backend'], 'audio')


class BeamRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = build_plan('audio.speak', {'prompt': 'Hello', 'output': str(self.root / 'out.wav')}, self.root)

    def test_remote_success_receipt_has_actual_model(self):
        def invoke(*a, **kw):
            output = Path(self.plan.output); data = wav_bytes(); output.write_bytes(data)
            output.with_suffix('.wav.beam.json').write_text(json.dumps({'artifact': wav_info(data),
                'model_repository': MODELS['phonon'][0], 'model_revision': MODELS['phonon'][1],
                'precision': 'Q8', 'device': 'CPU', 'task_id': 'test-task'}))
            return subprocess.CompletedProcess(a[0], 0)
        with patch('cgc.runtime.preflight'), patch('cgc.runtime.subprocess.run', side_effect=invoke):
            result = run(self.plan, self.root, quiet=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['remote']['task_id'], 'test-task')
        self.assertNotIn('weights_gb', result['model_details'])
        self.assertEqual(result['model_snapshot']['revision'], MODELS['phonon'][1])

    def test_timeout_records_uncertain_and_raises_usererror(self):
        with patch('cgc.runtime.preflight'), patch('cgc.runtime.subprocess.run', side_effect=subprocess.TimeoutExpired('beam', 1800)):
            with self.assertRaisesRegex(UserError, 'remote outcome is unknown'): run(self.plan, self.root, quiet=True)
        receipt = json.loads(Path(self.plan.output + '.json').read_text())
        self.assertEqual(receipt['status'], 'remote_outcome_unknown')
        self.assertFalse(list(self.root.glob('.cgc-receipt-*')))

    def test_interrupt_does_not_claim_remote_cancellation(self):
        with patch('cgc.runtime.preflight'), patch('cgc.runtime.subprocess.run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): run(self.plan, self.root, quiet=True)
        self.assertEqual(json.loads(Path(self.plan.output + '.json').read_text())['status'], 'remote_outcome_unknown')

    def test_nonzero_is_not_automatically_retried(self):
        with patch('cgc.runtime.preflight'), patch('cgc.runtime.subprocess.run', return_value=subprocess.CompletedProcess([], 1)) as invoke:
            with self.assertRaises(UserError): run(self.plan, self.root, quiet=True)
        self.assertEqual(invoke.call_count, 1)

    def test_remote_preflight_accepts_non_mac(self):
        executable = Path(self.plan.command[0]); executable.parent.mkdir(parents=True); executable.touch()
        with patch('cgc.runtime.platform.system', return_value='Linux'):
            preflight(self.plan, self.root)

    def test_wav_payload_must_be_complete(self):
        with self.assertRaises(ValueError): wav_info(wav_bytes()[:-10])

    def test_invalid_reference_fails_before_remote(self):
        ref = self.root / 'ref.wav'; ref.write_bytes(wav_bytes()[:-10])
        p = build_plan('audio.clone', {'prompt':'new','reference':str(ref),'transcript':'old','consent':True}, self.root)
        executable = Path(p.command[0]); executable.parent.mkdir(parents=True); executable.touch()
        with self.assertRaises(UserError): preflight(p, self.root)


class BeamInputTests(unittest.TestCase):
    def test_unused_reference_rejected_before_upload(self):
        for operation, model in (('audio.speak', 'phonon'), ('audio.design', 'voxcpm2')):
            with self.assertRaises(ValueError):
                validate_request({'operation': operation, 'model': model, 'text': 'Hello',
                                  'direction': 'Warm' if model == 'voxcpm2' else None,
                                  'reference_bytes': wav_bytes()})

    def test_missing_or_blank_direction_rejected(self):
        for direction in (None, '', '   '):
            with self.assertRaises(ValueError):
                validate_request({'operation': 'audio.design', 'model': 'voxcpm2',
                                  'text': 'Hello', 'direction': direction})

    def test_clone_requires_consent_and_transcript_before_upload(self):
        for consent, transcript in ((False, 'hello'), (True, None), (True, '  ')):
            with self.assertRaises(ValueError):
                validate_request({'operation': 'audio.clone', 'model': 'voxcpm2', 'text': 'Hello',
                                  'reference_bytes': wav_bytes(), 'speaker_consent': consent,
                                  'transcript': transcript})

    def test_phonon_direction_not_ignored(self):
        with self.assertRaises(ValueError):
            validate_request({'operation': 'audio.speak', 'model': 'phonon', 'text': 'Hello', 'direction': 'Warm'})


class BeamStagingTests(unittest.TestCase):
    def test_repeated_invocation_stages_only_worker_and_resolves_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); ref = root / 'ref.wav'; ref.write_bytes(wav_bytes())
            initial_cwd = Path.cwd(); stages = []; calls = []
            original = types.ModuleType('beam_audio_worker')
            def decorate(**config):
                self.assertEqual(config['retries'], 0); self.assertFalse(config['headless'])
                self.assertEqual(config['gpu'], 'RTX5090')
                stage = Path.cwd(); stages.append(stage)
                self.assertEqual(set(p.name for p in stage.iterdir()) - {'__pycache__'}, {'beam_audio_worker.py', '.beamignore'})
                self.assertEqual((stage / '.beamignore').read_text(), '*\n!beam_audio_worker.py\n')
                def wrap(fn):
                    self.assertEqual(Path(sys.modules[fn.__module__].__file__).parent, stage)
                    def remote(**args):
                        calls.append(args['request']); data = wav_bytes()
                        return {'audio': data, 'report': {'artifact': wav_info(data)}}
                    return types.SimpleNamespace(remote=remote)
                return wrap
            sdk = types.SimpleNamespace(Image=lambda **kw: kw, function=decorate)
            try:
                import os
                os.chdir(root)
                with patch.dict(sys.modules, {'beam': sdk, 'beam_audio_worker': original}), contextlib.redirect_stdout(io.StringIO()):
                    for n in (1, 2):
                        self.assertEqual(beam_main(['--model','voxcpm2','--operation','audio.clone','--text','Hello',
                            '--reference','ref.wav','--transcript','Original','--consent','--output',f'out{n}.wav']), 0)
                        self.assertIs(sys.modules['beam_audio_worker'], original)
                        self.assertEqual(Path.cwd(), root)
                self.assertEqual(calls[0]['reference_bytes'], ref.read_bytes())
                self.assertNotEqual(stages[0], stages[1]); self.assertTrue(all(not p.exists() for p in stages))
            finally:
                os.chdir(initial_cwd)

if __name__ == '__main__': unittest.main()
