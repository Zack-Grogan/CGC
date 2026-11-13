"""Replace one static GLB node while retaining untouched resources verbatim."""
import copy
import json
from pathlib import Path
import struct


def read(path):
    data=Path(path).read_bytes()
    if struct.unpack_from('<4sII',data)!=(b'glTF',2,len(data)):raise ValueError('Invalid GLB')
    length,kind=struct.unpack_from('<II',data,12)
    if kind!=0x4E4F534A:raise ValueError('Missing GLB document')
    document=json.loads(data[20:20+length]);size,kind=struct.unpack_from('<II',data,20+length)
    if kind!=0x004E4942 or len(document['buffers'])!=1:raise ValueError('Expected one embedded binary buffer')
    return document,bytearray(data[28+length:28+length+size])


def target_node(document,name):
    matches=[i for i,node in enumerate(document['nodes']) if node.get('name')==name]
    if not matches:
        meshes={i for i,mesh in enumerate(document['meshes']) if mesh.get('name')==name}
        matches=[i for i,node in enumerate(document['nodes']) if node.get('mesh') in meshes]
    if len(matches)!=1:raise ValueError('Select a unique source GLB node name: '+name)
    return matches[0]


def replace(source,generated,name,destination):
    document,binary=read(source);extra,extra_binary=read(generated)
    if document.get('skins') or document.get('animations'):raise ValueError('Replace static, unskinned parts')
    removed=set()
    def visit(index):
        if index in removed:return
        removed.add(index)
        for child in document['nodes'][index].get('children',[]):visit(child)
    visit(target_node(document,name))
    retained=[i for i in range(len(document['nodes'])) if i not in removed]
    node_map={old:new for new,old in enumerate(retained)}
    used_meshes=sorted({document['nodes'][i]['mesh'] for i in retained if 'mesh' in document['nodes'][i]})
    mesh_map={old:new for new,old in enumerate(used_meshes)}
    nodes=[]
    for index in retained:
        node=copy.deepcopy(document['nodes'][index])
        if 'children' in node:node['children']=[node_map[c] for c in node['children'] if c in node_map]
        if 'mesh' in node:node['mesh']=mesh_map[node['mesh']]
        nodes.append(node)
    scenes=copy.deepcopy(document['scenes'])
    for scene in scenes:scene['nodes']=[node_map[n] for n in scene['nodes'] if n in node_map]
    meshes=[copy.deepcopy(document['meshes'][i]) for i in used_meshes]
    if extra.get('images') or extra.get('textures') or extra.get('skins') or extra.get('animations'):
        raise ValueError('Generated replacement must be untextured static geometry')
    binary.extend(b'\0'*((-len(binary))%4));offset=len(binary);binary.extend(extra_binary)
    view_offset=len(document.get('bufferViews',[]));accessor_offset=len(document.get('accessors',[]));material_offset=len(document.get('materials',[]))
    for view in extra.get('bufferViews',[]):
        view=copy.deepcopy(view);view['buffer']=0;view['byteOffset']=view.get('byteOffset',0)+offset
        document.setdefault('bufferViews',[]).append(view)
    for accessor in extra.get('accessors',[]):
        accessor=copy.deepcopy(accessor)
        if 'sparse' in accessor:raise ValueError('Materialize sparse replacement accessors')
        accessor['bufferView']+=view_offset;document.setdefault('accessors',[]).append(accessor)
    document.setdefault('materials',[]).extend(extra.get('materials',[]))
    generated_mesh_offset=len(meshes)
    for mesh in extra['meshes']:
        mesh=copy.deepcopy(mesh)
        for primitive in mesh['primitives']:
            primitive['attributes']={key:value+accessor_offset for key,value in primitive['attributes'].items()}
            if 'indices' in primitive:primitive['indices']+=accessor_offset
            if 'material' in primitive:primitive['material']+=material_offset
        meshes.append(mesh)
    extra_nodes=[]
    for node in extra['nodes']:
        if 'mesh' not in node:continue
        if any(field in node for field in ('matrix','translation','rotation','scale')):raise ValueError('Bake replacement node transforms')
        extra_nodes.append({'name':name,'mesh':node['mesh']+generated_mesh_offset})
    if len(extra_nodes)!=1:raise ValueError('Export exactly one replacement mesh')
    replacement=len(nodes);nodes.extend(extra_nodes)
    scenes[document.get('scene',0)]['nodes'].append(replacement)
    document.update(nodes=nodes,meshes=meshes,scenes=scenes)
    for extension in extra.get('extensionsUsed',[]):
        if extension not in document.setdefault('extensionsUsed',[]):document['extensionsUsed'].append(extension)
    for field in ('extensionsUsed','extensionsRequired'):
        if field in document and not document[field]:document.pop(field)
    document['buffers'][0]['byteLength']=len(binary)
    encoded=json.dumps(document,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4)
    binary.extend(b'\0'*((-len(binary))%4))
    output=struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(binary))+struct.pack('<II',len(encoded),0x4E4F534A)+encoded+struct.pack('<II',len(binary),0x004E4942)+binary
    Path(destination).write_bytes(output)
    return {'removed_nodes':len(removed),'retained_nodes':len(retained),'original_material_count':material_offset,'untouched_resources_preserved':True}
