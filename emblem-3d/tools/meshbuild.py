"""Reference (numpy) mesh builder for the emblem plaque. The Blender script re-implements exactly this algorithm."""
import numpy as np
import mapbox_earcut as earcut
from shapely.geometry import Point, Polygon, box
from shapely import affinity
import shapely

BLACK, RED, GREEN, CREAM, TAN, BROWN = 1, 2, 3, 4, 5, 6

BASE = 3.6
RELIEF = {GREEN: 0.4, CREAM: 0.4, TAN: 0.6, BROWN: 0.8, RED: 0.8, BLACK: 1.2}


def load(path):
    d = np.load(path)
    return {k: d[k] for k in d.files}


def triangulate_ring_sets(P, ring_v, ring_len, ring_face, nfaces):
    """earcut every face (exterior + holes). returns tri (T,3) global vertex ids, tri_face (T,)"""
    start = np.concatenate([[0], np.cumsum(ring_len)])
    tris, tf = [], []
    # rings are stored face by face, exterior first
    r = 0
    nr = len(ring_len)
    while r < nr:
        f = ring_face[r]
        r2 = r
        while r2 < nr and ring_face[r2] == f:
            r2 += 1
        ids = ring_v[start[r]:start[r2]]
        ends = np.cumsum(ring_len[r:r2]).astype(np.uint32)
        xy = P[ids].astype(np.float64)
        t = earcut.triangulate_float64(xy, ends).reshape(-1, 3)
        tri = orient_ccw(P, ids[t])
        tri = tri[tri_area2(P, tri) != 0]                       # zero-area triangles carry no orientation
        tri = repair_dropped(P, tri, ids, ring_len[r:r2])
        tris.append(tri)
        tf.append(np.full(len(tri), f, np.int32))
        r = r2
    tri = np.concatenate(tris)
    tf = np.concatenate(tf)
    return tri, tf


def repair_dropped(P, tri, ids, lens):
    """tri must already be CCW. earcut silently drops vertices that are exactly collinear with their neighbours
    (also along hole bridges), leaving T-junctions against neighbouring faces / walls.
    Fix: every boundary edge a->c of the triangulation that is not a ring edge is split at the ring vertices lying
    exactly on it (integer arithmetic), by fanning the triangle that owns it (collinear => same area).
    Repeats until stable."""
    succ = {}
    off = 0
    for n in lens:
        ring = ids[off:off + n]
        for i in range(n):
            succ[int(ring[i])] = int(ring[(i + 1) % n])
        off += n
    ring_pts = P[ids].astype(np.int64)
    ring_id = ids.astype(np.int64)
    tl = [tuple(int(v) for v in t) for t in tri]
    for _ in range(40):
        edge_tri = {}
        for k, (x, y, z) in enumerate(tl):
            edge_tri[(x, y)] = k
            edge_tri[(y, z)] = k
            edge_tri[(z, x)] = k
        dead = set()
        extra = []
        for (a, c), k in edge_tri.items():
            if k in dead or (c, a) in edge_tri or succ.get(a) == c:
                continue
            pa, pc = P[a].astype(np.int64), P[c].astype(np.int64)
            d = pc - pa
            rel = ring_pts - pa
            cross = rel[:, 0] * d[1] - rel[:, 1] * d[0]
            dot = rel[:, 0] * d[0] + rel[:, 1] * d[1]
            dd = int(d[0] * d[0] + d[1] * d[1])
            m = (cross == 0) & (dot > 0) & (dot < dd)
            if not m.any():
                continue
            cand = ring_id[m]
            tpar = dot[m]
            cand = cand[np.argsort(tpar)]
            cand = [int(v) for v in dict.fromkeys(cand.tolist())]
            x, y, z = tl[k]
            if (x, y) == (a, c):
                o = z
            elif (y, z) == (a, c):
                o = x
            else:
                o = y
            chain = [a] + cand + [c]
            for i in range(len(chain) - 1):
                extra.append((chain[i], chain[i + 1], o))
            dead.add(k)
        if not dead:
            break
        tl = [t for k, t in enumerate(tl) if k not in dead] + extra
    return np.array(tl, dtype=np.int64).reshape(-1, 3)


