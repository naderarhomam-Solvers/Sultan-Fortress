"""Vectorise the segmented emblem into a conforming planar partition (faces) in millimetres.

faces: list of (class_id, shapely.Polygon) in plaque coordinates (origin = plaque centre, +y up),
for the nominal plaque diameter D_NOM. Rings are analytic circles; content boundaries are sub-pixel iso-contours."""
import sys, time, pickle, numpy as np, cv2, shapely
from shapely.geometry import LineString, Polygon, Point
from scipy.ndimage import map_coordinates
from skimage.measure import find_contours
from classify import *
from segment import segment, MM_PER_PX

S = 4
D_NOM = 238.0
CX6, CY6, R6 = RINGS[5]
SC = (D_NOM / 2) / R6                      # mm per original pixel
BLUR_SIGMA = 1.0                           # S-pixels, smooths the staircase of the thresholded masks
SIMPLIFY_MM = 0.010                        # Douglas-Peucker tolerance for content contours
N_CIRCLE = 2048
GRID_MM = 0.04                             # snap-rounding grid: merges near-coincident class boundaries


def to_mm(rc):
    x = WIN0 + (rc[:, 1] + 0.5) / S - 0.5
    y = WIN0 + (rc[:, 0] + 0.5) / S - 0.5
    return np.c_[(x - CX6) * SC, -(y - CY6) * SC]


def circle_xy(k, n=N_CIRCLE):
    cx, cy, R = RINGS[k]
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[((cx - CX6) + R * np.cos(t)) * SC, -((cy - CY6) + R * np.sin(t)) * SC]


def contours_of(mask):
    m = np.pad(mask.astype(np.float32), 2)
    G = cv2.GaussianBlur(m, (0, 0), BLUR_SIGMA)
    cs = find_contours(G, 0.5)
    out = []
    for c in cs:
        c = c - 2.0
        pts = to_mm(c)
        ls = LineString(pts).simplify(SIMPLIFY_MM, preserve_topology=False)
        if len(ls.coords) >= 4:
            out.append(ls)
    return out, G[2:-2, 2:-2]


def sample(G, xy):
    """bilinear sample of S-grid field G at plaque-mm points (N,2)"""
    xi = xy[:, 0] / SC + CX6
    yi = -xy[:, 1] / SC + CY6
    col = (xi + 0.5 - WIN0) * S - 0.5
    row = (yi + 0.5 - WIN0) * S - 0.5
    return map_coordinates(G, [row, col], order=1, mode='nearest')


def zone_of(xy):
    """0 = cream disc, 1 = inner red, 2 = inner black, 3 = green band, 4 = outer red, 5 = outer black, 6 = outside"""
    z = np.full(len(xy), 6)
    for k in range(5, -1, -1):
        cx, cy, R = RINGS[k]
        d = np.hypot(xy[:, 0] / SC + CX6 - cx, -xy[:, 1] / SC + CY6 - cy)
        z[d < R] = k
    return z


ZONE_CLASS = {1: RED, 2: BLACK, 4: RED, 5: BLACK}


def build(verbose=True):
    t0 = time.time()
    seg = segment(S)
    black_all = seg['black'] | seg['text']
    lines = [LineString(np.vstack([circle_xy(k), circle_xy(k)[:1]])) for k in range(6)]
    fields_ = {}
    for name, m in (('black', black_all), ('brown', seg['brown']), ('tan', seg['tan'])):
        cs, G = contours_of(m)
        lines += cs
        fields_[name] = G
        if verbose:
            print('%-6s contours %5d  vertices %8d' % (name, len(cs), sum(len(c.coords) for c in cs)), flush=True)
    if verbose:
        print('linework built %.1fs; noding...' % (time.time() - t0), flush=True)
    noded = shapely.union_all(lines, grid_size=GRID_MM)
    faces = shapely.get_parts(shapely.polygonize([noded]))
    if verbose:
        print('polygonize -> %d faces  (%.1fs)' % (len(faces), time.time() - t0), flush=True)
    reps = np.array([[p.x, p.y] for p in shapely.point_on_surface(faces)])
    zone = zone_of(reps)
    gk = sample(fields_['black'], reps)
    gn = sample(fields_['brown'], reps)
    gt = sample(fields_['tan'], reps)
    cls = np.zeros(len(faces), np.int32)
    for i in range(len(faces)):
        z = zone[i]
        if z == 6:
            cls[i] = 0
        elif z in ZONE_CLASS:
            cls[i] = ZONE_CLASS[z]
        elif z == 3:
            cls[i] = BLACK if gk[i] > 0.5 else GREEN
        else:  # disc
            if gk[i] > 0.5:
                cls[i] = BLACK
            elif gn[i] > 0.5:
                cls[i] = BROWN
            elif gt[i] > 0.5:
                cls[i] = TAN
            else:
                cls[i] = CREAM
    return faces, cls, reps, (gk, gn, gt)


def merge_slivers(faces, cls, thick_min=0.07, area_min=0.004, max_pass=20, verbose=True):
    """Merge faces that are too thin / small to ever print into the neighbour they share the longest border with."""
    faces = list(faces)
    cls = list(cls)
    for ps in range(max_pass):
        arr = np.empty(len(faces), dtype=object)
        arr[:] = faces
        area = shapely.area(arr)
        per = shapely.length(arr)
        bad = np.where((2 * area / np.maximum(per, 1e-12) < thick_min) | (area < area_min))[0]
        if verbose:
            print('  pass %2d: %d faces, %d slivers' % (ps, len(arr), len(bad)), flush=True)
        if len(bad) == 0:
            break
        tree = shapely.STRtree(arr)
        used = set()
        newgeom = {}
        removed = set()
        for i in bad[np.argsort(area[bad])]:
            i = int(i)
            if i in used:
                continue
            best, bl = None, 0.0
            for j in tree.query(arr[i], predicate='intersects'):
                j = int(j)
                if j == i or j in used:
                    continue
                L = arr[i].boundary.intersection(arr[j].boundary).length
                if L > bl:
                    best, bl = j, L
            if best is None or bl < 1e-7:
                continue
            u = shapely.union_all([arr[i], arr[best]])
            if u.geom_type != 'Polygon':
                continue
            used.add(i)
            used.add(best)
            newgeom[best] = u
            removed.add(i)
        if not removed:
            break
        faces = [newgeom.get(k, faces[k]) for k in range(len(faces)) if k not in removed]
        cls = [cls[k] for k in range(len(cls)) if k not in removed]
    return faces, np.array(cls, np.int32)


if __name__ == '__main__':
    faces, cls, reps, g = build()
    keep = cls > 0
    faces = faces[keep]
    cls = cls[keep]
    faces, cls = merge_slivers(faces, cls)
    faces = np.array(faces, dtype=object)
    area = shapely.area(faces)
    per = shapely.length(faces)
    thick = 2 * area / per
    print('faces kept', len(faces))
    for c in NAMES:
        m = cls == c
        print('%-6s n=%6d  area=%9.1f mm2   thin(<0.05mm) n=%d  tiny(<0.002mm2) n=%d' %
              (NAMES[c], m.sum(), area[m].sum(), (thick[m] < 0.05).sum(), (area[m] < 0.002).sum()))
    print('total area %.1f mm2 (disc pi*119^2 = %.1f)' % (area.sum(), np.pi * 119 ** 2))
    pickle.dump(dict(faces=list(faces), cls=cls), open('faces_raw.pkl', 'wb'))
