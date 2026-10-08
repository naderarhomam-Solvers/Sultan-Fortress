# -*- coding: utf-8 -*-
"""
SMB-87  |  اللواء 87 مهام خاصة  |  3D-printable wall plaque generator for Blender
==========================================================================================
Builds a watertight, print-ready relief plaque (diameter 238 mm by default -> fits the 250 x 250 mm bed of the
Anycubic Kobra 3) from the vectorised emblem layers stored in  sultan_emblem_layers.npz  (same folder).

HOW TO USE (tested on Blender 5.0.1; uses only standard bpy / mathutils / numpy API)
  1. Keep this file and  sultan_emblem_layers.npz  in the same folder.
  2. Blender > Scripting workspace > Open  build_sultan_plaque.py  > press "Run Script" (Alt+P).
     (Or headless:  blender -b -P build_sultan_plaque.py )
  3. The result is built in the scene (coloured parts + merged solid) and exported to  <folder>/SMB87_output/ :
        SMB87_plaque_merged.stl      one solid, for single-colour printing
        SMB87_plaque_parts.3mf       one object, 6 colour parts (black/red/green/cream/tan/brown) for multi-colour
        parts/SMB87_<colour>.stl     the same 6 parts as separate STL files
  Change the settings in the block below (diameter, relief heights, hangers ...) and run again.

The geometry core only needs numpy, so it also runs outside Blender (python build_sultan_plaque.py).
Units: 1 Blender unit = 1 mm.   Print orientation: back side on the bed, front (relief) up - no supports needed.
"""
import os
import sys
import time
import zipfile
import numpy as np

# =============================================================================================================
#  SETTINGS  (edit here)
# =============================================================================================================
DATA_FILE = "sultan_emblem_layers.npz"     # vectorised emblem (looked up next to this script / the .blend file)
OUTPUT_DIR = None                          # None -> <data folder>/SMB87_output

PLAQUE_DIAMETER = 238.0                    # mm, outer diameter of the black rim.  Kobra 3 bed = 250 x 250
BED_XY = (250.0, 250.0)                    # printer bed, only used for the fit check
BED_SAFE_MARGIN = 3.0                      # mm kept free on every side (skirt / brim)

BASE_THICKNESS = 3.6                       # mm, black back plate (multiple of the 0.2 mm layer height)
RELIEF = {                                 # mm above the back plate, multiples of 0.2 mm
    "green": 0.4,                          #   the green ring band          (field)
    "cream": 0.4,                          #   the cream disc               (field)
    "tan":   0.6,                          #   snake body / sword blade
    "brown": 0.8,                          #   snake scales + outline, sword shading
    "red":   0.8,                          #   the two thin red rings
    "black": 1.2,                          #   rims, eagle line-work, all lettering, "87"
}

HANGERS = True                             # two keyhole pockets on the back for wall mounting (screw head <= 8.5 mm)
HANGER_POSITIONS = [(-45.0, 55.0), (45.0, 55.0)]   # mm from the plaque centre (slot points up, +Y)
HANGER_HEAD_D = 9.0                        # mm, entry hole for the screw head
HANGER_SLOT_W = 4.6                        # mm, slot for the screw shank
HANGER_SLOT_LEN = 9.5                      # mm, slide distance
HANGER_DEPTH = 2.4                         # mm, pocket depth from the back (must stay below BASE_THICKNESS - 0.8)

EXPORT_MERGED_STL = True
EXPORT_PARTS = True                        # 3MF (one object, six parts) + six STL files
BUILD_IN_BLENDER = True                    # create objects / materials / camera / light in the open scene
HIDE_MERGED_IN_VIEWPORT = True             # show the colour parts, keep the merged solid hidden (still exported)

