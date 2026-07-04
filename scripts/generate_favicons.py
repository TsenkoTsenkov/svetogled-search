#!/usr/bin/env python3
"""
Rasterize the Светоглед favicon (eight-pointed star, gold on dark) into
PNG/ICO assets. Mirrors the geometry of static/favicon.svg exactly.

Outputs (in static/):
    favicon-16.png, favicon-32.png      browser tabs
    apple-touch-icon.png (180x180)      iOS home screen (square, iOS masks it)
    icon-192.png, icon-512.png          web manifest / Android (maskable-safe)
    favicon.ico                         16+32+48 multi-size

Requires Pillow:  pip install Pillow
Run from anywhere: python3 scripts/generate_favicons.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

# Palette (matches the site's CSS variables)
TILE_TOP = (20, 16, 25, 255)
TILE_BOTTOM = (9, 7, 12, 255)
BORDER = (200, 153, 76, 72)
GLOW = (212, 168, 83, 70)
STAR_TOP = (236, 210, 154)
STAR_BOTTOM = (165, 118, 47)
CORE_DARK = (13, 10, 17, 255)
CORE_DOT = (226, 189, 119, 255)

SS = 8  # supersampling factor


def star_points(cx, cy, r_out, r_in, n=8):
    """Vertices of an n-pointed star, one ray pointing straight up."""
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(-90 + i * (360 / (n * 2)))
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def vertical_gradient(size, top, bottom):
    img = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        c = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (size, y)], fill=c + (255,))
    return img


def render(size, rounded=True, star_scale=1.0):
    """Render the icon at `size`. star_scale<1 shrinks the star for
    maskable icons whose edges may be cropped by the platform."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Tile with vertical gradient, optionally rounded
    tile = vertical_gradient(s, TILE_TOP, TILE_BOTTOM)
    if rounded:
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, s - 1, s - 1], radius=round(s * 0.22), fill=255
        )
        img.paste(tile, (0, 0), mask)
    else:
        img.paste(tile, (0, 0))

    # Soft radial glow behind the star
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gr = s * 0.34 * star_scale
    ImageDraw.Draw(glow).ellipse(
        [s / 2 - gr, s * 0.47 - gr, s / 2 + gr, s * 0.47 + gr], fill=GLOW
    )
    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.07))
    if rounded:
        clipped = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        clipped.paste(glow, (0, 0), mask)
        glow = clipped
    img = Image.alpha_composite(img, glow)

    # Star: gold vertical gradient through a star-shaped mask
    r_out = s * 0.30 * star_scale
    r_in = r_out * 0.44
    star_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(star_mask).polygon(
        star_points(s / 2, s / 2, r_out, r_in), fill=255
    )
    grad = vertical_gradient(s, STAR_TOP, STAR_BOTTOM)
    star_layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    star_layer.paste(grad, (0, 0), star_mask)
    img = Image.alpha_composite(img, star_layer)

    # Center: dark core with a small gold dot (the "node" of the map).
    # At tab sizes the core muddies the star, so keep it solid there.
    if size >= 48:
        d = ImageDraw.Draw(img)
        cr = s * 0.046 * star_scale
        d.ellipse([s / 2 - cr, s / 2 - cr, s / 2 + cr, s / 2 + cr], fill=CORE_DARK)
        dr = s * 0.02 * star_scale
        d.ellipse([s / 2 - dr, s / 2 - dr, s / 2 + dr, s / 2 + dr], fill=CORE_DOT)

    # Hairline border to keep the tile visible on dark browser chrome
    if rounded:
        bw = max(1, round(s * 0.012))
        ImageDraw.Draw(img).rounded_rectangle(
            [bw // 2, bw // 2, s - 1 - bw // 2, s - 1 - bw // 2],
            radius=round(s * 0.215),
            outline=BORDER,
            width=bw,
        )

    return img.resize((size, size), Image.LANCZOS)


def main():
    STATIC.mkdir(exist_ok=True)

    render(16).save(STATIC / "favicon-16.png")
    render(32).save(STATIC / "favicon-32.png")

    # iOS supplies its own corner mask — full-bleed square tile
    render(180, rounded=False, star_scale=0.92).save(STATIC / "apple-touch-icon.png")

    # Manifest icons: full-bleed, star inside the 80% maskable safe zone
    render(192, rounded=False, star_scale=0.86).save(STATIC / "icon-192.png")
    render(512, rounded=False, star_scale=0.86).save(STATIC / "icon-512.png")

    ico_sizes = [16, 32, 48]
    imgs = [render(n) for n in ico_sizes]
    imgs[-1].save(
        STATIC / "favicon.ico",
        format="ICO",
        sizes=[(n, n) for n in ico_sizes],
        append_images=imgs[:-1],
    )

    for f in [
        "favicon-16.png", "favicon-32.png", "apple-touch-icon.png",
        "icon-192.png", "icon-512.png", "favicon.ico",
    ]:
        p = STATIC / f
        print(f"  {f:24s} {p.stat().st_size:6d} B")


if __name__ == "__main__":
    main()
