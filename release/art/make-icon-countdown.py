"""Frame Cinema icon, 2026-11 redesign: a strip of film runs across space above the
curve of the Earth at dusk. Its frames hold a countdown leader, 3 2 1, and the frame
in the gate is lit, as if the film is about to start.

Drawn in code at 2048 px and downsampled. The Earth uses NASA's public-domain Blue
Marble (December 2004), Black Marble 2016 (3 km) and Blue Marble cloud maps; the
digits are Inter (OFL). The tile follows Apple's shape: straight sides and corners
that ease in, lit from above.

Usage: python release/art/make-icon-countdown.py app/branding [--source DIR] [--font TTF]
Writes frame-cinema-<size>.png (16 to 1024 px) and preview.png (a size review sheet).
"""
import argparse
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None
HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
S = 2048
SIZES = (1024, 512, 256, 128, 64, 48, 32, 24, 16)
yy, xx = (np.mgrid[0:S, 0:S].astype(np.float32) + 0.5) / S

# The Earth's view: the sun to the right and a little behind, the limb's dusk side on the left.
SUN, TILT, LON0 = (0.85, 0.45, 0.05), 48.0, -15.0
# Film strip: centre height, the frame's half size, and the strip's half height.
STRIP_Y, FRAME_HX, FRAME_HY = 0.335, 0.235, 0.118
STRIP_HH = FRAME_HY + 0.088


