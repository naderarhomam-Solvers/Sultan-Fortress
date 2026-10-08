"""Shared geometry + per-pixel class model for the SMB-87 emblem (original image coordinates, pixels)."""
import numpy as np, cv2

import os, hashlib
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'source', 'smb87_logo.jpg')

# Measured circle fits (cx, cy, R) in original px, inner -> outer:
RINGS = [
    (538.97, 540.22, 258.89),  # cream disc | inner red
    (539.48, 539.76, 264.28),  # inner red | inner black
    (538.64, 539.53, 276.70),  # inner black | green band
    (539.09, 538.87, 338.31),  # green band | outer red
    (538.89, 538.75, 343.89),  # outer red | outer black
    (538.89, 538.75, 360.50),  # outer black | outside
]

# The outer edge of the outer black ring dissolves into the dark background and is NOT a circle (an ellipse-like curve,
# measured at every angle with rings_silhouette_fit.py: radius 357.4 .. 363.0 px).  r(theta) = c0 + sum_h a_h cos(h t) + b_h sin(h t)
# (image coordinates, y down).  Used by the full-image layout; the round layout keeps the clean circle RINGS[5].
SIL_CENTER = (538.89, 538.75)
SIL_COEFF = [360.3621, 0.9337, 0.7278, -1.8487, -0.054, 0.1421, -0.0499]


