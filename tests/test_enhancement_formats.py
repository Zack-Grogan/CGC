import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from cgc.face import inspect as inspect_face
from cgc.segmentation import inspect as inspect_segmentation
from cgc.glb_replace import replace, read


def npy(shape,values,kind='f4'):
    header=repr({'descr':'<'+kind,'fortran_order':False,'shape':shape})+'\n'
    code={'f4':'f','f8':'d','i4':'i','i8':'q'}[kind]
    return b'\x93NUMPY\x01\x00'+struct.pack('<H',len(header))+header.encode()+struct.pack('<'+code*len(values),*values)


def face(path,times=None,constant=False):
    rows=[0.]*(4*68)
    for index in range(4):rows[index*68+18]=.2 if constant else index/10
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('weights.npy',npy((4,68),rows))
        archive.writestr('times.npy',npy((4,),times or [0.,1/60,2/60,3/60],'f8'))


def segmentation(path,label_kind='i4',faces=None):
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('vertices.npy',npy((4,3),[0,0,0,1,0,0,0,1,0,1,1,0]))
        archive.writestr('faces.npy',npy((2,3),faces or [0,1,2,1,3,2],'i8'))
        archive.writestr('labels.npy',npy((2,),[1,0],label_kind))


def glb(path,two=False,image=False):
    data=bytearray(struct.pack('<9f3I',0,0,0,1,0,0,0,1,0,0,1,2))
    doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(data)}],
         'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':36},{'buffer':0,'byteOffset':36,'byteLength':12}],
         'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3','min':[0,0,0],'max':[1,1,0]},{'bufferView':1,'componentType':5125,'count':3,'type':'SCALAR'}],
         'materials':[{'name':'original' if two else 'replacement','emissiveFactor':[.1,.2,.3]}],
         'meshes':[{'name':'selected','primitives':[{'attributes':{'POSITION':0},'indices':1,'material':0}]}],
         'nodes':[{'name':'selected','mesh':0}],'scenes':[{'nodes':[0]}],'scene':0}
    if two:
        doc['meshes'].append({'name':'remainder','primitives':[{'attributes':{'POSITION':0},'indices':1,'material':0}]})
        doc['nodes'].append({'name':'remainder','mesh':1});doc['scenes'][0]['nodes'].append(1)
    if image:
        raw=b'original embedded image bytes';offset=len(data);data.extend(raw)
        doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(raw)})
        doc['images']=[{'bufferView':2,'mimeType':'image/png'}]
    doc['buffers'][0]['byteLength']=len(data)
    encoded=json.dumps(doc).encode();encoded+=b' '*((-len(encoded))%4);data.extend(b'\0'*((-len(data))%4))
    path.write_bytes(struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(data))+struct.pack('<II',len(encoded),0x4E4F534A)+encoded+struct.pack('<II',len(data),0x004E4942)+data)


class EnhancementFormats(unittest.TestCase):
    def test_face_clock_and_actual_motion_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'face.npz';face(path)
            self.assertEqual(inspect_face(path)['channels'],68)
            face(path,times=[0.,1/60,1/60,3/60])
            with self.assertRaisesRegex(ValueError,'increase'):inspect_face(path)
            face(path,constant=True)
            with self.assertRaisesRegex(ValueError,'changing'):inspect_face(path)

    def test_face_labels_require_integer_ids_and_valid_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'parts.npz';segmentation(path)
            self.assertEqual(inspect_segmentation(path)['selected_faces'],1)
            segmentation(path,label_kind='f4')
            with self.assertRaisesRegex(ValueError,'integers'):inspect_segmentation(path)
            segmentation(path,faces=[0,1,2,1,3,99])
            with self.assertRaisesRegex(ValueError,'index'):inspect_segmentation(path)

    def test_replacement_preserves_untouched_resources_and_scene_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.glb';generated=root/'replacement.glb';output=root/'out.glb'
            glb(source,two=True,image=True);glb(generated)
            original,original_binary=read(source)
            report=replace(source,generated,'selected',output)
            result,binary=read(output)
            self.assertTrue(report['untouched_resources_preserved'])
            self.assertEqual(result['materials'][0],original['materials'][0])
            self.assertEqual(result['images'],original['images'])
            self.assertEqual(binary[:len(original_binary)],original_binary)
            self.assertEqual([node['name'] for node in result['nodes']],['remainder','selected'])
            self.assertEqual(result['scenes'][0]['nodes'],[0,1])
            self.assertEqual(result['nodes'][0]['mesh'],0)


if __name__=='__main__':unittest.main()
