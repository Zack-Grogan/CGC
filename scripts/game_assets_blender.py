"""Compatibility entry point for the packaged Blender asset worker."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1]/'cgc/game_assets_blender.py'),run_name='__main__')
