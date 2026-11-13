import tempfile
import unittest
from pathlib import Path
from cgc.remote import plan
from cgc.planning import UserError

class RemotePlans(unittest.TestCase):
    def test_generation_and_edit_reference_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'target.png'; target.write_bytes(b'target')
            reference=Path(tmp)/'reference.png'; reference.write_bytes(b'reference')
            opts={'prompt':'edit','model':'qwen-image-2.1','accept_license':True,'reference':[str(reference.resolve())],'output':str(Path(tmp)/'out.png')}
            generated=plan('image.generate',opts)
            self.assertEqual(generated.parameters['references'],[str(reference.resolve())])
            edited=plan('image.edit',{**opts,'input':str(target)})
            self.assertEqual(edited.parameters['references'],[str(target.resolve()),str(reference.resolve())])
            with self.assertRaises(UserError): plan('image.edit',opts)
    def test_sfx_duration_rejected_before_network(self):
        with self.assertRaises(UserError):
            plan('audio.sfx',{'prompt':'hatch','duration':31})
    def test_unknown_profile_not_silently_substituted(self):
        with self.assertRaises(UserError):
            plan('audio.sfx',{'prompt':'hatch','model':'voxcpm2'})
    def test_clone_requires_consent(self):
        with self.assertRaises(UserError):
            plan('audio.clone',{'prompt':'hello'})

    def test_music_source_roles_and_base_only_track_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.wav';source.write_bytes(b'audio')
            reference=Path(tmp)/'style.wav';reference.write_bytes(b'style')
            opts={'prompt':'new arrangement','input':str(source),'reference':[str(reference)],'model':'ace-step-1.5-base','track':'drums'}
            result=plan('audio.music.layer',opts)
            self.assertEqual(result.parameters['music_task'],'lego')
            self.assertEqual(result.parameters['source_index'],0)
            self.assertEqual(result.parameters['style_reference_index'],1)
            with self.assertRaises(UserError): plan('audio.music.layer',{**opts,'model':'ace-step-1.5-turbo'})

    def test_source_is_not_silently_used_by_generation(self):
        with self.assertRaises(UserError):
            plan('image.generate',{'prompt':'test','accept_license':True,'input':'anything'})

    def test_nonfinite_duration_and_invalid_dimensions(self):
        with self.assertRaises(UserError):plan('audio.sfx',{'prompt':'test','duration':float('nan')})
        with self.assertRaises(UserError):plan('image.generate',{'prompt':'test','accept_license':True,'width':513,'height':512})

    def test_trellis_requires_one_real_input(self):
        with self.assertRaises(UserError):plan('model.generate',{})
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'input.png';source.write_bytes(b'image')
            result=plan('model.generate',{'reference':[str(source)],'output':str(Path(tmp)/'model.glb')})
            self.assertEqual(result.model,'trellis2')
            self.assertFalse(result.parameters['from_latents'])
