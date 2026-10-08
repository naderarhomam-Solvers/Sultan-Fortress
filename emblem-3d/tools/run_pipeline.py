"""Re-creates  sultan_emblem_layers.npz  from the source picture  source/smb87_logo.jpg .

    pip install -r requirements.txt
    python run_pipeline.py

Stages
  1. vectorize.py   sharpen (Richardson-Lucy) -> sub-pixel colour separation -> analytic ring circles + iso-contours of the
                    line-work -> snap-rounded noding -> conforming planar faces (faces_raw.pkl)
  2. pack_faces.py  weld to a 1 um grid, split pinch nodes, verify that every edge has a twin (emblem_faces.npz)
  3. build_data.py  triangulate the top faces -> sultan_emblem_layers.npz (copy it next to build_sultan_plaque.py)
"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
steps = [
    ["vectorize.py"],
    ["pack_faces.py", "faces_raw.pkl", "emblem_faces.npz"],
    ["build_data.py", "emblem_faces.npz", "sultan_emblem_layers.npz"],
]
for s in steps:
    print("\n=== %s ===" % " ".join(s), flush=True)
    subprocess.check_call([sys.executable] + s, cwd=here)
print("\nDone -> %s" % os.path.join(here, "sultan_emblem_layers.npz"))