def tri_area2(P, tri):
    a, b, c = P[tri[:, 0]].astype(np.int64), P[tri[:, 1]].astype(np.int64), P[tri[:, 2]].astype(np.int64)
    return (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])


def orient_ccw(P, tri):
    a, b, c = P[tri[:, 0]].astype(np.int64), P[tri[:, 1]].astype(np.int64), P[tri[:, 2]].astype(np.int64)
    cr = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    tri = tri.copy()
    neg = cr < 0
    tri[neg] = tri[neg][:, [0, 2, 1]]
    return tri


class Builder:
    """accumulates triangles over (vertex id, z) pairs and emits a compact mesh"""

    def __init__(self, P):
        self.P = P
        self.zs = []
        self.z_index = {}
        self.chunks = []              # list of (vid(T,3), zid(T,3))

    def zid(self, z):
        k = round(float(z), 6)
        if k not in self.z_index:
            self.z_index[k] = len(self.zs)
            self.zs.append(k)
        return self.z_index[k]

    def add_tris(self, tri, z):
        """tri (T,3) vertex ids; z scalar or (T,) per-tri heights"""
        z = np.broadcast_to(np.asarray(z, dtype=np.float64), (len(tri),))
        ks = np.array([self.zid(v) for v in np.unique(z)])
        uz = np.unique(z)
        zi = ks[np.searchsorted(uz, z)]
        self.chunks.append((tri, np.repeat(zi[:, None], 3, axis=1)))

    def add_tris_zz(self, vid, zz):
        """vid (T,3) vertex ids, zz (T,3) heights per corner"""
        uz = np.unique(zz)
        ks = np.array([self.zid(v) for v in uz])
        self.chunks.append((vid, ks[np.searchsorted(uz, zz)]))

    def add_walls(self, a, b, lo, hi):
        """quad per edge: (a,lo),(b,lo),(b,hi),(a,hi); outward normal = right of a->b"""
        v1 = np.stack([a, b, b], axis=1)
        z1 = np.stack([lo, lo, hi], axis=1)
        v2 = np.stack([a, b, a], axis=1)
        z2 = np.stack([lo, hi, hi], axis=1)
        self.add_tris_zz(np.concatenate([v1, v2]), np.concatenate([z1, z2]))

    def add_walls_nodal(self, a, b, lo, hi, node_z):
        """Walls whose vertical sides are split at the heights present at each end node (node_z: vid -> sorted z list),
        so neighbouring walls share identical vertical edges (no T-junctions)."""
        simple = np.ones(len(a), bool)
        extra_idx = []
        for i in range(len(a)):
            za = node_z.get(int(a[i]))
            zb = node_z.get(int(b[i]))
            ok = True
            if za is not None and ((za > lo[i] + 1e-9) & (za < hi[i] - 1e-9)).any():
                ok = False
            if ok and zb is not None and ((zb > lo[i] + 1e-9) & (zb < hi[i] - 1e-9)).any():
                ok = False
            if not ok:
                simple[i] = False
                extra_idx.append(i)
        if simple.any():
            self.add_walls(a[simple], b[simple], lo[simple], hi[simple])
        vids, zzs = [], []
        for i in extra_idx:
            ai, bi, l, h = int(a[i]), int(b[i]), float(lo[i]), float(hi[i])
            zl = [l] + [z for z in node_z.get(ai, []) if l + 1e-9 < z < h - 1e-9] + [h]
            zr = [l] + [z for z in node_z.get(bi, []) if l + 1e-9 < z < h - 1e-9] + [h]
            p = q = 0
            while p < len(zl) - 1 or q < len(zr) - 1:
                adv_a = q >= len(zr) - 1 or (p < len(zl) - 1 and zl[p + 1] <= zr[q + 1])
                if adv_a:
                    vids.append((ai, bi, ai)); zzs.append((zl[p], zr[q], zl[p + 1]))
                    p += 1
                else:
                    vids.append((ai, bi, bi)); zzs.append((zl[p], zr[q], zr[q + 1]))
                    q += 1
        if vids:
            self.add_tris_zz(np.array(vids, np.int64), np.array(zzs, np.float64))

    def mesh(self):
        vid = np.concatenate([c[0] for c in self.chunks])
        zid = np.concatenate([c[1] for c in self.chunks])
        N = len(self.P)
        L = len(self.zs)
        flat = (zid.astype(np.int64) * N + vid.astype(np.int64)).ravel()
        uniq, inv = np.unique(flat, return_inverse=True)
        zi = uniq // N
        vi = uniq % N
        V = np.c_[self.P[vi, 0] / 1000.0, self.P[vi, 1] / 1000.0, np.asarray(self.zs)[zi]]
        F = inv.reshape(-1, 3)
        # drop degenerate triangles (zero area from repeated indices)
        ok = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
        return V, F[ok]


