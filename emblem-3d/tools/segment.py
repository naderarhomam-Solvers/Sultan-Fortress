"""Pixel-level segmentation of the emblem at supersampling S -> per-class masks (inside the disc and the text band).
The six ring annuli are NOT taken from here (they are analytic circles in the vector stage); this module only
decides the *content*: black / brown / tan inside the cream disc and black text inside the green band."""
import numpy as np, cv2
from classify import *

PARAMS = dict(
    tau_d=0.50,        # absolute darkness (lum < ~59) is ink, even next to brown ...
    chroma_max=32.0,   # ... but only if its colour is not brown (R-B below this)   [used inside the snake/sword ROI only]
    tau_k=0.50,        # black threshold on the sharpened black fraction
    tau_n=0.85,        # dark-brown threshold: only the dark-brown core is 'brown' (0.85 makes the snake/sword dark share equal to the picture's: 39.4% vs 39.6%)
    tan_t=0.30,        # silhouette threshold on the blurred brown fraction  (snake / sword body)
    tau_t=0.50,        # black text in the green band
    min_area_px2=0.918,  # drop islands / pinholes smaller than this many ORIGINAL-picture pixels^2 (= 0.10 mm2 on the round plaque)
    brown_roi_pad=6.0,  # px (original) dilation of the snake+sword component
    hole_lum_max=160.0,  # enclosed gaps of the tan silhouette are filled only if the picture is darker than this (cream = 178)
)


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
    F = fields(S)
    Fk, Fn, Ft, Fl, Fd, Fch = F['Fk'], F['Fn'], F['Ft'], F['Fl'], F['Fd'], F['Fch']
    n = WINSZ * S
    min_px = P['min_area_px2'] * S * S
    inside = radial_masks(S)
    core = core_mask(S)
    band = inside[3] & ~inside[2]

    text = clean(band & (Ft > P['tau_t']), min_px)

    # --- brown ROI = the large connected snake+sword component only
    Fs = cv2.GaussianBlur(Fn, (0, 0), 3.0 * S)
    comp = (Fs > 0.22).astype(np.uint8)
    nc, lab, st, _ = cv2.connectedComponentsWithStats(comp, connectivity=8)
    if nc < 2:
        raise RuntimeError('no snake/sword component found (blurred brown field never exceeds 0.22): this is not the SMB-87 picture')
    big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    roi = (lab == big).astype(np.uint8)
    r = int(P['brown_roi_pad'] * S)
    roi = cv2.dilate(roi, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))).astype(bool)

    # --- black: luminance outside the ROI (nothing is brown there; the colour unmix would read thin dark lines on cream
    #     as brown after JPEG chroma sub-sampling); inside the ROI the 3-end-member unmix, plus every clearly dark
    #     pixel that is not brown-tinted (claw outlines next to brown)
    ink_in_roi = (Fk > P['tau_k']) | ((Fd > P['tau_d']) & (Fch < P['chroma_max']))
    black = clean(core & np.where(roi, ink_in_roi, Fl > P['tau_k']), min_px)
    brown = clean(core & roi & ~black & (Fn > P['tau_n']), min_px)

    # --- tan: closed + hole-filled silhouette of the brown density (snake / sword body)
    Fn_s = cv2.GaussianBlur(np.where(core, Fn, 0).astype(np.float32), (0, 0), 1.0 * S)
    sil = (Fn_s > P['tan_t']) & core & roi
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(2.0 * S) + 1,) * 2)
    sil = cv2.morphologyEx(sil.astype(np.uint8), cv2.MORPH_CLOSE, k)
    ff = sil.copy()
    msk = np.zeros((n + 2, n + 2), np.uint8)
    cv2.floodFill(ff, msk, (0, 0), 2)
    filled = (ff != 2)
    # enclosed gaps (e.g. the sword-blade interior) are filled only if the PICTURE is not cream there
    nh, hl = cv2.connectedComponents((filled & (sil == 0)).astype(np.uint8), connectivity=4)
    lum_s = up(load_rgb().mean(axis=2), S)
    cnt = np.maximum(np.bincount(hl.ravel(), minlength=nh), 1)
    keep_hole = (np.bincount(hl.ravel(), weights=lum_s.ravel(), minlength=nh) / cnt) < P['hole_lum_max']
    keep_hole[0] = False
    sil = (sil > 0) | keep_hole[hl]
    sil = _drop_small(sil, 40 * S * S) & core
    tan = sil & ~black & ~brown
    tan = clean(tan, min_px)
    return dict(black=black, brown=brown, tan=tan, text=text, roi=roi, core=core, band=band, inside=inside,
                Fk=Fk, Fn=Fn, Ft=Ft, Fl=Fl, Fd=Fd, Fch=Fch, S=S, P=P)
