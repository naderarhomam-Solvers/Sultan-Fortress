"""Measure the true outer edge r(theta) of the outer black ring (it dissolves into the dark background, so it is only
measurable where the background is lighter) and fit a smooth periodic curve (harmonics 0..H)."""
import numpy as np, cv2
from scipy.ndimage import map_coordinates
from classify import SRC
im = cv2.cvtColor(cv2.imread(SRC), cv2.COLOR_BGR2RGB).astype(np.float32)
lum = cv2.GaussianBlur(im.mean(axis=2), (0, 0), 0.7)
cx0, cy0 = 538.89, 538.75
N = 2880
rs = np.arange(350, 376, 0.1)
th = np.linspace(0, 2 * np.pi, N, endpoint=False)
R = np.full(N, np.nan); contrast = np.zeros(N)
for i, t in enumerate(th):
    v = map_coordinates(lum, [cy0 + rs * np.sin(t), cx0 + rs * np.cos(t)], order=1, mode='nearest')
    k = np.median(v[(rs > 350) & (rs < 354)]); b = np.median(v[(rs > 368) & (rs < 374)])
    contrast[i] = b - k
    if b - k < 9: continue
    mid = (k + b) / 2
    idx = np.where((v[:-1] < mid) & (v[1:] >= mid) & (rs[:-1] > 354))[0]
    if len(idx) == 0: continue
    j = idx[0]; R[i] = rs[j] + (mid - v[j]) / (v[j + 1] - v[j]) * 0.1
ok = ~np.isnan(R)
print('valid angles %d / %d (%.0f%%)' % (ok.sum(), N, 100 * ok.mean()))
print('valid per 30 deg:', np.histogram(np.degrees(th[ok]), bins=12, range=(0, 360))[0])
def design(t, H): 
    cols = [np.ones_like(t)]
    for h in range(1, H + 1): cols += [np.cos(h * t), np.sin(h * t)]
    return np.stack(cols, axis=1)
for H in (0, 1, 2, 3, 4, 5):
    A = design(th[ok], H); w = np.ones(ok.sum()); 
    for _ in range(8):
        c, *_ = np.linalg.lstsq(A * w[:, None], R[ok] * w, rcond=None)
        res = R[ok] - A @ c; sd = max(res.std(), 0.3); w = 1.0 / np.maximum(1, np.abs(res) / (2 * sd))
    print('H=%d: residual std %.2f px  p5/p95 %.2f/%.2f  mean R %.2f' % (H, res.std(), *np.percentile(res, [5, 95]), c[0]))
H = 3
A = design(th[ok], H); w = np.ones(ok.sum())
for _ in range(8):
    c, *_ = np.linalg.lstsq(A * w[:, None], R[ok] * w, rcond=None)
    res = R[ok] - A @ c; sd = max(res.std(), 0.3); w = 1.0 / np.maximum(1, np.abs(res) / (2 * sd))
print('H=3 coefficients:', np.round(c, 4).tolist())
full = design(th, H) @ c
print('fitted radius range: %.2f .. %.2f px (circle used so far: 360.50)' % (full.min(), full.max()))
np.save('sil_coeffs.npy', c)
