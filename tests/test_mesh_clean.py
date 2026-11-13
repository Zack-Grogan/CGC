"""Preservation and refusal tests for bounded static GLB cleanup."""
from copy import deepcopy
import json
import contextlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from cgc.mesh_clean import _accessor, _read, _view, clean_asset, transform


def encode(document, binary):
    binary += b'\0'*(-len(binary) % 4)
    document = deepcopy(document); document['buffers'] = [{'byteLength': len(binary)}]
    text = json.dumps(document).encode(); text += b' '*(-len(text) % 4)
    return struct.pack('<4sII', b'glTF', 2, 28+len(text)+len(binary))+struct.pack('<II', len(text), 0x4e4f534a)+text+struct.pack('<II', len(binary), 0x004e4942)+binary


def fixture(normal=(0., 0., 1.), tiny=False):
    positions = [(0., 0., 0.), (1., 0., 0.), (0., 1e-20 if tiny else 1., 0.),
                 (2., 0., 0.), (3., 0., 0.), (4., 0., 0.), (9., 9., 9.)]
    rows = [struct.pack('<8f', *position, *(normal if i < 3 else (0., 0., 0.)), i/8, 1-i/8) for i, position in enumerate(positions)]
    attributes = b''.join(rows)
    colors = bytes(range(28)); indices = struct.pack('<6H', 2, 1, 0, 3, 4, 5)
    def chunk(kind, payload):
        return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload))
    image = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>2I5B', 1, 1, 8, 6, 0, 0, 0))+chunk(b'IDAT', zlib.compress(b'\0\x12\x34\x56\xff'))+chunk(b'IEND', b'')
    binary = attributes+colors+indices+image
    document = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0], 'name': 'Scene'}],
                'nodes': [{'mesh': 0, 'name': 'Prop', 'translation': [1, 2, 3], 'rotation': [0, 0, 0, 1], 'extras': {'authored': True}}],
                'meshes': [{'name': 'Master', 'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2, 'COLOR_0': 3}, 'indices': 4, 'material': 0, 'extras': {'keep': 'exact'}}]}],
                'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}, 'doubleSided': True}],
                'textures': [{'source': 0}], 'images': [{'bufferView': 3, 'mimeType': 'image/png'}],
                'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(attributes), 'byteStride': 32},
                                {'buffer': 0, 'byteOffset': len(attributes), 'byteLength': len(colors)},
                                {'buffer': 0, 'byteOffset': len(attributes)+len(colors), 'byteLength': len(indices)},
                                {'buffer': 0, 'byteOffset': len(attributes)+len(colors)+len(indices), 'byteLength': len(image)}],
                'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 7, 'min': [0, 0, 0], 'max': [9, 9, 9]},
                              {'bufferView': 0, 'byteOffset': 12, 'componentType': 5126, 'type': 'VEC3', 'count': 7},
                              {'bufferView': 0, 'byteOffset': 24, 'componentType': 5126, 'type': 'VEC2', 'count': 7},
                              {'bufferView': 1, 'componentType': 5121, 'type': 'VEC4', 'count': 7, 'normalized': True},
                              {'bufferView': 2, 'componentType': 5123, 'type': 'SCALAR', 'count': 6}]}
    return encode(document, binary)


