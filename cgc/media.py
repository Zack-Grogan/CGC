"""Structural validation and metadata for generated local media; no model imports."""
import array
import hashlib
import json
from pathlib import Path
import struct
import sys
import wave


def inspect(path):
    path=Path(path)
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            digest.update(chunk)
    result={'bytes':path.stat().st_size,'sha256':digest.hexdigest()}
    if path.suffix=='.glb':
        data=path.read_bytes()
        if len(data)<20 or struct.unpack('<4sII',data[:12])!=(b'glTF',2,len(data)):
            raise ValueError('Invalid GLB header/length')
        length,kind=struct.unpack('<II',data[12:20])
        if kind!=0x4E4F534A or length>len(data)-20:
            raise ValueError('Missing GLB JSON chunk')
        document=json.loads(data[20:20+length])
        triangles=0
        primitives=0
        bounds=[]
        for mesh in document.get('meshes',[]):
            for primitive in mesh.get('primitives',[]):
                primitives+=1
                accessor=document['accessors'][primitive['attributes']['POSITION']]
                if 'min' in accessor and 'max' in accessor:
                    bounds.append((accessor['min'],accessor['max']))
                count=document['accessors'][primitive['indices']]['count'] if 'indices' in primitive else accessor['count']
                if primitive.get('mode',4)==4:
                    triangles+=count//3
        if not triangles or not bounds:
            raise ValueError('GLB has no measurable triangle geometry')
        result.update(triangles=triangles,primitives=primitives,materials=len(document.get('materials',[])),bounds_min=[min(b[0][a] for b in bounds) for a in range(3)],bounds_max=[max(b[1][a] for b in bounds) for a in range(3)],skins=len(document.get('skins',[])),animations=len(document.get('animations',[])))
    elif path.suffix=='.wav':
        try:
            with wave.open(str(path)) as source:
                frames=source.getnframes(); channels=source.getnchannels(); rate=source.getframerate()
                width=source.getsampwidth(); payload=source.readframes(frames)
            if len(payload)!=frames*channels*width or frames==0:
                raise ValueError('Truncated or empty WAV')
            result.update(sample_rate=rate,channels=channels,frames=frames,duration=frames/rate)
            if width==2:
                values=array.array('h',payload)
                if sys.byteorder!='little':values.byteswap()
                peak=max(abs(v) for v in values)/32768
                if not peak:raise ValueError('Silent WAV')
                result['peak']=peak
        except wave.Error:
            import soundfile as sf
            import numpy as np
            samples,rate=sf.read(path)
            if not samples.size or not np.isfinite(samples).all() or not np.any(samples):
                raise ValueError('Invalid audio samples')
            result.update(sample_rate=rate,channels=1 if samples.ndim==1 else samples.shape[1],frames=len(samples),duration=len(samples)/rate,peak=float(np.abs(samples).max()))
    elif path.suffix=='.png':
        from PIL import Image
        with Image.open(path) as image:
            image.load()
            result.update(width=image.width,height=image.height,mode=image.mode)
    return result


def standard_glb(source, destination):
    """Convert embedded EXT_texture_webp images to PNG without changing geometry."""
    import io
    from PIL import Image
    source=Path(source);destination=Path(destination)
    if destination.exists():raise ValueError('Output exists')
    data=source.read_bytes()
    inspect(source)
    json_size=struct.unpack_from('<I',data,12)[0]
    document=json.loads(data[20:20+json_size])
    offset=20+json_size
    bin_size,kind=struct.unpack_from('<II',data,offset)
    if kind!=0x004E4942:raise ValueError('GLB has no BIN chunk')
    binary=bytearray(data[offset+8:offset+8+bin_size])
    for texture in document.get('textures',[]):
        extension=texture.get('extensions',{}).pop('EXT_texture_webp',None)
        if extension is None:continue
        image_index=extension['source'];image=document['images'][image_index]
        view=document['bufferViews'][image['bufferView']]
        start=view.get('byteOffset',0)
        with Image.open(io.BytesIO(binary[start:start+view['byteLength']])) as decoded:
            png=io.BytesIO();decoded.save(png,format='PNG');payload=png.getvalue()
        binary.extend(b'\x00'*((-len(binary))%4))
        document['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':len(payload)})
        image.update(bufferView=len(document['bufferViews'])-1,mimeType='image/png')
        texture['source']=image_index
        binary.extend(payload)
    for field in ('extensionsUsed','extensionsRequired'):
        if field in document:
            document[field]=[v for v in document[field] if v!='EXT_texture_webp']
            if not document[field]:document.pop(field)
    document['buffers'][0]['byteLength']=len(binary)
    encoded=json.dumps(document,separators=(',',':')).encode()
    encoded+=b' '*((-len(encoded))%4)
    binary.extend(b'\x00'*((-len(binary))%4))
    body=struct.pack('<II',len(encoded),0x4E4F534A)+encoded+struct.pack('<II',len(binary),0x004E4942)+binary
    destination.write_bytes(struct.pack('<4sII',b'glTF',2,12+len(body))+body)
    return inspect(destination)