# colours used for the Blender materials and the 3MF colour table (sRGB 0-255)
PART_COLORS = {
    "black": (14, 14, 14), "red": (125, 25, 8), "green": (89, 113, 14),
    "cream": (208, 196, 129), "tan": (168, 138, 92), "brown": (110, 62, 36),
}
CLASS_NAME = {1: "black", 2: "red", 3: "green", 4: "cream", 5: "tan", 6: "brown"}
CLASS_ID = {v: k for k, v in CLASS_NAME.items()}

try:                                       # Blender is optional: the geometry core is pure numpy
    import bpy
    from mathutils import Vector
    from mathutils import geometry as mgeo
    IN_BLENDER = True
except Exception:                          # pragma: no cover
    IN_BLENDER = False


# =============================================================================================================
#  helpers: data, topology
# =============================================================================================================
def script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        pass
    if IN_BLENDER:
        for p in (bpy.path.abspath("//"), os.path.dirname(bpy.data.filepath or ""), os.getcwd()):
            if p and os.path.exists(os.path.join(p, DATA_FILE)):
                return p
        for t in bpy.data.texts:                       # script opened from a saved text block
            p = os.path.dirname(bpy.path.abspath(t.filepath)) if t.filepath else ""
            if p and os.path.exists(os.path.join(p, DATA_FILE)):
                return p
    return os.getcwd()


def load_layers(path):
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Cannot find %s\nPut sultan_emblem_layers.npz next to build_sultan_plaque.py (or set DATA_FILE to an "
            "absolute path).\nلم يتم العثور على ملف البيانات: ضعه في نفس مجلد السكربت." % path)
    d = np.load(path)
    return {k: d[k] for k in d.files}


def directed_edges(ring_v, ring_len, ring_face):
    start = np.concatenate([[0], np.cumsum(ring_len)[:-1]])
    idx = np.arange(len(ring_v))
    ring_of = np.repeat(np.arange(len(ring_len)), ring_len)
    last = start[ring_of] + ring_len[ring_of] - 1
    nxt = np.where(idx == last, start[ring_of], idx + 1)
    return ring_v.astype(np.int64), ring_v[nxt].astype(np.int64), ring_face[ring_of]


def twins(a, b, nverts):
    key = a * nverts + b
    tkey = b * nverts + a
    order = np.argsort(key)
    skey = key[order]
    pos = np.minimum(np.searchsorted(skey, tkey), len(skey) - 1)
    return np.where(skey[pos] == tkey, order[pos], -1)       # index of the opposite directed edge, or -1 on the rim


def tri_area2(P, tri):
    a, b, c = (P[tri[:, i]].astype(np.int64) for i in range(3))
    return (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])


def orient_ccw(P, tri):
    tri = tri.copy()
    neg = tri_area2(P, tri) < 0
    tri[neg] = tri[neg][:, [0, 2, 1]]
    return tri


def repair_dropped(P, tri, ids, lens):
    """Triangulators silently drop vertices that are exactly collinear with their neighbours (also along hole
    bridges), which leaves T-junctions against the walls. Every boundary edge a->c of the triangulation that is not a
    ring edge is split at the ring vertices lying exactly on it (integer arithmetic) by fanning its triangle."""
    succ, off = {}, 0
    for n in lens:
        ring = ids[off:off + n]
        for i in range(n):
            succ[int(ring[i])] = int(ring[(i + 1) % n])
        off += n
    ring_pts, ring_id = P[ids].astype(np.int64), ids.astype(np.int64)
    tl = [tuple(int(v) for v in t) for t in tri]
    for _ in range(40):
        edge_tri = {}
        for k, (x, y, z) in enumerate(tl):
            edge_tri[(x, y)] = k
            edge_tri[(y, z)] = k
            edge_tri[(z, x)] = k
        dead, extra = set(), []
        for (a, c), k in edge_tri.items():
            if k in dead or (c, a) in edge_tri or succ.get(a) == c:
                continue
            pa, pc = P[a].astype(np.int64), P[c].astype(np.int64)
            d = pc - pa
            rel = ring_pts - pa
            cross = rel[:, 0] * d[1] - rel[:, 1] * d[0]
            dot = rel[:, 0] * d[0] + rel[:, 1] * d[1]
            m = (cross == 0) & (dot > 0) & (dot < int(d[0] * d[0] + d[1] * d[1]))
            if not m.any():
                continue
            cand = ring_id[m][np.argsort(dot[m])]
            cand = [int(v) for v in dict.fromkeys(cand.tolist())]
            x, y, z = tl[k]
            o = z if (x, y) == (a, c) else (x if (y, z) == (a, c) else y)
            chain = [a] + cand + [c]
            for i in range(len(chain) - 1):
                extra.append((chain[i], chain[i + 1], o))
            dead.add(k)
        if not dead:
            break
        tl = [t for k, t in enumerate(tl) if k not in dead] + extra
    return np.array(tl, dtype=np.int64).reshape(-1, 3)


