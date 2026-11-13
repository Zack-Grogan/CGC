"""Texture source failures must be found before remote submission."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from cgc.texture_preflight import inspect_source


class TextureSourcePreflight(unittest.TestCase):
    def source(self,path,*,duplicate=False,nodes=None,vertices=None):
        vertices=vertices or (0,0,0,1,0,0,0,1,0)
        if duplicate:vertices=(*vertices,*vertices)
        count=len(vertices)//3;binary=struct.pack('<'+'f'*len(vertices),*vertices)
        nodes=nodes or [{'mesh':0}]
        doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(binary)}],
             'bufferViews':[{'buffer':0,'byteLength':len(binary)}],
             'accessors':[{'componentType':5126,'type':'VEC3','count':count,'bufferView':0}],
             'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
             'nodes':nodes,'scenes':[{'nodes':list(range(len(nodes)))}],'scene':0}
        chunk=json.dumps(doc).encode();chunk+=b' '*((-len(chunk))%4)
        path.write_bytes(struct.pack('<4sIIII',b'glTF',2,28+len(chunk)+len(binary),len(chunk),0x4e4f534a)+chunk+struct.pack('<II',len(binary),0x004e4942)+binary)

    def test_same_node_duplicates_are_counted_and_transforms_are_respected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.glb';self.source(path,duplicate=True)
            result=inspect_source(path)
            self.assertEqual(result['same_node_duplicate_triangles'],1)
            self.assertEqual(result['triangles'],2)
            self.source(path,nodes=[{'mesh':0},{'mesh':0,'translation':[2,0,0]}])
            self.assertEqual(inspect_source(path)['mesh_nodes'],2)

    def test_coincident_different_nodes_refuse_before_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.glb';self.source(path,nodes=[{'mesh':0},{'mesh':0}])
            with self.assertRaisesRegex(ValueError,'different nodes'):inspect_source(path)

    def test_zero_area_and_nonfinite_positions_refuse(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.glb'
            self.source(path,vertices=(0,0,0,1,0,0,2,0,0))
            with self.assertRaisesRegex(ValueError,'zero-area'):inspect_source(path)
            self.source(path,vertices=(0,0,0,1,0,0,0,float('nan'),0))
            with self.assertRaisesRegex(ValueError,'finite'):inspect_source(path)


if __name__=='__main__':unittest.main()