def directed_edges(ring_v, ring_len, ring_face):
    start = np.concatenate([[0], np.cumsum(ring_len)[:-1]])
    idx = np.arange(len(ring_v))
    ring_of = np.repeat(np.arange(len(ring_len)), ring_len)
    nxt = idx + 1
    last = start[ring_of] + ring_len[ring_of] - 1
    nxt = np.where(idx == last, start[ring_of], nxt)
    a = ring_v[idx].astype(np.int64)
    b = ring_v[nxt].astype(np.int64)
    f = ring_face[ring_of]
    return a, b, f


def twins(a, b, nverts):
    key = a * nverts + b
    tkey = b * nverts + a
    order = np.argsort(key)
    skey = key[order]
    pos = np.searchsorted(skey, tkey)
    pos[pos >= len(skey)] = len(skey) - 1
    ok = skey[pos] == tkey
    return np.where(ok, order[pos], -1)       # index of twin directed edge or -1


def node_heights(ring_v, ring_len, ring_face, heights, rim_vertices=()):
    """vid -> sorted np.array of the top heights of every face incident to the vertex (plus 0 on the rim)"""
    ring_of = np.repeat(np.arange(len(ring_len)), ring_len)
    hh = np.round(heights[ring_face[ring_of]], 6)
    tmp = {}
    for v, h in zip(ring_v.tolist(), hh.tolist()):
        tmp.setdefault(v, set()).add(h)
    for v in rim_vertices:
        tmp.setdefault(int(v), set()).add(0.0)
    return {v: np.array(sorted(hs)) for v, hs in tmp.items()}


def keyhole_polys(positions, big_d=9.0, slot_w=4.6, slot_len=9.5):
    out = []
    for (x, y) in positions:
        circ = Point(x, y).buffer(big_d / 2, 64)
        slot = shapely.LineString([(x, y), (x, y + slot_len)]).buffer(slot_w / 2, 32)
        out.append(shapely.union_all([circ, slot]))
    return out


def add_ring_polygon(P, poly, cw=False):
    """append polygon exterior vertices (mm) to P; returns (P, ids ring)"""
    pts = np.asarray(poly.exterior.coords)[:-1]
    pts = np.round(pts * 1000.0).astype(np.int32)
    ids = len(P) + np.arange(len(pts))
    P = np.vstack([P, pts])
    sa = shapely.Polygon(pts / 1000.0)
    ccw = sa.exterior.is_ccw
    if cw == ccw:
        ids = ids[::-1]
    return P, ids


