"""Split a static GLB using canonical GeoSAM labels; preserve every source face."""
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import traceback
import struct
import copy


def split(source,labels_path,destination,label):
    import numpy as np
    from collections import defaultdict
    payload=Path(source).read_bytes();digest=hashlib.sha256(payload).hexdigest()
    with np.load(labels_path,allow_pickle=False) as data:
        if str(data['source_sha256'].item())!=digest:raise ValueError('Face labels belong to a different source GLB')
        labels=data['labels'];triangles=data['vertices'][data['faces']]
    def key(triangle):return tuple(sorted(tuple(np.round(vertex.astype(np.float64),5)) for vertex in triangle))
    mapping=defaultdict(set)
    for triangle,value in zip(triangles,labels):mapping[key(triangle)].add(int(value))
    if any(len(values)!=1 for values in mapping.values()):raise ValueError('Coincident triangles have conflicting labels')
    size=struct.unpack_from('<I',payload,12)[0];document=json.loads(payload[20:20+size])
    binary_size,kind=struct.unpack_from('<II',payload,20+size)
    if kind!=0x004E4942 or len(document['buffers'])!=1 or document['buffers'][0].get('uri'):
        raise ValueError('Split requires one embedded GLB buffer')
    if document.get('skins') or document.get('animations'):raise ValueError('Split static, unskinned geometry')
    binary=bytearray(payload[28+size:28+size+binary_size])
    component={5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}
    dimensions={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}
    def read(index,normalized=False):
        accessor=document['accessors'][index]
        if accessor.get('sparse'):raise ValueError('Materialize sparse accessors before splitting')
        view=document['bufferViews'][accessor['bufferView']]
        if view.get('extensions'):raise ValueError('Decode compressed vertex buffers before splitting')
        dtype=np.dtype(component[accessor['componentType']]);width=dimensions[accessor['type']]
        values=np.ndarray((accessor['count'],width),dtype=dtype,buffer=binary,offset=view.get('byteOffset',0)+accessor.get('byteOffset',0),strides=(view.get('byteStride',width*dtype.itemsize),dtype.itemsize)).copy()
        if normalized and accessor.get('normalized'):
            values=np.maximum(values.astype(np.float64)/np.iinfo(dtype).max,-1)
        return values
    def append(values,template,target):
        values=np.ascontiguousarray(values)
        binary.extend(b'\0'*((-len(binary))%4));offset=len(binary);binary.extend(values.tobytes())
        document['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':values.nbytes,'target':target})
        accessor=copy.deepcopy(template);accessor.pop('byteOffset',None);accessor.pop('sparse',None)
        accessor.update(bufferView=len(document['bufferViews'])-1,count=len(values))
        if 'min' in template or 'max' in template:
            accessor['min']=values.min(axis=0).tolist();accessor['max']=values.max(axis=0).tolist()
        document['accessors'].append(accessor)
        return len(document['accessors'])-1
    nodes=[{'name':'selected','children':[]},{'name':'remainder','children':[]}];meshes=[];counts=[0,0]
    def local(node):
        if 'matrix' in node:return np.asarray(node['matrix'],dtype=np.float64).reshape(4,4,order='F')
        x,y,z,w=node.get('rotation',[0,0,0,1])
        rotation=np.asarray([[1-2*y*y-2*z*z,2*x*y-2*z*w,2*x*z+2*y*w],[2*x*y+2*z*w,1-2*x*x-2*z*z,2*y*z-2*x*w],[2*x*z-2*y*w,2*y*z+2*x*w,1-2*x*x-2*y*y]])
        matrix=np.eye(4);matrix[:3,:3]=rotation@np.diag(node.get('scale',[1,1,1]));matrix[:3,3]=node.get('translation',[0,0,0]);return matrix
    def visit(index,parent):
        node=document['nodes'][index];world=parent@local(node)
        if 'mesh' in node:
            groups=[[],[]]
            for primitive in document['meshes'][node['mesh']]['primitives']:
                if primitive.get('mode',4)!=4 or primitive.get('targets'):raise ValueError('Split triangle primitives without morph targets')
                positions=read(primitive['attributes']['POSITION'],normalized=True)
                indices=read(primitive['indices']).reshape(-1,3) if 'indices' in primitive else np.arange(len(positions)).reshape(-1,3)
                points=positions@world[:3,:3].T+world[:3,3]
                face_labels=[]
                for triangle in points[indices]:
                    values=mapping.get(key(triangle))
                    if values is None:raise ValueError('A source face has no canonical label mapping')
                    face_labels.append(next(iter(values)))
                chosen=np.asarray(face_labels)==label
                for group,mask in enumerate((chosen,~chosen)):
                    if not mask.any():continue
                    selected_indices=indices[mask].reshape(-1);used,inverse=np.unique(selected_indices,return_inverse=True)
                    new=copy.deepcopy(primitive);attributes={}
                    for name,old_index in primitive['attributes'].items():
                        attributes[name]=append(read(old_index)[used],document['accessors'][old_index],34962)
                    new['attributes']=attributes
                    new['indices']=append(inverse.astype('<u4').reshape(-1,1),{'componentType':5125,'type':'SCALAR'},34963)
                    groups[group].append(new);counts[group]+=int(mask.sum())
            for group,primitives in enumerate(groups):
                if not primitives:continue
                meshes.append({'name':nodes[group]['name']+'/'+node.get('name',str(index)),'primitives':primitives})
                nodes[group]['children'].append(len(nodes))
                nodes.append({'name':meshes[-1]['name'],'mesh':len(meshes)-1,'matrix':world.reshape(-1,order='F').tolist()})
        for child in node.get('children',[]):visit(child,world)
    for root in document['scenes'][document.get('scene',0)]['nodes']:visit(root,np.eye(4))
    if not all(counts):raise ValueError('Selection must contain a proper subset of the source faces')
    if sum(counts)!=len(labels):raise ValueError('Source and canonical face totals differ')
    document.update(nodes=nodes,meshes=meshes,scenes=[{'name':'CGC split parts','nodes':[0,1]}],scene=0)
    document.pop('cameras',None)
    for field in ('extensionsUsed','extensionsRequired'):
        if field in document and not document[field]:document.pop(field)
    document['buffers'][0]['byteLength']=len(binary)
    encoded=json.dumps(document,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4)
    binary.extend(b'\0'*((-len(binary))%4))
    result=struct.pack('<4sII',b'glTF',2,12+8+len(encoded)+8+len(binary))+struct.pack('<II',len(encoded),0x4E4F534A)+encoded+struct.pack('<II',len(binary),0x004E4942)+binary
    Path(destination).write_bytes(result)
    return {'source_sha256':digest,'source_faces':sum(counts),'selected_faces':counts[0],'remainder_faces':counts[1],
            'geometry_preserved':True,'materials_and_images_preserved':True,'vertex_attributes_preserved':True,
            'part_names':['selected','remainder'],'label':label,'split_format':'GLB groups with original materials and compacted original vertex attributes'}


def main():
    protocol=sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import trimesh
    protocol.write(json.dumps({'ready':True,'device':'CPU','versions':{'trimesh':trimesh.__version__},'provenance':{'operation':'Canonical face-to-source triangle mapping; no generative model'}})+'\n');protocol.flush()
    for line in sys.stdin:
        try:
            task=json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):answer=dict(split(task['input'],task['labels'],task['output'],task['label']),ok=True)
        except Exception:answer={'ok':False,'error':traceback.format_exc()}
        protocol.write(json.dumps(answer)+'\n');protocol.flush()


if __name__=='__main__':main()
