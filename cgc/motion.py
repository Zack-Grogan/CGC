"""Read and validate Kimodo SOMA77 motion without importing model libraries."""
import array
import ast
import math
from pathlib import Path
import struct
import sys
import zipfile


def _read_npy(data, allow_integer=False):
    if data[:6] != b'\x93NUMPY':
        raise ValueError('Invalid motion array header')
    major = data[6]
    if major not in (1, 2, 3):
        raise ValueError('Unsupported motion array version')
    width = 2 if major == 1 else 4
    length = int.from_bytes(data[8:8+width], 'little')
    start = 8+width+length
    header = ast.literal_eval(data[8+width:start].decode('utf-8' if major==3 else 'latin1').strip())
    dtype = header['descr']
    shape = header['shape']
    types={'f4':'f','f8':'d'}
    if allow_integer:types.update({'i4':'i','i8':'q','u4':'I','u8':'Q'})
    if not isinstance(dtype,str) or dtype[:1] not in ('<','>') or dtype[1:] not in types or header['fortran_order'] or not isinstance(shape,tuple) or any(type(n) is not int or n<1 for n in shape):
        raise ValueError('Expected contiguous float motion arrays; object arrays are forbidden')
    values = array.array(types[dtype[1:]])
    payload = data[start:]
    if len(payload) != math.prod(shape)*values.itemsize:
        raise ValueError('Truncated motion array')
    values.frombytes(payload)
    if (dtype[0]=='<') != (sys.byteorder=='little'):
        values.byteswap()
    if any(not math.isfinite(v) for v in values):
        raise ValueError('Motion contains nonfinite values')
    return shape, values


def inspect(path):
    with zipfile.ZipFile(Path(path)) as archive:
        members=archive.infolist()
        names=[member.filename for member in members]
        if len(names)!=len(set(names)) or sum(m.file_size for m in members)>64*1024*1024:
            raise ValueError('Invalid or oversized motion archive')
        arrays={name: _read_npy(archive.read(name+'.npy')) for name in ('posed_joints','local_rot_mats','root_positions')}
    frames=arrays['posed_joints'][0][0]
    expected={'posed_joints': (frames,77,3),'local_rot_mats': (frames,77,3,3),'root_positions': (frames,3)}
    if not 1<=frames<=1800 or any(arrays[key][0]!=shape for key,shape in expected.items()):
        raise ValueError('Motion does not satisfy the 30Hz SOMA77 output contract')
    values=arrays['local_rot_mats'][1]
    maximum=0.0
    for offset in range(0,len(values),9):
        m=values[offset:offset+9]
        for i in range(3):
            for j in range(3):
                maximum=max(maximum,abs(sum(m[k*3+i]*m[k*3+j] for k in range(3))-(1 if i==j else 0)))
        determinant=m[0]*(m[4]*m[8]-m[5]*m[7])-m[1]*(m[3]*m[8]-m[5]*m[6])+m[2]*(m[3]*m[7]-m[4]*m[6])
        maximum=max(maximum,abs(determinant-1))
    if maximum>0.02:
        raise ValueError('Motion contains invalid rotation matrices')
    return {'frames':frames,'joints':77,'fps':30,'duration':frames/30,'rotation_error_max':maximum}
