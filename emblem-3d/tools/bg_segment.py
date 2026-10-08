"""Segmentation of the faded BACKGROUND art of the picture (everything outside the round patch):
  ghost  = olive-grey line-art  (big wings, big 87 + speed lines, ghost Arabic text, ghost tail feathers)
  copper = copper-coloured art  (ghost sword/bullet + snake tail, ghost snake head)
  mark   = the TikTok logo + handle in the bottom-right corner (optional layer)
Method: per-channel light top-hat (value minus a large-opening background) removes the dark vignette and the JPEG
banding rings; the resulting colour *difference* vector is unmixed onto the olive / copper endpoint deltas; the
fractions are up-sampled to S x and sharpened with Richardson-Lucy exactly like the patch fields."""
import os
import numpy as np
import cv2
from classify import SRC, RINGS, _rl_sym, SIL_CENTER, silhouette_r


def _rl_sym_pad(a, sigma, iters, S, pad=32):
    """edge-padded symmetric RL: no artefacts at the borders of the window"""
    p = np.pad(a, pad, mode='edge')
    return _rl_sym(p, sigma, iters, S)[pad:-pad, pad:-pad]

EMB_C = (RINGS[5][0], RINGS[5][1])
EMB_R = RINGS[5][2]
BG_WIN0, BG_WINSZ = 20, 1040           # square crop (orig px, corner space) shown on the full-image plaque
BG_PARAMS = dict(
    fill_margin=1.0,     # px beyond the outer black ring that are excluded from the background estimate
    open_px=61,          # opening size for the background estimate (> widest ghost stroke, the big 87, ~38 px)
    tau=0.36,            # fraction threshold on the sharpened olive / copper fields (0.36: 99.2% recall of clear art, ~0 false positives)
    tau_mark=0.40,
    min_area_px2=0.459,  # drop islands / pinholes smaller than this many original pixels^2 (same as the patch)
)
D_OLIVE = np.array([40.0, 41.0, 37.0], np.float32)     # colour delta of olive ghost art above the local background
D_COPPER = np.array([97.0, 50.0, 46.0], np.float32)    # colour delta of copper art above the local background
MARK_BOX = (780, 1015, 1075, 1078)                     # x0, y0, x1, y1 (orig px) of the TikTok logo + handle


def load():
    return cv2.cvtColor(cv2.imread(SRC), cv2.COLOR_BGR2RGB).astype(np.float32)


def top_hat_channels(im, open_px, margin):
    H, W, _ = im.shape
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - SIL_CENTER[0], yy - SIL_CENTER[1])
    rs = silhouette_r(np.arctan2(yy - SIL_CENTER[1], xx - SIL_CENTER[0]))      # true (non-circular) edge of the black ring
    disc = r < (rs + margin)
    ring = (r > rs + 3) & (r < rs + 60)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_px, open_px))
    out = np.zeros_like(im)
    for c in range(3):
        ch = im[:, :, c].copy()
        ch[disc] = np.median(ch[ring])
        sm = cv2.GaussianBlur(ch, (0, 0), 0.9)
        bg = cv2.GaussianBlur(cv2.morphologyEx(sm, cv2.MORPH_OPEN, k), (0, 0), 12)
        out[:, :, c] = sm - bg
    return out, disc


def unmix_delta(d):
    E = np.stack([D_OLIVE, D_COPPER], axis=1)
    f = d.reshape(-1, 3) @ np.linalg.pinv(E).T
    f = np.clip(f, 0, 1.2).reshape(d.shape[0], d.shape[1], 2)
    return f[:, :, 0], f[:, :, 1]


def mark_field(im):
    H, W, _ = im.shape
    lum = im.mean(axis=2)
    m = np.zeros((H, W), np.float32)
    x0, y0, x1, y1 = MARK_BOX
    m[y0:y1, x0:x1] = np.clip((lum[y0:y1, x0:x1] - 70.0) / 120.0, 0, 1)
    return m


def up_bg(field, S):
    crop = field[BG_WIN0:BG_WIN0 + BG_WINSZ, BG_WIN0:BG_WIN0 + BG_WINSZ]
    return cv2.resize(crop, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)


def bg_fields(S, cache=True):
    fn = 'bgfields_S%d.npz' % S
    if cache and os.path.exists(fn):
        d = np.load(fn)
        return d['Fo'], d['Fc'], d['Fm']
    P = BG_PARAMS
    im = load()
    th, disc = top_hat_channels(im, P['open_px'], P['fill_margin'])
    fo, fc = unmix_delta(th)
    fm = mark_field(im)
    x0, y0, x1, y1 = MARK_BOX
    fo[y0:y1, x0:x1] = 0                                  # the mark is its own layer
    fc[y0:y1, x0:x1] = 0
    fo[disc] = 0
    fc[disc] = 0
    fm[disc] = 0
    Fo = _rl_sym_pad(np.clip(up_bg(fo, S), 0, 1), 0.8, 12, S)
    Fc = _rl_sym_pad(np.clip(up_bg(fc, S), 0, 1), 0.8, 12, S)
    Fm = _rl_sym_pad(np.clip(up_bg(fm, S), 0, 1), 0.8, 12, S)
    box = np.zeros((BG_WINSZ, BG_WINSZ), np.float32)                  # the mark exists only inside its box
    bx0, by0, bx1, by1 = MARK_BOX
    box[by0 - BG_WIN0:by1 - BG_WIN0, bx0 - BG_WIN0:bx1 - BG_WIN0] = 1.0
    Fm = Fm * (cv2.resize(box, None, fx=S, fy=S, interpolation=cv2.INTER_NEAREST) > 0.5)
    np.savez(fn, Fo=Fo.astype(np.float32), Fc=Fc.astype(np.float32), Fm=Fm.astype(np.float32))
    return Fo, Fc, Fm


def _drop_small(mask, min_px):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= min_px
    return keep[lab]


def clean(mask, min_px):
    m = _drop_small(mask, min_px)
    return ~_drop_small(~m, min_px)


def segment_bg(S, P=None):
    """masks (S-grid over the BG window): ghost / copper / mark."""
    P = dict(BG_PARAMS, **(P or {}))
    Fo, Fc, Fm = bg_fields(S)
    min_px = P['min_area_px2'] * S * S
    mark = clean(Fm > P['tau_mark'], min_px)
    copper = clean((Fc > P['tau']) & ~mark, min_px)
    ghost = clean((Fo > P['tau']) & ~copper & ~mark, min_px)
    return dict(ghost=ghost, copper=copper, mark=mark, Fo=Fo, Fc=Fc, Fm=Fm, S=S, P=P)
