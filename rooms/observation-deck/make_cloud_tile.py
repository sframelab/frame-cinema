"""Cloud detail tile, procedural, no source data: one channel, height. Periodic. Writes OUTPUT/cloud-detail.png and OUTPUT/cloud-detail.json; pack_earth.gd makes cloud-detail.res from the PNG. The defaults are the shipped tile.

Height is billowed cells plus fractal noise, high-passed so that everything longer than HIGHPASS texels stays the real cloud map's.
python make_cloud_tile.py --output DIR [--size 1024] [--seed 7] [--rgb]
"""
import argparse, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image

HIGHPASS = 20.0
LOWPASS = 2.0
SLOPE = 1.25


def fractal(size, rng, lowpass=LOWPASS):
    k = np.fft.fftfreq(size) * size
    kx, ky = np.meshgrid(k, k)
    r = np.hypot(kx, ky)
    r[0, 0] = 1
    a = r ** -SLOPE
    a *= np.exp(-(r * lowpass / size) ** 4)
    a[0, 0] = 0
    f = np.fft.ifft2(a * np.exp(2j * np.pi * rng.random((size, size)))).real
    return f / f.std()


def cells(size, count, rng):
    """1 at each cell's seed falling to 0 at its neighbours: periodic Worley."""
    pts = rng.random((count, count, 2), dtype=np.float32)
    step = size / count
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    cx = (x / step).astype(np.int32)
    cy = (y / step).astype(np.int32)
    fx = x / step - cx
    fy = y / step - cy
    best = np.full(x.shape, 9.0, dtype=np.float32)
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            p = pts[(cy + dj) % count, (cx + di) % count]
            best = np.minimum(best, (p[..., 0] + di - fx) ** 2 + (p[..., 1] + dj - fy) ** 2)
    return 1 - np.clip(np.sqrt(best), 0, 1)


def high_pass(f, size, highpass=HIGHPASS):
    k = np.fft.fftfreq(size) * size
    kx, ky = np.meshgrid(k, k)
    r = np.hypot(kx, ky)
    keep = 1 - np.exp(-(r * highpass / size) ** 4)
    return np.fft.ifft2(np.fft.fft2(f) * keep).real


def grad(f, size):
    k = np.fft.fftfreq(size) * 2j * np.pi
    F = np.fft.fft2(f)
    return np.fft.ifft2(F * k[None, :]).real, np.fft.ifft2(F * k[:, None]).real


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--output', type=Path, required=True)
    a.add_argument('--size', type=int, default=1024)
    a.add_argument('--seed', type=int, default=7)
    a.add_argument('--name', default='cloud-detail')
    a.add_argument('--worley', type=float, default=.2)
    a.add_argument('--cells', default='6,3,2')
    a.add_argument('--highpass', type=float, default=HIGHPASS)
    a.add_argument('--lowpass', type=float, default=LOWPASS)
    a.add_argument('--rgb', action='store_true', help='Also keep the gradient in G and B')
    a = a.parse_args()
    a.gray = not a.rgb
    OUT = a.output
    size = a.size
    rng = np.random.default_rng(a.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    w = sum(g * cells(size, size // c, rng) for g, c in zip((.45, .35, .2), [int(v) for v in a.cells.split(',')]))
    h = (1 - a.worley) * fractal(size, rng, a.lowpass) + a.worley * (w - w.mean()) / w.std()
    h = high_pass(h, size, a.highpass)
    h /= h.std()
    gx, gy = grad(h, size)
    g99 = float(np.percentile(np.hypot(gx, gy), 99.5))
    rgb = np.stack([np.clip(.5 + h / 6, 0, 1), np.clip(.5 + .5 * gx / g99, 0, 1), np.clip(.5 + .5 * gy / g99, 0, 1)], -1)
    out = rgb[..., 0] if a.gray else rgb
    Image.fromarray((out * 255 + .5).astype(np.uint8)).save(OUT / f'{a.name}.png', compress_level=6)
    mean = rgb.mean((0, 1))
    (OUT / f'{a.name}.json').write_text(json.dumps(dict(size=size, seed=a.seed, worley=a.worley, cells=a.cells, gray=a.gray, highpass_texels=a.highpass, lowpass_texels=a.lowpass, slope=SLOPE, mean=[round(float(v), 4) for v in mean],
                                                         std=[round(float(v), 4) for v in rgb.std((0, 1))], kurtosis_r=round(float(((h / h.std()) ** 4).mean() - 3), 3), gradient_p995=round(g99, 5)), indent=1))
    print((OUT / f'{a.name}.json').read_text())


if __name__ == '__main__':
    main()
