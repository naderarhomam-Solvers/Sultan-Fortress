"""Re-creates the two data files used by the Blender script from the source picture  source/smb87_logo.jpg :

    pip install -r requirements.txt
    python run_pipeline.py            # both layouts, ~6 minutes (the sharpening step is cached after the first run)
    python run_pipeline.py full       # only the full-image layout  (or: round)

Stages per layout
  1. vectorize.py   sharpen (symmetric Richardson-Lucy) -> sub-pixel colour separation -> analytic ring circles + iso-contours
                    of the line-work (+ the faded background art for 'full') -> snap-rounded noding -> conforming planar
                    faces (faces_raw_<layout>.pkl)
  2. pack_faces.py  weld to a 1 um grid, split pinch nodes, verify that every edge has a twin (emblem_faces_<layout>.npz)
  3. build_data.py  triangulate the top faces -> layers_<layout>.npz, copied to ../blender/ (next to build_sultan_plaque.py)
"""
import hashlib
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
OUT = {"round": "sultan_emblem_layers.npz", "full": "sultan_full_layers.npz"}
layouts = sys.argv[1:] or ["round", "full"]
for L in layouts:
    if L not in OUT:
        raise SystemExit("unknown layout %r (use round / full)" % L)
    for step in (["vectorize.py", L, "faces_raw_%s.pkl" % L],
                 ["pack_faces.py", "faces_raw_%s.pkl" % L, "emblem_faces_%s.npz" % L],
                 ["build_data.py", "emblem_faces_%s.npz" % L, "layers_%s.npz" % L]):
        print("\n=== %s ===" % " ".join(step), flush=True)
        subprocess.check_call([sys.executable] + step, cwd=here)             # any failure stops the whole run
    dst = os.path.join(here, "..", "blender", OUT[L])
    shutil.copyfile(os.path.join(here, "layers_%s.npz" % L), dst)
    with open(dst, "rb") as fh:
        print("copied -> %s  sha256 %s" % (os.path.normpath(dst), hashlib.sha256(fh.read()).hexdigest()[:16]))
