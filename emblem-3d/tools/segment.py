"""Pixel-level segmentation of the emblem at supersampling S -> per-class masks (inside the disc and the text band).
The six ring annuli are NOT taken from here (they are analytic circles in the vector stage); this module only
decides the *content*: black / brown / tan inside the cream disc and black text inside the green band."""
import numpy as np, cv2
from classify import *

PARAMS = dict(
    tau_k=0.50,        # black threshold on the RL-sharpened black fraction (disc)
    tau_n=0.50,        # dark-brown threshold (snake outline / scales / sword)
    tan_t=0.30,        # silhouette threshold on the blurred brown fraction  (snake / sword body)
    tau_t=0.50,        # black text in the green band
    min_area_mm2=0.05,  # drop islands / pinholes smaller than this
    brown_roi_pad=6.0,  # px (original) dilation of the snake+sword component
)
MM_PER_PX = 119.0 / RINGS[5][2]


def _drop_small(mask, min_area_px):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= min_area_px
    return keep[lab]


def clean(mask, min_area_px):
    """remove small islands and small pinholes"""
    m = _drop_small(mask, min_area_px)
    inv = _drop_small(~m, min_area_px)
    return ~inv


def segment(S, P=None):
    P = dict(PARAMS, **(P or {}))
    Fk, Fn, Ft = fields(S)
    n = WINSZ * S
    min_px = P['min_area_mm2'] / (MM_PER_PX / S) ** 2
    inside = radial_masks(S)
    core = core_mask(S)
    band = inside[3] & ~inside[2]

    text = clean(band & (Ft > P['tau_t']), min_px)
    black = clean(core & (Fk > P['tau_k']), min_px)

    # --- brown ROI = the large connected snake+sword component only
    Fs = cv2.GaussianBlur(Fn, (0, 0), 3.0 * S)
    comp = (Fs > 0.22).astype(np.uint8)
    nc, lab, st, _ = cv2.connectedComponentsWithStats(comp, connectivity=8)
    big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    roi = (lab == big).astype(np.uint8)
    r = int(P['brown_roi_pad'] * S)
    roi = cv2.dilate(roi, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))).astype(bool)

    brown = clean(core & roi & ~black & (Fn > P['tau_n']), min_px)

    # --- tan: closed + hole-filled silhouette of the brown density (snake / sword body)
    Fn_s = cv2.GaussianBlur(Fn, (0, 0), 1.0 * S)
    sil = (Fn_s > P['tan_t']) & core & roi
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(2.0 * S) + 1,) * 2)
    sil = cv2.morphologyEx(sil.astype(np.uint8), cv2.MORPH_CLOSE, k)
    ff = sil.copy()
    msk = np.zeros((n + 2, n + 2), np.uint8)
    cv2.floodFill(ff, msk, (0, 0), 2)
    sil = (ff != 2)
    sil = _drop_small(sil, 40 * S * S) & core
    tan = sil & ~black & ~brown
    tan = clean(tan, min_px)
    return dict(black=black, brown=brown, tan=tan, text=text, roi=roi, core=core, band=band, inside=inside,
                Fk=Fk, Fn=Fn, Ft=Ft, S=S, P=P)