def build_shell(d, heights, keyholes=None, pocket_depth=2.4, base_top=None):
    """Single closed heightfield shell: flat bottom at z=0, top surface = per-face height, walls between faces.
    heights: (nfaces,) top z of every face. keyholes: list of shapely polygons cut into the back."""
    P = d['verts'].copy()
    ring_v, ring_len, ring_face = d['ring_v'], d['ring_len'], d['ring_face']
    nf = len(d['face_class'])
    tri, tf = triangulate_ring_sets(P, ring_v, ring_len, ring_face, nf)
    B = Builder(P)
    B.add_tris(tri, heights[tf])
    a, b, f = directed_edges(ring_v, ring_len, ring_face)
    tw = twins(a, b, len(P))
    g = np.where(tw >= 0, f[np.maximum(tw, 0)], -1)
    hi = heights[f]
    lo = np.where(g >= 0, heights[np.maximum(g, 0)], 0.0)
    w = hi > lo + 1e-9
    rim = np.where(tw < 0)[0]
    node_z = node_heights(ring_v, ring_len, ring_face, heights, a[rim])
    B.add_walls_nodal(a[w], b[w], lo[w], hi[w], node_z)
    # --- bottom: outer rim ring (edges without twin form it) + keyholes as holes
    # order rim edges into a loop
    nxt = {int(a[i]): int(b[i]) for i in rim}
    start = int(a[rim[0]])
    loop = [start]
    cur = nxt[start]
    while cur != start:
        loop.append(cur)
        cur = nxt[cur]
    loop = np.array(loop)
    assert len(loop) == len(rim), 'rim is not a single loop'
    rings = [loop]
    holes_ids = []
    if keyholes:
        for kp in keyholes:
            P, ids = add_ring_polygon(P, kp, cw=True)       # CW => hole interior on the right of a->b
            B.P = P
            holes_ids.append(ids)
    allr = [loop] + holes_ids
    ids_cat = np.concatenate(allr)
    ends = np.cumsum([len(r) for r in allr]).astype(np.uint32)
    t = earcut.triangulate_float64(P[ids_cat].astype(np.float64), ends).reshape(-1, 3)
    bt = orient_ccw(P, ids_cat[t])
    bt = bt[tri_area2(P, bt) != 0]
    bt = repair_dropped(P, bt, ids_cat, np.array([len(r) for r in allr]))
    B.add_tris(bt[:, [0, 2, 1]], 0.0)                      # normal -z
    for ids in holes_ids:
        aa = ids
        bb = np.roll(ids, -1)
        B.add_walls(aa, bb, np.zeros(len(aa)), np.full(len(aa), pocket_depth))
        t2 = earcut.triangulate_float64(P[ids].astype(np.float64), np.array([len(ids)], np.uint32)).reshape(-1, 3)
        ct = orient_ccw(P, ids[t2])
        ct = ct[tri_area2(P, ct) != 0]
        ct = repair_dropped(P, ct, ids, np.array([len(ids)]))
        B.add_tris(ct[:, [0, 2, 1]], pocket_depth)         # ceiling, normal -z
    return B.mesh()


def build_prism(d, mask_faces, z0, z1):
    """closed prism over the union of the selected faces: bottom z0, top z1."""
    P = d['verts']
    ring_v, ring_len, ring_face = d['ring_v'], d['ring_len'], d['ring_face']
    nf = len(d['face_class'])
    tri, tf = triangulate_ring_sets(P, ring_v, ring_len, ring_face, nf)
    sel = mask_faces[tf]
    B = Builder(P)
    B.add_tris(tri[sel], z1)
    B.add_tris(tri[sel][:, [0, 2, 1]], z0)
    a, b, f = directed_edges(ring_v, ring_len, ring_face)
    tw = twins(a, b, len(P))
    g = np.where(tw >= 0, f[np.maximum(tw, 0)], -1)
    inside = mask_faces[f]
    nb_in = np.where(g >= 0, mask_faces[np.maximum(g, 0)], False)
    w = inside & ~nb_in
    B.add_walls(a[w], b[w], np.full(w.sum(), z0), np.full(w.sum(), z1))
    return B.mesh()
