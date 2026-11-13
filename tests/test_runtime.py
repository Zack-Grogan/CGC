import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cgc.cli import main
from cgc.planning import Plan, UserError, build_plan
from cgc.runtime import doctor, history, run
import subprocess

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def plan(self,script):
        output=self.root/'out.png'
        return Plan('image.generate','klein','image',[sys.executable,'-c',script],str(output),'fixture',42,False,[],{})

    def test_success_has_manifest_and_log(self):
        output=self.root/'out.png'
        p=self.plan(f"from pathlib import Path; print('fixture backend'); Path({str(output)!r}).write_bytes(b'\\x89PNG\\r\\n\\x1a\\n'+b'0'*40)")
        with patch('cgc.runtime.preflight'):
            r=run(p,self.root,quiet=True)
        self.assertEqual(r['status'],'completed')
        self.assertEqual(r['backend_exit_code'],0)
        self.assertGreater(r['output_bytes'],32)
        self.assertEqual(json.loads((self.root/'out.png.json').read_text())['status'],'completed')
        self.assertIn('fixture backend',(self.root/'out.png.log').read_text())

    def test_zero_exit_without_output_is_failure(self):
        p=self.plan("print('model failed but upstream swallowed it')")
        with patch('cgc.runtime.preflight'):
            with self.assertRaises(UserError):run(p,self.root,quiet=True)
        self.assertEqual(json.loads((self.root/'out.png.json').read_text())['status'],'failed')

    def test_nonzero_exit_receipt(self):
        p=self.plan('raise SystemExit(7)')
        with patch('cgc.runtime.preflight'):
            with self.assertRaises(UserError):run(p,self.root,quiet=True)
        r=json.loads((self.root/'out.png.json').read_text())
        self.assertEqual(r['backend_exit_code'],7)
        self.assertEqual(r['status'],'failed')

    def test_batch_partial_json_keeps_receipts(self):
        path=self.root/'brief.json'
        path.write_text(json.dumps({'version':1,'jobs':[{'operation':'image.generate','prompt':'one'},{'operation':'image.generate','prompt':'two'}]}))
        out=io.StringIO()
        with patch('cgc.cli.run',side_effect=[{'status':'completed','test':'receipt'},UserError('second failed')]),contextlib.redirect_stdout(out):
            code=main(['batch',str(path),'--backend','local','--json'])
        data=json.loads(out.getvalue())
        self.assertEqual(code,2)
        self.assertEqual(data['failed_job'],2)
        self.assertEqual(data['completed'][0]['test'],'receipt')
        self.assertEqual(data['not_run'],0)

class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def plan(self,**kw):
        return build_plan('image.generate',{'prompt':'test',**kw},self.root)
    def test_strict_numbers(self):
        for kw in ({'steps':0},{'size':0},{'seed':True},{'width':512.0,'height':512}):
            with self.assertRaises(UserError):self.plan(**kw)
    def test_strict_strings(self):
        for field in ('voice','language','direction'):
            with self.assertRaises(UserError):
                build_plan('audio.speak',{'prompt':'test',field:123},self.root)
    def test_uppercase_output_rejected(self):
        with self.assertRaises(UserError):self.plan(output=str(self.root/'UPPER.PNG'))
    def test_log_collision_rejected(self):
        (self.root/'old.png.log').write_text('preserve')
        with self.assertRaises(UserError):self.plan(output=str(self.root/'old.png'))
    def test_qwen_quantized_edit_path_for_generate(self):
        p=self.plan(model='qwen-image-2.1',aspect='landscape')
        self.assertTrue(p.command[0].endswith('mflux-generate-qwen-2.1-edit'))
        self.assertEqual(p.parameters['width']%32,0)
        self.assertEqual(p.parameters['height']%32,0)
        self.assertIn('40',p.command)
        self.assertTrue(any('Restricted' in w for w in p.warnings))
    def test_fibo_turbo_edit_only(self):
        with self.assertRaises(UserError):self.plan(model='fibo2-edit')
    def test_flux3_defaults(self):
        p=self.plan(model='flux3')
        self.assertTrue(p.command[0].endswith('mflux-generate-flux3'))
        self.assertEqual(p.parameters['steps'],16)

class DiagnosticTests(unittest.TestCase):
    def test_history_skips_unrelated_json(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'outputs').mkdir()
            (root/'outputs'/'array.json').write_text('[]')
            (root/'outputs'/'partial.json').write_text('{"schema_version":1,"plan":{}}')
            self.assertEqual(history(root),[])

    def test_doctor_handles_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'.backends/image/bin/python';p.parent.mkdir(parents=True);p.touch()
            with patch('cgc.runtime.subprocess.run',side_effect=subprocess.TimeoutExpired('python',15)):
                result=doctor(root)
            self.assertFalse(result['backends']['image']['installed'])
            self.assertIn('error',result['backends']['image'])

class AudioReleaseTests(unittest.TestCase):
    def test_audio_seed_not_claimed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=build_plan('audio.speak',{'prompt':'hello'},root)
            self.assertIsNone(p.seed)
            self.assertNotIn('--seed',p.command)
            with self.assertRaises(UserError):
                build_plan('audio.speak',{'prompt':'hello','seed':1},root)

    def test_voxcpm_auto_language(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=build_plan('audio.design',{'prompt':'hello','model':'voxcpm2','direction':'Warm adult voice'},root)
            self.assertNotIn('--lang_code',p.command)
            self.assertNotIn('--voice',p.command)
            with self.assertRaises(UserError):
                build_plan('audio.design',{'prompt':'hello','model':'voxcpm2','direction':'Warm voice','language':'English'},root)

class ArtifactTests(unittest.TestCase):
    def test_png_metadata_and_hash(self):
        from cgc.runtime import artifact_info
        import hashlib,struct
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'image.png';payload=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',512,384)+b'\0'*16;p.write_bytes(payload)
            info=artifact_info(p)
            self.assertEqual((info['width'],info['height']),(512,384))
            self.assertEqual(info['sha256'],hashlib.sha256(payload).hexdigest())
    def test_tested_defaults_and_audio_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            p=build_plan('audio.speak',{'prompt':'hello','metrics':True,'backend':'local'},Path(d))
            self.assertEqual(p.model,'phonon');self.assertIn('--verbose',p.command)
            self.assertIn('default',p.command)
            p=build_plan('audio.design',{'prompt':'hello','direction':'warm adult voice'},Path(d))
            self.assertEqual(p.model,'voxcpm2')
            p=build_plan('image.generate',{'prompt':'a vase'},Path(d))
            self.assertEqual(p.model,'flux3')
            self.assertEqual(p.parameters['width'],1024)
