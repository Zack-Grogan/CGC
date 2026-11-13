import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cgc.catalog import MODELS
from cgc.planning import UserError, build_plan, dimensions
from cgc.runtime import environment, setup_commands, validate_output

class PlanningTests(unittest.TestCase):
    def test_local_requirement_never_routes_remote_only_operations_to_beam(self):
        with patch('cgc.remote.plan') as remote:
            for operation in ('audio.music.generate','audio.music.cover','audio.sfx','model.generate','motion.generate'):
                with self.subTest(operation=operation), self.assertRaisesRegex(UserError,'requires Beam'):
                    build_plan(operation,{'backend':'local'})
            remote.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ref = self.root / 'reference.wav'
        self.ref.write_bytes(b'RIFF' + b'\0'*40)

    def plan(self, operation='image.generate', **opts):
        return build_plan(operation, {'backend':'local', 'prompt':'Make something wonderful', **({'seed':42} if operation.startswith('image.') else {}), **opts}, self.root)

    def test_klein_uses_prequantized_repository(self):
        p = self.plan(model="klein")
        self.assertIn('mflux-community/flux2-klein-4b-mflux-q4', p.command)
        self.assertIn('--base-model', p.command)
        self.assertNotIn('-q', p.command)
        self.assertIn('--low-ram', p.command)
        self.assertFalse(p.download)
        self.assertFalse((self.root / 'outputs').exists())

    def test_z_image_binary(self):
        p = self.plan(model='z-image')
        self.assertTrue(p.command[0].endswith('mflux-generate-z-image-turbo'))
        self.assertIn('9', p.command)

    def test_explicit_download(self):
        self.assertTrue(self.plan(download=True).download)

    def test_prompt_is_single_argument(self):
        prompt = "$(rm -rf /) ' ; hello\nworld"
        p = self.plan(prompt=prompt)
        self.assertEqual(p.command[p.command.index('--prompt')+1], prompt)

    def test_aspect(self):
        self.assertEqual(dimensions('landscape',768), (768,432))
        self.assertEqual(dimensions('social',1024), (816,1024))

    def test_reject_dimensions(self):
        for kw in ({'width':768}, {'width':769,'height':768}, {'size':100}, {'aspect':'nonsense'}):
            with self.assertRaises(UserError): self.plan(**kw)

    def test_reject_blank(self):
        with self.assertRaises(UserError): self.plan(prompt='   ')

    def test_reject_incompatible_model(self):
        with self.assertRaises(UserError): self.plan('image.edit',model='z-image',reference=[str(self.ref)])
        with self.assertRaises(UserError): self.plan('audio.speak',model='qwen3-clone')

    def test_existing_output_not_overwritten(self):
        p = self.root / 'old.png'; p.write_bytes(b'old')
        with self.assertRaises(UserError): self.plan(output=str(p))
        self.assertEqual(p.read_bytes(), b'old')

    def test_manifest_collision(self):
        p = self.root / 'x.png'; p.with_suffix('.png.json').write_text('{}')
        with self.assertRaises(UserError): self.plan(output=str(p))

    def test_wrong_extension(self):
        with self.assertRaises(UserError): self.plan(output=str(self.root/'x.jpg'))

    def test_missing_reference(self):
        with self.assertRaises(UserError): self.plan('image.edit')
        with self.assertRaises(UserError): self.plan('image.edit', reference=['/missing/file.png'])

    def test_edit_uses_reference_list(self):
        p = self.plan('image.edit', model='klein', reference=[str(self.ref)])
        self.assertTrue(p.command[0].endswith('flux2-edit'))
        self.assertIn('--image-paths',p.command)
        self.assertNotIn('--strength',p.command)

    def test_clone_requires_consent(self):
        with self.assertRaises(UserError): self.plan('audio.clone', reference=str(self.ref), transcript='Hello')

    def test_clone_requires_transcript(self):
        with self.assertRaises(UserError): self.plan('audio.clone', reference=str(self.ref), consent=True)

    def test_clone_exact_args(self):
        p = self.plan('audio.clone', model='qwen3-clone', reference=str(self.ref), transcript='Hello world.', consent=True)
        self.assertIn('--ref_audio',p.command)
        self.assertIn('--ref_text',p.command)
        self.assertIn('--join_audio',p.command)
        self.assertNotIn('--voice',p.command)
        self.assertIn('mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit',p.command)

    def test_clone_cannot_preset_voice(self):
        with self.assertRaises(UserError): self.plan('audio.clone', reference=str(self.ref), transcript='Hello', consent=True,voice='Ryan')

    def test_speech_custom_voice(self):
        p = self.plan('audio.speak',model='qwen3-voice',direction='Happy')
        self.assertEqual(p.model,'qwen3-voice')
        self.assertIn('--instruct',p.command)
        self.assertIn('Ryan',p.command)

    def test_design_requires_direction(self):
        with self.assertRaises(UserError): self.plan('audio.design')
        p=self.plan('audio.design',direction='A confident adult narrator')
        self.assertIn('--instruct',p.command)
        self.assertNotIn('--voice',p.command)

    def test_voxcpm_supported(self):
        p=self.plan('audio.design',model='voxcpm2',direction='A gentle storyteller')
        self.assertIn('mlx-community/VoxCPM2-4bit',p.command)

    def test_kokoro_flags(self):
        p = self.plan('audio.speak',model='kokoro',speed=1.2)
        for value in ['af_heart','--speed','1.2','--lang_code','a']:
            self.assertIn(value,p.command)
        with self.assertRaises(UserError): self.plan('audio.speak',model='kokoro',direction='Happy')

    def test_speed_restricted(self):
        with self.assertRaises(UserError): self.plan('audio.speak', speed=1.2)
        with self.assertRaises(UserError): self.plan('audio.speak', model='kokoro', speed=3)

    def test_seed_validation(self):
        for seed in (-1,2**32,'x'):
            with self.assertRaises(UserError): self.plan(seed=seed)

    def test_style_is_recorded(self):
        p=self.plan(style='product')
        self.assertTrue(p.prompt.startswith('Premium product'))
        self.assertEqual(p.parameters['original_prompt'],'Make something wonderful')

    def test_setup_has_no_weight_operation(self):
        commands = setup_commands('image',self.root)
        self.assertIn('3.12',commands[0])
        self.assertIn('mflux==0.24.0',commands[-1])
        self.assertNotIn('huggingface',json.dumps(commands))

    def test_offline_environment(self):
        env = environment()
        self.assertEqual(env['HF_HUB_OFFLINE'],'1')
        self.assertEqual(env['TRANSFORMERS_OFFLINE'],'1')
        self.assertNotIn('HF_HUB_OFFLINE',environment(True))

    def test_empty_and_fake_outputs_fail(self):
        with self.assertRaises(UserError): validate_output(self.root/'missing.png')
        p=self.root/'fake.png'; p.write_bytes(b'x'*80)
        with self.assertRaises(UserError): validate_output(p)

    def test_valid_signatures(self):
        p=self.root/'real.png'; p.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0'*40)
        validate_output(p)
        p=self.root/'real.wav';p.write_bytes(b'RIFF'+b'\0'*4+b'WAVE'+b'\0'*40)
        validate_output(p)

if __name__=='__main__': unittest.main()
