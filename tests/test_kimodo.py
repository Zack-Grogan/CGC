import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from cgc.kimodo_assets import CANONICAL, derive_mntp
from cgc.motion import inspect
from cgc.planning import build_plan, UserError


def npy(shape, values):
    header=repr({'descr':'<f4','fortran_order':False,'shape':shape})+'\n'
    encoded=header.encode()
    return b'\x93NUMPY\x01\x00'+struct.pack('<H',len(encoded))+encoded+struct.pack('<'+'f'*len(values),*values)


def motion(path, rotation=None, root=None):
    rotation=rotation or [1,0,0,0,1,0,0,0,1]
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('posed_joints.npy',npy((30,77,3),[0.]*(30*77*3)))
        archive.writestr('root_positions.npy',npy((30,3),root or [0.]*(30*3)))
        archive.writestr('local_rot_mats.npy',npy((30,77,3,3),rotation*(30*77)))


class KimodoTests(unittest.TestCase):
    def test_mirror_keeps_adapters_tokenizer_and_prompt_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'adapter';source.mkdir()
            (source/'config.json').write_text(json.dumps({'_name_or_path':CANONICAL}))
            (source/'adapter_config.json').write_text(json.dumps({'base_model_name_or_path':CANONICAL,'r':16}))
            (source/'adapter_model.safetensors').write_bytes(b'original-MNTP-adapter')
            (source/'tokenizer.json').write_bytes(b'original-tokenizer')
            derived=derive_mntp(source,root/'nous',root/'derived')
            self.assertEqual((derived/'adapter_model.safetensors').read_bytes(),b'original-MNTP-adapter')
            self.assertEqual((derived/'tokenizer.json').read_bytes(),b'original-tokenizer')
            self.assertEqual(json.loads((derived/'config.json').read_text())['_name_or_path'],CANONICAL)
            self.assertEqual(json.loads((derived/'adapter_config.json').read_text()),{'base_model_name_or_path':str((root/'nous').resolve()),'r':16})
            self.assertEqual(json.loads((source/'adapter_config.json').read_text())['base_model_name_or_path'],CANONICAL)
            (source/'config.json').write_text(json.dumps({'_name_or_path':'different-encoder'}))
            with self.assertRaises(ValueError):derive_mntp(source,root/'nous',root/'other')

    def test_motion_plan_uses_queue_and_rejects_unsupported_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            opts={'prompt':'A person walks forward.','output':str(Path(tmp)/'walk.npz'),'accept_license':True}
            plan=build_plan('motion.generate',opts)
            self.assertEqual((plan.backend,plan.model),('remote','kimodo-soma-rp-v1.2'))
            self.assertEqual((plan.parameters['duration'],plan.parameters['steps']),(5,100))
            for changes in ({'duration':float('nan')},{'duration':31},{'steps':0},{'input':'unexpected.glb'},{'accept_license':False}):
                with self.subTest(changes=changes),self.assertRaises(UserError):build_plan('motion.generate',{**opts,**changes})

    def test_motion_validation_rejects_nonfinite_and_reflected_rotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'clip.npz';motion(path)
            self.assertEqual(inspect(path)['joints'],77)
            motion(path,rotation=[-1,0,0,0,1,0,0,0,1])
            with self.assertRaisesRegex(ValueError,'rotation'):inspect(path)
            motion(path,root=[float('nan')]*90)
            with self.assertRaisesRegex(ValueError,'nonfinite'):inspect(path)


if __name__=='__main__':unittest.main()
