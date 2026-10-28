"""The living background, back to front: twilight nebula, twinkling stars, aurora
curtains, falling light, a desert-dusk glow on the horizon, misty mountain ranges
with a few far-off mesas, lantern motes, fireflies, drifting cherry petals, the
odd shooting star and a cinematic vignette. Layers shift with the
pointer at different rates for a sense of depth."""

import math
import random

import pyglet
from pyglet.graphics import Group
from pyglet.sprite import Sprite

from .board_view import additive


class Backdrop:
    def __init__(self, art):
        self.art = art
        self.batch = pyglet.graphics.Batch()
        b = self.batch
        self.w, self.h = 1, 1
        self.px = self.py = 0.0  # smoothed pointer offset in [-1, 1]
        self.tx = self.ty = 0.0
        rng = random.Random(42)

        self.sky = Sprite(art.sky, batch=b, group=Group(order=0))

        self.stars = []
        g = Group(order=1)
        for _ in range(220):
            s = additive(art.glow, b, g)
            s.color = rng.choice([(255, 255, 255), (200, 220, 255), (255, 232, 200)])
            self.stars.append({
                "sprite": s, "u": rng.random(), "v": 0.25 + 0.75 * rng.random() ** 0.8,
                "size": rng.uniform(2.5, 8) * (2.2 if rng.random() < 0.04 else 1),
                "phase": rng.uniform(0, 6.3), "speed": rng.uniform(0.4, 1.8), "base": rng.uniform(50, 200),
            })

        g = Group(order=2)
        self.auroras = []
        for i, (tex, tint) in enumerate(zip(art.auroras, [(255, 255, 255), (190, 170, 255)])):
            pair = [additive(tex, b, g), additive(tex, b, g)]
            for s in pair:
                s.color = tint
            self.auroras.append({"sprites": pair, "speed": (0.006, -0.004)[i], "phase": i * 2.1,
                                 "height": (0.40, 0.32)[i], "base": (0.50, 0.58)[i], "offset": i * 0.37})

        self.shafts = additive(art.shafts, b, Group(order=3))
        self.shafts.color = (255, 226, 180)

        # Last light of a desert sunset, low behind the ranges.
        self.dusk = additive(art.soft_glow, b, Group(order=3.5))
        self.dusk.color = (255, 138, 78)

        self.ranges = []
        specs = [  # (height as fraction of window, drift speed, parallax px)
            (0.55, 0.0016, 6),
            (0.42, 0.0032, 14),
            (0.30, 0.0060, 26),
        ]
        for i, (tex, (height, speed, parallax)) in enumerate(zip(art.mountains, specs)):
            g = Group(order=4 + i * 2)
            layer = {"sprites": [Sprite(tex, batch=b, group=g), Sprite(tex, batch=b, group=g)],
                     "height": height, "speed": speed, "parallax": parallax, "offset": rng.random()}
            self.ranges.append(layer)
            if i < 2:
                mist_group = Group(order=5 + i * 2)
                mist = [Sprite(art.mist, batch=b, group=mist_group) for _ in range(2)]
                for s in mist:
                    s.opacity = 70 - i * 20
                self.ranges.append({"sprites": mist, "height": height * 0.35, "speed": speed * 2.5,
                                    "parallax": parallax + 4, "offset": rng.random(), "lift": height * 0.25})

        # Mesas sit between the far range and the middle one.
        self.ranges.append({"sprites": [Sprite(art.mesas, batch=b, group=Group(order=5.5)) for _ in range(2)],
                            "height": 0.66, "speed": 0.0022, "parallax": 9, "offset": 0.62})

        self.motes = []
        g = Group(order=11)
        for _ in range(34):
            s = additive(art.soft_glow, b, g)
            s.color = rng.choice([(255, 186, 110), (255, 206, 140), (130, 210, 225)])
            self.motes.append({
                "sprite": s, "u": rng.random(), "v": rng.random(),
                "size": rng.uniform(18, 80), "rise": rng.uniform(0.004, 0.014),
                "sway": rng.uniform(0.004, 0.02), "phase": rng.uniform(0, 6.3), "base": rng.uniform(16, 55),
            })

        # A handful of fireflies drifting low over the ground, blinking now and then.
        self.fireflies = []
        g = Group(order=11.5)
        for _ in range(14):
            core = additive(art.glow, b, g)
            halo = additive(art.soft_glow, b, g)
            core.color = (226, 255, 140)
            halo.color = (190, 255, 110)
            self.fireflies.append({
                "core": core, "halo": halo, "u": rng.random(), "v": rng.uniform(0.05, 0.42),
                "du": rng.uniform(-0.01, 0.01), "dv": rng.uniform(-0.006, 0.006),
                "period": rng.uniform(3.5, 7.0), "phase": rng.uniform(0, 7), "wobble": rng.uniform(0, 6.3),
            })

        self.petals = []
        g = Group(order=12)
        for _ in range(42):
            s = Sprite(art.petal, batch=b, group=g)
            depth = rng.uniform(0.35, 1.0)
            s.color = (255, int(235 + 20 * depth), 245)
            self.petals.append({
                "sprite": s, "u": rng.random(), "v": rng.random(), "depth": depth,
                "fall": rng.uniform(0.018, 0.035) * depth, "drift": rng.uniform(0.006, 0.02),
                "spin": rng.uniform(-90, 90), "angle": rng.uniform(0, 360),
                "flutter": rng.uniform(1.5, 3.5), "phase": rng.uniform(0, 6.3),
            })

        self.meteor = additive(art.streak, b, Group(order=13))
        self.meteor.visible = False
        self.meteor_t = -1.0
        self.next_meteor = 4.0
        self.meteor_path = None

        self.vignette = Sprite(art.vignette, batch=b, group=Group(order=14))

    def resize(self, w, h):
        self.w, self.h = w, h
        tex = self.art.sky
        scale = max(w / tex.width, h / tex.height) * 1.08
        self.sky.update(x=w / 2, y=h / 2, scale=scale)
        self.vignette.update(x=w / 2, y=h / 2, scale_x=w * 1.02 / self.art.vignette.width,
                             scale_y=h * 1.02 / self.art.vignette.height)
        self.shafts.update(x=w * 0.5, y=h * 1.02, scale_x=w * 0.9 / self.art.shafts.width,
                           scale_y=h * 1.0 / self.art.shafts.height, rotation=-8)

    def set_pointer(self, x, y):
        if self.w > 1:
            self.tx = (x / self.w) * 2 - 1
            self.ty = (y / self.h) * 2 - 1

    def _tile(self, sprites, offset, y, scale_y, shift):
        """Lays two copies of a seamless texture side by side, scrolled by `offset`."""
        w = self.w * 1.1
        tex_w = sprites[0].image.width
        x0 = -((offset % 1.0) * w) - self.w * 0.05 - shift
        for i, s in enumerate(sprites):
            s.update(x=x0 + i * w, y=y, scale_x=w / tex_w, scale_y=scale_y)

    def update(self, dt, t):
        w, h = self.w, self.h
        ease = min(1.0, dt * 2.0)
        self.px += (self.tx - self.px) * ease
        self.py += (self.ty - self.py) * ease

        self.sky.update(x=w / 2 - self.px * 6, y=h / 2 - self.py * 4)
        gw = self.art.glow.width
        for star in self.stars:
            twinkle = 0.55 + 0.45 * math.sin(t * star["speed"] + star["phase"])
            star["sprite"].update(x=star["u"] * w - self.px * 4, y=star["v"] * h - self.py * 3,
                                  scale=star["size"] / gw)
            star["sprite"].opacity = int(star["base"] * twinkle)

        for a in self.auroras:
            a["offset"] += a["speed"] * dt
            breathe = 0.6 + 0.4 * math.sin(t * 0.21 + a["phase"])
            wave = 1 + 0.12 * math.sin(t * 0.33 + a["phase"])
            tex_h = a["sprites"][0].image.height
            self._tile(a["sprites"], a["offset"], h * a["base"] - self.py * 8,
                       h * a["height"] * wave / tex_h, self.px * 10)
            for s in a["sprites"]:
                s.opacity = int(200 * breathe)

        self.shafts.opacity = int(26 + 12 * math.sin(t * 0.17))
        gs = self.art.soft_glow.width
        self.dusk.update(x=w * 0.6 - self.px * 8, y=h * 0.30 - self.py * 4,
                         scale_x=w * 1.9 / gs, scale_y=h * 0.55 / gs)
        self.dusk.opacity = int(64 + 10 * math.sin(t * 0.11))
        self.shafts.x = w * 0.5 + math.sin(t * 0.05) * w * 0.03 - self.px * 12

        for layer in self.ranges:
            layer["offset"] += layer["speed"] * dt
            tex_h = layer["sprites"][0].image.height
            y = h * layer.get("lift", 0) - 4 - self.py * layer["parallax"] * 0.4
            self._tile(layer["sprites"], layer["offset"], y, h * layer["height"] / tex_h,
                       self.px * layer["parallax"])

        sw = self.art.soft_glow.width
        for mote in self.motes:
            mote["v"] += mote["rise"] * dt
            if mote["v"] > 1.12:
                mote["v"], mote["u"] = -0.12, random.random()
            x = (mote["u"] + math.sin(t * 0.3 + mote["phase"]) * mote["sway"]) * w - self.px * 18
            breath = 0.6 + 0.4 * math.sin(t * 0.7 + mote["phase"])
            mote["sprite"].update(x=x, y=mote["v"] * h - self.py * 10, scale=mote["size"] / sw)
            mote["sprite"].opacity = int(mote["base"] * breath)

        gw, hw = self.art.glow.width, self.art.soft_glow.width
        for fly in self.fireflies:
            fly["u"] = (fly["u"] + fly["du"] * dt + math.sin(t * 0.7 + fly["wobble"]) * 0.0006) % 1.0
            fly["v"] = min(0.44, max(0.04, fly["v"] + fly["dv"] * dt + math.cos(t * 0.9 + fly["wobble"]) * 0.0004))
            # A firefly's flash: a quick swell, a slower fade, then dark for a while.
            phase = ((t + fly["phase"]) % fly["period"]) / fly["period"]
            flash = math.sin(phase / 0.22 * math.pi) ** 2 if phase < 0.22 else 0.0
            x, y = fly["u"] * w - self.px * 22, fly["v"] * h - self.py * 10
            fly["core"].update(x=x, y=y, scale=7 / gw)
            fly["halo"].update(x=x, y=y, scale=52 / hw)
            fly["core"].opacity = int(30 + 225 * flash)
            fly["halo"].opacity = int(120 * flash)

        pw = self.art.petal.width
        for p in self.petals:
            p["v"] -= p["fall"] * dt
            p["u"] += p["drift"] * dt * (0.6 + 0.4 * math.sin(t * 0.4 + p["phase"]))
            if p["v"] < -0.06 or p["u"] > 1.06:
                p["v"], p["u"] = 1.06, random.uniform(-0.2, 1.0)
            p["angle"] += p["spin"] * dt
            tumble = math.sin(t * p["flutter"] + p["phase"])
            size = (9 + 13 * p["depth"]) / pw
            sway = math.sin(t * 0.9 + p["phase"]) * 0.012
            p["sprite"].update(x=(p["u"] + sway) * w - self.px * 30 * p["depth"],
                               y=p["v"] * h - self.py * 14 * p["depth"],
                               rotation=p["angle"], scale_x=size * (0.25 + 0.75 * abs(tumble)), scale_y=size)
            p["sprite"].opacity = int(110 + 120 * p["depth"])

        self._update_meteor(dt)

    def _update_meteor(self, dt):
        if self.meteor_t < 0:
            self.next_meteor -= dt
            if self.next_meteor <= 0:
                angle = math.radians(random.uniform(200, 225))
                start = (random.uniform(0.35, 1.0) * self.w, random.uniform(0.7, 0.95) * self.h)
                self.meteor_path = (start, angle, random.uniform(0.25, 0.45) * self.w)
                self.meteor_t = 0.0
                self.meteor.visible = True
            return
        self.meteor_t += dt / 1.1
        p = self.meteor_t
        (sx, sy), angle, length = self.meteor_path
        travel = length * p
        self.meteor.update(x=sx + math.cos(angle) * travel, y=sy + math.sin(angle) * travel,
                           rotation=-math.degrees(angle), scale_x=0.6 + 0.6 * math.sin(math.pi * min(p, 1)),
                           scale_y=0.7)
        self.meteor.opacity = int(230 * math.sin(math.pi * min(p, 1)))
        if p >= 1:
            self.meteor.visible = False
            self.meteor_t = -1.0
            self.next_meteor = random.uniform(7, 16)

    def draw(self):
        self.batch.draw()