class MeshCleanContracts(unittest.TestCase):
    def test_removes_only_zero_area_faces_and_preserves_samples_winding_and_resources(self):
        raw = fixture(); source, source_binary = _read(raw)
        cleaned, metrics = transform(raw); output, output_binary = _read(cleaned)
        primitive = output['meshes'][0]['primitives'][0]
        self.assertEqual(_accessor(output, output_binary, primitive['indices'])[2], [(2,), (1,), (0,)])
        self.assertEqual(metrics['zero_area_triangles_removed'], 1)
        self.assertEqual(metrics['unused_vertex_slots_removed'], 4)
        self.assertEqual(metrics['normals_normalized'], 0)
        self.assertEqual(metrics['primitives'][0]['removed_vertex_indices'], [3, 4, 5, 6])
        for semantic, original in source['meshes'][0]['primitives'][0]['attributes'].items():
            original_rows = _accessor(source, source_binary, original, True)[1]
            output_rows = _accessor(output, output_binary, primitive['attributes'][semantic], True)[1]
            self.assertEqual(output_rows, original_rows[:3], semantic)
        for key in ('materials', 'nodes', 'scenes', 'scene', 'textures'):
            self.assertEqual(output[key], source[key], key)
        self.assertEqual(_view(source, source_binary, source['images'][0]['bufferView'])[1], _view(output, output_binary, output['images'][0]['bufferView'])[1])
        self.assertEqual(primitive['extras'], {'keep': 'exact'})

    def test_nearly_degenerate_but_nonzero_triangle_is_retained(self):
        _, metrics = transform(fixture(tiny=True))
        self.assertEqual(metrics['primitives'][0]['triangles_after'], 1)
        self.assertEqual(metrics['primitives'][0]['removed_triangle_indices'], [1])

    def test_normalization_requires_explicit_flag_and_changes_only_normals(self):
        raw = fixture(normal=(0., 0., 2.))
        _, retained = transform(raw)
        cleaned, changed = transform(raw, normalize_normals=True)
        self.assertEqual(retained['normals_normalized'], 0)
        self.assertEqual(changed['normals_normalized'], 3)
        attributes = changed['primitives'][0]['attributes']
        self.assertFalse(attributes['NORMAL']['retained_values_exact'])
        self.assertTrue(all(row['retained_values_exact'] for name, row in attributes.items() if name != 'NORMAL'))
        document, binary = _read(cleaned)
        normal_index = document['meshes'][0]['primitives'][0]['attributes']['NORMAL']
        self.assertEqual(_accessor(document, binary, normal_index, True)[2], [(0., 0., 1.)]*3)
        with self.assertRaisesRegex(ValueError, 'zero normal remains'):
            transform(fixture(normal=(0., 0., 0.)), normalize_normals=True)

    def test_unsafe_geometry_is_refused_before_any_output_directory_is_written(self):
        base, binary = _read(fixture())
        changes = [lambda d: d.update(skins=[{'joints': [0]}]),
                   lambda d: d.update(animations=[{}]),
                   lambda d: d.update(extensionsUsed=['KHR_draco_mesh_compression']),
                   lambda d: d['accessors'][0].update(sparse={'count': 1}),
                   lambda d: d['meshes'][0]['primitives'][0].update(mode=5),
                   lambda d: d['meshes'][0]['primitives'][0].update(targets=[{'POSITION': 0}]),
                   lambda d: d['images'][0].update(uri='external.png')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source.glb'; output = root/'uncreated'/'result.glb'
            for mutation in changes:
                document = deepcopy(base); mutation(document); source.write_bytes(encode(document, binary))
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    clean_asset(source, output)
                self.assertFalse(output.parent.exists())

    def test_all_degenerate_primitive_is_refused(self):
        document, binary = _read(fixture()); index = document['accessors'][4]; index['count'] = 3; index['byteOffset'] = 6
        with self.assertRaisesRegex(ValueError, 'entire primitive'):
            transform(encode(document, binary))

    def test_nonindexed_triangle_geometry_is_compacted(self):
        document, binary = _read(fixture())
        primitive = document['meshes'][0]['primitives'][0]; primitive.pop('indices')
        for accessor in document['accessors'][:4]:
            accessor['count'] = 6
        _, metrics = transform(encode(document, binary))
        self.assertEqual(metrics['primitives'][0]['triangles_after'], 1)
        self.assertEqual(metrics['unused_vertex_slots_removed'], 3)

    def test_publication_gates_output_and_preserves_original_and_existing_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source.glb'; output = root/'clean.glb'; raw = fixture(); source.write_bytes(raw)
            with patch('cgc.standards.validate', return_value={'status': 'passed', 'errors': 0, 'warnings': 0}) as gate:
                report = clean_asset(source, output)
            self.assertEqual(source.read_bytes(), raw); self.assertEqual(report['standards']['status'], 'passed'); gate.assert_called_once()
            self.assertTrue(Path(str(output)+'.clean.json').is_file())
            self.assertTrue(Path(str(output)+'.validation.json').is_file())
            previous = output.read_bytes()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                clean_asset(source, output)
            self.assertEqual(output.read_bytes(), previous)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                clean_asset(source, source)
            self.assertEqual(source.read_bytes(), raw)

    def test_failed_gate_keeps_evidence_without_publishing_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source.glb'; source.write_bytes(fixture()); output = root/'clean.glb'
            with patch('cgc.standards.validate', return_value={'status': 'failed', 'errors': 1, 'warnings': 0}):
                with self.assertRaisesRegex(RuntimeError, 'Khronos'):
                    clean_asset(source, output)
            self.assertFalse(output.exists()); self.assertFalse(Path(str(output)+'.clean.json').exists())
            self.assertTrue(list(root.glob('clean.glb.failed-*/failure.json')))

    def test_existing_receipt_and_publication_race_never_replace_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source.glb'; source.write_bytes(fixture()); output = root/'clean.glb'
            receipt = Path(str(output)+'.clean.json'); receipt.write_text('prior receipt')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                clean_asset(source, output)
            self.assertEqual(receipt.read_text(), 'prior receipt'); receipt.unlink()
            real_link = os.link
            def raced_link(staged, destination):
                if destination == output.resolve():
                    output.write_bytes(b'another writer')
                    raise FileExistsError('concurrent output appeared')
                return real_link(staged, destination)
            with patch('cgc.standards.validate', return_value={'status': 'passed', 'errors': 0, 'warnings': 0}), \
                 patch('cgc.mesh_clean.os.link', side_effect=raced_link):
                with self.assertRaises(FileExistsError):
                    clean_asset(source, output)
            self.assertEqual(output.read_bytes(), b'another writer')
            self.assertFalse(receipt.exists()); self.assertFalse(Path(str(output)+'.validation.json').exists())
            self.assertTrue(list(root.glob('clean.glb.failed-*/cleaned.glb')))

    def test_cli_dispatch_uses_explicit_cleanup_and_normal_policy(self):
        from cgc.cli import main
        with patch('cgc.mesh_clean.clean_asset', return_value={'status': 'completed'}) as clean, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['asset', 'clean', '--input', 'raw.glb', '--output', 'clean.glb', '--normalize-normals', '--json']), 0)
        clean.assert_called_once_with('raw.glb', 'clean.glb', True)


if __name__ == '__main__':
    unittest.main()
