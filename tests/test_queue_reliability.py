import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from cgc import queue, remote_client
from cgc.planning import Plan


class QueueReliability(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.environment=patch.dict(os.environ,CGC_STATE_DIR=str(self.root));self.environment.start()
    def tearDown(self):self.environment.stop();self.folder.cleanup()
    def plan(self):
        source=self.root/'source.png';source.write_bytes(b'fixed input')
        return Plan('image.edit','qwen-image-2.1-turbo','remote',[],str(self.root/'out.png'),'edit',1,False,[],{'references':[str(source)]})
    def test_corrupted_cached_snapshot_is_not_admitted(self):
        with patch('cgc.runtime.preflight'):
            first=queue.enqueue(self.plan())
            Path(first['plan']['parameters']['references'][0]).write_bytes(b'tampered')
            from dataclasses import replace
            with self.assertRaisesRegex(ValueError,'digest'):
                queue.enqueue(replace(self.plan(),output=str(self.root/'other.png')))
    def test_control_command_crash_does_not_pause_queue_forever(self):
        with queue.connect() as db:db.execute("INSERT OR REPLACE INTO settings VALUES ('control_busy','1')")
        self.assertFalse(queue.paused())
        queue.paused(True);self.assertTrue(queue.paused())
    def test_live_control_lock_blocks_dispatch_even_before_hint_is_written(self):
        import fcntl
        with patch('cgc.runtime.preflight'):job=queue.enqueue(self.plan())
        with (self.root/'control.lock').open('a') as held:
            fcntl.flock(held,fcntl.LOCK_EX)
            self.assertTrue(queue.paused())
            self.assertIsNone(queue.claim_next(None))
            self.assertEqual(queue.get(job['id'])['state'],'queued')
        self.assertFalse(queue.paused())
    def test_retry_cannot_archive_a_running_attempt(self):
        with patch('cgc.runtime.preflight'):job=queue.enqueue(self.plan())
        queue.update(job['id'],'running')
        args=types.SimpleNamespace(command='jobs',action='retry',ids=[job['id']])
        with self.assertRaisesRegex(ValueError,'queued or running'):queue.cli(args)
        self.assertEqual(queue.get(job['id'])['state'],'running')
    def test_worker_keeps_the_callers_resolved_state_directory(self):
        previous=Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ,CGC_STATE_DIR='nested-state'),patch('cgc.queue.subprocess.Popen') as spawn:
                queue.start()
        finally:os.chdir(previous)
        self.assertEqual(spawn.call_args.kwargs['env']['CGC_STATE_DIR'],str((self.root/'nested-state').resolve()))


