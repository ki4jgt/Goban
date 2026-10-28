"""Renders a goban and its stones into a rectangle, with placement and capture effects."""

import math
import random

from pyglet import shapes
from pyglet.gl import GL_ONE, GL_SRC_ALPHA
from pyglet.graphics import Group
from pyglet.sprite import Sprite

from .game import BLACK, COLUMN_LETTERS, EMPTY, WHITE
from .ui import SANS, label

SMALL_TEX = 128
THICKNESS = 0.42  # visible board edge, in cells


def hoshi_points(cols, rows):
    if cols != rows:
        return []
    if cols == 19:
        return [(x, y) for x in (3, 9, 15) for y in (3, 9, 15)]
    if cols == 13:
        return [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)]
    if cols == 9:
        return [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)]
    if cols % 2 == 1 and cols >= 7:
        return [(cols // 2, cols // 2)]
    return []


def ease_out(t):
    return 1 - (1 - t) ** 3


LANDING = 0.62


def drop_height(p):
    """Height above the board for drop progress p: a fall, then one small bounce."""
    if p < LANDING:
        return (1 - p / LANDING) ** 2
    return 0.07 * math.sin((p - LANDING) / (1 - LANDING) * math.pi)


def additive(texture, batch, group):
    return Sprite(texture, blend_src=GL_SRC_ALPHA, blend_dest=GL_ONE, batch=batch, group=group)


class StoneSprite:
    def __init__(self, view, x, y, color, animate):
        self.x, self.y, self.color = x, y, color
        self.shadow = Sprite(view.art.shadow, batch=view.batch, group=view.g_shadow)
        self.contact = Sprite(view.art.contact, batch=view.batch, group=view.g_shadow)
        self.stone = Sprite(view.art.stone(color == WHITE, x, y), batch=view.batch, group=view.g_stone)
        h = (x * 73856093) ^ (y * 19349663)
        self.jx = ((h % 997) / 997 - 0.5) * 0.045
        self.jy = (((h // 997) % 991) / 991 - 0.5) * 0.045
        self.drop = 0.0 if animate else 1.0
        self.landed = not animate
        self.alpha = 255.0
        self.alpha_target = 255.0

    def layout(self, view):
        cx, cy = view.screen(self.x, self.y)
        cell = view.cell
        lift = drop_height(self.drop)
        sx, sy = cx + self.jx * cell, cy + self.jy * cell
        self.stone.update(x=sx, y=sy + lift * cell * 0.3, scale=cell * 0.965 / self.stone.image.width * (1 + 0.28 * lift))
        self.shadow.update(
            x=sx + cell * (0.08 + 0.2 * lift),
            y=sy - cell * (0.10 + 0.24 * lift),
            scale=cell * 1.3 / SMALL_TEX * (1 + 0.4 * lift),
        )
        self.contact.update(x=sx + cell * 0.025, y=sy - cell * 0.035, scale=cell * 1.0 / SMALL_TEX)
        visible = min(1.0, self.drop * 4)
        self.stone.opacity = int(self.alpha * visible)
        self.shadow.opacity = int(self.alpha * visible * (0.9 - 0.5 * min(1, lift)))
        self.contact.opacity = int(self.alpha * max(0.0, 1 - lift * 6) * 0.9)

    def update(self, dt, view):
        changed = False
        if self.drop < 1:
            self.drop = min(1.0, self.drop + dt / 0.36)
            changed = True
            if not self.landed and self.drop >= LANDING:
                self.landed = True
                view.dust(self)
        if abs(self.alpha - self.alpha_target) > 0.5:
            self.alpha += (self.alpha_target - self.alpha) * min(1, dt * 8)
            changed = True
        if changed:
            self.layout(view)

    def delete(self):
        self.stone.delete()
        self.shadow.delete()
        self.contact.delete()


class Effect:
    """A short-lived sprite animation driven by a per-frame function."""

    def __init__(self, sprite, duration, step, extra=None):
        self.sprite, self.duration, self.step, self.extra = sprite, duration, step, extra
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        p = min(1.0, self.t / self.duration)
        self.step(self, p)
        if p >= 1.0:
            self.sprite.delete()
            if self.extra is not None:
                self.extra.delete()
            return False
        return True


class BoardView:
    def __init__(self, art, batch, base_order=10, show_coords=True):
        self.art = art
        self.batch = batch
        self.show_coords = show_coords
        o = base_order
        self.g_shadow_board = Group(order=o)
        self.g_halo = Group(order=o + 1)
        self.g_side = Group(order=o + 2)
        self.g_side_shade = Group(order=o + 3)
        self.g_board = Group(order=o + 4)
        self.g_sheen = Group(order=o + 5)
        self.g_lines = Group(order=o + 6)
        self.g_shadow = Group(order=o + 7)
        self.g_stone = Group(order=o + 8)
        self.g_mark = Group(order=o + 9)
        self.g_fx = Group(order=o + 10)

        self.cols = self.rows = 19
        self.cell = 20
        self.ox = self.oy = 0
        self.rect = (0, 0, 100, 100)
        self.state = None
        self.stones = {}
        self.effects = []
        self.static = []
        self.removed = set()
        self.removal_mode = False
        self.last = None

        self.halo = additive(art.soft_glow, batch, self.g_halo)
        self.halo.color = (255, 196, 128)
        self.board_shadow = Sprite(art.board_shadow, batch=batch, group=self.g_shadow_board)
        self.side = Sprite(art.wood, batch=batch, group=self.g_side)
        self.side.color = (118, 80, 44)
        self.side_shade = Sprite(art.side_shade, batch=batch, group=self.g_side_shade)
        self.top = Sprite(art.wood, batch=batch, group=self.g_board)
        # A warm lamp pooled over the board and a lacquer sheen that follows the pointer.
        self.lamp = additive(art.soft_glow, batch, self.g_sheen)
        self.lamp.color = (255, 214, 160)
        self.sheen = additive(art.soft_glow, batch, self.g_sheen)
        self.sheen.color = (255, 246, 228)
        self.edges = []
        self.pointer = (0.0, 0.0)
        self.ghost_glow = additive(art.soft_glow, batch, self.g_shadow)
        self.ghost_glow.color = (255, 214, 150)
        self.ghost_glow.visible = False
        self.marker_glow = additive(art.glow, batch, self.g_mark)
        self.marker_glow.color = (255, 200, 120)
        self.marker_glow.visible = False
        self.marker = Sprite(art.marker, batch=batch, group=self.g_mark)
        self.marker.visible = False
        self.ghost = Sprite(art.black_stones[0], batch=batch, group=self.g_mark)
        self.ghost.visible = False
        self.ghost_at = None

    # ---------------------------------------------------------------- geometry
    def set_rect(self, x, y, w, h):
        self.rect = (x, y, w, h)
        self._layout()

    def _layout(self):
        x, y, w, h = self.rect
        border = 0.98 if self.show_coords else 0.62
        across = self.cols - 1 + 2 * border
        down = self.rows - 1 + 2 * border
        self.cell = max(4.0, min(w / across, h / (down + THICKNESS)))
        bw, bh = self.cell * across, self.cell * down
        thick = min(self.cell * THICKNESS, 22)
        bx = x + (w - bw) / 2
        by = y + (h - bh - thick) / 2 + thick
        self.ox = bx + border * self.cell
        self.oy = by + border * self.cell
        cx, cy = bx + bw / 2, by + bh / 2

        tex = self.art.wood.width
        self.top.update(x=cx, y=cy, scale_x=bw / tex, scale_y=bh / tex)
        self.side.update(x=cx, y=cy - thick, scale_x=bw / tex, scale_y=bh / tex)
        self.side_shade.update(x=cx, y=by - thick / 2, scale_x=bw / self.art.side_shade.width,
                               scale_y=thick / self.art.side_shade.height)
        gs = self.art.soft_glow.width
        self.lamp.update(x=cx - bw * 0.08, y=cy + bh * 0.1, scale_x=bw * 1.5 / gs, scale_y=bh * 1.5 / gs)
        self.board_box = (bx, by, bw, bh)
        self._place_sheen()
        for edge in self.edges:
            edge.delete()
        self.edges = [
            # bevel: lit top and left edges, a dark seam where the top meets the side
            shapes.Line(bx, by + bh - 0.5, bx + bw, by + bh - 0.5, width=1.5, color=(255, 236, 200, 120),
                        batch=self.batch, group=self.g_sheen),
            shapes.Line(bx + 0.5, by, bx + 0.5, by + bh, width=1.2, color=(255, 230, 190, 70),
                        batch=self.batch, group=self.g_sheen),
            shapes.Line(bx, by, bx + bw, by, width=1.5, color=(50, 28, 10, 200),
                        batch=self.batch, group=self.g_sheen),
            shapes.Line(bx, by - 1.5, bx + bw, by - 1.5, width=1.0, color=(255, 210, 160, 50),
                        batch=self.batch, group=self.g_side_shade),
        ]
        bs = self.art.board_shadow.width
        self.board_shadow.update(x=cx + self.cell * 0.4, y=cy - thick - self.cell * 0.5,
                                 scale_x=bw * 1.5 / bs, scale_y=bh * 1.5 / bs)
        self.board_shadow.opacity = 235
        hs = self.art.soft_glow.width
        self.halo.update(x=cx, y=cy, scale_x=bw * 2.4 / hs, scale_y=bh * 2.4 / hs)

        self._build_static()
        for stone in self.stones.values():
            stone.layout(self)
        self._place_marker()
        if self.ghost_at:
            self.set_ghost(*self.ghost_at)

    def _build_static(self):
        for item in self.static:
            item.delete()
        self.static = []
        cell, cols, rows = self.cell, self.cols, self.rows
        ink = (34, 22, 10, 225)
        width = max(1.0, cell * 0.032)
        x0, x1 = self.ox, self.ox + (cols - 1) * cell
        y0, y1 = self.oy, self.oy + (rows - 1) * cell
        for i in range(cols):
            w = width * (1.9 if i in (0, cols - 1) else 1)
            px = self.ox + i * cell
            self.static.append(shapes.Line(px, y0, px, y1, width=w,
                                           color=ink, batch=self.batch, group=self.g_lines))
        for j in range(rows):
            w = width * (1.9 if j in (0, rows - 1) else 1)
            py = self.oy + j * cell
            self.static.append(shapes.Line(x0 - width * 0.95, py, x1 + width * 0.95, py, width=w,
                                           color=ink, batch=self.batch, group=self.g_lines))
        for hx, hy in hoshi_points(cols, rows):
            sx, sy = self.screen(hx, hy)
            self.static.append(shapes.Circle(sx, sy, max(2.0, cell * 0.105), color=ink[:3],
                                             batch=self.batch, group=self.g_lines))
        if self.show_coords and cell >= 15:
            size = max(7, min(15, int(cell * 0.30)))
            color = (78, 52, 26)
            gap = min(cell * 0.62, 30)
            for i in range(cols):
                letter = COLUMN_LETTERS[i] if i < len(COLUMN_LETTERS) else str(i + 1)
                sx = self.ox + i * cell
                for sy in (y0 - gap, y1 + gap):
                    self.static.append(label(letter, sx, sy, size, self.batch, self.g_lines, color=color,
                                             font=SANS, anchor_x="center", anchor_y="center", alpha=200))
            for j in range(rows):
                sy = self.oy + j * cell
                for sx in (x0 - gap, x1 + gap):
                    self.static.append(label(str(j + 1), sx, sy, size, self.batch, self.g_lines, color=color,
                                             font=SANS, anchor_x="center", anchor_y="center", alpha=200))

    def set_pointer(self, mx, my):
        self.pointer = (mx, my)
        self._place_sheen()

    def _place_sheen(self):
        bx, by, bw, bh = getattr(self, "board_box", (0, 0, 1, 1))
        cx, cy = bx + bw / 2, by + bh / 2
        # Reflections move against the viewer: shift the sheen opposite the pointer.
        dx = max(-1.0, min(1.0, (self.pointer[0] - cx) / max(bw, 1)))
        dy = max(-1.0, min(1.0, (self.pointer[1] - cy) / max(bh, 1)))
        gs = self.art.soft_glow.width
        self.sheen.update(x=cx - bw * 0.22 - dx * bw * 0.12, y=cy + bh * 0.22 - dy * bh * 0.12,
                          scale_x=bw * 0.9 / gs, scale_y=bh * 0.55 / gs, rotation=-28)

    def screen(self, x, y):
        return self.ox + x * self.cell, self.oy + (self.rows - 1 - y) * self.cell

    def point_at(self, mx, my):
        fx = (mx - self.ox) / self.cell
        fy = (my - self.oy) / self.cell
        ix, iy = round(fx), round(fy)
        if abs(fx - ix) > 0.48 or abs(fy - iy) > 0.48:
            return None
        if 0 <= ix < self.cols and 0 <= iy < self.rows:
            return ix, self.rows - 1 - iy
        return None

    # -------------------------------------------------------------------- state
    def set_state(self, state):
        """Shows a new snapshot without animation (first load or resync)."""
        size_changed = (state.width, state.height) != (self.cols, self.rows)
        self.state = state
        if size_changed:
            for stone in self.stones.values():
                stone.delete()
            self.stones = {}
            self.cols, self.rows = state.width, state.height
            self._layout()
        self.sync(animate=False)

    def sync(self, animate=True):
        """Brings the stone sprites in line with self.state.board."""
        board = self.state.board if self.state else None
        for y in range(self.rows):
            for x in range(self.cols):
                color = board[y][x] if board else EMPTY
                current = self.stones.get((x, y))
                if current and current.color != color:
                    self._remove_stone(current, animate)
                    current = None
                if color != EMPTY and current is None:
                    stone = StoneSprite(self, x, y, color, animate)
                    stone.layout(self)
                    self.stones[(x, y)] = stone
        self.refresh_marks()

    def refresh_marks(self):
        for pos, stone in self.stones.items():
            dead = self.removal_mode and pos in self.removed
            stone.alpha_target = 92.0 if dead else 255.0
        self.last = self.state.last_move if self.state else None
        self._place_marker()

    def _place_marker(self):
        if not self.last or self.last not in self.stones:
            self.marker.visible = self.marker_glow.visible = False
            return
        x, y = self.last
        stone = self.stones[self.last]
        sx, sy = self.screen(x, y)
        self.marker.update(x=sx + stone.jx * self.cell, y=sy + stone.jy * self.cell,
                           scale=self.cell * 0.62 / SMALL_TEX)
        self.marker.color = (238, 236, 230) if stone.color == BLACK else (40, 40, 46)
        self.marker.visible = True
        self.marker_glow.update(x=self.marker.x, y=self.marker.y, scale=self.cell * 0.9 / SMALL_TEX)
        self.marker_glow.visible = stone.color == BLACK

    def set_ghost(self, x, y, color=None):
        self.ghost_at = (x, y, color) if color else None
        if not color:
            self.ghost.visible = self.ghost_glow.visible = False
            return
        tex = self.art.stone(color == WHITE, x, y)
        if self.ghost.image is not tex:
            self.ghost.image = tex
        sx, sy = self.screen(x, y)
        self.ghost.update(x=sx, y=sy, scale=self.cell * 0.965 / tex.width)
        self.ghost.opacity = 120
        self.ghost.visible = True
        self.ghost_glow.update(x=sx, y=sy, scale=self.cell * 2.2 / self.art.soft_glow.width)
        self.ghost_glow.visible = True

    # ------------------------------------------------------------------ effects
    def _remove_stone(self, stone, animate):
        self.stones.pop((stone.x, stone.y), None)
        if not animate:
            stone.delete()
            return
        stone.contact.delete()
        sx, sy = stone.stone.x, stone.stone.y
        base = stone.stone.scale
        cell = self.cell

        def fade(effect, p):
            e = ease_out(p)
            effect.sprite.opacity = int(255 * (1 - e))
            effect.sprite.update(y=sy + cell * 0.35 * e, scale=base * (1 + 0.18 * e))
            effect.extra.opacity = int(200 * (1 - e) ** 2)

        self.effects.append(Effect(stone.stone, 0.65, fade, stone.shadow))
        glow = (255, 230, 190) if stone.color == WHITE else (170, 200, 255)
        for _ in range(7):
            spark = additive(self.art.glow, self.batch, self.g_fx)
            spark.color = glow
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(0.6, 1.6) * cell
            size = random.uniform(0.12, 0.3) * cell / SMALL_TEX

            def drift(effect, p, angle=angle, speed=speed, size=size):
                e = ease_out(p)
                effect.sprite.update(x=sx + math.cos(angle) * speed * e,
                                     y=sy + math.sin(angle) * speed * e + cell * 0.6 * p,
                                     scale=size * (1 - 0.6 * p))
                effect.sprite.opacity = int(230 * (1 - p))

            effect = Effect(spark, random.uniform(0.7, 1.1), drift)
            drift(effect, 0)
            self.effects.append(effect)

    def dust(self, stone):
        """A soft puff where a stone meets the wood."""
        sx, sy = stone.stone.x, stone.stone.y
        cell = self.cell
        for i in range(10):
            mote = Sprite(self.art.soft_glow, batch=self.batch, group=self.g_shadow)
            mote.color = (255, 236, 205)
            angle = i / 10 * 2 * math.pi + random.uniform(-0.2, 0.2)
            reach = random.uniform(0.45, 0.8) * cell
            size = random.uniform(0.25, 0.45) * cell / self.art.soft_glow.width

            def puff(effect, p, angle=angle, reach=reach, size=size):
                e = ease_out(p)
                r = cell * 0.4 + reach * e
                effect.sprite.update(x=sx + math.cos(angle) * r, y=sy + math.sin(angle) * r * 0.8,
                                     scale=size * (1 + 1.5 * e))
                effect.sprite.opacity = int(60 * (1 - p) ** 2)

            effect = Effect(mote, random.uniform(0.5, 0.8), puff)
            puff(effect, 0)
            self.effects.append(effect)
        self._ripple(stone.x, stone.y, stone.color)

    def _ripple(self, x, y, color):
        sx, sy = self.screen(x, y)
        ring = additive(self.art.ring, self.batch, self.g_fx)
        ring.color = (255, 214, 150) if color == BLACK else (190, 220, 255)
        cell = self.cell

        def grow(effect, p):
            e = ease_out(p)
            effect.sprite.update(x=sx, y=sy, scale=cell * (0.9 + 1.8 * e) / SMALL_TEX)
            effect.sprite.opacity = int(170 * (1 - p) ** 1.5)

        effect = Effect(ring, 0.9, grow)
        grow(effect, 0)
        self.effects.append(effect)

    def update(self, dt, t):
        for stone in self.stones.values():
            stone.update(dt, self)
        self.effects = [e for e in self.effects if e.update(dt)]
        if self.marker.visible:
            self.marker.opacity = int(175 + 80 * math.sin(t * 3.2))
        self.halo.opacity = int(34 + 12 * math.sin(t * 0.5))
        self.lamp.opacity = int(26 + 6 * math.sin(t * 0.37))
        self.sheen.opacity = 20
        if self.marker_glow.visible:
            self.marker_glow.opacity = int(40 + 30 * math.sin(t * 3.2))
        if self.ghost_glow.visible:
            self.ghost_glow.opacity = int(36 + 14 * math.sin(t * 4.0))
