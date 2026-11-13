"""Execute the real transport with publication delays at the fake Beam CLI boundary."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from cgc import remote_client


class CollectionReliability(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.output=self.root/'asset.glb';self.accepted=[];self.downloads=[];self.collect_folders=set()
        self.failures={};self.corrupt=set();self.command_timeouts=[]
        self.payloads={'output.glb':b'verified generated mesh','output.provenance.json':b'{"source":"generated"}'}
        self.digests={name:hashlib.sha256(value).hexdigest() for name,value in self.payloads.items()}
        self.report={'file':'/remote/output.glb','sha256':self.digests['output.glb'],
                     'files':[{'name':name,'sha256':digest} for name,digest in self.digests.items()]}
        owner=self
        class Image:
            def __init__(self,**kwargs):self.image_id=kwargs.get('image_id','test-image')
            def add_commands(self,*args):return self
        class Volume:
            def __init__(self,**kwargs):pass
        def task_queue(**kwargs):
            class Remote:
                def put(self,**arguments):owner.accepted.append(arguments['request']);return types.SimpleNamespace(id='paid-exactly-once')
            return lambda function:Remote()
        beam=types.ModuleType('beam');beam.Image=Image;beam.Volume=Volume;beam.task_queue=task_queue
        beam.QueueDepthAutoscaler=lambda **kwargs:kwargs
        config=types.ModuleType('beta9.config');config.get_config_context=lambda:types.SimpleNamespace(token='test-not-secret')
        requests=types.ModuleType('requests')
        requests.get=lambda *args,**kwargs:types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'status':'COMPLETE'})
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.dict(os.environ,CGC_STATE_DIR=str(self.root/'state')))
        self.stack.enter_context(patch.dict(sys.modules,{'beam':beam,'beta9.config':config,'requests':requests}))
        self.stack.enter_context(patch('cgc.remote_client.subprocess.run',side_effect=self.command))
        self.sleep=self.stack.enter_context(patch('cgc.remote_client.time.sleep'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    def tearDown(self):
        self.stack.close();sys.modules.pop('remote_worker',None);self.folder.cleanup()
    def command(self,arguments,**kwargs):
        self.assertEqual(arguments[1],'cp')
        local=Path(kwargs['cwd'])/arguments[-1];name=local.name
        self.assertFalse(local.exists(),'A partial download was reused')
        self.collect_folders.add(local.parent);self.downloads.append(name)
        self.command_timeouts.append(kwargs['timeout'])
        if self.failures.get(name,0):
            self.failures[name]-=1;local.write_bytes(b'partial')
            self.assertFalse(self.output.exists(),'Main output published before all sidecars were verified')
            raise subprocess.CalledProcessError(1,arguments,stderr='404 publication pending')
        if name=='result.json':local.write_text(json.dumps(self.report))
        else:local.write_bytes(b'corrupt bytes' if name in self.corrupt else self.payloads[name])
        return types.SimpleNamespace(returncode=0,stdout='',stderr='')
    def run_transport(self):
        plan={'model':'qwen-image-2.1-turbo','output':str(self.output),'prompt':'test','seed':42,'parameters':{}}
        with patch.object(sys,'argv',['client','--plan',json.dumps(plan)]):remote_client.main()
    def tracking(self):return json.loads(Path(str(self.output)+'.remote.json').read_text())
    def assert_clean(self):
        self.assertTrue(all(not path.exists() for path in self.collect_folders))
        self.assertEqual(list(self.root.glob('.cgc-download-*')),[])
        self.assertEqual(list(self.root.glob('.cgc-sidecar-*')),[])
    def test_manifest_before_main_and_transient_sidecar_are_collected_without_resubmission(self):
        self.failures={'output.glb':1,'output.provenance.json':1}
        self.run_transport()
        self.assertEqual(len(self.accepted),1)
        self.assertEqual(self.downloads,['result.json','output.glb','output.glb','output.provenance.json','output.provenance.json'])
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list],[1,1])
        self.assertEqual(self.output.read_bytes(),self.payloads['output.glb'])
        self.assertEqual(self.output.with_suffix('.provenance.json').read_bytes(),self.payloads['output.provenance.json'])
        result=json.loads(Path(str(self.output)+'.result.json').read_text())
        self.assertEqual(result['sha256'],hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(result['execution']['task_id'],'paid-exactly-once')
        self.assertEqual(self.tracking()['collection']['status'],'completed')
        self.assertTrue(all(0<timeout<=180 for timeout in self.command_timeouts))
        self.assert_clean()
        self.run_transport();self.assertEqual(len(self.accepted),1)
        self.assert_clean()
    def test_persistent_failure_is_finite_and_recovery_keeps_the_paid_identity(self):
        self.failures={'output.glb':100}
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'after 4 attempts'):self.run_transport()
            tracking=self.tracking()
            self.assertEqual(tracking['status'],'COMPLETE')
            self.assertEqual(tracking['task_id'],'paid-exactly-once')
            self.assertEqual(tracking['collection']['status'],'collection_pending')
            self.assertFalse(self.output.exists());self.assert_clean()
        self.assertEqual(len(self.accepted),1)
        self.assertEqual(self.downloads.count('output.glb'),8)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list],[1,2,4,1,2,4])
    def test_corrupt_bytes_fail_without_download_retry_or_local_publication(self):
        self.corrupt={'output.provenance.json'}
        with self.assertRaisesRegex(RuntimeError,'digest mismatch; refusing automatic retry'):self.run_transport()
        self.assertEqual(self.downloads.count('output.provenance.json'),1)
        self.sleep.assert_not_called();self.assertFalse(self.output.exists())
        self.assertEqual(self.tracking()['collection']['status'],'collection_pending')
        self.assert_clean()
        self.corrupt.clear();self.run_transport()
        self.assertEqual(len(self.accepted),1);self.assertEqual(self.output.read_bytes(),self.payloads['output.glb'])
    def test_existing_sidecar_collision_preserves_bytes_and_avoids_publication(self):
        target=self.output.with_suffix('.provenance.json');target.write_bytes(b'user-owned original')
        with self.assertRaisesRegex(RuntimeError,'collision'):self.run_transport()
        self.assertEqual(target.read_bytes(),b'user-owned original');self.assertFalse(self.output.exists())
        self.assertEqual(self.downloads,['result.json']);self.assertEqual(len(self.accepted),1)
        self.assert_clean()
    def test_shared_budget_expiry_stops_before_another_download(self):
        with patch('cgc.remote_client.COLLECTION_BUDGET_SECONDS',0),self.assertRaisesRegex(TimeoutError,'time budget exhausted'):
            self.run_transport()
        self.assertEqual(self.downloads,[]);self.assertEqual(len(self.accepted),1)
        self.assertEqual(self.tracking()['collection']['status'],'collection_pending')
        self.assert_clean()
    def test_destination_staging_copy_failure_removes_partial_temp_file(self):
        with patch('cgc.remote_client.shutil.copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):self.run_transport()
        self.assertFalse(self.output.exists());self.assert_clean()
        self.assertEqual(self.tracking()['collection']['status'],'collection_pending')


if __name__=='__main__':unittest.main()
