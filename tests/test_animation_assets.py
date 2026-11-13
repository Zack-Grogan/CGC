"""Animation admission and publication contracts without model or Blender imports."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from cgc import animation_assets as animation


def write_glb(path, *, targets=('Smile',), animated=False, duplicate_node=False, clips=None):
    document = {
        'asset': {'version': '2.0'}, 'buffers': [{'byteLength': 4}],
        'meshes': [{'extras': {'targetNames': list(targets)},
                    'primitives': [{'attributes': {}, 'targets': [{} for _ in targets]}]}],
        'nodes': [{'name': 'Face', 'mesh': 0}],
    }
    if animated:
        document['animations'] = [{'name': name} for name in (clips or ['Source'])]
    if duplicate_node:
        document['nodes'].append({'name': 'Face', 'mesh': 0})
    encoded = json.dumps(document).encode()
    encoded += b' ' * (-len(encoded) % 4)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 32 + len(encoded)) +
                     struct.pack('<II', len(encoded), 0x4e4f534a) + encoded +
                     struct.pack('<II', 4, 0x004e4942) + b'\0' * 4)


def npy(dtype, shape, payload):
    header = repr({'descr': dtype, 'fortran_order': False, 'shape': shape}).encode()
    header += b' ' * ((-len(header) - 11) % 64) + b'\n'
    return b'\x93NUMPY\x01\x00' + struct.pack('<H', len(header)) + header + payload


def write_weights(path, names=None):
    names = names or ['channel_' + str(i) for i in range(68)]
    width = max(map(len, names))
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('weights.npy', npy('<f4', (2, 68), struct.pack('<136f', *([0.] * 68 + [.5] * 68))))
        archive.writestr('times.npy', npy('<f4', (2,), struct.pack('<2f', 0., 1.)))
        archive.writestr('channel_names.npy', npy('<U' + str(width), (len(names),),
                           b''.join(name.ljust(width, '\0').encode('utf-32-le') for name in names)))
    return names


class AnimationContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rig = self.root / 'rig.glb'
        self.weights = self.root / 'weights.npz'
        self.mapping = self.root / 'mapping.json'
        write_glb(self.rig)
        self.names = write_weights(self.weights)
        self.spec = {'format': 'cgc.face-map/1',
                     'channels': {self.names[0]: {'node': 'Face', 'target': 'Smile'}},
                     'ignore_channels': self.names[1:]}
        self.save_mapping()

    def save_mapping(self):
        self.mapping.write_text(json.dumps(self.spec))

    def validate(self):
        return animation.validate_face_mapping(self.rig, self.weights, self.mapping)

    def test_explicit_mapping_accepts_only_existing_named_targets(self):
        self.assertEqual(self.validate()['mapped'], 1)
        self.spec['channels'][self.names[0]]['target'] = 'InventedJaw'
        self.save_mapping()
        with self.assertRaisesRegex(ValueError, 'existing, uniquely named'):
            self.validate()

    def test_unrigged_starfall_style_mesh_cannot_acquire_facial_targets(self):
        write_glb(self.rig, targets=())
        with self.assertRaisesRegex(ValueError, 'existing, uniquely named'):
            self.validate()
        self.assertEqual(animation._doc(self.rig)['meshes'][0]['extras']['targetNames'], [])

    def test_ambiguous_nodes_and_duplicate_target_names_are_rejected(self):
        for options in ({'duplicate_node': True}, {'targets': ('Smile', 'Smile')}):
            write_glb(self.rig, **options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.validate()

    def test_channels_must_be_partitioned_without_implicit_blending(self):
        self.spec['ignore_channels'].remove(self.names[1])
        self.save_mapping()
        with self.assertRaisesRegex(ValueError, 'Every source channel'):
            self.validate()
        self.spec['channels'][self.names[1]] = {'node': 'Face', 'target': 'Smile'}
        self.save_mapping()
        with self.assertRaisesRegex(ValueError, 'implicitly combine'):
            self.validate()

    def test_duplicate_ignored_channels_and_nonfinite_weights_are_rejected(self):
        self.spec['ignore_channels'].append(self.names[1]); self.save_mapping()
        with self.assertRaisesRegex(ValueError, 'Duplicate ignored'):
            self.validate()
        self.spec['ignore_channels'].pop()
        self.spec['channels'][self.names[0]]['scale'] = float('nan'); self.save_mapping()
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.validate()

    def test_face_adapter_requires_one_named_mesh_and_68_channels(self):
        self.spec['channels'][self.names[1]] = {'node': 'Other', 'target': 'Smile'}
        self.spec['ignore_channels'].remove(self.names[1]); self.save_mapping()
        with self.assertRaisesRegex(ValueError, 'one morph mesh'):
            self.validate()
        write_weights(self.weights, self.names[:67])
        with self.assertRaisesRegex(ValueError, '68 named'):
            animation._channels(self.weights)

    def test_prepare_requires_animation_and_preserves_existing_destination(self):
        with self.assertRaisesRegex(ValueError, 'no animation'):
            animation.prepare(self.rig, self.root / 'delivery')
        output = self.root / 'delivery'; output.mkdir(); (output / 'keep').write_text('original')
        with self.assertRaisesRegex(ValueError, 'new output directory'):
            animation.prepare(self.rig, output)
        self.assertEqual((output / 'keep').read_text(), 'original')

    def test_multiple_clips_need_unique_explicit_selection(self):
        write_glb(self.rig, animated=True, clips=['Walk', 'Run'])
        with self.assertRaisesRegex(ValueError, 'exact --clip'):
            animation.prepare(self.rig, self.root / 'delivery')
        with self.assertRaisesRegex(ValueError, 'exactly one GLB'):
            animation.prepare(self.rig, self.root / 'delivery', clip='Invented')

    def test_timeout_retains_diagnostic_directory(self):
        write_glb(self.rig, animated=True)
        with patch('cgc.game_assets.find_blender', return_value='/test/Blender'), \
             patch('cgc.animation_assets.subprocess.run', side_effect=subprocess.TimeoutExpired('Blender', 1800)):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                animation.prepare(self.rig, self.root / 'delivery')
        self.assertFalse((self.root / 'delivery').exists())
        self.assertTrue(list(self.root.glob('delivery.failed-*/blender.log')))

    def fake_worker(self, command, **kwargs):
        job = json.loads(Path(command[-1]).read_text()); stage = Path(job['output'])
        write_glb(stage / 'animation.glb', animated=True)
        (stage / 'animation-report.json').write_text(json.dumps({'clip_name': job['name']}))
        return types.SimpleNamespace(returncode=0)

    def test_package_snapshots_original_and_gates_every_glb(self):
        write_glb(self.rig, animated=True); original = self.rig.read_bytes()
        with patch('cgc.game_assets.find_blender', return_value='/test/Blender'), \
             patch('cgc.animation_assets.subprocess.run', side_effect=self.fake_worker), \
             patch('cgc.standards.validate', return_value={'status': 'passed', 'errors': 0, 'warnings': 1}) as gate:
            result = animation.prepare(self.rig, self.root / 'delivery', name='ReviewedWalk')
        package = Path(result['package'])
        self.assertEqual((package / 'source.glb').read_bytes(), original)
        self.assertEqual(self.rig.read_bytes(), original)
        self.assertEqual({call.args[0].name for call in gate.call_args_list}, {'source.glb', 'animation.glb'})
        manifest = json.loads((package / 'animation-package.json').read_text())
        self.assertTrue(manifest['originals_retained_exact'])
        self.assertEqual(len(manifest['worker_sha256']), 64)
        self.assertEqual(manifest['standards']['artifacts'][0]['status'], 'passed')

    def test_failed_gate_does_not_publish_or_remove_original(self):
        write_glb(self.rig, animated=True); original = self.rig.read_bytes()
        with patch('cgc.game_assets.find_blender', return_value='/test/Blender'), \
             patch('cgc.animation_assets.subprocess.run', side_effect=self.fake_worker), \
             patch('cgc.standards.validate', return_value={'status': 'failed', 'errors': 1, 'warnings': 0}):
            with self.assertRaisesRegex(RuntimeError, 'standards'):
                animation.prepare(self.rig, self.root / 'delivery')
        self.assertFalse((self.root / 'delivery').exists())
        self.assertTrue(list(self.root.glob('delivery.failed-*')))
        self.assertEqual(self.rig.read_bytes(), original)

    def test_blender_zero_exit_without_success_report_is_a_failure(self):
        write_glb(self.rig, animated=True)
        with patch('cgc.game_assets.find_blender', return_value='/test/Blender'), \
             patch('cgc.animation_assets.subprocess.run', return_value=types.SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, 'did not finish'):
                animation.prepare(self.rig, self.root / 'delivery')
        self.assertFalse((self.root / 'delivery').exists())
        self.assertTrue(list(self.root.glob('delivery.failed-*')))

    def test_cli_contract_names_root_loop_and_face_inputs(self):
        parser = argparse.ArgumentParser(); animation.add_parser(parser.add_subparsers(dest='command'))
        args = parser.parse_args(['animation', 'retarget', '--input', 'bind.glb', '--motion', 'walk.npz',
                                 '--output-dir', 'delivery', '--name', 'Walk', '--loop', 'cycle',
                                 '--root-motion', 'in-place', '--engine', 'unity'])
        self.assertEqual((args.loop, args.root_motion, args.name), ('cycle', 'in-place', 'Walk'))
        with patch.object(animation, 'retarget', return_value={'status': 'completed'}) as run:
            animation.handle(args)
        self.assertEqual(run.call_args.args[:5], ('bind.glb', 'walk.npz', 'delivery', 'unity', 'Walk'))
        with self.assertRaisesRegex(ValueError, 'Clip name'):
            animation._clip_name('../Walk')


if __name__ == '__main__':
    unittest.main()
