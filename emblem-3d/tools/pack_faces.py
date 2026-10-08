"""faces_raw.pkl (shapely faces, mm)  ->  emblem_faces.npz  (welded integer-micrometre planar partition).

Steps: weld vertices on a 1 um grid; orient rings (exterior CCW, holes CW, interior on the left); split interior
degree-4 nodes ("pinch" nodes) into two degree-3 nodes joined by a 4 um edge so that any relief heights give a
manifold shell; re-trace rings from the directed edges; verify that every directed edge has a twin."""
import sys, os, pickle, numpy as np, shapely
from shapely.geometry import Polygon

src = sys.argv[1] if len(sys.argv) > 1 else 'faces_raw.pkl'
dst = sys.argv[2] if len(sys.argv) > 2 else 'emblem_faces.npz'
d = pickle.load(open(src, 'rb'))
faces, cls = d['faces'], np.asarray(d['cls'])
REL = {1: 1.2, 2: 0.8, 3: 0.4, 4: 0.4, 5: 0.6, 6: 0.8, 7: 0.4, 8: 0.8, 9: 0.8, 10: 0.8}      # default relief, only used to pick the split orientation
SPLIT_EPS_UM = 4.0

vid, verts = {}, []


def vkey(xum, yum):
    k = (int(xum), int(yum))
    i = vid.get(k)
    if i is None:
        i = len(verts)
        vid[k] = i
        verts.append(k)
    return i


# ---- 1. directed edges (u, v, face) from oriented rings -------------------------------------------------------
edges = []
for fi, f in enumerate(faces):
    f = shapely.geometry.polygon.orient(f, sign=1.0)
    for r in [f.exterior] + list(f.interiors):
        pts = np.asarray(r.coords)[:-1]
        ids = [vkey(round(x * 1000.0), round(y * 1000.0)) for x, y in pts]
        clean = [ids[0]]
        for i in ids[1:]:
            if i != clean[-1]:
                clean.append(i)
        if len(clean) > 1 and clean[0] == clean[-1]:
            clean.pop()
        if len(clean) < 3:
            continue
        for j in range(len(clean)):
            edges.append((clean[j], clean[(j + 1) % len(clean)], fi))
print('faces', len(faces), 'directed edges', len(edges), 'unique verts', len(verts))

# ---- 2. split interior degree-4 nodes ------------------------------------------------------------------------
dset = {(u, v) for u, v, _ in edges}
rim = set()
for u, v, _ in edges:
    if (v, u) not in dset:
        rim.add(u)
        rim.add(v)
nbrs = {}
for u, v, _ in edges:
    nbrs.setdefault(u, set()).add(v)
    nbrs.setdefault(v, set()).add(u)
owner = {(u, v): f for u, v, f in edges}        # sector CCW after the out-edge u->v belongs to face f
hist = {}
node_for = {}
extra = []
for p, nb in nbrs.items():
    hist[len(nb)] = hist.get(len(nb), 0) + 1
    if len(nb) != 4 or p in rim:
        continue
    px, py = verts[p]
    ang = lambda q: np.arctan2(verts[q][1] - py, verts[q][0] - px)
    qs = sorted(nb, key=ang)                      # E0..E3 counter-clockwise
    f_sec = [owner[(p, q)] for q in qs]           # sector S_k lies CCW after E_k
    h = [REL[int(cls[f])] for f in f_sec]
    # connect the pair of opposite sectors (S0,S2) or (S1,S3) that belong to DIFFERENT faces (a pair owned by one
    # face would create a slit inside that face); if both qualify take the pair with the closer heights
    ok02, ok13 = f_sec[0] != f_sec[2], f_sec[1] != f_sec[3]
    if ok13 and (not ok02 or abs(h[1] - h[3]) < abs(h[0] - h[2]) - 1e-9):
        qs = qs[1:] + qs[:1]
        f_sec = f_sec[1:] + f_sec[:1]
    elif not ok02 and not ok13:
        print('  warning: node', p, 'both opposite sector pairs belong to the same face')
    A = [ang(q) for q in qs]
    mids = []
    for k in (1, 3):
        a1, a2 = A[k], A[(k + 1) % 4]
        mids.append(a1 + ((a2 - a1) % (2 * np.pi)) / 2)
    eps = SPLIT_EPS_UM
    for _try in range(3):
        c = [(px + round(eps * np.cos(m)), py + round(eps * np.sin(m))) for m in mids]
        if c[0] != c[1] and c[0] != (px, py) and c[1] != (px, py):
            break
        eps *= 2
    n1, n2 = vkey(*c[0]), vkey(*c[1])
    node_for[p] = {qs[1]: n1, qs[2]: n1, qs[3]: n2, qs[0]: n2}
    extra.append((n1, n2, f_sec[0]))              # sector S0 : in = E1 (n1), out = E0 (n2)
    extra.append((n2, n1, f_sec[2]))              # sector S2 : in = E3 (n2), out = E2 (n1)
