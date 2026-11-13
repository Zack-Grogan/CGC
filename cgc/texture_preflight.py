"""Local static GLB checks before paying for native texturing; stdlib only."""
import json
import math
from pathlib import Path
import struct


def inspect_source(path):
    data=Path(path).read_bytes()
    if len(data)<28 or struct.unpack_from('<4sII',data)!=(b'glTF',2,len(data)):
        raise ValueError('Texturing requires a GLB 2.0 file')
    length,kind=struct.unpack_from('<II',data,12)
    if kind!=0x4e4f534a:raise ValueError('GLB JSON is missing')
    document=json.loads(data[20:20+length]);offset=20+length
    size,kind=struct.unpack_from('<II',data,offset)
    if kind!=0x004e4942 or offset+8+size!=len(data):raise ValueError('Texturing requires one embedded GLB binary buffer')
    binary=data[offset+8:]
    if len(document.get('buffers',[]))!=1 or document['buffers'][0].get('uri'):
        raise ValueError('Embed geometry in one GLB binary buffer before texturing')
    if document.get('skins') or document.get('animations'):raise ValueError('Texture static, unskinned geometry before rigging')
    if document.get('extensionsRequired'):raise ValueError('Decode required GLB extensions before texturing')
    if any('uri' in image and not image['uri'].startswith('data:') for image in document.get('images',[])):
        raise ValueError('Embed external images before texturing')
    identity=((1.,0.,0.,0.),(0.,1.,0.,0.),(0.,0.,1.,0.),(0.,0.,0.,1.))
    def multiply(a,b):return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)) for i in range(4))
    def matrix(node):
        if 'matrix' in node:
            values=node['matrix']
            if len(values)!=16:raise ValueError('Invalid node matrix')
            result=tuple(tuple(values[j*4+i] for j in range(4)) for i in range(4))
        else:
            x,y,z,w=node.get('rotation',(0.,0.,0.,1.));s=node.get('scale',(1.,1.,1.));t=node.get('translation',(0.,0.,0.))
            if abs(x*x+y*y+z*z+w*w-1)>1e-4:raise ValueError('Normalize node rotations before texturing')
            rotation=((1-2*y*y-2*z*z,2*x*y-2*z*w,2*x*z+2*y*w),
                      (2*x*y+2*z*w,1-2*x*x-2*z*z,2*y*z-2*x*w),
                      (2*x*z-2*y*w,2*y*z+2*x*w,1-2*x*x-2*y*y))
            result=tuple(tuple(rotation[i][j]*s[j] for j in range(3))+(t[i],) for i in range(3))+(identity[3],)
        if not all(math.isfinite(v) for row in result for v in row):raise ValueError('Node transforms must be finite')
        a,b,c=result[0][:3];d,e,f=result[1][:3];g,h,i=result[2][:3]
        if abs(a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g))<1e-12:raise ValueError('Bake singular mesh transforms before texturing')
        return result
    def accessor(index,positions=False):
        value=document['accessors'][index]
        if 'sparse' in value or 'bufferView' not in value or value.get('normalized'):
            raise ValueError('Materialize sparse or normalized geometry accessors before texturing')
        component=value['componentType'];formats={5121:'B',5123:'H',5125:'I',5126:'f'}
        expected='VEC3' if positions else 'SCALAR'
        if value['type']!=expected or component not in formats or (positions and component!=5126) or (not positions and component==5126):
            raise ValueError('Use FLOAT VEC3 positions and unsigned integer triangle indices')
        view=document['bufferViews'][value['bufferView']]
        if view.get('buffer',0)!=0:raise ValueError('Expected the embedded geometry buffer')
        count=value['count'];components=3 if positions else 1;fmt='<'+formats[component]*components;width=struct.calcsize(fmt)
        start=view.get('byteOffset',0)+value.get('byteOffset',0);stride=view.get('byteStride',width)
        end=start+(count-1)*stride+width
        if count<1 or stride<width or start<0 or end>len(binary) or end>view.get('byteOffset',0)+view['byteLength']:
            raise ValueError('Invalid GLB geometry accessor bounds')
        rows=[struct.unpack_from(fmt,binary,start+n*stride) for n in range(count)]
        if positions and not all(math.isfinite(v) for row in rows for v in row):raise ValueError('Mesh positions must be finite')
        return rows if positions else [row[0] for row in rows]
    seen_nodes=set();owners={};faces=0;duplicates=0;mesh_nodes=0
    def visit(index,parent):
        nonlocal faces,duplicates,mesh_nodes
        if type(index) is not int or not 0<=index<len(document.get('nodes',[])) or index in seen_nodes:
            raise ValueError('Invalid or repeated scene node hierarchy')
        seen_nodes.add(index);node=document['nodes'][index];world=multiply(parent,matrix(node))
        if 'mesh' in node:
            mesh_nodes+=1
            for primitive in document['meshes'][node['mesh']]['primitives']:
                if primitive.get('mode',4)!=4 or primitive.get('targets') or primitive.get('extensions'):
                    raise ValueError('Bake morph targets, decode compression, and triangulate before texturing')
                local=accessor(primitive['attributes']['POSITION'],True)
                vertices=[tuple(sum(world[i][j]*point[j] for j in range(3))+world[i][3] for i in range(3)) for point in local]
                indices=accessor(primitive['indices']) if 'indices' in primitive else list(range(len(vertices)))
                if len(indices)%3 or any(not 0<=i<len(vertices) for i in indices):raise ValueError('Invalid triangle indices')
                for n in range(0,len(indices),3):
                    triangle=[vertices[i] for i in indices[n:n+3]];key=tuple(sorted(triangle))
                    edge_a=[triangle[1][i]-triangle[0][i] for i in range(3)];edge_b=[triangle[2][i]-triangle[0][i] for i in range(3)]
                    cross=[edge_a[1]*edge_b[2]-edge_a[2]*edge_b[1],edge_a[2]*edge_b[0]-edge_a[0]*edge_b[2],edge_a[0]*edge_b[1]-edge_a[1]*edge_b[0]]
                    if not any(cross):raise ValueError('Remove zero-area source triangles before texturing')
                    if key in owners:
                        if owners[key]!=index:raise ValueError('Coincident source triangles belong to different nodes; separate them before texturing')
                        duplicates+=1
                    owners[key]=index;faces+=1
        for child in node.get('children',[]):visit(child,world)
    scenes=document.get('scenes',[]);selected=document.get('scene',0)
    if not scenes or not 0<=selected<len(scenes):raise ValueError('Define a default GLB scene before texturing')
    for index in scenes[selected].get('nodes',[]):visit(index,identity)
    if not faces:raise ValueError('No static triangle geometry to texture')
    return {'triangles':faces,'mesh_nodes':mesh_nodes,'same_node_duplicate_triangles':duplicates,
            'cross_node_coincidences':False,'preflight':'static triangle ownership; native output surface is checked again'}