class TransportRecovery(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.environment=patch.dict(os.environ,CGC_STATE_DIR=str(self.root/'state'));self.environment.start()
    def tearDown(self):self.environment.stop();self.folder.cleanup()
    def request_module(self,status):
        response=types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'status':status,'container_id':'worker-one'})
        return types.SimpleNamespace(get=lambda *args,**kwargs:response)
    def test_active_own_task_can_be_reconciled_but_another_job_is_blocked(self):
        state=self.root/'state';state.mkdir();(state/'gpu-session.json').write_text(json.dumps({'task_id':'paid','profile':'qwen','runtime_id':'old'}))
        with patch.dict(sys.modules,requests=self.request_module('RUNNING')),patch('cgc.remote_client.subprocess.run') as stop:
            lock,_=remote_client.acquire_gpu('qwen','secret','changed-code',current_task_id='paid');lock.close()
            stop.assert_not_called()
            with self.assertRaisesRegex(RuntimeError,'active or uncertain'):remote_client.acquire_gpu('other','secret','new')
    def test_tracking_update_never_publishes_partial_json(self):
        path=self.root/'record.json';remote_client.write_tracking(path,{'task_id':'paid','status':'RUNNING'})
        remote_client.write_tracking(path,{'task_id':'paid','status':'COMPLETE'})
        self.assertEqual(json.loads(path.read_text()),{'task_id':'paid','status':'COMPLETE'})
        self.assertEqual(list(self.root.glob('.record.json-*')),[])
    def test_large_inputs_use_small_descriptors_and_cached_uploads(self):
        source=self.root/'large.glb';source.write_bytes(b'a'*(17*1024*1024))
        stored={};uploaded=[]
        beam=types.ModuleType('beam')
        class Volume:
            def __init__(self,**kwargs):pass
            def get_or_create(self):return True
        beam.Volume=Volume
        config=types.ModuleType('beta9.config');config.get_config_context=lambda:object()
        channel=types.ModuleType('beta9.channel')
        class Service:
            def __init__(self,**kwargs):self.volume=self
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def stat_path(self,request):return types.SimpleNamespace(ok=request.path in stored,path_info=types.SimpleNamespace(size=stored.get(request.path,0)))
        channel.ServiceClient=Service
        volume=types.ModuleType('beta9.clients.volume');volume.StatPathRequest=lambda **kwargs:types.SimpleNamespace(**kwargs)
        def upload(command,**kwargs):
            path=Path(kwargs['cwd'])/command[2]
            self.assertEqual(path.parent,Path(kwargs['cwd']))
            self.assertNotEqual(path.parent,source.parent)
            stored[command[3].removeprefix('beam://')]=path.stat().st_size;uploaded.append(command)
            return types.SimpleNamespace(returncode=0)
        with patch.dict(sys.modules,{'beam':beam,'beta9.config':config,'beta9.channel':channel,'beta9.clients.volume':volume}),patch('cgc.remote_client.subprocess.run',side_effect=upload):
            first=remote_client.stage_references([str(source)])
            second=remote_client.stage_references([str(source)])
        self.assertEqual(first,second);self.assertEqual(len(uploaded),1)
        self.assertEqual(first[0]['bytes'],17*1024*1024)
        self.assertEqual(first[0]['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertLess(len(json.dumps(first)),1024)
    def test_submit_interruption_recovery_collects_without_second_paid_request(self):
        # This executes the complete real transport controller with a fake Beam
        # boundary. It deliberately drops polling after accepting the first task.
        output=self.root/'result.png';accepted=[];configuration=[];phase=['disconnect']
        payload=b'authoritative provider output';checksum=hashlib.sha256(payload).hexdigest()
        class Image:
            def __init__(self,**kwargs):self.image_id=kwargs.get('image_id','fixed-image')
            def add_commands(self,*args):return self
        class Volume:
            def __init__(self,**kwargs):pass
        def task_queue(**kwargs):
            configuration.append(kwargs)
            class Remote:
                def put(self,**arguments):accepted.append(arguments['request']);return types.SimpleNamespace(id='paid-once')
            return lambda function:Remote()
        beam=types.ModuleType('beam');beam.Image=Image;beam.Volume=Volume;beam.task_queue=task_queue
        beam.QueueDepthAutoscaler=lambda **kwargs:kwargs
        config=types.ModuleType('beta9.config');config.get_config_context=lambda:types.SimpleNamespace(token='not-printed')
        calls=[0]
        def get(*args,**kwargs):
            if phase[0]=='disconnect':raise ConnectionError('lost connection after provider accepted task')
            calls[0]+=1
            return types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'status':'RUNNING' if calls[0]==1 else 'COMPLETE','container_id':'worker-one'})
        requests=types.ModuleType('requests');requests.get=get
        def command(arguments,**kwargs):
            if arguments[1]=='cp':
                target=Path(kwargs['cwd'])/arguments[-1]
                if target.name=='result.json':
                    target.write_text(json.dumps({'file':'output.png','sha256':checksum,'files':[{'name':'output.png','sha256':checksum}]}))
                else:target.write_bytes(payload)
            return types.SimpleNamespace(returncode=0,stdout='',stderr='')
        plan={'model':'qwen-image-2.1-turbo','output':str(output),'prompt':'generate','seed':42,'parameters':{}}
        original_cwd=Path.cwd();original_path=list(sys.path)
        try:
            with patch.dict(sys.modules,{'beam':beam,'beta9.config':config,'requests':requests}),patch('cgc.remote_client.subprocess.run',side_effect=command),contextlib.redirect_stdout(io.StringIO()):
                with patch.object(sys,'argv',['client','--plan',json.dumps(plan)]),self.assertRaises(ConnectionError):remote_client.main()
                self.assertEqual(Path.cwd(),original_cwd)
                self.assertEqual(sys.path,original_path)
                record=json.loads(Path(str(output)+'.remote.json').read_text());self.assertEqual(record['task_id'],'paid-once')
                self.assertEqual(len(accepted),1)
                phase[0]='recover'
                with patch.object(sys,'argv',['client','--plan',json.dumps(plan)]):remote_client.main()
        finally:
            os.chdir(original_cwd);sys.path[:]=original_path;sys.modules.pop('remote_worker',None)
        self.assertEqual(len(accepted),1)
        self.assertEqual(output.read_bytes(),payload)
        self.assertEqual(json.loads(Path(str(output)+'.result.json').read_text())['sha256'],checksum)
        self.assertTrue(all(c['retries']==0 and c['autoscaler']['min_containers']==0 and c['autoscaler']['max_containers']==1 for c in configuration))


if __name__=='__main__':unittest.main()
