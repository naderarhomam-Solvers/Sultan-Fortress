"""emblem_faces.npz (+ earcut/repair triangulation of the top faces) -> sultan_emblem_layers.npz  (final Blender input)"""
import sys, os, numpy as np
import meshbuild as M
src = sys.argv[1] if len(sys.argv) > 1 else 'emblem_faces.npz'
dst = sys.argv[2] if len(sys.argv) > 2 else 'sultan_emblem_layers.npz'
d = M.load(src)
tri, tf = M.triangulate_ring_sets(d['verts'], d['ring_v'], d['ring_len'], d['ring_face'], len(d['face_class']))
print('top triangles', len(tri), 'faces', len(d['face_class']))
np.savez_compressed(dst,
    verts=d['verts'].astype(np.int32), ring_v=d['ring_v'].astype(np.int32), ring_len=d['ring_len'].astype(np.int32),
    ring_face=d['ring_face'].astype(np.int32), face_class=d['face_class'].astype(np.uint8),
    tri=tri.astype(np.int32), tri_face=tf.astype(np.int32),
    nominal_extent_mm=np.float64(d['nominal_extent_mm']), nominal_diameter_mm=np.float64(d['nominal_extent_mm']),
    layout=d['layout'])
print('saved', dst, '%.2f MB' % (os.path.getsize(dst) / 1e6))
