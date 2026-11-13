"""Fix the pinned exporter's new armature object name before skin binding."""
import hashlib
from pathlib import Path

ANCHOR = "        armature_name = asset.armature_name if asset.armature_name is not None else 'Armature'\n"
REPLACEMENT = ANCHOR+"        bpy.context.object.name = armature_name  # CGC: keep object lookup consistent\n"


def patch(root):
    path=Path(root)/'src/rig_package/parser/bpy.py'
    source=path.read_text()
    before=hashlib.sha256(source.encode()).hexdigest()
    if REPLACEMENT not in source:
        if source.count(ANCHOR)!=1:raise RuntimeError('TokenRig export anchor changed; refusing an unverified patch')
        source=source.replace(ANCHOR,REPLACEMENT)
        path.write_text(source)
    return {'file':'src/rig_package/parser/bpy.py','fix':'Name the newly created armature object before binding','before_sha256':before,'after_sha256':hashlib.sha256(source.encode()).hexdigest()}
