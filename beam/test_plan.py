"""Offline checks. These tests do not contact Beam or load model packages."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

SOURCE = Path(__file__).with_name('flux3_smoke.py')
spec = importlib.util.spec_from_file_location('flux3_smoke', SOURCE)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokePlanTests(unittest.TestCase):
    def test_plan_is_not_a_run(self):
        p = smoke.plan()
        self.assertEqual(p['status'], 'not_run')
        self.assertEqual(p['gpu'], 'RTX5090')
        self.assertEqual(p['retries'], 0)
        self.assertEqual(p['timeout_seconds'], 600)
        self.assertEqual(p['gpu_count'], 1)
        self.assertEqual(p['variant'], 'sdnq-int4')
        self.assertAlmostEqual(p['conservative_hourly_resource_usd'], 2.48248)
        self.assertLess(p['ten_minute_resource_estimate_usd'], 0.50)

    def test_default_is_offline_and_import_safe(self):
        code = "import runpy, sys; sys.argv = [%r]; runpy.run_path(%r, run_name='__main__')" % (str(SOURCE), str(SOURCE))
        # -S excludes site packages, so an accidental top-level Beam/model import fails.
        result = subprocess.run([sys.executable, '-S', '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'not_run')

    def test_execute_without_budget_stops_before_import(self):
        result = subprocess.run([sys.executable, '-S', str(SOURCE), '--execute'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('recorded Beam approval', result.stderr)

    def test_large_budget_is_not_silently_accepted(self):
        result = subprocess.run([sys.executable, '-S', str(SOURCE), '--execute', '--approved-max-usd', '20'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_prompt_matches_recorded_mac_benchmark(self):
        receipt = SOURCE.parent.parent / 'outputs' / 'benchmark-flux3-generate-1024.png.json'
        if not receipt.exists():
            self.skipTest('Mac comparison receipt is not present on this executor')
        recorded = json.loads(receipt.read_text())['plan']
        self.assertEqual(smoke.PROMPT, recorded['prompt'])
        for key in ['width', 'height', 'steps']:
            self.assertEqual(smoke.plan()[key], recorded['parameters'][key])
        self.assertEqual(smoke.SEED, recorded['seed'])

    def test_handler_is_top_level_for_beam_loader(self):
        module = ast.parse(SOURCE.read_text())
        self.assertIn('run_inference', {n.name for n in module.body if isinstance(n, ast.FunctionDef)})


if __name__ == '__main__':
    unittest.main()
