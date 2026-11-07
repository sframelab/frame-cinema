"""Compose Frame Cinema's Steam library artwork from room renders and the icon.

Inputs: the Observation Deck's library shots (starship/preview.gd with STARSHIP_PREVIEW_LIBRARY=1 and
STARSHIP_PREVIEW_PICTURE set to the Coast still from render_room_still.gd), branding/frame-cinema-1024.png,
Inter (OFL).
Outputs (Steam's non-Steam-shortcut grid names are applied by the installer):
  capsule.png 600x900   portrait library capsule
  header.png  920x430   wide capsule / recent games
  hero.png    3840x1240 library hero banner (no text; Steam overlays the logo)
  logo.png    1280x720  transparent logo lockup placed over the hero
  icon.png    256x256   shortcut icon
Usage: python compose_art.py <renders dir> <branding dir> <Inter ttf> <out dir>
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

renders, branding, font_path, out = (Path(a) for a in sys.argv[1:5])
out.mkdir(parents=True, exist_ok=True)
icon = Image.open(branding / 'frame-cinema-1024.png').convert('RGBA')
INK = (246, 242, 233, 255)  # brand cream (make-icon.py)


def font(size, weight='SemiBold'):
    face = ImageFont.truetype(str(font_path), size)
    try:
        face.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass
    return face


def cover(image, size, focus=(0.5, 0.5)):
    """Scale to cover `size`, cropping around a focus point (fractions)."""
    w, h = size
    scale = max(w / image.width, h / image.height)
    scaled = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left = min(max(round(scaled.width * focus[0] - w / 2), 0), scaled.width - w)
    top = min(max(round(scaled.height * focus[1] - h / 2), 0), scaled.height - h)
    return scaled.crop((left, top, left + w, top + h))


def shade(image, top=0.0, bottom=0.72):
    """Darken toward the bottom so type stays legible over any scene."""
    w, h = image.size
    ramp = Image.new('L', (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        ramp.putpixel((0, y), round(255 * (top + (bottom - top) * max(0.0, (t - 0.45) / 0.55) ** 1.6)))
    mask = ramp.resize((w, h))
    black = Image.new('RGBA', (w, h), (6, 8, 14, 255))
    return Image.composite(black, image.convert('RGBA'), mask)


def lockup(height, wordmark=True):
    """Icon + 'Frame Cinema' wordmark on transparency, `height` px tall."""
    mark = icon.resize((height, height), Image.LANCZOS)
    if not wordmark:
        return mark
    face = font(round(height * 0.46))
    probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    box = probe.textbbox((0, 0), 'Frame Cinema', font=face)
    gap = round(height * 0.22)
    canvas = Image.new('RGBA', (height + gap + box[2] - box[0], height), (0, 0, 0, 0))
    canvas.alpha_composite(mark, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((height + gap - box[0], (height - (box[3] - box[1])) // 2 - box[1]), 'Frame Cinema', font=face, fill=INK)
    return canvas


def with_shadow(layer, radius, opacity=150):
    alpha = layer.split()[3].point(lambda a: a * opacity // 255)
    shadow = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    pad = radius * 3
    canvas = Image.new('RGBA', (layer.width + pad * 2, layer.height + pad * 2), (0, 0, 0, 0))
    canvas.alpha_composite(shadow, (pad, pad + radius // 2))
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius))
    canvas.alpha_composite(layer, (pad, pad))
    return canvas, pad


# 2026-11: all library art is the Observation Deck, the Earth's night side in the left windows and
# the Coast at dusk on the screen (0.5.3 to 0.5.15 used the Moon room).
hero = Image.open(renders / 'library_hero.png').convert('RGBA')
wide = Image.open(renders / 'library_header.png').convert('RGBA')
tall = Image.open(renders / 'library_capsule.png').convert('RGBA')

# Hero: rendered at 3840x1240 (screen centred, the Earth in the windows to its left), no text.
cover(hero, (3840, 1240)).convert('RGB').save(out / 'hero.png', optimize=True)

# Logo lockup for the hero overlay.
logo = Image.new('RGBA', (1280, 720), (0, 0, 0, 0))
mark, pad = with_shadow(lockup(260), 14)
mark.thumbnail((1280, 720), Image.LANCZOS)
logo.alpha_composite(mark, ((1280 - mark.width) // 2, (720 - mark.height) // 2))
logo.save(out / 'logo.png', optimize=True)

# Header 920x430: the Deck, lockup bottom-left.
header = shade(cover(wide, (920, 430)), 0.0, 0.78)
mark, pad = with_shadow(lockup(92), 8)
header.alpha_composite(mark, (40 - pad, 430 - 92 - 34 - pad))
header.convert('RGB').save(out / 'header.png', optimize=True)

# Portrait capsule 600x900: the canopy and the screen, stacked icon + title over the deck.
capsule = shade(cover(tall, (600, 900)), 0.0, 0.86)
mark, pad = with_shadow(lockup(150, wordmark=False), 10)
capsule.alpha_composite(mark, ((600 - mark.width) // 2, 900 - 150 - 196 - pad))
draw = ImageDraw.Draw(capsule)
title = font(70)
box = draw.textbbox((0, 0), 'Frame Cinema', font=title)
draw.text(((600 - (box[2] - box[0])) // 2 - box[0], 900 - 150 - box[1]), 'Frame Cinema', font=title, fill=INK)
capsule.convert('RGB').save(out / 'capsule.png', optimize=True)

icon.resize((256, 256), Image.LANCZOS).save(out / 'icon.png', optimize=True)
print('ART_OK', sorted(p.name for p in out.iterdir()))
