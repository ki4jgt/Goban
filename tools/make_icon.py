"""Renders the Goban app icon and writes it in every desktop format.

    .venv/bin/python tools/make_icon.py

Outputs (in assets/icons/):
    goban.ico            Windows: 16-256 px in one file
    goban.icns           macOS: Apple-style margin and drop shadow, 16-1024 px
    goban-<N>.png        Linux hicolor sizes and the runtime window icon
    goban.png            1024 px master

The artwork reuses the game's own procedural wood and stones: the lamp-lit corner
of a kaya board with a slate stone and a shell stone on diagonal points.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from scipy.ndimage import zoom as resample

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goban.art import stone_pixels, wood_pixels  # noqa: E402

OUT = ROOT / "assets" / "icons"
MASTER = 1024
PNG_SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def over(dst, rgb, alpha):
    """Composites rgb with coverage alpha over a premultiplied-free RGBA canvas."""
    a = alpha[..., None]
    out_a = a + dst[..., 3:] * (1 - a)
    dst[..., :3] = (rgb * a + dst[..., :3] * dst[..., 3:] * (1 - a)) / np.maximum(out_a, 1e-6)
    dst[..., 3:] = out_a


def paste(dst, src, cx, cy):
    """Alpha-composites the RGBA array src centred at pixel (cx, cy)."""
    h, w = src.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    region = dst[y0:y0 + h, x0:x0 + w]
    over(region, src[..., :3], src[..., 3])


def render(size=MASTER, inset=0.94, shadow=False, line_boost=1.0, zoom=1.0, focus=(0.0, 0.0)):
    """Returns the icon as an RGBA float array, bottom row first (like the game's textures).

    `zoom` and `focus` frame the board inside the tile, so tiny sizes can crop in
    on the stones while the tile shape, bevel and lamp stay put."""
    s = size
    half = inset * s / 2
    c = (np.arange(s) + 0.5 - s / 2) / half
    TX, TY = np.meshgrid(c, c)  # tile coordinates
    X, Y = TX / zoom + focus[0], TY / zoom + focus[1]  # board coordinates
    px = 1.0 / (half * zoom)  # one pixel in board units

    # Squircle tile (superellipse, n=5), antialiased on its boundary.
    radial = (np.abs(TX) ** 5 + np.abs(TY) ** 5) ** 0.2
    tile = np.clip((1 - radial) * half + 0.5, 0, 1)

    canvas = np.zeros((s, s, 4))
    if shadow:
        drop = gaussian_filter(np.roll(tile, -int(0.018 * s), axis=0), 0.02 * s)
        over(canvas, np.zeros((s, s, 3)), drop * 0.5)

    # Kaya wood under a warm lamp toward the upper left.
    wood = wood_pixels(512)[..., :3]
    wood = resample(wood, (s / 512, s / 512, 1), order=1)
    lamp = 0.74 + 0.42 * np.exp(-(((TX + 0.35) ** 2) + ((TY - 0.4) ** 2)) / 0.8)
    face = np.clip(wood * lamp[..., None], 0, 1)

    # Board-corner grid: the edge lines at -0.82 / +0.82, then one cell (0.66) apart.
    ink = np.zeros_like(X)
    lw = 0.020 * line_boost
    for i, pos in enumerate((-0.82, -0.16, 0.50)):
        edge = i == 0
        w = lw * (1.8 if edge else 1)
        vertical = np.clip((w / 2 - np.abs(X - pos)) / px + 0.5, 0, 1) * (Y <= 0.82 + w / 2)
        ink = np.maximum(ink, vertical)
    for i, pos in enumerate((0.82, 0.16, -0.50)):
        edge = i == 0
        w = lw * (1.8 if edge else 1)
        horizontal = np.clip((w / 2 - np.abs(Y - pos)) / px + 0.5, 0, 1) * (X >= -0.82 - w / 2)
        ink = np.maximum(ink, horizontal)
    face = face * (1 - ink[..., None] * 0.86) + np.array([0.13, 0.08, 0.03]) * ink[..., None] * 0.86

    # Bevel: a lit rim along the top-left, a darker one along the bottom-right.
    rim = np.clip(1 - (1 - radial) / (0.045), 0, 1) ** 2
    light = np.clip((TY - TX) * 0.7 + 0.3, 0, 1)
    face += (rim * light * 0.22)[..., None] * np.array([1.0, 0.92, 0.75])
    face *= (1 - rim * (1 - light) * 0.35)[..., None]

    layer = np.dstack([np.clip(face, 0, 1), tile])
    canvas_face = layer.copy()

    # Stones on diagonal points, each with a soft shadow on the wood.
    diameter = int(round(0.64 * half * zoom / 2)) * 2  # just under one 0.66-wide cell
    for color_white, (sx, sy) in ((False, (-0.16, 0.16)), (True, (0.50, -0.50))):
        cx = s / 2 + (sx - focus[0]) * zoom * half
        cy = s / 2 + (sy - focus[1]) * zoom * half
        dist = np.sqrt((X - sx - 0.06) ** 2 + (Y - sy + 0.08) ** 2)
        soft = gaussian_filter(np.clip((0.31 - dist) / px, 0, 1), 0.04 * half * zoom) * 0.6
        over(canvas_face, np.zeros((s, s, 3)), soft * tile)
        stone = stone_pixels(color_white, 0, diameter)
        paste(canvas_face, stone, cx, cy)

    over(canvas, canvas_face[..., :3], canvas_face[..., 3])
    return canvas


def to_image(rgba, size=None):
    img = Image.fromarray((np.clip(rgba[::-1], 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")
    if size and size != img.width:
        img = img.resize((size, size), Image.LANCZOS)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    full = to_image(render())
    # Thicker grid lines read better once shrunk to toolbar sizes.
    small = to_image(render(line_boost=1.6, zoom=1.45, focus=(0.17, -0.17)))
    mac = to_image(render(inset=0.805, shadow=True))

    full.save(OUT / "goban.png")
    pngs = {}
    for n in PNG_SIZES:
        pngs[n] = (small if n <= 48 else full).resize((n, n), Image.LANCZOS)
        pngs[n].save(OUT / f"goban-{n}.png")

    ico_images = [pngs[n] for n in ICO_SIZES]
    ico_images[-1].save(OUT / "goban.ico", sizes=[(n, n) for n in ICO_SIZES],
                        append_images=ico_images[:-1])

    mac.save(OUT / "goban.icns")
    print(f"wrote icons to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
