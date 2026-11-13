"""Bounded, explicit static GLB triangle cleanup with source-preserving publication."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile

COMPONENTS = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
WIDTHS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _reject_extensions(value):
    if isinstance(value, dict):
        if value.get('extensions') or value.get('extensionsUsed') or value.get('extensionsRequired'):
            raise ValueError('Cleanup supports core uncompressed glTF only; extensions need a separate adapter')
        for key, item in value.items():
            if key != 'extras':
                _reject_extensions(item)
    elif isinstance(value, list):
        for item in value:
            _reject_extensions(item)


def _read(raw):
    if len(raw) < 28 or struct.unpack_from('<4sII', raw) != (b'glTF', 2, len(raw)):
        raise ValueError('Cleanup requires GLB 2.0')
    size, kind = struct.unpack_from('<II', raw, 12)
    if kind != 0x4e4f534a or size % 4 or 20 + size + 8 > len(raw):
        raise ValueError('Invalid GLB JSON chunk')
    document = json.loads(raw[20:20+size])
    binary_size, kind = struct.unpack_from('<II', raw, 20+size)
    if kind != 0x004e4942 or binary_size % 4 or 28+size+binary_size != len(raw):
        raise ValueError('Cleanup requires exactly one embedded binary chunk')
    if document.get('asset', {}).get('version') != '2.0':
        raise ValueError('Cleanup requires the glTF 2.0 asset schema')
    buffers = document.get('buffers', [])
    if len(buffers) != 1 or 'uri' in buffers[0]:
        raise ValueError('Cleanup requires one embedded buffer')
    length = buffers[0].get('byteLength')
    if type(length) is not int or not 0 <= binary_size-length <= 3:
        raise ValueError('Invalid embedded buffer length')
    if document.get('skins') or document.get('animations'):
        raise ValueError('Cleanup supports static geometry; skins and animations are refused')
    if any('skin' in node or 'weights' in node for node in document.get('nodes', [])):
        raise ValueError('Skinned nodes and morph weights are refused')
    _reject_extensions(document)
    binary = raw[28+size:28+size+length]
    for image in document.get('images', []):
        if 'uri' in image and not image['uri'].startswith('data:'):
            raise ValueError('Embed external images before cleanup')
        if ('bufferView' in image) == ('uri' in image):
            raise ValueError('Each image must have one embedded image source')
    # Reject sparse/unsupported data even if the accessor is currently unused.
    for accessor in document.get('accessors', []):
        if 'sparse' in accessor:
            raise ValueError('Sparse accessors are refused')
        if accessor.get('componentType') not in COMPONENTS or accessor.get('type') not in WIDTHS:
            raise ValueError('Unsupported accessor type')
    return document, binary


def _view(document, binary, index):
    if type(index) is not int or not 0 <= index < len(document.get('bufferViews', [])):
        raise ValueError('Invalid bufferView reference')
    view = document['bufferViews'][index]
    start, size = view.get('byteOffset', 0), view.get('byteLength')
    if view.get('buffer') != 0 or type(start) is not int or type(size) is not int or start < 0 or size < 0 or start+size > len(binary):
        raise ValueError('Buffer view exceeds embedded data')
    return view, binary[start:start+size]


def _accessor(document, binary, index, attribute=False):
    if type(index) is not int or not 0 <= index < len(document.get('accessors', [])):
        raise ValueError('Invalid accessor reference')
    accessor = document['accessors'][index]
    if 'bufferView' not in accessor:
        raise ValueError('Zero-initialized accessors are unsupported; supply explicit data')
    component, size = COMPONENTS[accessor['componentType']]
    width = WIDTHS[accessor['type']]; element = size*width
    view, payload = _view(document, binary, accessor['bufferView'])
    offset, count = accessor.get('byteOffset', 0), accessor.get('count')
    stride = view.get('byteStride', element)
    if type(offset) is not int or offset < 0 or offset % size or type(count) is not int or count < 1:
        raise ValueError('Invalid accessor extent')
    if type(stride) is not int or stride < element or stride % size or ('byteStride' in view and not 4 <= stride <= 252):
        raise ValueError('Unsupported accessor stride')
    if not attribute and 'byteStride' in view:
        raise ValueError('Strided index data is unsupported')
    if offset+(count-1)*stride+element > len(payload):
        raise ValueError('Accessor exceeds its buffer view')
    rows = [payload[offset+i*stride:offset+i*stride+element] for i in range(count)]
    values = [struct.unpack('<'+component*width, row) for row in rows]
    if any(not all(math.isfinite(value) for value in row) for row in values):
        raise ValueError('Nonfinite geometry attributes are refused')
    return accessor, rows, values


def _zero_area(a, b, c):
    u = [b[i]-a[i] for i in range(3)]; v = [c[i]-a[i] for i in range(3)]
    cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    if any(value != 0 for value in cross):
        return False
    # Confirm exact degeneracy in the stored floating-point positions. No epsilon
    # can remove thin, valid triangles through this operation.
    u = [Fraction(b[i])-Fraction(a[i]) for i in range(3)]
    v = [Fraction(c[i])-Fraction(a[i]) for i in range(3)]
    return all(u[i]*v[j] == u[j]*v[i] for i, j in ((0, 1), (0, 2), (1, 2)))


def _transform(raw, normalize_normals=False):
    """Return cleaned GLB bytes and metrics. Does not write or load a model."""
    if type(normalize_normals) is not bool:
        raise ValueError('normalize_normals must be explicit boolean')
    source, source_binary = _read(raw)
    document = deepcopy(source); document['accessors'] = []; document['bufferViews'] = []
    binary = bytearray(); primitives = []; image_hashes = []

    def append_view(payload, template=None, **properties):
        binary.extend(b'\0'*(-len(binary) % 4)); offset = len(binary); binary.extend(payload)
        view = deepcopy(template or {}); view.update(buffer=0, byteOffset=offset, byteLength=len(payload), **properties)
        document['bufferViews'].append(view)
        return len(document['bufferViews'])-1

    def append_accessor(template, rows, values, attribute):
        accessor = deepcopy(template)
        accessor.pop('byteOffset', None); accessor.pop('bufferView', None)
        size = len(rows[0]); stride = (size+3)//4*4 if attribute else size
        payload = b''.join(row+b'\0'*(stride-size) for row in rows)
        properties = {'target': 34962 if attribute else 34963}
        if stride != size:
            properties['byteStride'] = stride
        accessor['bufferView'] = append_view(payload, **properties)
        accessor['count'] = len(rows)
        for field, operation in (('min', min), ('max', max)):
            if field in template or (attribute and template['type'] == 'VEC3' and template.get('_position')):
                accessor[field] = [operation(row[i] for row in values) for i in range(len(values[0]))]
        accessor.pop('_position', None)
        document['accessors'].append(accessor)
        return len(document['accessors'])-1

    for index, image in enumerate(document.get('images', [])):
        if 'bufferView' in image:
            view, payload = _view(source, source_binary, image['bufferView'])
            if 'byteStride' in view:
                raise ValueError('Image buffer views cannot be strided')
            image['bufferView'] = append_view(payload, view)
            image_hashes.append({'image': index, 'bytes': len(payload), 'sha256': _hash(payload)})
        else:
            image_hashes.append({'image': index, 'data_uri_sha256': _hash(image['uri'].encode())})
    for mesh_index, mesh in enumerate(source.get('meshes', [])):
        if 'weights' in mesh:
            raise ValueError('Morph weights are refused')
        for primitive_index, primitive in enumerate(mesh.get('primitives', [])):
            if primitive.get('mode', 4) != 4 or 'targets' in primitive:
                raise ValueError('Cleanup supports static TRIANGLES without morph targets')
            attributes = primitive.get('attributes', {})
            if 'POSITION' not in attributes or any(name.startswith(('JOINTS_', 'WEIGHTS_')) for name in attributes):
                raise ValueError('Supply static position attributes without skin weights')
            decoded = {name: _accessor(source, source_binary, index, True) for name, index in attributes.items()}
            position_accessor, _, positions = decoded['POSITION']
            if position_accessor['type'] != 'VEC3' or position_accessor['componentType'] != 5126 or position_accessor.get('normalized'):
                raise ValueError('Cleanup requires FLOAT VEC3 positions')
            count = len(positions)
            if any(len(item[1]) != count for item in decoded.values()):
                raise ValueError('Primitive attributes must have identical vertex counts')
            if 'indices' in primitive:
                index_accessor, _, index_values = _accessor(source, source_binary, primitive['indices'])
                if index_accessor['type'] != 'SCALAR' or index_accessor['componentType'] not in (5121, 5123, 5125) or index_accessor.get('normalized'):
                    raise ValueError('Triangle indices must be unsigned integers')
                indices = [value[0] for value in index_values]
            else:
                index_accessor = {'componentType': 5125, 'type': 'SCALAR'}; indices = list(range(count))
            if len(indices) % 3 or any(index >= count for index in indices):
                raise ValueError('Invalid triangle index extent')
            kept = []; removed = []
            for offset in range(0, len(indices), 3):
                triangle = indices[offset:offset+3]
                if _zero_area(*(positions[index] for index in triangle)):
                    removed.append(offset//3)
                else:
                    kept.extend(triangle)
            if not kept:
                raise ValueError(f'Mesh {mesh_index} primitive {primitive_index} has no nondegenerate triangles; cleanup refuses to remove the entire primitive')
            used = sorted(set(kept)); lookup = {old: new for new, old in enumerate(used)}
            target = document['meshes'][mesh_index]['primitives'][primitive_index]
            normalized_count = 0; preserved = {}
            for name, (accessor, rows, values) in decoded.items():
                selected_rows = [rows[index] for index in used]; selected_values = [values[index] for index in used]
                original_selected_hash = _hash(b''.join(selected_rows))
                if name == 'NORMAL':
                    if accessor['type'] != 'VEC3' or accessor['componentType'] != 5126:
                        raise ValueError('Cleanup supports FLOAT VEC3 normals only')
                    for index, value in enumerate(selected_values):
                        length = math.hypot(*value)
                        if length == 0:
                            raise ValueError('A zero normal remains on a retained vertex; author a compatible normal repair before cleanup')
                        if normalize_normals:
                            encoded = struct.pack('<3f', *(component/length for component in value))
                            normalized_count += encoded != selected_rows[index]
                            selected_rows[index] = encoded; selected_values[index] = struct.unpack('<3f', encoded)
                template = dict(accessor)
                if name == 'POSITION':
                    template['_position'] = True
                target['attributes'][name] = append_accessor(template, selected_rows, selected_values, True)
                preserved[name] = {'source_retained_values_sha256': original_selected_hash, 'output_values_sha256': _hash(b''.join(selected_rows)), 'retained_values_exact': original_selected_hash == _hash(b''.join(selected_rows))}
            remapped = [(lookup[index],) for index in kept]
            code = COMPONENTS[index_accessor['componentType']][0]
            target['indices'] = append_accessor(index_accessor, [struct.pack('<'+code, value[0]) for value in remapped], remapped, False)
            primitives.append({'mesh': mesh_index, 'primitive': primitive_index, 'triangles_before': len(indices)//3, 'triangles_after': len(kept)//3,
                               'zero_area_triangles_removed': len(removed), 'removed_triangle_indices': removed,
                               'vertices_before': count, 'vertices_after': len(used), 'unused_vertices_removed': count-len(used),
                               'removed_vertex_indices': sorted(set(range(count))-set(used)), 'normals_normalized': normalized_count, 'attributes': preserved})
    if not primitives:
        raise ValueError('Cleanup requires triangle geometry')
    binary.extend(b'\0'*(-len(binary) % 4)); document['buffers'][0]['byteLength'] = len(binary)
    encoded = json.dumps(document, separators=(',', ':'), allow_nan=False).encode(); encoded += b' '*(-len(encoded) % 4)
    cleaned = struct.pack('<4sII', b'glTF', 2, 28+len(encoded)+len(binary))+struct.pack('<II', len(encoded), 0x4e4f534a)+encoded+struct.pack('<II', len(binary), 0x004e4942)+binary
    return cleaned, {'primitives': primitives, 'images': image_hashes,
                     'zero_area_triangles_removed': sum(row['zero_area_triangles_removed'] for row in primitives),
                     'unused_vertex_slots_removed': sum(row['unused_vertices_removed'] for row in primitives),
                     'normals_normalized': sum(row['normals_normalized'] for row in primitives),
                     'normal_policy': 'normalize nonzero retained normals explicitly' if normalize_normals else 'retain normal samples exactly',
                     'material_and_node_metadata_exact': all(document.get(key) == source.get(key) for key in ('materials', 'textures', 'samplers', 'nodes', 'scenes', 'scene'))}


def transform(raw, normalize_normals=False):
    """Validate supported structure and return an additive cleanup derivative."""
    try:
        return _transform(raw, normalize_normals)
    except (KeyError, IndexError, TypeError, AttributeError, struct.error, OverflowError) as error:
        raise ValueError('Malformed or unsupported static GLB structure: '+str(error)) from error


def clean_asset(source, output, normalize_normals=False):
    source = Path(source).expanduser().resolve(strict=True); output = Path(output).expanduser().resolve()
    if source.suffix.lower() != '.glb' or output.suffix.lower() != '.glb':
        raise ValueError('Cleanup requires GLB input and output')
    receipt = Path(str(output)+'.clean.json'); validation_path = Path(str(output)+'.validation.json')
    if any(path.exists() for path in (output, receipt, validation_path)):
        raise ValueError('Cleanup output or report already exists; select a new path')
    raw = source.read_bytes(); source_hash = _hash(raw)
    cleaned, metrics = transform(raw, normalize_normals)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.cgc-clean-', dir=output.parent)); published = []
    try:
        temporary = stage/'cleaned.glb'; temporary.write_bytes(cleaned)
        from .standards import validate
        validation = validate(temporary, stage/'validation.json')
        if validation['status'] != 'passed':
            raise RuntimeError('Cleaned derivative failed the official Khronos gate')
        if _hash(source.read_bytes()) != source_hash:
            raise ValueError('Source changed during cleanup; no derivative was published')
        validation['source'] = str(output); validation['resource_root'] = str(output.parent); validation['report_path'] = str(validation_path)
        (stage/'validation.json').write_text(json.dumps(validation, indent=2))
        report = {'status': 'completed', 'operation': 'asset.clean', 'source': str(source), 'output': str(output),
                  'source_sha256': source_hash, 'output_sha256': _hash(cleaned), 'source_preserved': True,
                  'normalize_normals': normalize_normals, **metrics,
                  'standards': {'status': validation['status'], 'errors': validation['errors'], 'warnings': validation['warnings'], 'report': str(validation_path)},
                  'limits': ['Only exactly zero-area triangles and unreferenced vertex slots are removed.', 'No welding, remeshing, topology inference, smoothing, or artistic approval is performed.', 'Normal values change only with explicit normalization; zero retained normals are refused.']}
        (stage/'receipt.json').write_text(json.dumps(report, indent=2, allow_nan=False))
        # Same-filesystem hard links publish complete files without replacing an
        # existing destination. Commit the GLB last after its reports are ready.
        for staged, destination in ((stage/'validation.json', validation_path), (stage/'receipt.json', receipt), (temporary, output)):
            os.link(staged, destination); published.append(destination)
        shutil.rmtree(stage)
        return report
    except BaseException as error:
        for path in reversed(published):
            path.unlink()
        if stage.exists():
            (stage/'source.glb').write_bytes(raw)
            (stage/'failure.json').write_text(json.dumps({'status': 'failed', 'error': str(error), 'source_sha256': source_hash}, indent=2))
            failed = output.parent/(output.name+'.failed-'+stage.name.rsplit('-', 1)[-1]); os.rename(stage, failed)
        raise