def tessellate(P, loops):
    """triangulate a polygon (loops[0] outer, others holes; arrays of vertex ids) -> (T,3) vertex ids, CCW."""
    ids = np.concatenate(loops)
    lens = np.array([len(l) for l in loops])
    if IN_BLENDER:
        polys = [[Vector((P[v][0] / 1000.0, P[v][1] / 1000.0, 0.0)) for v in l] for l in loops]
        t = np.array(mgeo.tessellate_polygon(polys), dtype=np.int64).reshape(-1, 3)
    else:
        import mapbox_earcut as earcut
        t = earcut.triangulate_float64(P[ids].astype(np.float64), np.cumsum(lens).astype(np.uint32)).reshape(-1, 3)
    tri = orient_ccw(P, ids[t])
    tri = tri[tri_area2(P, tri) != 0]
    return repair_dropped(P, tri, ids, lens)


# =============================================================================================================
#  mesh accumulation
# =============================================================================================================
class Acc:
    """Collects triangles whose corners are (vertex id, height) pairs and emits a compact indexed mesh."""

    def __init__(self, P, scale):
        self.P, self.scale = P, scale
        self.zs, self.zi, self.chunks = [], {}, []

    def _z(self, z):
        k = round(float(z), 6)
        if k not in self.zi:
            self.zi[k] = len(self.zs)
            self.zs.append(k)
        return self.zi[k]

    def tris_zz(self, vid, zz):
        uz = np.unique(zz)
        ks = np.array([self._z(v) for v in uz])
        self.chunks.append((np.asarray(vid, np.int64), ks[np.searchsorted(uz, zz)]))

    def tris(self, tri, z):
        z = np.broadcast_to(np.asarray(z, np.float64), (len(tri),))
        self.tris_zz(tri, np.repeat(z[:, None], 3, axis=1))

    def walls(self, a, b, lo, hi):
        """vertical quad (a,lo)(b,lo)(b,hi)(a,hi); outward normal = right of a->b"""
        v = np.concatenate([np.stack([a, b, b], 1), np.stack([a, b, a], 1)])
        z = np.concatenate([np.stack([lo, lo, hi], 1), np.stack([lo, hi, hi], 1)])
        self.tris_zz(v, z)

    def walls_nodal(self, a, b, lo, hi, node_z):
        """walls whose vertical sides are split at the heights present at each end node, so that neighbouring
        walls share identical vertical edges (no T-junctions)."""
        simple = np.ones(len(a), bool)
        for i in range(len(a)):
            for n, ok in ((int(a[i]), 0), (int(b[i]), 1)):
                z = node_z.get(n)
                if z is not None and ((z > lo[i] + 1e-9) & (z < hi[i] - 1e-9)).any():
                    simple[i] = False
                    break
        if simple.any():
            self.walls(a[simple], b[simple], lo[simple], hi[simple])
        vids, zzs = [], []
        for i in np.where(~simple)[0]:
            ai, bi, l, h = int(a[i]), int(b[i]), float(lo[i]), float(hi[i])
            zl = [l] + [z for z in node_z.get(ai, []) if l + 1e-9 < z < h - 1e-9] + [h]
            zr = [l] + [z for z in node_z.get(bi, []) if l + 1e-9 < z < h - 1e-9] + [h]
            p = q = 0
            while p < len(zl) - 1 or q < len(zr) - 1:
                if q >= len(zr) - 1 or (p < len(zl) - 1 and zl[p + 1] <= zr[q + 1]):
                    vids.append((ai, bi, ai)); zzs.append((zl[p], zr[q], zl[p + 1])); p += 1
                else:
                    vids.append((ai, bi, bi)); zzs.append((zl[p], zr[q], zr[q + 1])); q += 1
        if vids:
            self.tris_zz(np.array(vids), np.array(zzs, np.float64))

    def mesh(self):
        vid = np.concatenate([c[0] for c in self.chunks])
        zid = np.concatenate([c[1] for c in self.chunks])
        N = len(self.P)
        uniq, inv = np.unique((zid.astype(np.int64) * N + vid.astype(np.int64)).ravel(), return_inverse=True)
        V = np.c_[self.P[uniq % N, 0] / 1000.0 * self.scale, self.P[uniq % N, 1] / 1000.0 * self.scale,
                  np.asarray(self.zs)[uniq // N]]
        F = inv.reshape(-1, 3)
        ok = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
        return V.astype(np.float64), F[ok].astype(np.int64)


def node_heights(L, heights, rim_vertices):
    """vertex id -> sorted heights of all faces touching it (+0 on the rim): where the vertical edges are split"""
    ring_of = np.repeat(np.arange(len(L["ring_len"])), L["ring_len"])
    hh = np.round(heights[L["ring_face"][ring_of]], 6)
    tmp = {}
    for v, h in zip(L["ring_v"].tolist(), hh.tolist()):
        tmp.setdefault(v, set()).add(h)
    for v in rim_vertices:
        tmp.setdefault(int(v), set()).add(0.0)
    return {v: np.array(sorted(s)) for v, s in tmp.items()}


def keyhole_outline(cx, cy, head_d, slot_w, slot_len, n_arc=48):
    """keyhole = big circle + slot pointing +Y, outline counter-clockwise (mm)"""
    R, r = head_d / 2.0, slot_w / 2.0
    phi = np.arccos(r / R)                                    # circle angle where the slot sides meet the circle
    arc = np.linspace(np.pi - phi, 2 * np.pi + phi, n_arc * 4)
    pts = [(cx + R * np.cos(t), cy + R * np.sin(t)) for t in arc]
    pts.append((cx + r, cy + slot_len))
    for t in np.linspace(0, np.pi, n_arc // 2)[1:-1]:
        pts.append((cx + r * np.cos(t), cy + slot_len + r * np.sin(t)))
    pts.append((cx - r, cy + slot_len))                     # (the slot side runs back down to the first arc point)
    return np.array(pts)


def add_polygon(P, xy_mm, scale, cw):
    """append polygon vertices (mm, final size) to P as integer um in the un-scaled data frame; returns (P, ids)"""
    pts = np.round(np.asarray(xy_mm) / scale * 1000.0).astype(np.int32)
    keep = np.r_[True, np.any(np.diff(pts, axis=0) != 0, axis=1)]
    pts = pts[keep]
    if np.all(pts[0] == pts[-1]):                              # closing duplicate
        pts = pts[:-1]
    ids = len(P) + np.arange(len(pts))
    P = np.vstack([P, pts])
    area = 0.5 * np.sum(pts[:, 0].astype(np.int64) * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1).astype(np.int64) * pts[:, 1])
    if (area < 0) != cw:
        ids = ids[::-1]
    return P, ids


# =============================================================================================================
#  the two solids
# =============================================================================================================
def build_shell(L, heights, scale, keyholes_mm=None, pocket_depth=0.0):
    """ONE closed heightfield shell: flat bottom at z=0, top = per-face height, vertical walls between faces.
    Optional keyhole pockets are cut into the flat back."""
    P = L["verts"].copy()
    ring_v, ring_len, ring_face = L["ring_v"], L["ring_len"], L["ring_face"]
    acc = Acc(P, scale)
    acc.tris(L["tri"], heights[L["tri_face"]])                                     # top surface
    a, b, f = directed_edges(ring_v, ring_len, ring_face)
    tw = twins(a, b, len(P))
    g = np.where(tw >= 0, f[np.maximum(tw, 0)], -1)
    hi = heights[f]
    lo = np.where(g >= 0, heights[np.maximum(g, 0)], 0.0)
    w = hi > lo + 1e-9
    rim = np.where(tw < 0)[0]
    acc.walls_nodal(a[w], b[w], lo[w], hi[w], node_heights(L, heights, a[rim]))   # walls (incl. outer rim: 0 -> top)
    nxt = {int(a[i]): int(b[i]) for i in rim}                                      # order the rim edges into a loop
    s0 = int(a[rim[0]])
    loop, cur = [s0], nxt[s0]
    while cur != s0:
        loop.append(cur)
        cur = nxt[cur]
    assert len(loop) == len(rim), "outer rim is not a single loop"
    loops, holes = [np.array(loop)], []
    for (x, y) in (keyholes_mm or []):
        P, ids = add_polygon(P, keyhole_outline(x, y, HANGER_HEAD_D, HANGER_SLOT_W, HANGER_SLOT_LEN), scale, cw=True)
        holes.append(ids)
    acc.P = P
    bt = tessellate(P, loops + holes)                                              # back face (normal -z)
    acc.tris(bt[:, [0, 2, 1]], 0.0)
    for ids in holes:                                                              # pocket walls + ceiling
        acc.walls(ids, np.roll(ids, -1), np.zeros(len(ids)), np.full(len(ids), pocket_depth))
        ct = tessellate(P, [ids])
        acc.tris(ct[:, [0, 2, 1]], pocket_depth)
    return acc.mesh()


def build_prism(L, sel_faces, z0, z1, scale):
    """closed prism over the union of the selected faces (one colour part): bottom z0, top z1"""
    P = L["verts"]
    ring_v, ring_len, ring_face = L["ring_v"], L["ring_len"], L["ring_face"]
    acc = Acc(P, scale)
    t = L["tri"][sel_faces[L["tri_face"]]]
    acc.tris(t, z1)
    acc.tris(t[:, [0, 2, 1]], z0)
    a, b, f = directed_edges(ring_v, ring_len, ring_face)
    tw = twins(a, b, len(P))
    nb = np.where(tw >= 0, sel_faces[f[np.maximum(tw, 0)]], False)
    w = sel_faces[f] & ~nb
    acc.walls(a[w], b[w], np.full(w.sum(), z0), np.full(w.sum(), z1))
    return acc.mesh()


# =============================================================================================================
#  checks + writers
# =============================================================================================================
def check_mesh(V, F):
    e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    # winding consistency: every directed edge must occur exactly once
    de = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = de[:, 0].astype(np.int64) * len(V) + de[:, 1]
    consistent = len(np.unique(key)) == len(key)
    tri = V[F]
    vol = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)
    return dict(tris=len(F), verts=len(V), open_or_nonmanifold_edges=int((cnt != 2).sum()), winding_ok=consistent,
                watertight=bool((cnt == 2).all() and consistent), volume_mm3=vol,
                bbox_min=V.min(0).round(3).tolist(), bbox_max=V.max(0).round(3).tolist())


def write_stl(path, V, F, name="SMB87"):
    tri = V[F].astype(np.float32)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(ln > 0, n / np.maximum(ln, 1e-30), 0).astype(np.float32)
    rec = np.zeros(len(F), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as fh:
        fh.write(name.encode("ascii", "ignore")[:79].ljust(80, b" "))
        fh.write(np.uint32(len(F)).tobytes())
        fh.write(rec.tobytes())


def write_3mf(path, parts, title="SMB87 plaque"):
    """parts: list of (name, V, F, (r,g,b)). One assembly object with one mesh component per colour."""
    mats = "".join('<base name="%s" displaycolor="#%02X%02X%02XFF"/>' % (n, *c) for n, _, _, c in parts)
    objs, comps = [], []
    for i, (n, V, F, c) in enumerate(parts):
        vx = "".join("<vertex x=\"%.4f\" y=\"%.4f\" z=\"%.4f\"/>" % tuple(v) for v in V)
        tr = "".join("<triangle v1=\"%d\" v2=\"%d\" v3=\"%d\"/>" % tuple(t) for t in F)
        objs.append('<object id="%d" name="%s" type="model" pid="1" pindex="%d"><mesh><vertices>%s</vertices>'
                    '<triangles>%s</triangles></mesh></object>' % (i + 2, n, i, vx, tr))
        comps.append('<component objectid="%d"/>' % (i + 2))
    aid = len(parts) + 2
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><metadata name="Title">%s</metadata>'
             '<resources><basematerials id="1">%s</basematerials>%s<object id="%d" name="%s" type="model">'
             '<components>%s</components></object></resources><build><item objectid="%d"/></build></model>'
             % (title, mats, "".join(objs), aid, title, "".join(comps), aid))
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
          'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships'
          '+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/'
            '3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)


# =============================================================================================================
#  Blender scene
# =============================================================================================================
def make_object(name, V, F, rgb, collection):
    me = bpy.data.meshes.new(name)
    me.from_pydata(V.tolist(), [], F.tolist())
    me.update()
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    mat = bpy.data.materials.new("MAT_" + name)
    col = (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0)
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = col
            bsdf.inputs["Roughness"].default_value = 0.45
    except Exception:
        pass
    mat.diffuse_color = col
    me.materials.append(mat)
    return ob


def build_scene(parts, merged, diameter):
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 0.001
    sc.unit_settings.length_unit = "MILLIMETERS"
    name = "SMB87_Plaque"
    if name in bpy.data.collections:                         # re-running the script replaces the previous result
        old = bpy.data.collections[name]
        for ob in list(old.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(old)
    col = bpy.data.collections.new(name)
    sc.collection.children.link(col)
    for n, V, F, c in parts:
        make_object("SMB87_" + n, V, F, c, col)
    ob = make_object("SMB87_merged_solid", merged[0], merged[1], (150, 150, 150), col)
    if HIDE_MERGED_IN_VIEWPORT:
        ob.hide_viewport = True
        ob.hide_render = True
    cam = bpy.data.objects.get("SMB87_Camera")
    if cam is None:
        cd = bpy.data.cameras.new("SMB87_Camera")
        cam = bpy.data.objects.new("SMB87_Camera", cd)
        sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = diameter * 1.08
    cam.location = (0, 0, 300)
    cam.rotation_euler = (0, 0, 0)
    cam.data.clip_end = 2000
    sc.camera = cam
    if bpy.data.objects.get("SMB87_Sun") is None:
        ld = bpy.data.lights.new("SMB87_Sun", "SUN")
        ld.energy = 3.0
        lo = bpy.data.objects.new("SMB87_Sun", ld)
        sc.collection.objects.link(lo)
        lo.rotation_euler = (np.radians(35), np.radians(-25), np.radians(30))


# =============================================================================================================
#  main
# =============================================================================================================
def main():
    t0 = time.time()
    folder = script_dir()
    data_path = DATA_FILE if os.path.isabs(DATA_FILE) else os.path.join(folder, DATA_FILE)
    L = load_layers(data_path)
    scale = PLAQUE_DIAMETER / float(L["nominal_diameter_mm"])
    out_dir = OUTPUT_DIR or os.path.join(os.path.dirname(os.path.abspath(data_path)), "SMB87_output")
    os.makedirs(os.path.join(out_dir, "parts"), exist_ok=True)

    fit = max(PLAQUE_DIAMETER + 2 * BED_SAFE_MARGIN - BED_XY[0], PLAQUE_DIAMETER + 2 * BED_SAFE_MARGIN - BED_XY[1])
    print("[SMB87] plaque diameter %.1f mm  (bed %.0f x %.0f)  %s" % (
        PLAQUE_DIAMETER, BED_XY[0], BED_XY[1], "FITS" if fit <= 0 else "WARNING: too large for the bed with the safety margin"))
    if HANGERS and HANGER_DEPTH > BASE_THICKNESS - 0.8:
        raise ValueError("HANGER_DEPTH must be at most BASE_THICKNESS - 0.8 mm")

    cls = L["face_class"]
    rel = np.array([RELIEF[CLASS_NAME[c]] for c in range(1, 7)])
    heights = BASE_THICKNESS + rel[cls.astype(int) - 1]
    holes = HANGER_POSITIONS if HANGERS else []

    merged = build_shell(L, heights, scale, holes, HANGER_DEPTH)
    rep = check_mesh(*merged)
    print("[SMB87] merged solid : %d tris | watertight=%s | non-manifold edges=%d | volume %.1f cm3 | bbox %s .. %s" % (
        rep["tris"], rep["watertight"], rep["open_or_nonmanifold_edges"], rep["volume_mm3"] / 1000.0,
        rep["bbox_min"], rep["bbox_max"]))

    parts = []
    black_h = np.where(cls == CLASS_ID["black"], heights, BASE_THICKNESS)       # black part = back plate + black relief
    V, F = build_shell(L, black_h, scale, holes, HANGER_DEPTH)
    parts.append(("black", V, F, PART_COLORS["black"]))
    for n in ("red", "green", "cream", "tan", "brown"):
        V, F = build_prism(L, cls == CLASS_ID[n], BASE_THICKNESS, BASE_THICKNESS + RELIEF[n], scale)
        parts.append((n, V, F, PART_COLORS[n]))
    tot = 0.0
    for n, V, F, c in parts:
        r = check_mesh(V, F)
        tot += r["volume_mm3"]
        print("[SMB87] part %-6s: %7d tris | watertight=%s | volume %8.1f mm3" % (n, r["tris"], r["watertight"], r["volume_mm3"]))
    print("[SMB87] sum of parts %.1f mm3 vs merged %.1f mm3 (difference %.3f)" % (tot, rep["volume_mm3"], tot - rep["volume_mm3"]))
    pla = rep["volume_mm3"] / 1000.0 * 1.24
    print("[SMB87] ~%.0f g of PLA at 100%% infill; roughly %.0f g with 20%% infill" % (pla, pla * 0.45))

    if EXPORT_MERGED_STL:
        p = os.path.join(out_dir, "SMB87_plaque_merged.stl")
        write_stl(p, *merged, name="SMB87 merged")
        print("[SMB87] wrote", p)
    if EXPORT_PARTS:
        for n, V, F, c in parts:
            write_stl(os.path.join(out_dir, "parts", "SMB87_%s.stl" % n), V, F, name="SMB87 " + n)
        p = os.path.join(out_dir, "SMB87_plaque_parts.3mf")
        write_3mf(p, parts)
        print("[SMB87] wrote", p, "and 6 part STL files")
    if IN_BLENDER and BUILD_IN_BLENDER:
        build_scene(parts, merged, PLAQUE_DIAMETER)
        print("[SMB87] scene built (collection SMB87_Plaque)")
    print("[SMB87] done in %.1f s  ->  %s" % (time.time() - t0, out_dir))
    return dict(report=rep, parts=parts, merged=merged, out_dir=out_dir)


if __name__ == "__main__" or IN_BLENDER:
    RESULT = main()
