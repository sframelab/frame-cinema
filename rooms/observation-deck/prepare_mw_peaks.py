"""Real peaks of the NASA milkyway map near the band, with the local star-cloud level and the dark-lane field read at each one, for prepare_stars.py. Numbers only, from local untrusted arrays: run with python -I from another folder. The lane field is the definition in study/tools/recipe.py on the shown strip; a better one can replace data/lane_strip.npy with no other change."""
import math, sys
from pathlib import Path
import numpy as np, cv2
cv2.setNumThreads(4)
import argparse
_a = argparse.ArgumentParser(description=__doc__)
_a.add_argument('--work', type=Path, required=True, help='folder holding mw8kgal.npy')
_a.add_argument('--strip', type=Path, required=True, help="galaxy_exr.npy: the 0.5.13 strip, whose lane field is stored beside each peak")
_a.add_argument('--out', type=Path, required=True, help='file to write, mw_peaks.npz')
_a = _a.parse_args()
W = _a.work
LUMA = np.array([.2126, .7152, .0722], np.float32)
BMAX = 20.0
mw = np.load(W / 'mw8kgal.npy', mmap_mode='r')
h, w = mw.shape[:2]
PPD = w / 360.0
y0, y1 = int((90 - BMAX) / 180 * h), int((90 + BMAX) / 180 * h)
L = (np.asarray(mw[y0:y1]).astype(np.float32) @ LUMA)
RGB = np.asarray(mw[y0:y1]).astype(np.float32)


def blur(a, deg):
    pad = int(deg * PPD * 4) + 2
    b = np.concatenate([a[:, -pad:], a, a[:, :pad]], 1)
    return cv2.GaussianBlur(b, (0, 0), deg * PPD, borderType=cv2.BORDER_REFLECT)[:, pad:-pad]


bg = blur(L, .35)
cloud = blur(L, .2)
broad = blur(L, 3.0)
c = L
# 8-neighbour local maximum, ties broken toward the first.
ok = np.ones_like(L, bool)
for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
    ok[1:-1] &= c[1:-1] > np.roll(np.roll(c, -dy, 0), -dx, 1)[1:-1]
for dy, dx in ((0, 1), (1, -1), (1, 0), (1, 1)):
    ok[1:-1] &= c[1:-1] >= np.roll(np.roll(c, -dy, 0), -dx, 1)[1:-1]
ok &= c > 1e-4
ok[0] = ok[-1] = False
yy, xx = np.nonzero(ok)
print('peaks', len(yy), 'per deg2', round(len(yy) / ((y1 - y0) * w / PPD ** 2), 1))
xl, xr = L[yy, (xx - 1) % w], L[yy, (xx + 1) % w]
yu, yd = L[yy - 1, xx], L[yy + 1, xx]
cc = L[yy, xx]
sx = np.clip(.5 * (xl - xr) / np.minimum(xl - 2 * cc + xr, -1e-9), -.5, .5)
sy = np.clip(.5 * (yu - yd) / np.minimum(yu - 2 * cc + yd, -1e-9), -.5, .5)
lon = np.radians((xx + .5 + sx) / w * 360 - 180)
lat = np.radians(90 - (yy + y0 + .5 + sy) / h * 180)
gal = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1)
# Lane field on the shown strip: 0.5.13's map, same definition as study/tools/recipe.py lane_field, in strip pixels.
strip = np.load(_a.strip, mmap_mode='r')
sh, sw = strip.shape[:2]
SL = np.asarray(strip).astype(np.float32) @ LUMA * .1875
PX, PY = sw / 360.0, sh / 1.2 / 57.2958


def sblur(a, deg):
    px, py = deg * PX, deg * PY
    pad = int(px * 4) + 2
    b = np.concatenate([a[:, -pad:], a, a[:, :pad]], 1)
    return cv2.GaussianBlur(b, (0, 0), sigmaX=px, sigmaY=py, borderType=cv2.BORDER_REFLECT)[:, pad:-pad]


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


ref = sblur(SL, 1.6)
rel = (sblur(SL, .1) + 1e-5) / (ref + 1e-5)
lane = smooth(.92, .55, rel) * smooth(.0015, .006, ref)
np.save(_a.out.with_name('lane_strip.npy'), lane.astype(np.float32))
print('lane share of |b|<10 strip', float((lane[int((.5 - .1736 / 1.2) * sh):int((.5 + .1736 / 1.2) * sh)] > .5).mean()))


def at_strip(field, gal):
    u = (np.arctan2(gal[:, 1], gal[:, 0]) / (2 * np.pi) + .5) * sw - .5
    v = (gal[:, 2] / 1.2 + .5) * sh - .5
    x0, y0_ = np.floor(u).astype(int), np.floor(v).astype(int)
    fx, fy = (u - x0).astype(np.float32), (v - y0_).astype(np.float32)
    ya, yb = np.clip(y0_, 0, sh - 1), np.clip(y0_ + 1, 0, sh - 1)
    return (field[ya, x0 % sw] * (1 - fx) + field[ya, (x0 + 1) % sw] * fx) * (1 - fy) + (field[yb, x0 % sw] * (1 - fx) + field[yb, (x0 + 1) % sw] * fx) * fy


np.savez_compressed(_a.out, gal=gal.astype(np.float32), ex=(cc - bg[yy, xx]).astype(np.float32), peak=cc.astype(np.float32), cloud=cloud[yy, xx].astype(np.float32),
                    broad=broad[yy, xx].astype(np.float32), rgb=RGB[yy, xx].astype(np.float32), lane=at_strip(lane, gal).astype(np.float32), b=np.degrees(lat).astype(np.float32))
print('cloud p', np.percentile(cloud[yy, xx], [1, 10, 50, 90, 99]).round(4), 'ex p', np.percentile(cc - bg[yy, xx], [1, 10, 50, 90, 99]).round(4))
print('rgb B/R median at peaks', float(np.median(RGB[yy, xx, 2] / np.maximum(RGB[yy, xx, 0], 1e-6))))
