import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from cgc.planning import ROOT
from cgc.standards import validate


def triangle(path,empty_extensions=False):
    binary=struct.pack('<9f3H',0,0,0,1,0,0,0,1,0,0,1,2)
    document={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(binary)}],
              'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':36,'target':34962},{'buffer':0,'byteOffset':36,'byteLength':6,'target':34963}],
              'accessors':[{'bufferView':0,'componentType':5126,'type':'VEC3','count':3,'min':[0,0,0],'max':[1,1,0]},{'bufferView':1,'componentType':5123,'type':'SCALAR','count':3}],
              'meshes':[{'primitives':[{'attributes':{'POSITION':0},'indices':1}]}],'nodes':[{'mesh':0}],'scenes':[{'nodes':[0]}],'scene':0}
    if empty_extensions:document['extensionsUsed']=[]
    encoded=json.dumps(document).encode();encoded+=b' '*((-len(encoded))%4);binary+=b'\0'*((-len(binary))%4)
    path.write_bytes(struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(binary))+struct.pack('<II',len(encoded),0x4E4F534A)+encoded+struct.pack('<II',len(binary),0x004E4942)+binary)


@unittest.skipUnless(shutil.which('node') and (ROOT/'.backends/gltf-validator/node_modules/gltf-validator/package.json').exists(),'Optional official validator is not installed')
class StandardsIntegration(unittest.TestCase):
    def test_official_validator_accepts_valid_and_rejects_schema_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'triangle.glb';triangle(path)
            good=validate(path)
            self.assertEqual(good['status'],'passed')
            self.assertEqual(good['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            triangle(path,empty_extensions=True)
            bad=validate(path)
            self.assertEqual(bad['status'],'failed')
            self.assertTrue(any(item['code']=='EMPTY_ENTITY' for item in bad['report']['issues']['messages']))

    def test_external_resources_cannot_escape_asset_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'asset').mkdir();(root/'outside.bin').write_bytes(bytes(36))
            path=root/'asset/mesh.gltf'
            path.write_text(json.dumps({'asset':{'version':'2.0'},'buffers':[{'uri':'../outside.bin','byteLength':36}],
                'bufferViews':[{'buffer':0,'byteLength':36}],'accessors':[{'bufferView':0,'componentType':5126,'type':'VEC3','count':3,'min':[0,0,0],'max':[0,0,0]}],
                'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],'nodes':[{'mesh':0}],'scenes':[{'nodes':[0]}],'scene':0}))
            report=validate(path)
            self.assertEqual(report['status'],'failed')
            self.assertEqual(report['external_resources'],[])
            allowed=validate(path,resource_root=root)
            self.assertEqual(len(allowed['external_resources']),1)
            self.assertEqual(allowed['external_resources'][0]['sha256'],hashlib.sha256(bytes(36)).hexdigest())


if __name__=='__main__':unittest.main()
