"""8192x2880 cloud belt from the 1 km NASA hemispheres, the recipe of prepare_earth.py at twice the rows. Parses downloaded data only. Run with python -I; it needs READY.json beside the files.
build_cloud_belt.py SOURCE OUT [W H]. Writes OUT/earth-clouds-WxH.png (R clouds, G second sample, as shipped); rename it earth-clouds.png for pack_earth.gd."""
import hashlib, json, math, sys
from pathlib import Path
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
SOURCE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
W, H = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (8192, 2880)
PINS = {'cloud.W.2001210.21600x21600.png': 'd7a6b03bb54b8ba56f72af6d1d49f191a25c12e911c43739c900e893d10eb814', 'cloud.E.2001210.21600x21600.png': '11eb1aaf8e6056b9aebc0de4894dc5ad8a21cbe8738c6ddc92e88701eb7e1b99'}
TOP, BOTTOM = math.sin(math.radians(80.0)), math.sin(math.radians(-6.0))
SECOND_DLAT, SECOND_DLON = -13.0, 129.0
SHARPEN = 0.5
# The shipped belt's sigma, 2 texels of 8192 x 2048, in the same kilometres.
SIGMA_X, SIGMA_Y = 2.0 * W / 8192, 2.0 * H / 2048


def blur_axis(a, sigma, axis, wrap):
    r = max(1, int(math.ceil(3 * sigma)))
    taps = np.exp(-.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    taps /= taps.sum()
    if wrap:
        pad = np.pad(a, [(0, 0), (r, r)] if axis == 1 else [(r, r), (0, 0)], mode='wrap')
    else:
        pad = np.pad(a, [(0, 0), (r, r)] if axis == 1 else [(r, r), (0, 0)], mode='edge')
    n = a.shape[axis]
    return sum(w * (pad[:, i:i + n] if axis == 1 else pad[i:i + n, :]) for i, w in enumerate(taps))


def relief(a):
    b = blur_axis(blur_axis(a, SIGMA_X, 1, True), SIGMA_Y, 0, False)
    return np.clip(a + SHARPEN * (a - b), 0, 1)


def belt(world, dlat=None, dlon=0.0):
    """Area average of the source on the belt. Rows linear in sin(lat), row 0 north."""
    rows, cols = world.shape
    out = np.zeros((H, W), np.float32)
    # The longitude of column edges in source pixels.
    edges = ((np.arange(W + 1) / W * 360.0 - 180.0 + dlon + 180.0) % 360.0) / 360.0 * cols
    for j in range(H):
        z0 = TOP - (TOP - BOTTOM) * j / H
        z1 = TOP - (TOP - BOTTOM) * (j + 1) / H
        lat0, lat1 = math.degrees(math.asin(z0)), math.degrees(math.asin(z1))
        if dlat is not None:
            lat0, lat1 = dlat - lat1, dlat - lat0
        r0 = (90.0 - max(min(lat0, 89.9), -89.9)) / 180.0 * rows
        r1 = (90.0 - max(min(lat1, 89.9), -89.9)) / 180.0 * rows
        a, b = int(math.floor(min(r0, r1))), int(math.ceil(max(r0, r1)))
        b = max(b, a + 1)
        row = world[a:b].astype(np.float64).mean(0)
        cum = np.concatenate([[0.0], np.cumsum(row)])
        left = edges[:-1]
        right = edges[1:]
        right = np.where(right <= left, right + cols, right)
        cum2 = np.concatenate([cum, cum[-1] + cum[1:]])
        at = lambda x: np.interp(x, np.arange(len(cum2)), cum2)
        out[j] = (at(right) - at(left)) / (right - left) / 255.0
    return out


def main():
    ready = SOURCE / 'READY.json'
    if not ready.exists():
        raise SystemExit('no READY.json in ' + str(SOURCE))
    listed = json.loads(ready.read_text())
    for name, digest in PINS.items():
        assert listed[name]['sha256'] == digest and hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest, 'Source differs from its pin: ' + name
    west = np.asarray(Image.open(SOURCE / 'cloud.W.2001210.21600x21600.png').convert('L'))
    east = np.asarray(Image.open(SOURCE / 'cloud.E.2001210.21600x21600.png').convert('L'))
    world = np.concatenate([west, east], 1)
    del west, east
    print('world', world.shape, flush=True)
    first = relief(belt(world))
    print('first', flush=True)
    second = relief(belt(world, SECOND_DLAT, SECOND_DLON))
    print('second', flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rgb = np.rint(np.stack([first, second, np.zeros_like(first)], -1) * 255).astype(np.uint8)
    Image.fromarray(rgb).save(OUT / f'earth-clouds-{W}x{H}.png', compress_level=1)
    (OUT / f'belt-{W}x{H}.json').write_text(json.dumps(dict(source=ready.read_text()[:2000], width=W, height=H, sharpen=SHARPEN, sigma_x=SIGMA_X, sigma_y=SIGMA_Y, second=[SECOND_DLAT, SECOND_DLON]), indent=1))
    print('done', flush=True)


if __name__ == '__main__':
    main()