# ---------------------------------------------------------------- colour and shapes
def lin(c):
    c = np.asarray(c, dtype=np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    t = np.asarray(t, dtype=np.float32)
    if t.ndim == 2:
        t = t[..., None]
    return a * (1 - t) + b * t


def tone(c, k=1.15):
    """A soft shoulder, so glows saturate gently instead of clipping."""
    return 1 - np.exp(-c * k)


GOLD = lin([236, 196, 132])


def _box(a, r, axis):
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode='edge'), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def blur(a, sigma):
    """Gaussian-like blur from three box passes; sigma in tile units."""
    sigma *= S
    f = 4 if sigma > 24 else 1
    small = a.reshape(a.shape[0] // f, f, a.shape[1] // f, f, *a.shape[2:]).mean(axis=(1, 3)) if f > 1 else a
    s = sigma / f
    r = max(1, int(round((math.sqrt(4 * s * s + 1) - 1) / 2)))
    for _ in range(3):
        small = _box(_box(small, r, 0), r, 1)
    return small if f == 1 else np.repeat(np.repeat(small, f, axis=0), f, axis=1)


def sd_rrect(cx, cy, hx, hy, r):
    qx = np.abs(xx - cx) - hx + r
    qy = np.abs(yy - cy) - hy + r
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def cover(sd):
    return np.clip(0.5 - sd * S, 0, 1)


def tile_shape(n=4.0, span=0.36):
    """Coverage of the tile and a field that is 1 on its edge. Each corner is a
    superellipse arc over `span` of the side, so the curve eases in."""
    a = 0.5
    qx = np.maximum(np.abs(xx - 0.5) - (a - span), 0) / span
    qy = np.maximum(np.abs(yy - 0.5) - (a - span), 0) / span
    corner = (qx ** n + qy ** n) ** (1 / n)
    side = np.maximum(np.abs(xx - 0.5), np.abs(yy - 0.5)) / a
    f = np.where((qx > 0) & (qy > 0), 1 - (1 - corner) * span / a, side)
    return np.clip((1 - f) * a * S + 0.5, 0, 1), f


def noise(seed, cell):
    grid = np.random.default_rng(seed).random((int(1 / cell),) * 2).astype(np.float32)
    return np.asarray(Image.fromarray(grid, 'F').resize((S, S), Image.BICUBIC), dtype=np.float32)


def stars(seed, count, keep):
    rng = np.random.default_rng(seed)
    field = np.zeros((S, S), np.float32)
    for _ in range(count):
        x, y = rng.random(), rng.random()
        if not keep(x, y):
            continue
        b = rng.random() ** 2.5
        rad = 0.9 + 1.6 * b
        px, py, k = int(x * S), int(y * S), int(rad * 3) + 1
        y0, y1, x0, x1 = max(0, py - k), min(S, py + k + 1), max(0, px - k), min(S, px + k + 1)
        gy, gx = np.mgrid[y0:y1, x0:x1]
        field[y0:y1, x0:x1] += (0.25 + 1.6 * b) * np.exp(-((gx - x * S) ** 2 + (gy - y * S) ** 2) / (2 * rad * rad))
    return field


# ---------------------------------------------------------------- the Earth
class Earth:
    def __init__(self, source):
        def tex(name, mode='RGB'):
            image = Image.open(source / name).convert(mode).resize((4096, 2048), Image.LANCZOS)
            return np.asarray(image, dtype=np.float32) / 255.0
        self.day = lin(tex('world.200412.3x5400x2700.jpg') * 255)
        self.night = lin(tex('BlackMarble_2016_3km.jpg') * 255)
        self.cloud = tex('cloud_combined_2048.jpg', 'L')

    @staticmethod
    def sample(t, lat, lon):
        h, w = t.shape[:2]
        u = ((lon / (2 * math.pi)) + 0.5) % 1.0 * (w - 1)
        v = np.clip(0.5 - lat / math.pi, 0, 1) * (h - 1)
        x0, y0 = np.floor(u).astype(int), np.floor(v).astype(int)
        x1, y1 = (x0 + 1) % w, np.minimum(y0 + 1, h - 1)
        fx, fy = u - x0, v - y0
        if t.ndim == 3:
            fx, fy = fx[..., None], fy[..., None]
        return (t[y0, x0] * (1 - fx) + t[y0, x1] * fx) * (1 - fy) + (t[y1, x0] * (1 - fx) + t[y1, x1] * fx) * fy

    def render(self, cx, cy, r, night_gain=2.6, halo=0.045):
        """Linear colour and coverage of the planet, lit by SUN (view space: x right, y up, z out)."""
        dx, dy = (xx - cx) / r, (yy - cy) / r
        d = np.sqrt(dx * dx + dy * dy)
        inside = np.clip((1 - d) * r * S + 0.5, 0, 1)
        z = np.sqrt(np.clip(1 - d * d, 0, 1))
        nx, ny, nz = dx, -dy, z
        sun = np.asarray(SUN, np.float32) / np.linalg.norm(SUN)
        ndl = nx * sun[0] + ny * sun[1] + nz * sun[2]
        t = math.radians(TILT)
        wy = ny * math.cos(t) - nz * math.sin(t)
        wz = ny * math.sin(t) + nz * math.cos(t)
        sel = np.nonzero(d < 1.0)
        la = np.arcsin(np.clip(wy[sel], -1, 1))
        lo = np.arctan2(nx[sel], wz[sel]) + math.radians(LON0)
        day, night = self.sample(self.day, la, lo), self.sample(self.night, la, lo)
        cloud = smooth(0.25, 0.85, self.sample(self.cloud, la, lo))
        n = ndl[sel]
        surface = day * (1 - cloud[:, None] * 0.85) + cloud[:, None] * 0.9
        col = surface * (0.012 + 1.25 * np.clip(n, 0, 1) ** 0.85)[:, None]
        # City lights on the night side only, dimmed under cloud.
        col += night * np.array([1.0, 0.72, 0.42], np.float32) * night_gain * ((1 - smooth(-0.05, 0.25, n)) * (1 - 0.7 * cloud))[:, None]
        # Air: a blue rim inside the disk, brightest on the lit limb.
        limb = (1 - z[sel]) ** 2.2
        sky = lin([90, 160, 255])
        col = col * (1 - 0.35 * limb[:, None]) + sky * (limb * (0.15 + 1.1 * smooth(-0.35, 0.6, n)))[:, None]
        color = np.zeros((S, S, 3), np.float32)
        color[sel] = col
        # The halo outside the limb, warm where the sun has just set.
        facing = (dx * sun[0] - dy * sun[1]) / np.maximum(d, 1e-4)
        glow = np.exp(-np.maximum(d - 1, 0) / halo) * (d >= 1) * (0.08 + smooth(-0.45, 0.7, facing))
        tint = mix(lin([255, 120, 60]), sky, smooth(-0.15, 0.45, facing)[..., None])
        return color + tint * glow[..., None] * 0.9, inside


# ---------------------------------------------------------------- the film
def leader(number, sweep_deg, font, width=2000):
    """One frame of a countdown leader: crosshair, two rings, the sweep hand's shade and a big number."""
    height = int(round(width * FRAME_HY / FRAME_HX))
    s = 2
    img = Image.new('L', (width * s, height * s), 214)
    d = ImageDraw.Draw(img)
    cx, cy = width * s // 2, height * s // 2
    r_out, r_in = int(height * s * 0.44), int(height * s * 0.36)
    d.pieslice((cx - r_out * 3, cy - r_out * 3, cx + r_out * 3, cy + r_out * 3), -90, -90 + sweep_deg, fill=150)
    line = int(height * s * 0.012)
    d.line((0, cy, width * s, cy), fill=40, width=line)
    d.line((cx, 0, cx, height * s), fill=40, width=line)
    for r in (r_out, r_in):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=30, width=line * 2)
    face = ImageFont.truetype(str(font), int(height * s * 0.56))
    try:
        face.set_variation_by_name('Bold')
    except (OSError, ValueError):
        pass
    box = d.textbbox((0, 0), str(number), font=face)
    d.text((cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2), str(number), font=face, fill=18)
    return img.resize((width, height), Image.LANCZOS)


