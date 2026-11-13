"""Control-contract tests. These do not rate generated content."""
import tempfile
import json
import struct
import unittest
from pathlib import Path

from cgc.planning import UserError
from cgc.remote import plan
from cgc.remote_worker import image_controls,effective_controls


class QualityControls(unittest.TestCase):
    def test_explicit_settings_override_compute_budgets(self):
        p=plan('image.generate',{'prompt':'crate','model':'qwen-image-2.1','quality':'draft','steps':40})
        self.assertEqual(p.parameters['steps'],40)
        self.assertEqual(p.parameters['quality_profile']['explicit_overrides']['steps'],40)
        self.assertFalse(p.parameters['quality_profile']['guarantees_quality'])

    def test_turbo_never_gets_a_different_schedule_or_inert_negative(self):
        p=plan('image.generate',{'prompt':'crate','quality':'detail'})
        self.assertEqual(p.model,'qwen-image-2.1-turbo')
        self.assertEqual(image_controls(p.model,p.parameters),{})
        for controls in ({'steps':40},{'negative_prompt':'blur'},{'guidance_scale':3}):
            with self.subTest(controls=controls),self.assertRaises(UserError):plan('image.generate',{'prompt':'crate',**controls})

    def test_base_negative_conditioning_must_be_active(self):
        for controls in ({'negative_prompt':'blur'},{'guidance_scale':2}):
            with self.assertRaises(UserError):plan('image.generate',{'prompt':'crate','model':'qwen-image-2.1',**controls})
        p=plan('image.edit',{'prompt':'recolor','model':'qwen-image-2.1','input':__file__,'negative_prompt':'','guidance_scale':2.5})
        mapped=image_controls(p.model,p.parameters)
        self.assertEqual(mapped['true_cfg_scale'],2.5)
        self.assertEqual(mapped['negative_prompt'],'')
        self.assertNotIn('guidance_scale',mapped)

    def test_unused_controls_reject_before_network(self):
        for operation,options in [('audio.speak',{'prompt':'hello','steps':10}),('audio.sfx',{'prompt':'hatch','guidance_scale':4}),('motion.generate',{'prompt':'walk','accept_license':True,'cfg_scale':3}),('audio.music',{'prompt':'music','guidance_scale':7})]:
            with self.subTest(operation=operation),self.assertRaises(UserError):plan(operation,options)

    def test_source_only_music_modes_select_base_and_validate_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.wav';source.write_bytes(b'fixture')
            p=plan('audio.music.extract',{'input':str(source),'track':'drums','steps':64,'guidance_scale':7})
            self.assertEqual(p.model,'ace-step-1.5-base')
            self.assertEqual(p.parameters['steps'],64)
            for controls in ({'bpm':0},{'start':float('nan')},{'steps':0}):
                with self.assertRaises(UserError):plan('audio.music.extract',{'input':str(source),'track':'drums',**controls})

    def test_zero_trellis_controls_and_unused_reexport_seed_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.png';source.write_bytes(b'fixture')
            for controls in ({'texture_size':0},{'decimation_target':0},{'resolution':''}):
                with self.assertRaises(UserError):plan('model.generate',{'reference':[str(source)],**controls})
            with self.assertRaises(UserError):plan('model.generate',{'from_latents':str(source),'seed':42})
            for controls in ({'resolution':'1024'},{'save_latents':True}):
                with self.assertRaises(UserError):plan('model.generate',{'from_latents':str(source),**controls})
            export=plan('model.generate',{'from_latents':str(source),'quality':'detail'})
            self.assertNotIn('resolution',export.parameters)
            self.assertNotIn('save_latents',export.parameters)
            p=plan('model.generate',{'reference':[str(source)],'quality':'detail','save_latents':False})
            self.assertFalse(p.parameters['save_latents'])
            self.assertEqual(p.parameters['decimation_target'],300000)

    def test_sfx_and_pinned_voice_native_controls(self):
        p=plan('audio.sfx',{'prompt':'hatch','steps':100,'cfg_scale':4})
        self.assertEqual(p.parameters['cfg_scale'],4)
        p=plan('audio.design',{'prompt':'hello','direction':'calm','steps':10,'guidance_scale':2})
        self.assertEqual(effective_controls(p.model,p.parameters)['guidance_scale'],2)
        with self.assertRaises(UserError):plan('audio.design',{'prompt':'hello','direction':'calm','seed':42})

    def test_published_non_square_canvas_is_exposed_without_unbounded_sizes(self):
        p=plan('image.generate',{'prompt':'poster','width':2752,'height':1536})
        self.assertEqual((p.parameters['width'],p.parameters['height']),(2752,1536))
        with self.assertRaises(UserError):plan('image.generate',{'prompt':'poster','width':3072,'height':3072})

    def test_texture_plan_keeps_geometry_controls_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            mesh=Path(directory)/'mesh.glb'
            document={'asset':{'version':'2.0'},'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
                      'accessors':[{'bufferView':0,'componentType':5126,'type':'VEC3','count':3,'min':[0,0,0],'max':[1,1,0]}],
                      'nodes':[{'mesh':0}],'scenes':[{'nodes':[0]}],'scene':0,'buffers':[{'byteLength':36}],
                      'bufferViews':[{'buffer':0,'byteLength':36}]}
            chunk=json.dumps(document).encode();chunk+=b' '*((-len(chunk))%4)
            binary=struct.pack('<9f',0,0,0,1,0,0,0,1,0)
            mesh.write_bytes(struct.pack('<4sIIII',b'glTF',2,28+len(chunk)+len(binary),len(chunk),0x4E4F534A)+chunk+struct.pack('<II',len(binary),0x004E4942)+binary)
            image=Path(directory)/'reference.png';image.write_bytes(b'fixture')
            options={'input':str(mesh),'reference':[str(image)],'quality':'detail'}
            p=plan('model.texture',options)
            self.assertEqual(p.parameters['references'],[str(mesh.resolve()),str(image.resolve())])
            self.assertEqual(p.parameters['texture_size'],2048)
            self.assertNotIn('decimation_target',p.parameters)
            self.assertNotIn('save_latents',p.parameters)
            for controls in ({'resolution':'1536'},{'decimation_target':50000},{'save_latents':True},{'reference':[]}):
                with self.subTest(controls=controls),self.assertRaises(UserError):plan('model.texture',{**options,**controls})


if __name__=='__main__':unittest.main()
