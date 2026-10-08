"""Measure every ring edge of the emblem as its own robust circle fit (sub-pixel)."""
import numpy as np, cv2
from scipy.ndimage import map_coordinates

import os
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'source', 'smb87_logo.jpg')
im = cv2.cvtColor(cv2.imread(SRC), cv2.COLOR_BGR2RGB).astype(np.float32)
cx0, cy0 = 539.79, 539.44


def chan(a, rs, ch):
    xs = cx0 + rs * np.cos(a)
    ys = cy0 + rs * np.sin(a)
    if ch == 'lum':
        return sum(map_coordinates(im[:, :, c], [ys, xs], order=1, mode='nearest') for c in range(3)) / 3
    return map_coordinates(im[:, :, 'RGB'.index(ch)], [ys, xs], order=1, mode='nearest')


def edge_points(r0, ch, sign, win=5.0, n=1440):
    """sign=-1: value falls going outward, +1: rises. returns subpixel crossing of the half level."""
    rs = np.arange(r0 - win, r0 + win, 0.1)
    pts = []
    for a in np.linspace(0, 2 * np.pi, n, endpoint=False):
        v = chan(a, rs, ch)
        lo, hi = np.percentile(v, 8), np.percentile(v, 92)
        if hi - lo < 40:
            continue
        mid = (lo + hi) / 2
        s = (v - mid) * sign
        idx = np.where((s[:-1] < 0) & (s[1:] >= 0))[0]
        if len(idx) != 1:
            continue
        i = idx[0]
        t = -s[i] / (s[i + 1] - s[i])
        r = rs[i] + t * (rs[i + 1] - rs[i])
        pts.append((cx0 + r * np.cos(a), cy0 + r * np.sin(a)))
    return np.array(pts)


def fit(p):
    A = np.c_[2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))]
    b = p[:, 0] ** 2 + p[:, 1] ** 2
    s, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = s[0], s[1]
    return cx, cy, np.sqrt(s[2] + cx * cx + cy * cy)


def robust_fit(p):
    m = np.ones(len(p), bool)
    for _ in range(12):
        cx, cy, R = fit(p[m])
        res = np.hypot(p[:, 0] - cx, p[:, 1] - cy) - R
        sd = res[m].std()
        m = np.abs(res) < max(0.6, 2.2 * sd)
    return cx, cy, R, res[m].std(), m.sum(), len(p)


edges = [
    ('cream -> red inner   ', 258.0, 'G', -1),
    ('red inner -> black   ', 263.5, 'R', -1),
    ('black -> green       ', 276.5, 'G', +1),
    ('green -> red outer   ', 335.5, 'G', -1),
    ('red outer -> black   ', 342.5, 'R', -1),
    ('black -> background  ', 360.5, 'lum', +1),
]
out = {}
for name, r0, ch, sg in edges:
    p = edge_points(r0, ch, sg)
    cx, cy, R, sd, nin, n = robust_fit(p)
    print('%s center=(%.2f, %.2f)  R=%.2f px   res.std=%.2f   inliers %d/%d' % (name, cx, cy, R, sd, nin, n))
    out[name.strip()] = (cx, cy, R)
np.save('rings.npy', np.array([v for v in out.values()]))
