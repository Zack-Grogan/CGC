"""Run a Python CLI script inside Blender with its ordinary argument list.

blender --background --python scripts/blender_python.py -- SCRIPT.py ARGS...
"""
from pathlib import Path
import runpy
import sys

arguments = sys.argv[sys.argv.index('--')+1:]
if not arguments:
    raise ValueError('Supply a Python script and its arguments after --')
script = Path(arguments[0]).expanduser().resolve(strict=True)
sys.path.insert(0, str(script.parent))
sys.argv = [str(script), *arguments[1:]]
runpy.run_path(str(script), run_name='__main__')
