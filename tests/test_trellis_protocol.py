"""The JSON protocol must survive native writes to stdout."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


class NativeSessionProtocol(unittest.TestCase):
    def test_native_stdout_cannot_be_mistaken_for_json_response(self):
        code='''
import json,os
from cgc.trellis_session import reserve_protocol
protocol=reserve_protocol()
os.write(1,b"\\nnative mesh conversion log\\n")
print("Python model log",flush=True)
print(json.dumps({"ok":True}),file=protocol,flush=True)
'''
        process=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],
                               capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(process.stdout),{'ok':True})
        self.assertIn('native mesh conversion log',process.stderr)
        self.assertIn('Python model log',process.stderr)


if __name__=='__main__':unittest.main()