print('node degree histogram', dict(sorted(hist.items())), '-> split', len(node_for), 'pinch nodes')
new_edges = []
for u, v, f in edges:
    uu, vv = u, v
    if v in node_for:
        vv = node_for[v][u]
    if u in node_for:
        uu = node_for[u][v]
    new_edges.append((uu, vv, f))
new_edges += extra

# ---- 3. re-trace rings per face -------------------------------------------------------------------------------
by_face = {}
for u, v, f in new_edges:
    by_face.setdefault(f, []).append((u, v))
V = np.array(verts, np.int64)
out_faces = []      # list of (class, [rings]) ; ring = list of vertex ids, rings[0] exterior CCW
for f in sorted(by_face):
    nxt = {}
    for u, v in by_face[f]:
        if u in nxt:
            raise SystemExit('face %d: ambiguous tail vertex %d after split' % (f, u))
        nxt[u] = v
    seen = set()
    rings = []
    for u0 in nxt:
        if u0 in seen:
            continue
        ring = [u0]
        seen.add(u0)
        w = nxt[u0]
        while w != u0:
            ring.append(w)
            seen.add(w)
            w = nxt[w]
        rings.append(ring)
    area = []
    for r in rings:
        xy = V[r]
        area.append(0.5 * float(np.sum(xy[:, 0] * np.roll(xy[:, 1], -1) - np.roll(xy[:, 0], -1) * xy[:, 1])))
    ext = [i for i, a in enumerate(area) if a > 0]
    hol = [i for i, a in enumerate(area) if a < 0]
    if len(ext) == 1:
        out_faces.append((int(cls[f]), [rings[ext[0]]] + [rings[i] for i in hol]))
    else:                                           # a face split into several lobes by the node split
        polys = [Polygon(V[rings[i]] / 1000.0) for i in ext]
        for k, i in enumerate(ext):
            hs = [rings[j] for j in hol if polys[k].contains(Polygon(V[rings[j]] / 1000.0).representative_point())]
            out_faces.append((int(cls[f]), [rings[i]] + hs))
print('faces after split', len(out_faces))

ring_v, ring_len, ring_face, ring_hole, face_class = [], [], [], [], []
for fi, (c, rings) in enumerate(out_faces):
    face_class.append(c)
    for k, r in enumerate(rings):
        ring_v.extend(r)
        ring_len.append(len(r))
        ring_face.append(fi)
        ring_hole.append(0 if k == 0 else 1)
verts = np.array(verts, np.int32)
ring_v = np.array(ring_v, np.int32)
ring_len = np.array(ring_len, np.int32)
ring_face = np.array(ring_face, np.int32)
ring_hole = np.array(ring_hole, np.uint8)
face_class = np.array(face_class, np.uint8)

# ---- 4. verify twin edges --------------------------------------------------------------------------------------
start = np.concatenate([[0], np.cumsum(ring_len)[:-1]])
ring_of = np.repeat(np.arange(len(ring_len)), ring_len)
idx = np.arange(len(ring_v))
last = start[ring_of] + ring_len[ring_of] - 1
nxt_i = np.where(idx == last, start[ring_of], idx + 1)
ea = ring_v.astype(np.int64)
eb = ring_v[nxt_i].astype(np.int64)
N = len(verts)
key, tkey = ea * N + eb, eb * N + ea
skey = np.sort(key)
dup = int(np.sum(skey[1:] == skey[:-1]))
pos = np.minimum(np.searchsorted(skey, tkey), len(skey) - 1)
has = skey[pos] == tkey
nt = np.where(~has)[0]
# the edges without twin must form exactly ONE closed loop (the outer outline of the plaque)
succ = {int(ea[i]): int(eb[i]) for i in nt}
loop_ok = False
if len(succ) == len(nt) and len(nt):
    s0 = next(iter(succ)); cur = succ[s0]; n = 1
    while cur != s0 and n <= len(nt):
        cur = succ[cur]; n += 1
    loop_ok = (cur == s0 and n == len(nt))
rimx = np.abs(verts[ea[nt], 0]) / 1000.0; rimy = np.abs(verts[ea[nt], 1]) / 1000.0
print('rings', len(ring_len), 'verts', N, 'directed edges', len(key), '| duplicate directed edges', dup,
      '| edges without twin', len(nt), '| they form ONE closed outline loop:', loop_ok)
if not loop_ok or dup:
    raise SystemExit('conformity check FAILED')
np.savez_compressed(dst, verts=verts, ring_v=ring_v, ring_len=ring_len, ring_face=ring_face, ring_hole=ring_hole,
                    face_class=face_class, nominal_extent_mm=np.float64(d.get('extent', 238.0)),
                    layout=np.array(d.get('layout', 'round')))
print('saved', dst, '%.2f MB' % (os.path.getsize(dst) / 1e6))