def film_frame(picture, fx, gain, seed):
    """A frame of black-and-white film on the strip: graded, grained, vignetted, with a lit top edge."""
    x0, x1 = int(round((fx - FRAME_HX) * S)), int(round((fx + FRAME_HX) * S))
    y0, y1 = int(round((STRIP_Y - FRAME_HY) * S)), int(round((STRIP_Y + FRAME_HY) * S))
    w, h = picture.size
    crop = picture.crop((0, 0, w, int(w * FRAME_HY / FRAME_HX))).resize((x1 - x0, y1 - y0), Image.LANCZOS)
    g = np.asarray(crop, dtype=np.float32) / 255.0
    g = np.clip((g - 0.5) * 1.1 + 0.52, 0, 1)
    g = g + np.random.default_rng(seed).normal(0, 0.03, g.shape).astype(np.float32)
    v, u = np.mgrid[0:g.shape[0], 0:g.shape[1]].astype(np.float32)
    u, v = (u + 0.5) / g.shape[1] - 0.5, (v + 0.5) / g.shape[0] - 0.5
    g = g * (1 - 0.55 * (u * u + v * v * 1.6))
    layer = np.zeros((S, S), np.float32)
    ax0, ax1, ay0, ay1 = max(x0, 0), min(x1, S), max(y0, 0), min(y1, S)
    layer[ay0:ay1, ax0:ax1] = g[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0]
    rgb = lin(np.clip(layer, 0, 1)[..., None] * 255) * np.array([1.0, 0.975, 0.93], np.float32) * gain
    sd = sd_rrect(fx, STRIP_Y, FRAME_HX, FRAME_HY, 0.022)
    t = np.clip((yy - (STRIP_Y - FRAME_HY)) / (2 * FRAME_HY), 0, 1)
    rim = cover(sd) - cover(sd + 0.004)
    rgb = rgb + lin([255, 255, 255]) * (rim * smooth(0.6, 0.0, t) * 0.7)[..., None]
    band = smooth(0.05, 0.0, np.abs((xx - fx) * 0.55 + (yy - STRIP_Y) + FRAME_HY * 0.35) - 0.035)
    return rgb + 0.06 * (band * (1 - t))[..., None], cover(sd)


