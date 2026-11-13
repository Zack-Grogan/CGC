"""Offline suite, cost and artifact checks; never starts remote compute."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch
from contextlib import redirect_stdout
import audio_smoke
import benchmark_suite
import flux3_smoke


class ExpandedSuiteTests(unittest.TestCase):
    def test_both_image_plans_same_workload(self):
        a, b = flux3_smoke.plan('RTX4090'), flux3_smoke.plan('RTX5090')
        for key in ['model', 'variant', 'prompt', 'seed', 'width', 'height', 'steps']:
            self.assertEqual(a[key], b[key])
        self.assertAlmostEqual(b['conservative_hourly_resource_usd'], 2.48248)

    def test_all_default_gpu_recipes_select_5090(self):
        self.assertEqual(flux3_smoke.plan()['gpu'], 'RTX5090')
        self.assertEqual(audio_smoke.plan()['gpu'], 'RTX5090')
        root = Path(__file__).parent
        for name in ('flux3_smoke.py', 'audio_smoke.py'):
            result = subprocess.run([sys.executable, '-S', str(root / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['gpu'], 'RTX5090')

    def test_legacy_4090_case_is_only_explicit(self):
        self.assertNotIn('image-4090', benchmark_suite.DEFAULT_CASES)
        self.assertNotIn('voxcpm2-4090', benchmark_suite.DEFAULT_CASES)
        case = benchmark_suite.CASES['voxcpm2-4090']
        self.assertEqual(case['config']['gpu'], 'RTX4090')
        self.assertEqual(case['args'][-2:], ['--gpu', 'RTX4090'])

    def test_probe_defaults_to_only_5090(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'probe.json'
            command = [sys.executable, '-S', str(Path(__file__).with_name('gpu_probe.py')), '--output', str(dest)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['gpus'], ['RTX5090'])
            self.assertFalse(dest.exists())
            result = subprocess.run(command + ['--gpu', 'RTX4090'], capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout)['gpus'], ['RTX4090'])

    def test_gpu_stacks_pin_cuda_12_8_compatible_torch(self):
        self.assertIn('torch==2.9.1', flux3_smoke.PACKAGES)
        self.assertIn('torchvision==0.24.1', flux3_smoke.PACKAGES)
        for dependency in ('torch==2.9.1', 'torchaudio==2.9.1', 'torchcodec==0.8.1'):
            self.assertIn(dependency, audio_smoke.PACKAGES['voxcpm2'])

    def test_total_price(self):
        p = benchmark_suite.suite_plan()
        self.assertEqual(list(p['cases']), ['image-5090', 'phonon-cpu', 'voxcpm2-5090'])
        self.assertEqual({c['gpu'] for c in p['cases'].values()}, {'RTX5090', None})
        self.assertAlmostEqual(p['combined_timeout_resource_estimate_usd'], 0.79469)

    def test_cpu_audio_has_no_gpu(self):
        p = audio_smoke.plan('phonon')
        self.assertIsNone(p['gpu'])
        self.assertEqual(p['timeout_seconds'], 300)
        self.assertIn('CPU', p['backend'])

    def test_audio_no_recording_upload(self):
        self.assertIn('none', audio_smoke.plan()['recording_uploads'])
        self.assertEqual(audio_smoke.plan()['retries'], 0)

    def test_every_plan_is_offline_without_site_packages(self):
        root = Path(__file__).parent
        for name in ['audio_smoke.py', 'benchmark_suite.py']:
            result = subprocess.run([sys.executable, '-S', str(root / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'not_run')

    def test_suite_requires_approval_before_sdk(self):
        result = subprocess.run([sys.executable, '-S', str(Path(__file__).with_name('benchmark_suite.py')), '--execute'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('recorded combined approval', result.stderr)

    def test_wav_validation_and_tamper(self):
        data = io.BytesIO()
        with wave.open(data, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b'\x01\x00' * 240)
        blob = data.getvalue()
        meta = audio_smoke.describe_wav(blob)
        self.assertEqual(meta['duration_seconds'], 0.01)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'phonon-speech.wav').write_bytes(blob)
            report = {'status': 'generated', 'artifacts': {'phonon-speech.wav': meta}}
            (p/'report.json').write_text(json.dumps(report))
            self.assertEqual(benchmark_suite.validate_receipt(p/'report.json'), report)
            (p/'phonon-speech.wav').write_bytes(blob + b'bad')
            with self.assertRaisesRegex(RuntimeError, 'digest'):
                benchmark_suite.validate_receipt(p/'report.json')

    def test_truncated_wav_is_rejected(self):
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b'\x01\x00' * 240)
        header_only = stream.getvalue()[:44]
        with self.assertRaisesRegex(RuntimeError, 'Truncated WAV'):
            audio_smoke.describe_wav(header_only)

    def _assert_client_failure_is_recorded(self, exception, expected):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'suite'
            argv = ['benchmark_suite.py', '--execute', '--approved-max-usd', '3',
                    '--output-dir', str(destination)]
            with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()), \
                 patch.object(benchmark_suite.subprocess, 'run', side_effect=exception) as run:
                self.assertEqual(benchmark_suite.main(), 1)
            self.assertEqual(run.call_count, 1, 'Must stop without retry or later paid cases')
            self.assertEqual(run.call_args.kwargs['timeout'], 1800)
            self.assertEqual(run.call_args.kwargs['env']['BETA9_SDK_TIMINGS'], '1')
            summary = json.loads((destination / 'summary.json').read_text())
            self.assertEqual(summary['status'], expected)
            self.assertTrue(summary['results'][0]['remote_state_verification_required'])
            self.assertNotIn('command_to_validated_completion_seconds', summary['results'][0])
            self.assertFalse((destination / 'summary.json.tmp').exists())

    def test_client_timeout_preserves_uncertain_outcome(self):
        self._assert_client_failure_is_recorded(subprocess.TimeoutExpired('recipe', 1800), 'client_timed_out')

    def test_client_interrupt_preserves_uncertain_outcome(self):
        self._assert_client_failure_is_recorded(KeyboardInterrupt(), 'client_interrupted')


if __name__ == '__main__':
    unittest.main()
