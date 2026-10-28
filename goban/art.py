"""Procedurally generated textures: kaya wood, slate and shell stones, glows and sky.

Arrays are built bottom-row-first (pyglet's image origin), so +y is "up" and the
key light sits at the upper left of every stone.
"""

import numpy as np
import pyglet
from pyglet import gl
from scipy.ndimage import gaussian_filter, zoom

RNG_SEED = 7


def _to_texture(rgba, mipmap=True, anchor="center"):
    rgba = np.clip(rgba * 255.0 + 0.5, 0, 255).astype(np.uint8)
    h, w = rgba.shape[:2]
    image = pyglet.image.ImageData(w, h, "RGBA", rgba.tobytes(), pitch=w * 4)
    texture = image.get_texture()
    if mipmap:
        # Sprites draw these far smaller than their source size; mipmaps keep them smooth.
        try:
            gl.glBindTexture(texture.target, texture.id)
            gl.glGenerateMipmap(texture.target)
            gl.glTexParameteri(texture.target, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        except gl.GLException:
            pass
    if anchor == "center":
        texture.anchor_x, texture.anchor_y = w // 2, h // 2
    elif anchor == "top":
        texture.anchor_x, texture.anchor_y = w // 2, h
    return texture


def _grid(size):
    c = (np.arange(size) + 0.5) / size * 2.0 - 1.0
    x, y = np.meshgrid(c, c)
    return x, y


def _noise(rng, shape, cells):
    """Smooth value noise in [0, 1] with roughly `cells` features across."""
    small = rng.random((max(2, cells), max(2, cells)))
    big = zoom(small, (shape[0] / small.shape[0], shape[1] / small.shape[1]), order=3)
    big = big[: shape[0], : shape[1]]
    return (big - big.min()) / (np.ptp(big) + 1e-9)


def wood_pixels(size=1024):
    rng = np.random.default_rng(RNG_SEED)
    x, y = _grid(size)
    warp = _noise(rng, (size, size), 6) - 0.5
    fine_warp = _noise(rng, (size, size), 40) - 0.5
    blotch = _noise(rng, (size, size), 4)

    # Straight "masame" grain: fine, nearly parallel lines with slow drift.
    u = x * 11.0 + warp * 0.45 + fine_warp * 0.06 + 0.06 * np.sin(y * 1.3)
    primary = (0.5 + 0.5 * np.sin(u * 2 * np.pi)) ** 14
    secondary = (0.5 + 0.5 * np.sin(u * 2 * np.pi * 3.7 + warp * 2.0)) ** 8
    pores = gaussian_filter(rng.random((size, size)), (5.0, 0.5))
    pores = (pores - pores.mean()) / (pores.std() + 1e-9)

    base = np.array([0.88, 0.70, 0.43])
    dark = np.array([0.70, 0.49, 0.25])
    t = np.clip(0.42 * primary + 0.16 * secondary + 0.22 * (blotch - 0.5) + 0.03 * pores, 0, 1)[..., None]
    rgb = base * (1 - t) + dark * t

    # Lacquered sheen: a broad soft highlight toward the upper left.
    sheen = np.exp(-(((x + 0.35) ** 2) / 0.9 + ((y - 0.45) ** 2) / 0.6))
    rgb = rgb * (0.92 + 0.12 * sheen[..., None])
    vignette = 1 - 0.10 * np.clip(np.maximum(abs(x), abs(y)) - 0.7, 0, 1) / 0.3
    rgb *= vignette[..., None]

    return np.dstack([rgb, np.ones((size, size))])


def wood_texture(size=1024):
    return _to_texture(wood_pixels(size))


def _smoothstep(e0, e1, v):
    t = np.clip((v - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def _periodic_noise_1d(rng, n, max_freq, power):
    """Fractal noise in [0, 1] that wraps seamlessly at the ends."""
    spectrum = np.zeros(n // 2 + 1, complex)
    k = np.arange(1, max_freq + 1)
    spectrum[1:max_freq + 1] = (rng.standard_normal(max_freq) + 1j * rng.standard_normal(max_freq)) / k ** power
    signal = np.fft.irfft(spectrum, n)
    return (signal - signal.min()) / (np.ptp(signal) + 1e-9)


def _periodic_noise_2d(rng, h, w, cells_y, cells_x):
    ky = np.fft.fftfreq(h) * h / cells_y
    kx = np.fft.rfftfreq(w) * w / cells_x
    k = np.sqrt(ky[:, None] ** 2 + kx[None, :] ** 2)
    amp = np.exp(-k ** 2) * (k > 0)
    phase = rng.standard_normal(k.shape) + 1j * rng.standard_normal(k.shape)
    field = np.fft.irfft2(amp * phase, (h, w))
    return (field - field.min()) / (np.ptp(field) + 1e-9)


def stone_pixels(white, variant=0, size=256):
    """A lens-shaped stone lit by a soft window up and to the left.

    Shading is a reflected-environment model: the reflection vector picks up a
    rounded window highlight and a warm bounce from the board, mixed with Fresnel
    rim light. Shell stones get banded striations and a translucent warm rim."""
    rng = np.random.default_rng(RNG_SEED + 31 * variant + (100 if white else 0))
    x, y = _grid(size)
    r2 = x * x + y * y
    r = np.sqrt(r2)
    alpha = np.clip((1.0 - r) * size * 0.5, 0, 1)

    z = np.sqrt(np.clip(1 - r2, 0, 1)) * 0.62
    n = np.dstack([x, y, z])
    n /= np.linalg.norm(n, axis=2, keepdims=True) + 1e-9
    nx, ny, nz = n[..., 0], n[..., 1], n[..., 2]
    light = np.array([-0.45, 0.55, 0.70])
    light /= np.linalg.norm(light)
    diffuse = np.clip(n @ light, 0, 1)
    # reflection of the view ray (0, 0, -1) about the normal
    rx, ry = 2 * nx * nz, 2 * ny * nz
    fresnel = (1 - nz) ** 3

    def window(cx, cy, hx, hy, soft):
        return (_smoothstep(hx + soft, hx - soft, np.abs(rx - cx))
                * _smoothstep(hy + soft, hy - soft, np.abs(ry - cy)))

    key = window(-0.40, 0.46, 0.20, 0.14, 0.07)
    key_soft = window(-0.40, 0.46, 0.34, 0.28, 0.25)
    bounce = np.exp(-(((rx - 0.35) ** 2 + (ry + 0.55) ** 2) / 0.12))
    occlusion = 0.82 + 0.18 * _smoothstep(-1.0, 0.2, y - x * 0.4)

    if white:
        angle = rng.uniform(-0.35, 0.35) + np.pi / 2
        warp = _noise(rng, (size, size), 6) - 0.5
        u = (x * np.cos(angle) + y * np.sin(angle)) + warp * 0.12
        fine = 0.5 + 0.5 * np.sin(u * (46 + 8 * variant))
        broad = 0.5 + 0.5 * np.sin(u * (9 + 2 * variant) + 1.3)
        shell = np.array([0.955, 0.940, 0.900])
        bands = 1 - 0.035 * fine[..., None] - 0.045 * broad[..., None] ** 3
        rgb = shell * bands * (0.70 + 0.34 * diffuse)[..., None] * occlusion[..., None]
        # light scattering through the thin, translucent rim
        translucency = fresnel * (1 - diffuse) * 0.28
        rgb += translucency[..., None] * np.array([1.0, 0.86, 0.66])
        rgb += (key * 0.42 + key_soft * 0.10)[..., None]
        rgb += (bounce * 0.05)[..., None] * np.array([1.0, 0.75, 0.45])
        rgb += (fresnel * 0.06)[..., None]
    else:
        base = np.array([0.040, 0.043, 0.054])
        speckle = gaussian_filter(rng.random((size, size)), 0.8) - 0.5
        rgb = base * (1 + speckle * 0.6)[..., None]
        rgb = rgb + np.array([0.10, 0.11, 0.13]) * (diffuse ** 2 * occlusion)[..., None]
        rgb += (key * 0.38 + key_soft * 0.07)[..., None] * np.array([0.92, 0.96, 1.0])
        rgb += (bounce * 0.07)[..., None] * np.array([0.95, 0.70, 0.40])
        rgb += (fresnel * 0.20)[..., None] * np.array([0.55, 0.65, 0.85])

    return np.dstack([np.clip(rgb, 0, 1), alpha])


def stone_texture(white, variant=0, size=256):
    return _to_texture(stone_pixels(white, variant, size))


def contact_shadow_texture(size=128):
    x, y = _grid(size)
    r = np.sqrt(x * x + y * y)
    a = gaussian_filter((r < 0.86).astype(float), size * 0.035) * 0.85
    return _to_texture(np.dstack([np.zeros((size, size, 3)), a]))


def _range_pixels(rng, ridge, color, mist, h):
    """Fills below a ridge line (fractions of h per column), fading into mist at the base."""
    w = len(ridge)
    rows = (np.arange(h) + 0.5) / h
    Y, R = rows[:, None], ridge[None, :]
    edge = (R - Y) * h
    alpha = np.clip(edge / 1.3, 0, 1)
    depth = np.clip((R - Y) / R, 0, 1)
    texture_noise = _periodic_noise_2d(rng, h, w, 18, 90)
    mix = np.clip(depth ** 0.7 * 0.9 + (texture_noise - 0.5) * 0.15, 0, 1)[..., None]
    rgb = np.array(color) * (1 - mix) + np.array(mist) * mix
    rim = np.clip(1 - edge / 3.0, 0, 1) * (edge > 0)
    rgb += rim[..., None] * 0.06
    alpha *= 1 - 0.82 * depth ** 1.3
    return np.dstack([np.clip(rgb, 0, 1), alpha])


def mountain_texture(seed, color, mist, w=1024, h=320, base=0.30, height=0.55, roughness=1.5):
    """A horizontally tileable ridge line that dissolves into mist at its base."""
    rng = np.random.default_rng(seed)
    ridge = base + height * _periodic_noise_1d(rng, w, 60, roughness)
    return _to_texture(_range_pixels(rng, ridge, color, mist, h), mipmap=False, anchor="bottom_left")


def mesa_texture(seed, color, mist, w=1024, h=320):
    """Flat-topped mesas and a slender butte, like the American Southwest at dusk.
    Each has sheer cliffs above a sloping skirt of scree. Tiles horizontally."""
    rng = np.random.default_rng(seed)
    u = (np.arange(w) + 0.5) / w
    ridge = 0.10 + 0.04 * _periodic_noise_1d(rng, w, 30, 1.2)
    # (centre, half-width of the cap, height)
    for centre, half_width, height in ((0.10, 0.055, 0.46), (0.205, 0.014, 0.60),
                                       (0.52, 0.085, 0.40), (0.79, 0.035, 0.53)):
        d = np.abs(u - centre)
        d = np.minimum(d, 1 - d)  # wrap so the tile repeats seamlessly
        cliff = np.clip((half_width - d) / 0.014 + 0.5, 0, 1) ** 0.7
        scree = np.clip((half_width + 0.075 - d) / 0.075, 0, 1) ** 2.4 * height * 0.62
        cap = height * (1 - 0.05 * _periodic_noise_1d(rng, w, 160, 0.7))
        ridge = np.maximum(ridge, np.maximum(cap * cliff, scree))
    pixels = _range_pixels(rng, ridge, color, mist, h)
    # faint horizontal rock strata
    rows = (np.arange(h) + 0.5)[:, None]
    pixels[..., :3] *= (1 + 0.07 * np.sin(rows / 5.5) * np.sin(rows / 23.0))[..., None]
    return _to_texture(np.clip(pixels, 0, 1), mipmap=False, anchor="bottom_left")


def mist_texture(w=1024, h=128):
    rng = np.random.default_rng(RNG_SEED + 9)
    clouds = _periodic_noise_2d(rng, h, w, 3, 14)
    rows = (np.arange(h) + 0.5) / h
    band = np.exp(-((rows - 0.5) / 0.22) ** 2)[:, None]
    a = np.clip(clouds * 1.4 - 0.35, 0, 1) * band
    return _to_texture(np.dstack([np.ones((h, w, 3)) * np.array([0.78, 0.80, 0.95]), a]),
                       mipmap=False, anchor="bottom_left")


def aurora_texture(seed, w=1024, h=256):
    rng = np.random.default_rng(seed)
    base = 0.18 + 0.30 * _periodic_noise_1d(rng, w, 5, 1.4)
    rays = _periodic_noise_1d(rng, w, 220, 0.5)
    rays = 0.25 + 0.75 * rays ** 2
    patches = 0.15 + 0.85 * _periodic_noise_1d(rng, w, 4, 1.0) ** 1.5
    Y = ((np.arange(h) + 0.5) / h)[:, None]
    d = Y - base[None, :]
    profile = np.where(d < 0, np.exp(-(d / 0.025) ** 2), np.exp(-d / 0.22))
    profile *= np.clip((1 - Y) / 0.25, 0, 1)
    intensity = profile * rays[None, :] * patches[None, :]
    t = np.clip(d / 0.4, 0, 1)[..., None]
    green, violet = np.array([0.35, 1.0, 0.72]), np.array([0.62, 0.42, 1.0])
    rgb = green * (1 - t) + violet * t
    return _to_texture(np.dstack([rgb * np.ones((h, w, 1)), np.clip(intensity, 0, 1)]),
                       mipmap=False, anchor="bottom_left")


def shafts_texture(w=512, h=512):
    """Soft beams of light falling from above, wider and fainter toward the bottom."""
    rng = np.random.default_rng(RNG_SEED + 21)
    x = np.linspace(-1, 1, w)[None, :]
    Y = np.linspace(0, 1, h)[:, None]
    spread = 0.55 + 0.45 * (1 - Y)
    a = np.zeros((h, w))
    for _ in range(9):
        cx = rng.uniform(-0.6, 0.6)
        width = rng.uniform(0.02, 0.09)
        a += rng.uniform(0.3, 1.0) * np.exp(-(((x - cx * spread) / (width * spread)) ** 2))
    a *= Y ** 1.4 * np.clip(1 - np.abs(x) ** 2, 0, 1)
    a /= a.max()
    return _to_texture(np.dstack([np.ones((h, w, 3)), a * 0.9]), mipmap=False, anchor="top")


def petal_texture(size=64):
    x, y = _grid(size)
    width = 0.62 * (0.35 + 0.65 * (y + 1) / 2)
    f = (x / width) ** 2 + (y * 1.02) ** 2
    notch = np.sqrt(x ** 2 + (y - 1.0) ** 2)
    a = np.clip((0.88 - f) * 10, 0, 1) * np.clip((notch - 0.2) * 20, 0, 1)
    t = ((1 - y) / 2)[..., None]
    rgb = np.array([1.0, 0.86, 0.90]) * (1 - t) + np.array([0.96, 0.62, 0.74]) * t
    rgb += (0.08 * np.exp(-(x ** 2) / 0.02))[..., None]
    return _to_texture(np.dstack([np.clip(rgb, 0, 1), a]))


def streak_texture(w=256, h=16):
    u = np.linspace(0, 1, w)[None, :]
    v = np.linspace(-1, 1, h)[:, None]
    a = u ** 3 * np.exp(-(v / (0.15 + 0.35 * u)) ** 2)
    return _to_texture(np.dstack([np.ones((h, w, 3)), a]), mipmap=False)


def vignette_texture(size=256):
    x, y = _grid(size)
    r = np.sqrt(x * x * 0.9 + y * y)
    a = np.clip((r - 0.55) / 0.75, 0, 1) ** 1.5 * 0.8
    return _to_texture(np.dstack([np.zeros((size, size, 3)), a]), mipmap=False)


def gradient_texture(top_alpha, bottom_alpha, h=64):
    a = np.linspace(bottom_alpha, top_alpha, h)[:, None] * np.ones((1, 4))
    return _to_texture(np.dstack([np.zeros((h, 4, 3)), a]), mipmap=False)


def shadow_texture(size=128):
    x, y = _grid(size)
    r = np.sqrt(x * x + y * y) / 0.78
    a = np.clip(1.15 - r, 0, 1)
    a = gaussian_filter(a, size * 0.05) * 0.75
    return _to_texture(np.dstack([np.zeros((size, size, 3)), a]))


def glow_texture(size=128, falloff=4.0):
    x, y = _grid(size)
    a = np.exp(-(x * x + y * y) * falloff) * np.clip(1 - np.sqrt(x * x + y * y), 0, 1)
    return _to_texture(np.dstack([np.ones((size, size, 3)), a]))


def ring_texture(size=128, radius=0.78, width=0.07):
    x, y = _grid(size)
    r = np.sqrt(x * x + y * y)
    a = np.exp(-(((r - radius) / width) ** 2))
    return _to_texture(np.dstack([np.ones((size, size, 3)), a]))


def soft_rect_texture(size=256, inset=0.18):
    """A blurred square used as the board's drop shadow."""
    a = np.zeros((size, size))
    lo, hi = int(size * inset), int(size * (1 - inset))
    a[lo:hi, lo:hi] = 1
    a = gaussian_filter(a, size * inset * 0.45)
    return _to_texture(np.dstack([np.zeros((size, size, 3)), a]))


def sky_texture(w=640, h=400):
    """Deep twilight with drifting nebula colour — scaled up to cover the window."""
    rng = np.random.default_rng(RNG_SEED + 5)
    t = np.linspace(0, 1, h)[:, None] * np.ones((1, w))
    top = np.array([0.020, 0.028, 0.065])
    bottom = np.array([0.055, 0.050, 0.080])
    rgb = bottom * (1 - t[..., None]) + top * t[..., None]

    cloud_a = _noise(rng, (h, w), 5) * _noise(rng, (h, w), 11)
    cloud_b = _noise(rng, (h, w), 4) * _noise(rng, (h, w), 9)
    rgb += cloud_a[..., None] ** 1.6 * np.array([0.10, 0.05, 0.16])
    rgb += cloud_b[..., None] ** 1.8 * np.array([0.02, 0.10, 0.12])

    x = np.linspace(-1, 1, w)[None, :]
    y = np.linspace(-1, 1, h)[:, None]
    vignette = np.clip(1 - 0.45 * (x * x * 0.6 + y * y), 0.35, 1)
    rgb *= vignette[..., None]
    return _to_texture(np.dstack([np.clip(rgb, 0, 1), np.ones((h, w))]), mipmap=False)


class Art:
    """All textures, built once after the GL context exists."""

    def __init__(self):
        self.wood = wood_texture()
        self.black_stones = [stone_texture(False, i) for i in range(3)]
        self.white_stones = [stone_texture(True, i) for i in range(5)]
        self.shadow = shadow_texture()
        self.contact = contact_shadow_texture()
        self.glow = glow_texture()
        self.soft_glow = glow_texture(falloff=2.2)
        self.ring = ring_texture()
        self.marker = ring_texture(radius=0.62, width=0.11)
        self.board_shadow = soft_rect_texture()
        self.side_shade = gradient_texture(0.05, 0.6)
        self.sky = sky_texture()
        self.mountains = [
            mountain_texture(101, (0.17, 0.17, 0.32), (0.26, 0.25, 0.42), base=0.42, height=0.50, roughness=1.3),
            mountain_texture(202, (0.09, 0.10, 0.20), (0.19, 0.19, 0.33), base=0.30, height=0.45, roughness=1.5),
            mountain_texture(303, (0.035, 0.04, 0.085), (0.10, 0.10, 0.19), base=0.18, height=0.38, roughness=1.7),
        ]
        self.mesas = mesa_texture(606, (0.20, 0.13, 0.22), (0.30, 0.20, 0.30))
        self.mist = mist_texture()
        self.auroras = [aurora_texture(404), aurora_texture(505)]
        self.shafts = shafts_texture()
        self.petal = petal_texture()
        self.streak = streak_texture()
        self.vignette = vignette_texture()

    def stone(self, color_is_white, x, y):
        variants = self.white_stones if color_is_white else self.black_stones
        return variants[(x * 7 + y * 13 + x * y) % len(variants)]
