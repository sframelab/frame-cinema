"""Merge Coast bakes so the floor around the seat shows the original rock scan.

The 0.4.21 contact overlay replaced these parts' lighting with a generic pebble
texture (rocks_ground_06) in bands, and reshaped some geometry there. Here:
- inside the overlay bands, the original bake's fine detail (the true scan) is
  used under the shipped bake's broad lighting, which is correct for the
  current geometry: out = old * blur(new) / blur(old);
- texels the original never lit (buried before the reshaping) keep the shipped
  bake; everything outside the bands is unchanged;
- band edges are feathered. Writes <name>-merged.raw.
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter


def box(a, r):
    """Separable box blur with edge clamping (r texels)."""
    for axis in (0, 1):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode='edge'), axis=axis, dtype=np.float64)
        hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
        a = ((hi - lo) / (2 * r + 1)).astype(np.float32)
    return a


def soft(a, r):
    return box(box(box(a, r), r), r)  # ~Gaussian


w = Path(sys.argv[1])
for name, size in (('seat-ledge', 4096), ('middle-ledge', 4096), ('near-left-rocks', 2048), ('near-rear-rocks', 2048)):
    new = np.fromfile(w / f'{name}-new.raw', np.float32).reshape(size, size, 4)
    old = np.fromfile(w / f'{name}-old.raw', np.float32).reshape(size, size, 4)
    ln, lo = new[..., :3].mean(-1), old[..., :3].mean(-1)
    used_new, used_old = ln > 1e-4, lo > 1e-4
    rel = np.abs(ln - lo) / (np.maximum(ln, lo) + 1e-3)
    replaced = used_new & used_old & (rel >= 0.08)
    scale = size / 4096
    mask = Image.fromarray((replaced * 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MaxFilter(int(9 * scale) | 1)).filter(ImageFilter.MinFilter(int(5 * scale) | 1))
    mask = mask.filter(ImageFilter.GaussianBlur(4 * scale))
    weight = np.asarray(mask, np.float32) / 255.0
    # Broad lighting from the shipped bake, fine detail from the original. Blur
    # only over lit texels (normalised), so island borders do not darken.
    r = max(2, int(12 * scale))
    occ_n, occ_o = used_new.astype(np.float32), used_old.astype(np.float32)
    broad_new = soft(ln * occ_n, r) / np.maximum(soft(occ_n, r), 1e-4)
    broad_old = soft(lo * occ_o, r) / np.maximum(soft(occ_o, r), 1e-4)
    gain = np.clip(broad_new / np.maximum(broad_old, 1e-5), 0.0, 6.0)
    relit = old[..., :3] * gain[..., None]
    # Texels the original never lit (or lit at under 8% of today's level) are
    # noise there: keep the shipped bake (smooth ramp, then feathered).
    valid = np.clip((lo / np.maximum(ln, 1e-5) - 0.08) / 0.10, 0.0, 1.0) * used_old
    valid = np.asarray(Image.fromarray((valid * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(int(5 * scale) | 1)).filter(ImageFilter.GaussianBlur(3 * scale)), np.float32) / 255.0
    weight *= valid
    out = new.copy()
    out[..., :3] = new[..., :3] * (1.0 - weight[..., None]) + relit * weight[..., None]
    out.astype(np.float32).tofile(w / f'{name}-merged.raw')
    preview = np.clip((out[..., :3] / max(np.percentile(out[..., :3], 99.5), 1e-4)) ** (1 / 2.2), 0, 1)
    Image.fromarray((preview * 255).astype(np.uint8)).resize((1024, 1024), Image.LANCZOS).save(w / f'{name}-merged.png')
    print(f'{name:16} original detail on {weight.mean():.3f} of texels; median gain in bands {np.median(gain[replaced]):.2f}')