def silhouette_r(theta):
    t = np.asarray(theta, dtype=np.float64)
    r = np.full_like(t, SIL_COEFF[0])
    for h in range(1, (len(SIL_COEFF) - 1) // 2 + 1):
        r = r + SIL_COEFF[2 * h - 1] * np.cos(h * t) + SIL_COEFF[2 * h] * np.sin(h * t)
    return r


BLACK, RED, GREEN, CREAM, TAN, BROWN = 1, 2, 3, 4, 5, 6
PLATE, GHOST, COPPER, MARK = 7, 8, 9, 10           # classes used only by the full-image layout (background art)
NAMES = {BLACK: 'black', RED: 'red', GREEN: 'green', CREAM: 'cream', TAN: 'tan', BROWN: 'brown',
         PLATE: 'plate', GHOST: 'ghost', COPPER: 'copper', MARK: 'mark'}
ALBEDO = {0: (20, 30, 20), BLACK: (14, 14, 14), RED: (125, 25, 8), GREEN: (89, 113, 14),
          CREAM: (208, 196, 129), TAN: (168, 138, 92), BROWN: (110, 62, 36),
          PLATE: (24, 38, 26), GHOST: (84, 96, 64), COPPER: (170, 106, 78), MARK: (245, 245, 245)}

E_BLACK = np.array([8, 5, 2], np.float32)
E_CREAM = np.array([208, 196, 129], np.float32)
E_BROWN = np.array([95, 64, 36], np.float32)
E_GREEN = np.array([89, 113, 14], np.float32)

WIN0 = 170           # crop window origin (orig px) used for all supersampled rasters
WINSZ = 740


def load_rgb():
    return cv2.cvtColor(cv2.imread(SRC), cv2.COLOR_BGR2RGB).astype(np.float32)


def unmix3(rgb):
    """black / cream / brown fractions per pixel (sum to 1)."""
    E = np.stack([E_BLACK, E_CREAM, E_BROWN], axis=1)
    A = np.vstack([E, 100.0 * np.ones((1, 3), np.float32)])
    pinv = np.linalg.pinv(A)
    H, W, _ = rgb.shape
    flat = rgb.reshape(-1, 3)
    rhs = np.concatenate([flat, 100.0 * np.ones((flat.shape[0], 1), np.float32)], axis=1)
    f = np.clip((rhs @ pinv.T).reshape(H, W, 3), 0, 1)
    return f / np.maximum(f.sum(axis=2, keepdims=True), 1e-6)


def black_lum_fraction(rgb):
    """black fraction from luminance only (cream -> black axis).  Used OUTSIDE the snake/sword ROI, where nothing is brown.
    The 3-end-member unmix reads thin dark lines on cream (JPEG chroma sub-sampling makes them yellow-brown, e.g. RGB
    47,35,0) as 'brown' and drops them; luminance does not suffer from that."""
    lum = rgb.mean(axis=2)
    lc, lk = float(E_CREAM.mean()), float(E_BLACK.mean())
    return np.clip((lc - lum) / (lc - lk), 0, 1)


def black_text_fraction(rgb):
    """black fraction inside the green band (2 endpoints: black / green)."""
    lum = rgb.mean(axis=2)
    lg, lk = float(E_GREEN.mean()), float(E_BLACK.mean())
    return np.clip((lg - lum) / (lg - lk), 0, 1)


def radial_masks(S, win0=WIN0, size=WINSZ):
    """returns dict of float 'signed distance to ring' fields? -> simpler: per-ring boolean 'inside' masks at scale S."""
    n = size * S
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    # ring fits are in pixel-INDEX space (pixel j centre = j); S-pixel i centre -> orig index = win0 + (i+0.5)/S - 0.5
    X = win0 + (xs + 0.5) / S - 0.5
    Y = win0 + (ys + 0.5) / S - 0.5
    inside = []
    for cx, cy, R in RINGS:
        inside.append(np.hypot(X - cx, Y - cy) < R)
    return inside


def up(field, S, win0=WIN0, size=WINSZ, interp=cv2.INTER_CUBIC):
    crop = field[win0:win0 + size, win0:win0 + size]
    return cv2.resize(crop, None, fx=S, fy=S, interpolation=interp)


# ---------------------------------------------------------------------------
# Sharpened, supersampled fields (Richardson-Lucy restores 1-px lines blurred by the JPEG / resize)
# ---------------------------------------------------------------------------
def _rl(a, sigma_px, iters, S):
    from skimage.restoration import richardson_lucy
    k = int(6 * sigma_px * S) | 1
    g = cv2.getGaussianKernel(k, sigma_px * S)
    psf = (g @ g.T).astype(np.float32)
    return np.clip(richardson_lucy(np.clip(a, 1e-3, 1).astype(np.float32), psf, num_iter=iters, clip=False), 0, 1)


def _rl_sym(a, sigma_px, iters, S):
    """Edge-neutral Richardson-Lucy.  RL is multiplicative, so it is NOT symmetric between 'bright' and 'dark': deconvolving
    the black fraction alone pulls every black/cream edge INWARD (-0.36 px for sigma 0.8 / 15 it. on a synthetic edge with the
    measured blur), deconvolving the cream fraction pushes it OUTWARD by the same amount.  The average keeps the 0.5 contour
    on the true edge (+0.004 px) and keeps 0.75-4 px lines at 0.98-1.05 of their true area."""
    a = np.clip(a, 0, 1).astype(np.float32)
    return 0.5 * (_rl(a, sigma_px, iters, S) + 1.0 - _rl(1.0 - a, sigma_px, iters, S))


def core_mask(S, margin=2.5, win0=WIN0, size=WINSZ):
    n = size * S
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    cx1, cy1, R1 = RINGS[0]
    return np.hypot(win0 + (xs + 0.5) / S - 0.5 - cx1, win0 + (ys + 0.5) / S - 0.5 - cy1) < (R1 - margin)


def _cache_name(S):
    """cache file name keyed on the picture AND on this file's source: editing a parameter or swapping the picture can never
    silently reuse stale fields"""
    h = hashlib.sha1()
    with open(SRC, 'rb') as f:
        h.update(f.read())
    with open(os.path.abspath(__file__), 'rb') as f:
        h.update(f.read())
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fields_S%d_%s.npz' % (S, h.hexdigest()[:12]))


def check_picture(rgb, tol_px=1.0):
    """Fail loudly if the picture is not the one RINGS / WIN0 / WINSZ were measured on (different size, shifted, rescaled)."""
    if rgb.shape[0] < WIN0 + WINSZ or rgb.shape[1] < WIN0 + WINSZ:
        raise RuntimeError('picture %s is too small for the crop window %d..%d' % (rgb.shape[:2], WIN0, WIN0 + WINSZ))
    from scipy.ndimage import map_coordinates
    a = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    for k, ch, sg in ((0, 1, -1), (2, 1, +1), (4, 0, -1)):          # cream|red (G falls), black|green (G rises), red|black (R falls)
        cx, cy, R = RINGS[k]
        rs = np.arange(-2.6, 2.6, 0.1)
        offs = []
        for t in a:
            v = map_coordinates(rgb[:, :, ch], [cy + (R + rs) * np.sin(t), cx + (R + rs) * np.cos(t)], order=1, mode='nearest')
            lo, hi = np.percentile(v, 5), np.percentile(v, 95)
            if hi - lo < 30:
                continue
            s_ = (v - (lo + hi) / 2) * sg
            i = np.where((s_[:-1] < 0) & (s_[1:] >= 0))[0]
            if len(i) == 1:
                offs.append(rs[i[0]] - s_[i[0]] / (s_[i[0] + 1] - s_[i[0]]) * 0.1)
        offs = np.array(offs)
        if len(offs) < 270 or abs(offs.mean()) > tol_px or offs.std() > tol_px:
            raise RuntimeError('ring %d does not sit on the picture edge (found %d/360 edges, mean offset %.2f px, std %.2f px): '
                               'RINGS do not match %s' % (k, len(offs), offs.mean() if len(offs) else float('nan'),
                                                        offs.std() if len(offs) else float('nan'), SRC))


def fields(S, cache=True):
    """dict of fields at scale S over the crop window:
         Fk  black fraction, 3-end-member unmix   (valid inside the brown snake/sword ROI)
         Fl  black fraction from luminance        (valid outside the ROI, where nothing is brown)
         Fn  brown fraction (disc)               Ft  black fraction of the green-band text
         Fd  absolute darkness (lum <= 8 -> 1, >= 110 -> 0)   Fch  chroma R-B smoothed over ~1 px
    All Richardson-Lucy fields use the symmetric (edge-neutral) variant."""
    fn = _cache_name(S)
    if cache and os.path.exists(fn):
        d = np.load(fn)
        return {k: d[k] for k in d.files}
    rgb = load_rgb()
    check_picture(rgb)
    f3 = unmix3(rgb)
    out = {}
    out['Fk'] = _rl_sym(up(f3[:, :, 0], S), 0.8, 15, S)
    core = core_mask(S)
    out['Fn'] = _rl_sym(np.where(core, up(f3[:, :, 2], S), 0).astype(np.float32), 0.8, 10, S)   # never let the red-ring edge leak in
    out['Ft'] = _rl_sym(up(black_text_fraction(rgb), S), 0.8, 12, S)
    out['Fl'] = _rl_sym(up(black_lum_fraction(rgb), S), 0.8, 15, S)
    lum = rgb.mean(axis=2)
    out['Fd'] = _rl_sym(np.clip(up(np.clip((110.0 - lum) / (110.0 - 8.0), 0, 1).astype(np.float32), S), 0, 1), 0.8, 15, S)
    out['Fch'] = up(cv2.GaussianBlur((rgb[:, :, 0] - rgb[:, :, 2]).astype(np.float32), (0, 0), 1.0), S)
    np.savez(fn, **{k: v.astype(np.float32) for k, v in out.items()})
    return out
