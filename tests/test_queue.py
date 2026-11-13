import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cgc import queue
from cgc.planning import Plan


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CGC_STATE_DIR': self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def plan(self):
        source = Path(self.tmp.name) / 'source.png'
        source.write_bytes(b'original reference')
        return Plan('image.edit', 'flux3', 'image', ['engine', str(source)], str(Path(self.tmp.name) / 'result.png'), 'edit', 42, False, [], {'references': [str(source)]})

    def test_snapshot_and_output_reservation(self):
        plan = self.plan()
        with patch('cgc.runtime.preflight'):
            job = queue.enqueue(plan)
            with self.assertRaisesRegex(ValueError,'reserved'):
                queue.enqueue(plan)
        Path(plan.parameters['references'][0]).write_bytes(b'changed')
        snapshot = job['plan']['parameters']['references'][0]
        self.assertEqual(Path(snapshot).read_bytes(), b'original reference')
        self.assertEqual(queue.get(job['id'])['state'], 'queued')

    def test_worker_records_completion(self):
        with patch('cgc.runtime.preflight'):
            job = queue.enqueue(self.plan())
        with patch('cgc.runtime.run', return_value={'status': 'completed'}) as run:
            queue.worker(once=True)
        self.assertEqual(queue.get(job['id'])['state'], 'completed')
        run.assert_called_once()

    def test_restart_does_not_repeat_uncertain_execution(self):
        with patch('cgc.runtime.preflight'):
            job = queue.enqueue(self.plan())
        queue.update(job['id'], 'running')
        with patch('cgc.runtime.run') as run:
            queue.worker(once=True)
        self.assertEqual(queue.get(job['id'])['state'], 'remote_outcome_unknown')
        run.assert_not_called()

    def test_pause_prevents_dispatch(self):
        with patch('cgc.runtime.preflight'):
            job = queue.enqueue(self.plan())
        queue.paused(True)
        with patch('cgc.runtime.run') as run:
            queue.worker(once=True)
        run.assert_not_called()
        self.assertEqual(queue.get(job['id'])['state'], 'queued')

    def test_import_key_returns_same_job(self):
        with patch('cgc.runtime.preflight'):
            plan=self.plan()
            first=queue.enqueue(plan,import_key='row-1')
            second=queue.enqueue(plan,import_key='row-1')
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(queue.listing()),1)

    def test_recovery_uses_known_remote_task_without_resubmission(self):
        from dataclasses import replace
        with patch('cgc.runtime.preflight'):
            job=queue.enqueue(replace(self.plan(),backend='remote'))
        Path(job['output']+'.remote.json').write_text('{"task_id":"known"}')
        queue.update(job['id'],'running')
        with patch('cgc.remote.run',return_value={'status':'completed'}) as recover:
            queue.worker(once=True)
        self.assertTrue(recover.call_args.kwargs['recover'])
        self.assertEqual(queue.get(job['id'])['state'],'completed')
