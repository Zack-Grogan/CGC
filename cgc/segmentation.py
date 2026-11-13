"""Validate canonical face labels without importing model packages."""
import zipfile
try:
    from .motion import _read_npy
except ImportError:
    from remote_motion import _read_npy


def inspect(path):
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist()
        if sum(item.file_size for item in members)>128*1024*1024:raise ValueError('Oversized segmentation output')
        labels_shape,labels=_read_npy(archive.read('labels.npy'),allow_integer=True)
        faces_shape,faces=_read_npy(archive.read('faces.npy'),allow_integer=True)
        vertex_shape,vertices=_read_npy(archive.read('vertices.npy'))
    if len(labels_shape)!=1 or faces_shape!=(labels_shape[0],3) or len(vertex_shape)!=2 or vertex_shape[1]!=3:
        raise ValueError('Labels do not match the canonical mesh faces')
    if labels.typecode not in ('i','q','I','Q') or faces.typecode not in ('i','q','I','Q'):
        raise ValueError('Face labels and indices must be integers')
    if min(faces)<0 or max(faces)>=vertex_shape[0]:raise ValueError('Invalid canonical mesh face index')
    if min(labels)<0 or max(labels)>1000000 or not any(label>0 for label in labels):raise ValueError('Invalid or empty face selection')
    return {'faces':labels_shape[0],'vertices':vertex_shape[0],'selected_faces':sum(label>0 for label in labels),'part_labels':sorted(set(labels))}
