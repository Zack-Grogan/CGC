import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave

from cgc.media_quality import (IMAGE_PYTHON, inspect_audio, check_audio, process_audio, process_image,
                               inspect_image, pack_image, extract_channel)


def audio(path,seconds=1.,frequency=440.25):
    values=array.array('h',(int(.2*32767*math.sin(2*math.pi*frequency*index/48000)) for index in range(round(seconds*48000))))
    with wave.open(str(path),'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(48000);writer.writeframes(values.tobytes())


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg tools are required')
class AudioFinishing(unittest.TestCase):
    def test_nonfinite_float_wav_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'invalid.wav';samples=struct.pack('<4f',0,.1,float('nan'),.2)
            fmt=struct.pack('<HHIIHH',3,1,48000,192000,4,32)
            body=b'fmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(samples))+samples
            path.write_bytes(b'RIFF'+struct.pack('<I',len(body)+4)+b'WAVE'+body)
            report=inspect_audio(path,loudness=False)
            self.assertFalse(report['finite']);self.assertEqual(check_audio(report)['status'],'failed')

    def test_overlap_loop_has_declared_length_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.wav';audio(source)
            digest=hashlib.sha256(source.read_bytes()).hexdigest();before=inspect_audio(source,loudness=False)
            result=process_audio(source,root/'loop.wav',loop_crossfade=.05,profile='master')
            self.assertEqual(result['output']['frames'],48000-2400)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
            self.assertLess(result['output']['loop_seam']['sample_jump_peak'],before['loop_seam']['sample_jump_peak'])
            self.assertFalse(result['loop']['metadata_embedded'])
            self.assertTrue(Path(str(root/'loop.wav')+'.quality.json').is_file())
            with self.assertRaisesRegex(ValueError,'exists'):process_audio(source,root/'loop.wav')

    def test_game_delivery_is_measured_after_gain_and_pcm_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.wav';audio(source,seconds=2.)
            result=process_audio(source,root/'game.wav',profile='game',peak_db=-3.)
            self.assertEqual(result['output']['sample_format'],'s16')
            self.assertEqual(result['output']['sample_rate'],48000)
            self.assertLessEqual(result['output']['loudness']['true_peak_db'],-2.85)
            self.assertGreaterEqual(result['output']['loudness']['true_peak_db'],-3.15)

    def test_invalid_transform_does_not_create_delivery_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.wav';audio(source)
            for options in ({'loop_crossfade':.6},{'trim_end':2.},{'lufs':float('nan')}):
                with self.subTest(options=options),self.assertRaises(ValueError):process_audio(source,root/'bad.wav',**options)
                self.assertFalse((root/'bad.wav').exists())


@unittest.skipUnless(IMAGE_PYTHON.is_file(),'Run cgc media setup for image finishing tests')
class ImageFinishing(unittest.TestCase):
    def fixture(self,directory,code):
        subprocess.run([str(IMAGE_PYTHON),'-c',code,str(directory)],check=True,capture_output=True,text=True)

    def pixels(self,path):
        result=subprocess.run([str(IMAGE_PYTHON),'-c',"from PIL import Image; import json,sys; im=Image.open(sys.argv[1]); print(json.dumps(list(im.getdata())))",str(path)],check=True,capture_output=True,text=True)
        return json.loads(result.stdout)

    def test_linear_light_resize_and_straight_alpha(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root,"from PIL import Image; from pathlib import Path; import sys; p=Path(sys.argv[1]); i=Image.new('RGB',(2,1));i.putdata([(0,0,0),(255,255,255)]);i.save(p/'source.png');j=Image.new('RGBA',(4,4),(0,0,255,0));j.putpixel((1,1),(255,0,0,255));j.save(p/'alpha.png')")
            process_image(root/'source.png',root/'small.png',role='base-color',max_size=1,assume_srgb=True)
            pixel=self.pixels(root/'small.png')[0]
            self.assertTrue(185<=pixel[0]<=190)
            process_image(root/'alpha.png',root/'alpha-small.png',role='base-color',max_size=2,assume_srgb=True)
            for r,g,b,a in self.pixels(root/'alpha-small.png'):
                if a:self.assertGreater(r,250);self.assertEqual(g,0);self.assertEqual(b,0)

    def test_channel_layouts_are_exact_numeric_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root,"from PIL import Image; from pathlib import Path; import sys;p=Path(sys.argv[1]);i=Image.new('RGB',(2,1));i.putdata([(10,20,30),(40,50,60)]);i.save(p/'source.png')")
            inputs={name:{'path':str(root/'source.png'),'channel':channel} for name,channel in [('occlusion','r'),('roughness','g'),('metallic','b')]}
            orm=pack_image(root/'orm.png',layout='orm',inputs=inputs)
            self.assertEqual(self.pixels(root/'orm.png'),[[10,20,30],[40,50,60]])
            self.assertFalse(orm['output']['png_color_chunks'])
            pack_image(root/'unity.png',layout='unity-metallic',inputs=inputs)
            self.assertEqual(self.pixels(root/'unity.png'),[[30,0,0,235],[60,0,0,205]])
            pack_image(root/'hdrp.png',layout='unity-hdrp-mask',inputs=inputs)
            self.assertEqual(self.pixels(root/'hdrp.png'),[[30,10,255,235],[60,40,255,205]])
            extract_channel(root/'unity.png',root/'roughness.png',channel='a',invert=True)
            self.assertEqual(self.pixels(root/'roughness.png'),[20,50])

    def test_high_precision_copy_is_exact_and_resize_refuses_downconversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root,"from PIL import Image; import numpy as np,sys;from pathlib import Path;p=Path(sys.argv[1]);Image.fromarray(np.array([[0,1024],[50000,65535]],dtype=np.uint16)).save(p/'source.png')")
            result=process_image(root/'source.png',root/'copy.png',role='height')
            self.assertEqual(result['output']['bit_depth'],16)
            self.assertEqual((root/'source.png').read_bytes(),(root/'copy.png').read_bytes())
            with self.assertRaisesRegex(ValueError,'precision'):process_image(root/'source.png',root/'small.png',role='height',max_size=1)
            self.assertFalse((root/'small.png').exists())

    def test_normal_filter_renormalizes_and_flips_only_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root,"from PIL import Image; import sys;from pathlib import Path;p=Path(sys.argv[1]);Image.new('RGB',(4,4),(128,190,230)).save(p/'normal.png')")
            result=process_image(root/'normal.png',root/'small.png',role='normal',max_size=2,flip_green=True)
            self.assertLess(self.pixels(root/'small.png')[0][1],128)
            self.assertAlmostEqual(result['output']['normal_vectors']['mean_length'],1.,delta=.02)
            with self.assertRaisesRegex(ValueError,'normal'):process_image(root/'normal.png',root/'bad.png',role='base-color',flip_green=True)

    def test_numeric_alpha_zero_is_not_rejected_as_transparency(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root,"from PIL import Image; import sys;from pathlib import Path;p=Path(sys.argv[1]);Image.new('RGBA',(2,2),(0,0,0,0)).save(p/'data.png')")
            self.assertEqual(inspect_image(root/'data.png',role='data')['checks']['status'],'passed')
            self.assertEqual(inspect_image(root/'data.png',role='base-color')['checks']['status'],'failed')


if __name__=='__main__':unittest.main()
