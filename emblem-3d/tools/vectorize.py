"""Vectorise the segmented picture into a conforming planar partition (faces) in millimetres.

    python vectorize.py round      the round patch only            (plaque = disc, 238 mm)
    python vectorize.py full       the whole picture, background art included (plaque = rounded square, 240 mm)

faces: list of (class_id, shapely.Polygon) in plaque coordinates (origin = plaque centre, +y up).
Rings are analytic circles; content boundaries are sub-pixel iso-contours of the sharpened colour fields."""
import sys, time, pickle, numpy as np, cv2, shapely
from shapely.geometry import LineString, Polygon, Point
from scipy.ndimage import map_coordinates
from skimage.measure import find_contours
from classify import *
from classify import silhouette_r, SIL_CENTER
from segment import segment

S = 4
CX6, CY6, R6 = RINGS[5]
BLUR_SIGMA = 1.0                           # S-pixels, smooths the staircase of the thresholded masks
SIMPLIFY_MM = 0.010                        # Douglas-Peucker tolerance for content contours
N_CIRCLE = 2048
GRID_MM = 0.04                             # snap-rounding grid: merges near-coincident class boundaries

LAYOUTS = {
    'round': dict(cx=CX6, cy=CY6, extent=238.0, sc=119.0 / R6, outer='circle'),
    'full': dict(cx=539.5, cy=539.5, extent=240.0, sc=240.0 / 1040, outer='rounded_square', half=120.0, corner=6.0,
                 silhouette=True),
}
FR = dict(LAYOUTS['round'])


def configure(layout):
    FR.clear()
    FR.update(LAYOUTS[layout])
    FR['layout'] = layout


configure('round')


def to_mm(rc, win0):
    x = win0 + (rc[:, 1] + 0.5) / S - 0.5
    y = win0 + (rc[:, 0] + 0.5) / S - 0.5
    return np.c_[(x - FR['cx']) * FR['sc'], -(y - FR['cy']) * FR['sc']]


def circle_xy(k, n=N_CIRCLE):
    cx, cy, R = RINGS[k]
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    if k == 5 and FR.get('silhouette'):                       # measured, non-circular outer edge of the black ring
        cx, cy = SIL_CENTER
        R = silhouette_r(t)
    return np.c_[((cx - FR['cx']) + R * np.cos(t)) * FR['sc'], -((cy - FR['cy']) + R * np.sin(t)) * FR['sc']]


def rounded_square_xy(half, r, n_arc=64):
    """counter-clockwise outline of a square (side 2*half) with corner radius r"""
    pts = []
    for (cx, cy, a0) in ((half - r, half - r, 0.0), (-(half - r), half - r, 90.0),
                         (-(half - r), -(half - r), 180.0), (half - r, -(half - r), 270.0)):
        for a in np.linspace(a0, a0 + 90.0, n_arc):
            pts.append((cx + r * np.cos(np.radians(a)), cy + r * np.sin(np.radians(a))))
    return np.array(pts)


def contours_of(mask, win0):
    m = np.pad(mask.astype(np.float32), 2)
    G = cv2.GaussianBlur(m, (0, 0), BLUR_SIGMA)
    cs = find_contours(G, 0.5)
    out = []
    for c in cs:
        c = c - 2.0
        pts = to_mm(c, win0)
        ls = LineString(pts).simplify(SIMPLIFY_MM, preserve_topology=False)
        if len(ls.coords) >= 4:
            out.append(ls)
    return out, G[2:-2, 2:-2]


def sample(G, xy, win0):
    """bilinear sample of S-grid field G (window origin win0) at plaque-mm points (N,2)"""
    xi = xy[:, 0] / FR['sc'] + FR['cx']
    yi = -xy[:, 1] / FR['sc'] + FR['cy']
    col = (xi + 0.5 - win0) * S - 0.5
    row = (yi + 0.5 - win0) * S - 0.5
    return map_coordinates(G, [row, col], order=1, mode='nearest')


