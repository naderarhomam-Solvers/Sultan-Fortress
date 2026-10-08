"""Shared geometry + per-pixel class model for the SMB-87 emblem (original image coordinates, pixels)."""
import numpy as np, cv2

import os
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'source', 'smb87_logo.jpg')

# Measured circle fits (cx, cy, R) in original px, inner -> outer:
RINGS = [
    (538.97, 540.22, 258.89),  # cream disc | inner red
    (539.48, 539.76, 263.97),  # inner red | inner black
    (538.64, 539.53, 276.70),  # inner black | green band
    (539.09, 538.87, 338.02),  # green band | outer red
    (538.89, 538.75, 343.89),  # outer red | outer black
    (538.89, 538.75, 360.50),  # outer black | outside
]

BLACK, RED, GREEN, CREAM, TAN, BROWN = 1, 2, 3, 4, 5, 6
NAMES = {BLACK: 'black', RED: 'red', GREEN: 'green', CREAM: 'cream', TAN: 'tan', BROWN: 'brown'}
ALBEDO = {0: (20, 30, 20), BLACK: (14, 14, 14), RED: (125, 25, 8), GREEN: (89, 113, 14),
          CREAM: (208, 196, 129), TAN: (168, 138, 92), BROWN: (110, 62, 36)}

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


def core_mask(S, margin=2.5, win0=WIN0, size=WINSZ):
    n = size * S
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    cx1, cy1, R1 = RINGS[0]
    return np.hypot(win0 + (xs + 0.5) / S - 0.5 - cx1, win0 + (ys + 0.5) / S - 0.5 - cy1) < (R1 - margin)


def fields(S, cache=True):
    """returns (Fk, Fn, Ft) at scale S over the crop window: black fraction (disc), brown fraction (disc),
    black fraction (green band text)."""
    import os
    fn = 'fields_S%d.npz' % S
    if cache and os.path.exists(fn):
        d = np.load(fn)
        return d['Fk'], d['Fn'], d['Ft']
    rgb = load_rgb()
    f3 = unmix3(rgb)
    Fk = _rl(up(f3[:, :, 0], S), 0.8, 15, S)
    Fn_raw = up(f3[:, :, 2], S)
    core = core_mask(S)
    Fn = np.where(core, Fn_raw, 0).astype(np.float32)        # never let the red-ring edge leak in
    Fn = _rl(Fn, 0.8, 10, S)
    Ft = _rl(up(black_text_fraction(rgb), S), 0.8, 12, S)
    np.savez(fn, Fk=Fk.astype(np.float32), Fn=Fn.astype(np.float32), Ft=Ft.astype(np.float32))
    return Fk, Fn, Ft
