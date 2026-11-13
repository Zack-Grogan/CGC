"""Project-scoped Pillow/LittleCMS worker for lossless image finishing."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import warnings
import zlib

ROLES = {'color','base-color','emissive','ui','normal','roughness','metallic','occlusion','height','opacity','data'}
COLOR_ROLES = {'color','base-color','emissive','ui'}
COLOR_CHUNKS = {b'iCCP',b'sRGB',b'gAMA',b'cHRM',b'cICP',b'mDCV',b'cLLI'}


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def png_metadata(path):
    if Path(path).suffix.lower()!='.png':return None
    data=Path(path).read_bytes()
    if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid PNG signature')
    offset=8;chunks=[];ended=False
    while offset+12<=len(data):
        size=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8]
        if offset+12+size>len(data):raise ValueError('Truncated PNG chunk')
        payload=data[offset+8:offset+8+size];crc=struct.unpack_from('>I',data,offset+8+size)[0]
        if zlib.crc32(kind+payload)&0xffffffff!=crc:raise ValueError('PNG CRC mismatch: '+kind.decode(errors='replace'))
        chunks.append((kind,payload));offset+=size+12
        if kind==b'IEND':ended=True;break
    if not ended or not chunks or chunks[0][0]!=b'IHDR':raise ValueError('Incomplete PNG')
    width,height,depth,color,_,_,_=struct.unpack('>IIBBBBB',chunks[0][1])
    return {'width':width,'height':height,'bit_depth':depth,'color_type':color,'color_chunks':[kind.decode() for kind,payload in chunks if kind in COLOR_CHUNKS],
            'animated':any(kind==b'acTL' for kind,payload in chunks),'chunks':chunks,'trailing_bytes':len(data)-offset}


def restore_color_chunks(path,chunks):
    data=Path(path).read_bytes();meta=png_metadata(path);body=bytearray(data[:8])
    def append(kind,payload):body.extend(struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff))
    for kind,payload in meta['chunks']:
        if kind in COLOR_CHUNKS:continue
        append(kind,payload)
        if kind==b'IHDR':
            for source_kind,source_payload in chunks:
                if source_kind in COLOR_CHUNKS:append(source_kind,source_payload)
    Path(path).write_bytes(body)


def inspect(path,role='color'):
    from PIL import Image,ImageCms
    import PIL,numpy as np
    if role not in ROLES:raise ValueError('Unknown image role: '+role)
    path=Path(path).resolve();meta=png_metadata(path)
    Image.MAX_IMAGE_PIXELS=100_000_000
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(path) as image:
            image.load()
            if getattr(image,'n_frames',1)!=1:raise ValueError('Finish individual static image frames')
            mode=image.mode;size=image.size;icc=image.info.get('icc_profile')
            depth=meta['bit_depth'] if meta else max(image.tag_v2.get(258,(8,))) if hasattr(image,'tag_v2') else 16 if '16' in mode else 32 if mode in ('F','I') else 8
            rgba=image.convert('RGBA');alpha=np.asarray(rgba.getchannel('A'))
            alpha_min=int(alpha.min());alpha_max=int(alpha.max());zero=int(np.count_nonzero(alpha==0));opaque=int(np.count_nonzero(alpha==255))
            profile=None
            if icc:
                try:profile=ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
                except Exception:profile='Unrecognized embedded ICC profile'
            findings=[]
            if alpha_max==0 and role in COLOR_ROLES:findings.append({'level':'error','code':'fully_transparent','message':'Every pixel is transparent'})
            if role not in COLOR_ROLES and icc:findings.append({'level':'warning','code':'color_profile_on_data','message':'An ICC profile is attached to a numeric texture; use linear engine import and verify the intended encoding'})
            if meta and 'sRGB' in meta['color_chunks'] and 'iCCP' in meta['color_chunks']:findings.append({'level':'warning','code':'conflicting_color_tags','message':'PNG contains both sRGB and ICC declarations; resolve the intended source encoding'})
            if role in COLOR_ROLES and not icc and not (meta and any(kind in meta['color_chunks'] for kind in ('sRGB','gAMA','cHRM','cICP'))):findings.append({'level':'warning','code':'untagged_color','message':'The color encoding is untagged; correct interpretation requires a source assumption'})
            if meta and meta['trailing_bytes']:findings.append({'level':'warning','code':'png_trailing_bytes','message':'Data follows the PNG end marker'})
            if depth>8:findings.append({'level':'warning','code':'high_precision_image','message':'Pixel/alpha summaries use an 8-bit display decode; high-precision processing is restricted to byte-preserving PNG copy or metadata changes'})
            vector_stats=None
            if role=='normal':
                vectors=np.asarray(rgba,dtype=np.float32)[:,:,:3]/127.5-1
                length=np.linalg.norm(vectors,axis=2);visible=np.ones_like(alpha,dtype=bool)
                values=length[visible]
                vector_stats={'mean_length':float(values.mean()) if values.size else None,'nonunit_fraction_tolerance_0_15':float(np.mean(np.abs(values-1)>.15)) if values.size else None,'assumed_encoding':'RGB UNORM tangent-space normal; convention is not inferred'}
                if values.size and np.mean(np.abs(values-1)>.15)>.05:findings.append({'level':'warning','code':'nonunit_normal_vectors','message':'More than 5% of visible normal vectors differ from unit length by over 0.15; verify the texture role and encoding'})
            status='failed' if any(f['level']=='error' for f in findings) else 'review' if findings else 'passed'
            pixel_hash=hashlib.sha256(rgba.tobytes()).hexdigest()
    return {'kind':'image','path':str(path),'bytes':path.stat().st_size,'sha256':digest(path),'width':size[0],'height':size[1],'mode':mode,
            'bit_depth':depth,'icc_profile':profile,'icc_sha256':hashlib.sha256(icc).hexdigest() if icc else None,
            'png_color_chunks':meta['color_chunks'] if meta else [],'role':role,'engine_color_import':'sRGB' if role in COLOR_ROLES else 'linear/non-color',
            'alpha':{'minimum_8bit':alpha_min,'maximum_8bit':alpha_max,'transparent_pixels':zero,'opaque_pixels':opaque,'partial_pixels':size[0]*size[1]-zero-opaque,'interpretation':'coverage' if role in COLOR_ROLES else 'numeric or unused; depends on material role','measurement_precision':'8-bit display decode; original bit depth is recorded separately'},
            'decoded_rgba8_sha256':pixel_hash,'normal_vectors':vector_stats,'checks':{'status':status,'findings':findings,'limitation':'Structural/color checks do not establish artistic quality, correct material meaning, or normal-map handedness'},
            'versions':{'Pillow':PIL.__version__,'numpy':np.__version__,'LittleCMS':ImageCms.core.littlecms_version}}


def process(request):
    from PIL import Image,ImageCms
    from PIL.PngImagePlugin import PngInfo
    import numpy as np
    source=Path(request['source']).resolve();output=Path(request['output']).resolve();receipt=Path(str(output)+'.quality.json')
    if source==output or output.exists() or receipt.exists():raise ValueError('Output or receipt exists; choose a new PNG path')
    if output.suffix.lower()!='.png':raise ValueError('The image master/delivery output must be lossless PNG')
    role=request.get('role','color');action=request.get('color_action','preserve');assume=bool(request.get('assume_srgb'))
    flip=bool(request.get('flip_green'));strip=bool(request.get('strip_color_tags'));max_size=request.get('max_size')
    if role not in ROLES or action not in ('preserve','to-srgb'):raise ValueError('Invalid image role or color action')
    if flip and role!='normal':raise ValueError('Green inversion is only valid with --role normal')
    if strip and role in COLOR_ROLES:raise ValueError('Strip color tags only for explicitly numeric texture roles')
    if action!='preserve' and role not in COLOR_ROLES:raise ValueError('Do not apply a display-color transform to numeric texture data')
    if max_size is not None and (type(max_size) is not int or not 1<=max_size<=16384):raise ValueError('Max size must be an integer from 1 through 16384')
    before=inspect(source,role);meta=png_metadata(source);notes=[];operations=[]
    if before['checks']['status']=='failed':raise ValueError('Source image failed technical checks')
    if before['bit_depth']>8 and (max_size or flip or action!='preserve'):
        raise ValueError('This worker refuses high-bit-depth resizing/color transforms that would reduce precision; preserve the source or use a verified high-precision image tool')
    if before['bit_depth']>8 and source.suffix.lower()!='.png':raise ValueError('High-precision processing is limited to source PNG copy/metadata operations')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='.cgc-image-') as directory:
        target=Path(directory)/'finished.png'
        untouched=source.suffix.lower()=='.png' and not (max_size or flip or strip or action!='preserve')
        if untouched:
            import shutil
            shutil.copyfile(source,target);operations.append('byte-for-byte PNG copy')
        else:
            with Image.open(source) as raw:
                raw.load();icc=raw.info.get('icc_profile');image=raw.copy()
                if raw.mode not in ('RGB','RGBA','L','LA','P') and before['bit_depth']<=8:raise ValueError('Use an explicit color-managed conversion for this source pixel mode')
                if before['bit_depth']>8:
                    # Metadata-only rewrite retains the original IDAT bytes and precision.
                    import shutil
                    shutil.copyfile(source,target)
                    restore_color_chunks(target,[] if strip else meta['chunks']);operations.append('PNG color metadata only; pixel payload unchanged')
                else:
                    alpha=image.convert('RGBA').getchannel('A')
                    srgb=False
                    if icc:
                        if max_size and max(image.size)>max_size and role in COLOR_ROLES and action=='preserve':raise ValueError('Use --color-action to-srgb for an ICC-managed color resize; profile names alone do not establish the required transfer curve')
                        if action=='to-srgb':source_profile=ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    elif meta and 'sRGB' in meta['color_chunks']:srgb=True
                    elif assume:srgb=True;notes.append('Untagged source samples were explicitly assumed to use the sRGB transfer function')
                    if action=='to-srgb':
                        if icc:
                            image=ImageCms.profileToProfile(image.convert('L') if image.mode in ('L','LA') else image.convert('RGB'),source_profile,ImageCms.createProfile('sRGB'),outputMode='RGB')
                            icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes();operations.append('LittleCMS ICC transform to sRGB');srgb=True
                        elif not srgb:raise ValueError('Untagged color conversion requires --assume-srgb')
                        else:icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes();operations.append('Explicit sRGB tagging; values retained')
                        image=image.convert('RGBA');image.putalpha(alpha)
                    else:image=image.convert('RGBA')
                    resize=bool(max_size and max(image.size)>max_size)
                    if resize:
                        factor=max_size/max(image.size);size=tuple(max(1,round(v*factor)) for v in image.size)
                        pixels=np.asarray(image,dtype=np.float32)/255;rgb=pixels[:,:,:3];a=pixels[:,:,3]
                        if role in COLOR_ROLES:
                            if not srgb:raise ValueError('Linear-light color resizing requires known sRGB samples; use --color-action to-srgb or --assume-srgb')
                            rgb=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4);rgb*=a[:,:,None]
                            def resample(channel):return np.asarray(Image.fromarray(channel.astype('float32')).resize(size,Image.Resampling.LANCZOS),dtype=np.float32)
                            rgb=np.stack([resample(rgb[:,:,c]) for c in range(3)],axis=2);a=np.clip(resample(a),0,1)
                            rgb=np.divide(rgb,a[:,:,None],out=np.zeros_like(rgb),where=a[:,:,None]>1e-7);rgb=np.clip(rgb,0,1)
                            rgb=np.where(rgb<=.0031308,rgb*12.92,1.055*rgb**(1/2.4)-.055);operations.append('Linear-light, premultiplied-alpha Lanczos resize; straight-alpha PNG output')
                        else:
                            def resample(channel):return np.asarray(Image.fromarray(channel.astype('float32')).resize(size,Image.Resampling.BILINEAR),dtype=np.float32)
                            rgb=np.stack([resample(rgb[:,:,c]) for c in range(3)],axis=2);a=np.clip(resample(a),0,1)
                            operations.append('Linear numeric bilinear resize')
                        image=Image.fromarray(np.clip(np.rint(np.dstack([rgb,a])*255),0,255).astype(np.uint8))
                    if flip or (resize and role=='normal'):
                        pixels=np.array(image);vectors=pixels[:,:,:3].astype(np.float32)/127.5-1
                        if flip:vectors[:,:,1]*=-1;operations.append('Explicit normal green-channel inversion')
                        if resize:
                            length=np.linalg.norm(vectors,axis=2,keepdims=True);bad=length[:,:,0]<1e-6
                            vectors=np.divide(vectors,length,out=np.zeros_like(vectors),where=length>1e-6);vectors[bad]=[0,0,1]
                            operations.append('Normal vectors renormalized after filtering')
                        pixels[:,:,:3]=np.clip(np.rint((vectors+1)*127.5),0,255).astype(np.uint8);image=Image.fromarray(pixels)
                    if strip:icc=None;operations.append('Explicit removal of display-color tags; numeric sample values retained')
                    image.save(target,format='PNG',compress_level=9,icc_profile=icc)
                    if action=='preserve' and meta and not strip:restore_color_chunks(target,meta['chunks'])
        after=inspect(target,role)
        if after['checks']['status']=='failed':raise ValueError('Image output failed technical checks')
        if not (max_size or flip or action!='preserve') and before['bit_depth']<=8 and before['decoded_rgba8_sha256']!=after['decoded_rgba8_sha256']:
            raise ValueError('A metadata/format-only conversion changed decoded pixels')
        if digest(source)!=before['sha256']:raise ValueError('Source changed during image finishing')
        os.link(target,output)
    after['path']=str(output)
    report={'status':'completed','operation':'media.image','source':before,'output':after,'operations':operations,'notes':notes,
            'source_preserved':True,'role':role,'engine_color_import':after['engine_color_import'],'normal_convention':'Green inversion requested' if flip else 'Not inferred or changed'}
    with receipt.open('x') as file:json.dump(report,file,indent=2,allow_nan=False)
    return report


def channel_source(path,channel):
    from PIL import Image
    import numpy as np
    if channel not in ('r','g','b','a'):raise ValueError('Channel must be r, g, b, or a')
    path=Path(path).expanduser().resolve()
    before=inspect(path,'data')
    if before['bit_depth']>8:raise ValueError('This channel packer requires 8-bit input and refuses implicit precision reduction')
    with Image.open(path) as source:
        source.load()
        if source.mode not in ('L','LA','P','RGB','RGBA'):raise ValueError('Channel packing requires grayscale or RGB source pixels')
        values=np.asarray(source.convert('RGBA'))[:,:,('r','g','b','a').index(channel)].copy()
    return values,{'path':str(path),'sha256':before['sha256'],'channel':channel,'color_transform_applied':False,'ignored_color_profile':before['icc_profile']}


def data_output(request,image,mapping,operation):
    output=Path(request['output']).expanduser().resolve();receipt=Path(str(output)+'.quality.json')
    if output.exists() or receipt.exists():raise ValueError('Output or quality receipt exists')
    if output.suffix.lower()!='.png':raise ValueError('Packed data textures must use lossless PNG')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='.cgc-pack-') as directory:
        target=Path(directory)/'data.png';image.save(target,format='PNG',compress_level=9)
        after=inspect(target,'data')
        if png_metadata(target)['color_chunks']:raise ValueError('Numeric texture unexpectedly contains display-color metadata')
        for item in mapping.values():
            if item.get('path') and digest(item['path'])!=item['sha256']:raise ValueError('Source texture changed during packing')
        os.link(target,output)
    after['path']=str(output)
    report={'status':'completed','operation':operation,'output':after,'layout':request.get('layout'),'channel_mapping':mapping,
            'engine_color_import':'linear/non-color','notes':['Packing copies numeric samples without ICC, gamma conversion, or implicit resizing. Configure the target shader/importer for this explicit layout.']}
    with receipt.open('x') as file:json.dump(report,file,indent=2,allow_nan=False)
    return report


def extract(request):
    from PIL import Image
    values,source=channel_source(request['source'],request['channel'])
    if request.get('invert'):values=255-values
    source['inverted']=bool(request.get('invert'))
    return data_output(request,Image.fromarray(values),{'gray':source},'media.channel')


def pack(request):
    from PIL import Image
    import numpy as np
    layout=request['layout'];inputs=request.get('inputs',{})
    if layout not in ('orm','unity-metallic','unity-hdrp-mask'):raise ValueError('Unknown explicit material packing layout')
    if not inputs:raise ValueError('Supply at least one scalar texture')
    loaded={};mapping={};shape=None
    for name,spec in inputs.items():
        if name not in ('occlusion','roughness','metallic','detail'):raise ValueError('Unknown scalar role')
        values,source=channel_source(spec['path'],spec.get('channel','r'))
        if shape is None:shape=values.shape
        if values.shape!=shape:raise ValueError('Scalar texture dimensions differ; resize each input explicitly before packing')
        loaded[name]=values;mapping[name]=source
    def value(name,default):return loaded.get(name,np.full(shape,default,dtype=np.uint8))
    def description(name,default,invert=False):
        result=dict(mapping.get(name,{'constant_unorm8':default}));result['inverted']=invert;return result
    if layout=='orm':
        pixels=np.stack([value('occlusion',255),value('roughness',255),value('metallic',0)],axis=2)
        channels={'r':description('occlusion',255),'g':description('roughness',255),'b':description('metallic',0)}
    else:
        pixels=np.stack([value('metallic',0),value('occlusion',255) if layout=='unity-hdrp-mask' else np.zeros(shape,dtype=np.uint8),value('detail',255) if layout=='unity-hdrp-mask' else np.zeros(shape,dtype=np.uint8),255-value('roughness',255)],axis=2)
        channels={'r':description('metallic',0),'g':description('occlusion',255) if layout=='unity-hdrp-mask' else {'constant_unorm8':0},
                  'b':description('detail',255) if layout=='unity-hdrp-mask' else {'constant_unorm8':0},'a':description('roughness',255,invert=True)}
    return data_output(request,Image.fromarray(pixels),channels,'media.pack')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);args=parser.parse_args()
    try:
        request=json.loads(args.request)
        if request['operation']=='inspect':result=inspect(request['source'],request.get('role','color'))
        elif request['operation']=='pack':result=pack(request)
        elif request['operation']=='channel':result=extract(request)
        else:result=process(request)
        print(json.dumps(result,allow_nan=False));return 0
    except Exception as error:
        print(json.dumps({'status':'failed','error':str(error)}));return 2


if __name__=='__main__':raise SystemExit(main())
