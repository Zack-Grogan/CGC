"""Qwen decode memory controls and terminal failed-session containment, no GPU."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from cgc import remote_client, remote_worker


class QwenMemoryRecovery(unittest.TestCase):
    def test_native_spatial_tiling_and_batch_slicing_preserve_canvas_controls(self):
        calls = []
        class VAE:
            # Signature verified against the deployed Diffusers revision.
            def enable_tiling(self, tile_sample_min_height=None, tile_sample_min_width=None,
                              tile_sample_stride_height=None, tile_sample_stride_width=None):
                calls.append(('tiles', tile_sample_min_height, tile_sample_min_width, tile_sample_stride_height, tile_sample_stride_width))
            def enable_slicing(self):
                calls.append(('slicing',))
        controls = remote_worker.configure_qwen_memory(types.SimpleNamespace(vae=VAE()))
        self.assertEqual(calls, [('tiles', 256, 256, 192, 192), ('slicing',)])
        self.assertFalse(controls['canvas_reduced'])
        request = {'width': 2048, 'height': 2048, 'steps': 40}
        self.assertEqual(remote_worker.effective_controls('qwen-image-2.1', request)['width'], 2048)
        self.assertEqual(remote_worker.effective_controls('qwen-image-2.1', request)['height'], 2048)

    def test_oom_clears_vae_cache_hooks_and_blocks_reuse_without_retry(self):
        class OutOfMemoryError(RuntimeError):
            pass
        original = OutOfMemoryError('CUDA out of memory during VAE decode')
        events = []; cache = [object()]
        class Pipe:
            vae = types.SimpleNamespace(clear_cache=lambda: (cache.clear(), events.append('vae_clear')))
            def maybe_free_model_hooks(self):
                events.append('offload')
                raise RuntimeError('a failed hook must not mask the original OOM')
        state = {'pipe': Pipe(), 'session': 'warm-session'}
        context = types.SimpleNamespace(on_start_value=state)
        torch = types.SimpleNamespace(cuda=types.SimpleNamespace(empty_cache=lambda: events.append('empty_cuda')))
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.dict(os.environ, CGC_PROFILE='qwen-image-2.1'), patch.dict(sys.modules, torch=torch), \
                     patch.object(remote_worker, '_generate', side_effect=original) as generate:
                    with self.assertRaises(OutOfMemoryError) as raised:
                        remote_worker.generate(context, {'id': 'paidonce'})
                    self.assertIs(raised.exception, original)
                    with self.assertRaisesRegex(RuntimeError, 'quarantined'):
                        remote_worker.generate(context, {'id': 'nextrequest'})
                    self.assertEqual(generate.call_count, 1)
                failure = json.loads(Path('results/paidonce/failure.json').read_text())
                self.assertFalse(failure['retry_performed']); self.assertEqual(failure['session'], 'warm-session')
                self.assertEqual(failure['cleanup'][1]['status'], 'failed')
            finally:
                os.chdir(previous)
        self.assertEqual(cache, []); self.assertEqual(events, ['vae_clear', 'offload', 'empty_cuda'])
        self.assertIsNone(state['pipe'])

    def test_successful_requests_keep_the_same_warm_pipeline(self):
        pipe = object(); state = {'pipe': pipe}; context = types.SimpleNamespace(on_start_value=state)
        with patch.object(remote_worker, '_generate', return_value={'status': 'completed'}) as generate, \
             patch.object(remote_worker, 'quarantine_qwen_failure') as quarantine:
            remote_worker.generate(context, {}); remote_worker.generate(context, {})
        self.assertEqual(generate.call_count, 2); quarantine.assert_not_called(); self.assertIs(state['pipe'], pipe)

    def test_only_terminal_failed_container_can_be_retired(self):
        with patch('cgc.remote_client.subprocess.run', return_value=types.SimpleNamespace(returncode=0, stdout='', stderr='')) as stop:
            with self.assertRaisesRegex(ValueError, 'terminal'):
                remote_client.retire_failed_worker({'status': 'RUNNING', 'container_id': 'live'}, 'active')
            stop.assert_not_called()
            result = remote_client.retire_failed_worker({'status': 'ERROR', 'container_id': 'failed-worker'}, 'failed-task')
            self.assertEqual(result['status'], 'retired')
            self.assertEqual(stop.call_args.args[0][-3:], ['container', 'stop', 'failed-worker'])
            self.assertEqual(result['task_id'], 'failed-task')

    def test_same_model_failed_lease_is_retired_before_next_admission(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CGC_STATE_DIR=directory):
            lease = Path(directory)/'gpu-session.json'
            lease.write_text(json.dumps({'task_id': 'failed', 'profile': 'qwen-image-2.1', 'runtime_id': 'same-code'}))
            data = {'status': 'ERROR', 'container_id': 'poisoned'}
            requests = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: data))
            with patch.dict(sys.modules, requests=requests), patch('cgc.remote_client.subprocess.run', return_value=types.SimpleNamespace(returncode=0, stdout='', stderr='')) as stop:
                lock, _ = remote_client.acquire_gpu('qwen-image-2.1', 'not-printed', 'same-code'); lock.close()
                self.assertEqual(stop.call_count, 1)
                self.assertEqual(json.loads(lease.read_text())['worker_retirement']['status'], 'retired')
                data.pop('container_id')  # Some provider responses omit the already-removed container.
                lock, _ = remote_client.acquire_gpu('qwen-image-2.1', 'not-printed', 'same-code'); lock.close()
                self.assertEqual(stop.call_count, 1)

    def test_failed_retirement_blocks_admission_and_preserves_failed_identity(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CGC_STATE_DIR=directory):
            lease = Path(directory)/'gpu-session.json'
            lease.write_text(json.dumps({'task_id': 'failed', 'profile': 'qwen-image-2.1', 'runtime_id': 'same-code'}))
            requests = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'status': 'ERROR', 'container_id': 'poisoned'}))
            with patch.dict(sys.modules, requests=requests), patch('cgc.remote_client.subprocess.run', return_value=types.SimpleNamespace(returncode=1, stdout='', stderr='unavailable')):
                for profile in ('qwen-image-2.1', 'cooldown'):
                    with self.subTest(profile=profile), self.assertRaisesRegex(RuntimeError, 'retired before dispatch'):
                        remote_client.acquire_gpu(profile, 'not-printed', 'same-code')
            retained = json.loads(lease.read_text())
            self.assertEqual(retained['task_id'], 'failed'); self.assertEqual(retained['worker_retirement']['status'], 'failed')

    def test_controller_records_terminal_failure_retires_exact_worker_and_never_resubmits(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CGC_STATE_DIR=str(Path(directory)/'state')):
            output = Path(directory)/'result.png'; accepted = []; stopped = []
            class Image:
                def __init__(self, **kwargs): self.image_id = kwargs.get('image_id', 'fixed')
                def add_commands(self, *args): return self
            def task_queue(**kwargs):
                self.assertEqual(kwargs['retries'], 0)
                class Remote:
                    def put(self, **arguments): accepted.append(arguments); return types.SimpleNamespace(id='paid-once')
                return lambda function: Remote()
            beam = types.ModuleType('beam'); beam.Image = Image; beam.Volume = lambda **kwargs: None
            beam.task_queue = task_queue; beam.QueueDepthAutoscaler = lambda **kwargs: kwargs
            config = types.ModuleType('beta9.config'); config.get_config_context = lambda: types.SimpleNamespace(token='not-printed')
            requests = types.ModuleType('requests'); requests.get = lambda *a, **k: types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'status': 'ERROR', 'container_id': 'failed-exact-container'})
            def command(arguments, **kwargs):
                if arguments[1:3] == ['container', 'stop']: stopped.append(arguments[-1])
                return types.SimpleNamespace(returncode=0, stdout='', stderr='')
            plan = {'model': 'qwen-image-2.1', 'output': str(output), 'prompt': '2048 marine', 'seed': 42, 'parameters': {'width': 2048, 'height': 2048}}
            try:
                with patch.dict(sys.modules, {'beam': beam, 'beta9.config': config, 'requests': requests}), \
                     patch('cgc.remote_client.subprocess.run', side_effect=command), contextlib.redirect_stdout(io.StringIO()), \
                     patch.object(sys, 'argv', ['client', '--plan', json.dumps(plan)]):
                    with self.assertRaisesRegex(RuntimeError, 'Beam task ended: ERROR'):
                        remote_client.main()
                    with self.assertRaisesRegex(RuntimeError, 'Beam task ended: ERROR'):
                        remote_client.main()
            finally:
                sys.modules.pop('remote_worker', None)
            self.assertEqual(len(accepted), 1); self.assertTrue(all(item == 'failed-exact-container' for item in stopped))
            record = json.loads(Path(str(output)+'.remote.json').read_text())
            self.assertEqual(record['status'], 'ERROR'); self.assertEqual(record['task_id'], 'paid-once')
            self.assertEqual(record['container_id'], 'failed-exact-container'); self.assertEqual(record['worker_retirement']['status'], 'retired')
            self.assertIn('worker_bundle_sha256', record)


if __name__ == '__main__': unittest.main()
