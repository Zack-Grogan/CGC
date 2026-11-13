"""Encode a prepared lossless audio derivative through libsndfile's Vorbis codec."""
import json
from pathlib import Path
import sys
import soundfile as sf


def main():
    source,output=map(Path,sys.argv[1:])
    if output.exists():raise ValueError('Output exists')
    if 'VORBIS' not in sf.available_subtypes('OGG'):raise ValueError('This libsndfile build has no Vorbis encoder')
    with sf.SoundFile(source) as reader,sf.SoundFile(output,mode='w',samplerate=reader.samplerate,channels=reader.channels,
                                                    format='OGG',subtype='VORBIS',compression_level=.2) as writer:
        while samples:=reader.buffer_read(8192,dtype='float32'):
            writer.buffer_write(samples,dtype='float32')
    print(json.dumps({'encoder':'libsndfile Vorbis','soundfile':sf.__version__,'libsndfile':sf.__libsndfile_version__,'compression_level':.2}))


if __name__=='__main__':main()
