import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cgc.cli import main

class CliTests(unittest.TestCase):
    def invoke(self,args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
            code=main(args)
        return code,out.getvalue()

    def test_models_json(self):
        code,out=self.invoke(['models','--json'])
        self.assertEqual(code,0)
        self.assertGreaterEqual(len(json.loads(out)),7)

    def test_json_plan(self):
        code,out=self.invoke(['image','generate','A wonderful idea','--seed','7','--dry-run','--json'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(out)['seed'],7)

    def test_errors_json(self):
        code,out=self.invoke(['image','generate','','--dry-run','--json'])
        self.assertEqual(code,2)
        self.assertEqual(json.loads(out)['status'],'failed')

    def test_no_backend_execution_on_dry_run(self):
        with patch('cgc.cli.run') as run:
            self.assertEqual(self.invoke(['audio','design','Hello','--direction','Warm narrator','--dry-run'])[0],0)
            run.assert_not_called()

    def test_batch_validates_all_before_running(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'brief.json'
            path.write_text(json.dumps({'version':1,'jobs':[{'operation':'image.generate','prompt':'okay'},{'operation':'nope','prompt':'bad'}]}))
            with patch('cgc.cli.run') as run:
                code,out=self.invoke(['batch',str(path),'--json'])
                self.assertEqual(code,2)
                self.assertIn('Job 2',out)
                run.assert_not_called()

    def test_batch_cannot_grant_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'brief.json'
            path.write_text(json.dumps({'version':1,'jobs':[{'operation':'image.generate','prompt':'okay','download':True}]}))
            self.assertEqual(self.invoke(['batch',str(path),'--dry-run'])[0],2)

    def test_batch_duplicate_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'brief.json'
            row={'operation':'image.generate','prompt':'okay','output':d+'/duplicate.png'}
            path.write_text(json.dumps({'version':1,'jobs':[row,row]}))
            self.assertEqual(self.invoke(['batch',str(path),'--dry-run'])[0],2)

    def test_unknown_batch_type(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'brief.json';path.write_text('[]')
            self.assertEqual(self.invoke(['batch',str(path),'--dry-run'])[0],2)