def icon(source, font):
    cy, hy, H = STRIP_Y, FRAME_HY, STRIP_HH
    # Space: deep blue fading to black, a few stars above and below the strip.
    img = mix(lin([13, 21, 58]), lin([3, 5, 15]), smooth(0.0, 0.75, yy))
    img = img + lin([60, 80, 150]) * (np.exp(-((xx - 0.5) ** 2 + (yy - 0.36) ** 2) / 0.09) * 0.12)[..., None]
    img = img + lin([235, 240, 255]) * (stars(7, 320, lambda x, y: y < 0.10 or 0.60 < y < 0.70) * 0.55)[..., None]
    planet, cov = Earth(source).render(0.5, 1.62, 1.02)
    img = mix(img, planet, cov) + planet * (1 - cov[..., None])
    # The strip: dark film base, two rows of sprocket holes cut out, a lit top edge and a soft sheen.
    strip = cover(sd_rrect(0.5, cy, 0.62, H, 0.0))
    t = np.clip((yy - (cy - H)) / (2 * H), 0, 1)
    base = mix(lin([44, 38, 36]), lin([20, 17, 17]), t) * (0.9 + 0.2 * noise(5, 1 / 400))[..., None]
    holes = np.zeros((S, S), np.float32)
    for row in (cy - hy - 0.044, cy + hy + 0.044):
        for k in range(-12, 13):
            holes = np.maximum(holes, cover(sd_rrect(0.5 + k * 0.058 + 0.029, row, 0.0145, 0.0185, 0.006)))
    edge = strip - cover(sd_rrect(0.5, cy, 0.616, H - 0.004, 0.0))
    base = base + lin([255, 225, 180]) * (edge * smooth(0.5, 0.0, t) * 0.35)[..., None]
    base = base + lin([255, 240, 220]) * (smooth(0.06, 0.0, np.abs((xx - 0.5) * 0.35 + (yy - cy) + 0.12) - 0.02) * 0.06)[..., None]
    alpha = strip * (1 - holes) * 0.97
    # Frames 3, 2, 1: the 2 is in the gate and lit; its neighbours run off the tile.
    fill, face = film_frame(leader(2, 120, font), 0.5, 1.3, 21)
    fill = fill + GOLD * 0.05
    side_pic = np.zeros((S, S, 3), np.float32)
    side = np.zeros((S, S), np.float32)
    for i, (number, sweep) in enumerate(((3, 250), (1, 300))):
        fx = 0.5 + (2 * FRAME_HX + 0.04) * (1 if i else -1)
        rgb, m = film_frame(leader(number, sweep, font), fx, 0.7, 22 + i)
        side_pic = side_pic + rgb * m[..., None]
        side = np.maximum(side, m)
    side, side_pic = side * strip, side_pic * strip[..., None]
    # Light from the gate: a glow behind the strip, a soft shadow under it, a halo over the film.
    img = img + GOLD * ((blur(face, 0.024) * 0.75 + blur(face, 0.08) * 0.28) * 1.1)[..., None]
    img = img * (1 - 0.35 * blur(np.roll(strip, int(0.02 * S), 0), 0.02))[..., None]
    img = mix(img, base, alpha)
    img = mix(img, side_pic, side * 0.95)
    img = mix(img, fill, face)
    img = img + GOLD * (blur(face, 0.018) * (1 - face) * 0.9)[..., None]
    img = img + GOLD * (np.exp(-((xx - 0.5) ** 2 / 0.06 + (yy - 0.60) ** 2 / 0.010)) * cov * 0.10)[..., None]
    img = tone(img)
    # The tile: light from above and a fine bright rim along its top edge.
    tile, f = tile_shape()
    img = img + lin([255, 255, 255]) * (smooth(0.55, 0.0, yy) * 0.025)[..., None]
    rim = np.clip((1 - f) * 0.5 * S + 0.5, 0, 1) - np.clip((1 - f) * 0.5 * S - 4.5, 0, 1)
    img = img + lin([255, 255, 255]) * (rim * smooth(0.65, 0.05, yy) * 0.22)[..., None]
    img = img * (1 - rim * smooth(0.5, 1.0, yy) * 0.25)[..., None]
    rgba = np.dstack([to_srgb(img), tile])
    return Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), 'RGBA').resize((1024, 1024), Image.LANCZOS)


def preview(master, path):
    """Size review sheet: 1024 down to 32 px on the dark library background."""
    sizes = (512, 256, 128, 64, 32)
    sheet = Image.new('RGB', (sum(sizes) + 40 * (len(sizes) + 1), 512 + 80), (27, 29, 36))
    x = 40
    for s in sizes:
        im = master.resize((s, s), Image.LANCZOS)
        sheet.paste(im, (x, 40 + 512 - s), im)
        x += s + 40
    sheet.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path)
    parser.add_argument('--source', type=Path, default=Path(os.environ.get('FRAME_CINEMA_EARTH_SOURCE', WORKSPACE / '.local/earth-nasa')),
                        help='folder with the NASA Blue Marble, Black Marble 3 km and cloud maps')
    parser.add_argument('--font', type=Path, default=HERE.parents[1] / 'app/InterVariable.ttf', help='Inter variable font')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    master = icon(args.source, args.font)
    for size in SIZES:
        master.resize((size, size), Image.LANCZOS).save(args.out / f'frame-cinema-{size}.png', optimize=True)
    preview(master, args.out / 'preview.png')
    print('ICON_OK', args.out)


if __name__ == '__main__':
    main()