def zone_of(xy):
    """0 = cream disc, 1 = inner red, 2 = inner black, 3 = green band, 4 = outer red, 5 = outer black, 6 = outside"""
    z = np.full(len(xy), 6)
    for k in range(5, -1, -1):
        cx, cy, R = RINGS[k]
        dx, dy = xy[:, 0] / FR['sc'] + FR['cx'] - cx, -xy[:, 1] / FR['sc'] + FR['cy'] - cy
        if k == 5 and FR.get('silhouette'):
            dx, dy = xy[:, 0] / FR['sc'] + FR['cx'] - SIL_CENTER[0], -xy[:, 1] / FR['sc'] + FR['cy'] - SIL_CENTER[1]
            R = silhouette_r(np.arctan2(dy, dx))
        z[np.hypot(dx, dy) < R] = k
    return z


ZONE_CLASS = {1: RED, 2: BLACK, 4: RED, 5: BLACK}


def build(verbose=True):
    import bg_segment
    t0 = time.time()
    full = FR['layout'] == 'full'
    seg = segment(S)
    black_all = seg['black'] | seg['text']
    lines = [LineString(np.vstack([circle_xy(k), circle_xy(k)[:1]])) for k in range(6)]
    if full:
        sq = rounded_square_xy(FR['half'], FR['corner'])
        lines.append(LineString(np.vstack([sq, sq[:1]])))
    fields_ = {}
    for name, m in (('black', black_all), ('brown', seg['brown']), ('tan', seg['tan'])):
        cs, G = contours_of(m, WIN0)
        lines += cs
        fields_[name] = G
        if verbose:
            print('%-6s contours %5d  vertices %8d' % (name, len(cs), sum(len(c.coords) for c in cs)), flush=True)
    if full:
        bg = bg_segment.segment_bg(S)
        for name in ('ghost', 'copper', 'mark'):
            cs, G = contours_of(bg[name], bg_segment.BG_WIN0)
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
    if full:                                         # faces outside the outline of the plaque are leftovers of contours: drop
        outline = Polygon(rounded_square_xy(FR['half'], FR['corner']))
        inside_ok = np.array([outline.contains(p) for p in shapely.point_on_surface(faces)])
        if verbose and (~inside_ok).any():
            print('dropped %d faces outside the plaque outline' % (~inside_ok).sum(), flush=True)
        faces = faces[inside_ok]
    reps = np.array([[p.x, p.y] for p in shapely.point_on_surface(faces)])
    zone = zone_of(reps)
    gk = sample(fields_['black'], reps, WIN0)
    gn = sample(fields_['brown'], reps, WIN0)
    gt = sample(fields_['tan'], reps, WIN0)
    if full:
        gm = sample(fields_['mark'], reps, bg_segment.BG_WIN0)
        gc = sample(fields_['copper'], reps, bg_segment.BG_WIN0)
        gg = sample(fields_['ghost'], reps, bg_segment.BG_WIN0)
    cls = np.zeros(len(faces), np.int32)
    for i in range(len(faces)):
        z = zone[i]
        if z == 6:
            if not full:
                cls[i] = 0
            elif gm[i] > 0.5:
                cls[i] = MARK
            elif gc[i] > 0.5:
                cls[i] = COPPER
            elif gg[i] > 0.5:
                cls[i] = GHOST
            else:
                cls[i] = PLATE
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
    return faces, cls, reps


def merge_slivers(faces, cls, thick_min=0.07, area_min=0.004, max_pass=40, verbose=True):
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
    layout = sys.argv[1] if len(sys.argv) > 1 else 'round'
    out = sys.argv[2] if len(sys.argv) > 2 else 'faces_raw.pkl'
    configure(layout)
    faces, cls, reps = build()
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
        if m.any():
            print('%-6s n=%6d  area=%9.1f mm2   thin(<0.05mm) n=%d  tiny(<0.002mm2) n=%d' %
                  (NAMES[c], m.sum(), area[m].sum(), (thick[m] < 0.05).sum(), (area[m] < 0.002).sum()))
    ref = np.pi * 119 ** 2 if layout == 'round' else 240.0 ** 2 - (4 - np.pi) * FR['corner'] ** 2
    print('total area %.1f mm2 (expected outline area %.1f)' % (area.sum(), ref))
    pickle.dump(dict(faces=list(faces), cls=cls, layout=layout, extent=FR['extent']), open(out, 'wb'))
