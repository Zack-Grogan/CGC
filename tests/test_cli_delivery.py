import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from cgc.cli import main


class DeliveryFailures(unittest.TestCase):
    def test_worker_and_timeout_failures_return_structured_json(self):
        cases=[
            ('cgc.game_assets.prepare_asset',['asset','prepare','--input','source.glb','--output-dir','new-package'],RuntimeError('The package failed glTF standards checks')),
            ('cgc.game_assets.prepare_asset',['asset','prepare','--input','source.glb','--output-dir','new-package'],subprocess.TimeoutExpired('Blender',1800)),
            ('cgc.media_quality.handle',['media','inspect','--input','source.wav'],subprocess.TimeoutExpired('ffprobe',120)),
        ]
        for target,arguments,error in cases:
            with self.subTest(target=target,error=type(error).__name__):
                output=io.StringIO()
                with patch(target,side_effect=error),contextlib.redirect_stdout(output):
                    code=main([*arguments,'--json'])
                self.assertEqual(code,2)
                response=json.loads(output.getvalue())
                self.assertEqual(response['status'],'failed')
                self.assertTrue(response['error'])


if __name__=='__main__':unittest.main()
