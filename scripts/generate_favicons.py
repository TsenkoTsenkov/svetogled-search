#!/usr/bin/env python3
"""
Generate the Светоглед favicon set: a circular medallion of the Sinai
Christ Pantocrator (the site's hero icon) with a gold ring on the site's
dark tile — the favicon is literally one of the site's icons.

Outputs (in static/):
    favicon-16.png, favicon-32.png, favicon-48.png    browser tabs / SERP
    apple-touch-icon.png (180x180)                    iOS home screen
    icon-192.png, icon-512.png                        manifest / Android
    favicon.ico                                       16+32+48 multi-size

Google Search prefers icons sized in multiples of 48px with a stable,
crawlable URL — favicon-48 and icon-192 are exposed for that.

Requires Pillow:  pip install Pillow
Run from anywhere: python3 scripts/generate_favicons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
SRC = STATIC / "christ-pantocrator-lg.jpg"

# Face crop: fractions of the source image width, tuned by eye for the
# 600x1119 Sinai Pantocrator so the halo frames the face.
FACE_CX = 0.47   # face center x (fraction of width)
FACE_CY = 0.272  # face center y (fraction of HEIGHT)
FACE_SIDE = 0.72 # crop square side (fraction of width)

# Palette (matches the site's CSS variables)
TILE_TOP = (20, 16, 25, 255)
TILE_BOTTOM = (9, 7, 12, 255)
GLOW = (212, 168, 83, 80)
RING_GOLD = (200, 153, 76, 255)
RING_LIGHT = (232, 201, 135, 255)

SS = 4  # supersampling factor


def load_face():
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    side = int(w * FACE_SIDE)
    cx = int(w * FACE_CX)
    cy = int(h * FACE_CY)
    box = (
        max(0, cx - side // 2),
        max(0, cy - side // 2),
        min(w, cx + side // 2),
        min(h, cy + side // 2),
    )
    face = im.crop(box)
    # Slight lift so the medallion pops on the dark tile
    face = ImageEnhance.Color(face).enhance(1.12)
    face = ImageEnhance.Contrast(face).enhance(1.06)
    face = ImageEnhance.Brightness(face).enhance(1.04)
    return face


FACE = load_face()


def render(size, rounded=True, medallion_frac=0.8):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Tile with vertical gradient, optionally rounded
    tile = Image.new("RGBA", (s, s))
    d = ImageDraw.Draw(tile)
    for y in range(s):
        t = y / max(1, s - 1)
        c = tuple(
            round(TILE_TOP[i] + (TILE_BOTTOM[i] - TILE_TOP[i]) * t)
            for i in range(3)
        )
        d.line([(0, y), (s, y)], fill=c + (255,))
    mask = None
    if rounded:
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, s - 1, s - 1], radius=round(s * 0.22), fill=255
        )
        img.paste(tile, (0, 0), mask)
    else:
        img.paste(tile, (0, 0))

    # Warm glow behind the medallion
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gr = s * 0.44
    ImageDraw.Draw(glow).ellipse(
        [s / 2 - gr, s / 2 - gr, s / 2 + gr, s / 2 + gr], fill=GLOW
    )
    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.08))
    if rounded:
        clipped = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        clipped.paste(glow, (0, 0), mask)
        glow = clipped
    img = Image.alpha_composite(img, glow)

    # Circular medallion of the icon
    md = round(s * medallion_frac)
    face = FACE.resize((md, md), Image.LANCZOS)
    circle = Image.new("L", (md, md), 0)
    ImageDraw.Draw(circle).ellipse([0, 0, md - 1, md - 1], fill=255)
    ox = (s - md) // 2
    img.paste(face, (ox, ox), circle)

    # Gold ring (thin light inner line over a solid gold ring)
    d = ImageDraw.Draw(img)
    rw = max(SS, round(s * 0.02))
    d.ellipse(
        [ox - rw // 2, ox - rw // 2, ox + md + rw // 2, ox + md + rw // 2],
        outline=RING_GOLD,
        width=rw,
    )
    d.ellipse(
        [ox + rw // 2, ox + rw // 2, ox + md - rw // 2, ox + md - rw // 2],
        outline=(232, 201, 135, 110),
        width=max(1, rw // 3),
    )

    return img.resize((size, size), Image.LANCZOS)


def main():
    STATIC.mkdir(exist_ok=True)

    # Small sizes: medallion fills more of the tile to stay legible
    render(16, medallion_frac=0.88).save(STATIC / "favicon-16.png")
    render(32, medallion_frac=0.86).save(STATIC / "favicon-32.png")
    render(48, medallion_frac=0.84).save(STATIC / "favicon-48.png")

    # iOS supplies its own corner mask — full-bleed square tile
    render(180, rounded=False, medallion_frac=0.8).save(
        STATIC / "apple-touch-icon.png"
    )

    # Manifest icons: full-bleed, medallion inside the maskable safe zone
    render(192, rounded=False, medallion_frac=0.78).save(STATIC / "icon-192.png")
    render(512, rounded=False, medallion_frac=0.78).save(STATIC / "icon-512.png")

    ico_sizes = [16, 32, 48]
    imgs = [render(n, medallion_frac=0.86) for n in ico_sizes]
    imgs[-1].save(
        STATIC / "favicon.ico",
        format="ICO",
        sizes=[(n, n) for n in ico_sizes],
        append_images=imgs[:-1],
    )

    for f in [
        "favicon-16.png", "favicon-32.png", "favicon-48.png",
        "apple-touch-icon.png", "icon-192.png", "icon-512.png", "favicon.ico",
    ]:
        p = STATIC / f
        print(f"  {f:24s} {p.stat().st_size:6d} B")


if __name__ == "__main__":
    main()
