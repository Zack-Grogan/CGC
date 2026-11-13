import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from cgc.game_assets import inspect_asset,prepare_asset,_read,_scale_glb

def glb(path,skin=False):
 binary=struct.pack('<9f3H',0,0,0,1,0,0,0,1,0,0,1,2);binary+=b'\0'*((-len(binary))%4)
 doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(binary)}],'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':36},{'buffer':0,'byteOffset':36,'byteLength':6}],
 'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3','min':[0,0,0],'max':[1,1,0]},{'bufferView':1,'componentType':5123,'count':3,'type':'SCALAR'}],
 'meshes':[{'primitives':[{'attributes':{'POSITION':0},'indices':1}]}],'nodes':[{'name':'triangle','mesh':0}],'scenes':[{'nodes':[0]}],'scene':0}
 if skin:doc['skins']=[{'joints':[0]}]
 encoded=json.dumps(doc).encode();encoded+=b' '*((-len(encoded))%4)
 path.write_bytes(struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(binary))+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary)

class GameAssetContracts(unittest.TestCase):
 def test_timed_out_package_retains_snapshot_and_log(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source);raw=source.read_bytes()
   with patch('cgc.game_assets.find_blender',return_value='/test/blender'),patch('cgc.game_assets.subprocess.run',side_effect=subprocess.TimeoutExpired('Blender',1800)):
    with self.assertRaisesRegex(RuntimeError,'timed out'):prepare_asset(source,root/'package')
   self.assertFalse((root/'package').exists())
   failed=list(root.glob('package.failed-*'));self.assertEqual(len(failed),1)
   self.assertEqual((failed[0]/'source.glb').read_bytes(),raw)
   self.assertTrue((failed[0]/'blender.log').is_file())
 def test_delivery_uses_snapshot_if_original_changes_during_processing(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source);raw=source.read_bytes()
   def change_original_then_scale(snapshot,destination,scale,yaw):
    source.write_bytes(b'concurrent edit')
    return _scale_glb(snapshot,destination,scale,yaw)
   with patch('cgc.game_assets._scale_glb',side_effect=change_original_then_scale),patch('cgc.standards.validate',return_value={'status':'passed','errors':0,'warnings':0}):
    result=prepare_asset(source,root/'package',lod_ratios=[])
   self.assertEqual((root/'package/source.glb').read_bytes(),raw)
   self.assertEqual((root/'package/lod0.glb').read_bytes(),raw)
   self.assertFalse(result['source_preserved'])
 def test_original_bytes_are_retained_and_existing_package_is_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source);raw=source.read_bytes()
   with patch('cgc.standards.validate',return_value={'status':'passed','errors':0,'warnings':2}):
    result=prepare_asset(source,root/'package',lod_ratios=[])
   self.assertEqual(source.read_bytes(),raw);self.assertEqual((root/'package/source.glb').read_bytes(),raw);self.assertEqual((root/'package/lod0.glb').read_bytes(),raw)
   manifest=json.loads((root/'package/asset-package.json').read_text());self.assertEqual(manifest['standards_validation'][0]['warnings'],2)
   with self.assertRaisesRegex(ValueError,'new output'):prepare_asset(source,root/'package',lod_ratios=[])
 def test_explicit_units_scale_wraps_roots_without_changing_binary(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source);original,binary=_read(source)
   with patch('cgc.standards.validate',return_value={'status':'passed','errors':0,'warnings':0}):prepare_asset(source,root/'package',lod_ratios=[],meters_per_unit=.01)
   doc,processed=_read(root/'package/lod0.glb');self.assertEqual(processed,binary);self.assertEqual(doc['nodes'][-1]['scale'],[.01,.01,.01]);self.assertEqual(doc['nodes'][-1]['children'],original['scenes'][0]['nodes'])
 def test_invalid_lod_policies_are_rejected_before_blender(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source)
   for ratios in ([.2,.5],[0],[float('nan')]):
    with self.subTest(ratios=ratios),self.assertRaises(ValueError):prepare_asset(source,root/'package',lod_ratios=ratios)
 def test_rigged_mesh_is_not_silently_decimated(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'rig.glb';glb(source,skin=True)
   self.assertEqual(inspect_asset(source)['skins'],1)
   with self.assertRaisesRegex(ValueError,'static'):prepare_asset(source,root/'package')
 def test_failed_standards_gate_does_not_publish_a_successful_package(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source)
   with patch('cgc.standards.validate',return_value={'status':'failed','errors':1,'warnings':0}):
    with self.assertRaisesRegex(RuntimeError,'standards'):prepare_asset(source,root/'package',lod_ratios=[])
   self.assertFalse((root/'package').exists());self.assertTrue(list(root.glob('package.failed-*')))


class NodeRequirements(unittest.TestCase):
 def test_caller_names_are_checked_without_inventing_sockets(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp)/'asset.glb';glb(source)
   self.assertEqual(inspect_asset(source,['triangle'])['required_nodes'][0]['status'],'passed')
   self.assertEqual(inspect_asset(source,['SOCKET_FIRE'])['status'],'failed')
   with self.assertRaisesRegex(ValueError,'Required node'):prepare_asset(source,Path(tmp)/'package',lod_ratios=[],required_nodes=['SOCKET_FIRE'])


class AssetReviewContracts(unittest.TestCase):
 def test_admission_preserves_existing_directories_and_rejects_bad_limits(self):
  from cgc.game_assets import render_asset
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source);existing=root/'review';existing.mkdir();(existing/'keep').write_text('original')
   with self.assertRaisesRegex(ValueError,'new output'):render_asset(source,existing)
   for size in (255,4097,True):
    with self.subTest(size=size),self.assertRaises(ValueError):render_asset(source,root/'out',size=size)
   self.assertEqual((existing/'keep').read_text(),'original')
 def test_timeout_retains_snapshot_and_logs_without_publishing_success(self):
  import subprocess,sys
  from cgc.game_assets import render_asset
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source);original=source.read_bytes()
   with patch('cgc.game_assets.subprocess.run',side_effect=subprocess.TimeoutExpired(['blender'],.01)):
    with self.assertRaisesRegex(RuntimeError,'timeout'):render_asset(source,root/'review',blender=sys.executable,timeout=.01)
   self.assertFalse((root/'review').exists());failed=next(root.glob('review.failed-*'))
   self.assertEqual((failed/'source.glb').read_bytes(),original);self.assertTrue((failed/'blender.log').exists());self.assertTrue((failed/'failure.json').exists());self.assertEqual(source.read_bytes(),original)
 def test_success_renders_from_exact_snapshot_and_hashes_all_views(self):
  import subprocess,sys,zlib,hashlib
  from cgc.game_assets import render_asset
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.glb';glb(source);original=source.read_bytes()
   def fake_renderer(command,**kwargs):
    snapshot=Path(command[command.index('--input')+1]);stage=Path(command[command.index('--output-dir')+1]);self.assertNotEqual(snapshot,source);self.assertEqual(snapshot.read_bytes(),original)
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',256,256,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x10\x20\x30'*256)*256))+chunk(b'IEND',b'')
    for name in ('front','side','back','three-quarter'):(stage/(name+'.png')).write_bytes(png)
    (stage/'inspection.json').write_text(json.dumps({'image_size':[256,256],'meshes':1,'triangles':1}))
    return subprocess.CompletedProcess(command,0)
   with patch('cgc.game_assets.subprocess.run',side_effect=fake_renderer):result=render_asset(source,root/'review',size=256,blender=sys.executable)
   self.assertEqual(result['status'],'completed');self.assertEqual(source.read_bytes(),original)
   report=json.loads((root/'review/render-review.json').read_text())
   self.assertEqual(report['source_sha256'],hashlib.sha256(original).hexdigest());self.assertEqual(len(result['views']),4)
   for entry in report['artifacts']:self.assertEqual(hashlib.sha256((root/'review'/entry['path']).read_bytes()).hexdigest(),entry['sha256'])

class ExclusiveReviewPublication(unittest.TestCase):
 def test_empty_existing_directory_is_not_replaced_at_publish(self):
  from cgc.game_assets import _publish_directory
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);stage=root/'stage';target=root/'review';stage.mkdir();target.mkdir();(stage/'asset').write_text('new')
   inode=target.stat().st_ino
   with self.assertRaises(OSError):_publish_directory(stage,target)
   self.assertEqual(target.stat().st_ino,inode);self.assertFalse(list(target.iterdir()));self.assertTrue((stage/'asset').exists())

if __name__=='__main__':unittest.main()
