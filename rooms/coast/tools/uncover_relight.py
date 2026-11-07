"""Relight pebble texels that the original middle ledge covered.

ledge_fix.py lowers the ledge where it poked through the pebble beds; the pebble
surface it uncovers was baked in the ledge's shadow and shows dark. For each
pebble part, find texels whose world position lay under the original ledge
(within the poke band) and scale them to the broad brightness of the
surrounding uncovered pebbles, keeping their own detail.
Usage: uncover_relight.py <orig coast dir> <bake-merge dir>
"""
import struct
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

src, w = Path(sys.argv[1]), Path(sys.argv[2])
CELL, BAND = 0.02, 0.18


def read(name):
    b = (src / f'{name}.bin').read_bytes()
    magic, count, indices = struct.unpack('<III', b[:12])
    v = np.frombuffer(b, np.float32, count * 3, 12).reshape(-1, 3)
    uv = np.frombuffer(b, np.float32, count * 2, 12 + count * 40).reshape(-1, 2)
    tri = np.frombuffer(b, np.int32, indices, 12 + count * 48).reshape(-1, 3)
    return v, uv, tri


def bary(n):
    pts = [(i / n, j / n) for i in range(n + 1) for j in range(n + 1 - i)]
    a = np.array(pts, np.float32)
    return a[:, 0], a[:, 1]


# Original ledge height field (max over dense triangle samples), 2 cm grid.
lv, _, lt = read('middle-ledge')
u, t = bary(6)
la, lb, lc = lv[lt[:, 0]], lv[lt[:, 1]], lv[lt[:, 2]]
lp = (la[:, None] * (1 - u - t)[None, :, None] + lb[:, None] * u[None, :, None] + lc[:, None] * t[None, :, None]).reshape(-1, 3)
lo = lp[:, [0, 2]].min(0) - 0.1
lij = np.floor((lp[:, [0, 2]] - lo) / CELL).astype(np.int64)
grid = np.full(tuple(lij.max(0) + 2), -np.inf, np.float32)
np.maximum.at(grid, (lij[:, 0], lij[:, 1]), lp[:, 1])


def box(a, r):
    for axis in (0, 1):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode='edge'), axis=axis, dtype=np.float64)
        a = ((np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis) - np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)) / (2 * r + 1)).astype(np.float32)
    return a


def soft(a, r):
    return box(box(box(a, r), r), r)


for name, size in (('near-rear-rocks', 2048), ('near-left-rocks', 2048), ('seat-ledge', 4096)):
    v, uv, tri = read(name)
    raw = np.fromfile(w / f'{name}-merged.raw', np.float32).reshape(size, size, 4)
    # Splat world height/xz into texel space with dense barycentric samples.
    u, t = bary(10)
    A, B, C = tri[:, 0], tri[:, 1], tri[:, 2]
    covered = np.zeros((size, size), bool)
    chunk = 20000
    for s in range(0, len(tri), chunk):
        a, b, c = A[s:s + chunk], B[s:s + chunk], C[s:s + chunk]
        wu, wt, ww = u[None, :], t[None, :], (1 - u - t)[None, :]
        p = v[a][:, None] * ww[..., None] + v[b][:, None] * wu[..., None] + v[c][:, None] * wt[..., None]
        q = uv[a][:, None] * ww[..., None] + uv[b][:, None] * wu[..., None] + uv[c][:, None] * wt[..., None]
        p, q = p.reshape(-1, 3), q.reshape(-1, 2)
        gij = np.floor((p[:, [0, 2]] - lo) / CELL).astype(np.int64)
        ok = (gij[:, 0] >= 0) & (gij[:, 1] >= 0) & (gij[:, 0] < grid.shape[0]) & (gij[:, 1] < grid.shape[1])
        ledge_y = np.full(len(p), -np.inf, np.float32)
        ledge_y[ok] = grid[gij[ok, 0], gij[ok, 1]]
        under = (ledge_y > p[:, 1]) & (ledge_y < p[:, 1] + BAND)
        tx = np.clip((q[:, 0] * size).astype(np.int64), 0, size - 1)
        ty = np.clip((q[:, 1] * size).astype(np.int64), 0, size - 1)
        covered[ty[under], tx[under]] = True
    scale = size / 2048
    occ = np.asarray(Image.fromarray((covered * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(2 * scale)), np.float32) / 255.0
    lum = raw[..., :3].mean(-1)
    lit = (lum > 1e-4).astype(np.float32)
    free = lit * (1.0 - np.clip(occ * 2.0, 0, 1))
    r = max(3, int(16 * scale))
    broad_free = soft(lum * free, r) / np.maximum(soft(free, r), 1e-4)
    broad_occ = soft(lum * lit * occ, r) / np.maximum(soft(lit * occ, r), 1e-4)
    gain = np.clip(broad_free / np.maximum(broad_occ, 1e-5), 1.0, 6.0)
    g = 1.0 + (gain - 1.0) * occ * lit
    raw[..., :3] *= g[..., None]
    # Faces that were buried under the ledge got no light at all (scaling keeps
    # them black): fill those from the surrounding pebbles' broad colour.
    broad_rgb = np.stack([soft(raw[..., c] * free, r) / np.maximum(soft(free, r), 1e-4) for c in range(3)], -1)
    lum2 = raw[..., :3].mean(-1)
    dark = np.clip(1.0 - lum2 / np.maximum(0.35 * broad_free, 1e-5), 0.0, 1.0) * occ
    raw[..., :3] = raw[..., :3] * (1.0 - dark[..., None]) + 0.55 * broad_rgb * dark[..., None]  # stone sides sit in shade
    raw.astype(np.float32).tofile(w / f'{name}-merged.raw')
    print(f'{name:16} uncovered texels {covered.mean():.4f}, median gain there {np.median(gain[covered]) if covered.any() else 1:.2f}')
