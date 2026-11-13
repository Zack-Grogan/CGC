"""Validate the SDK Mark blendshape animation package without model imports."""
import zipfile
try:
    from .motion import _read_npy
except ImportError:
    from remote_motion import _read_npy


def inspect(path):
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist())>64*1024*1024:raise ValueError('Oversized face animation')
        shape,weights=_read_npy(archive.read('weights.npy'))
        clock,times=_read_npy(archive.read('times.npy'))
    if len(shape)!=2 or shape[1]!=68 or clock!=(shape[0],) or not 2<=shape[0]<=4000:raise ValueError('Invalid SDK Mark animation shape')
    if any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Face timestamps must increase')
    if times[0]<-1 or times[-1]-times[0]>61:raise ValueError('Invalid face animation clock')
    variation=max(max(weights[column::68])-min(weights[column::68]) for column in range(68))
    if variation<1e-5:raise ValueError('Face animation has no changing blendshape weights')
    return {'frames':shape[0],'channels':68,'time_start':times[0],'time_end':times[-1],'maximum_channel_variation':variation,'identity':'SDK Mark'}
