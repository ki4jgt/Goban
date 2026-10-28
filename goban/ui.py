"""Small retained-mode widgets drawn with pyglet shapes and labels."""

import math

import pyglet
from pyglet import shapes
from pyglet.graphics import Group

# pyglet uses the first installed family in each list (Linux, then Windows, then macOS picks).
SERIF = ["EB Garamond", "Cormorant Garamond", "Georgia", "Palatino Linotype", "Palatino",
         "Book Antiqua", "DejaVu Serif", "Liberation Serif", "Times New Roman"]
SANS = ["Inter", "Noto Sans", "Segoe UI", "Helvetica Neue", "Ubuntu", "DejaVu Sans",
        "Liberation Sans", "Arial"]

GOLD = (233, 197, 122)
TEXT = (234, 230, 220)
MUTED = (150, 152, 170)
PANEL = (12, 16, 28, 150)
# pyglet does not fall back per glyph, so names in other scripts need a font that has them.
# Korean needs a Hangul-capable family first; Yu Gothic, for example, has no Hangul.
CJK_FONTS = {
    "korean": ["Noto Sans CJK KR", "Malgun Gothic", "Apple SD Gothic Neo", "AppleGothic", "Noto Sans CJK JP"],
    "sans": ["Noto Sans CJK JP", "Noto Sans CJK SC", "Yu Gothic UI", "Yu Gothic", "Meiryo",
             "Microsoft YaHei", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "PingFang SC", "Malgun Gothic"],
    "serif": ["Noto Serif CJK JP", "Noto Serif CJK SC", "Yu Mincho", "MS Mincho", "Hiragino Mincho ProN",
              "Songti SC", "SimSun", "Noto Sans CJK JP", "Yu Gothic", "Hiragino Sans"],
}
PANEL_EDGE = (233, 197, 122, 46)


def label(text, x, y, size, batch, group, color=TEXT, font=SANS, anchor_x="left",
          anchor_y="baseline", bold=False, width=None, multiline=False, alpha=255):
    lbl = pyglet.text.Label(
        "", font_name=font, font_size=size, x=x, y=y, batch=batch, group=group,
        color=(*color[:3], alpha), anchor_x=anchor_x, anchor_y=anchor_y, bold=bold,
        width=width, multiline=multiline,
    )
    lbl.base_font = font
    set_text(lbl, text)
    return lbl


def _script(text):
    """Returns 'korean', 'cjk' or None for text that the Latin UI fonts cannot show."""
    found = None
    for ch in text:
        code = ord(ch)
        if 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F or 0xAC00 <= code <= 0xD7AF:
            return "korean"
        if code >= 0x2E80 and not 0xFE00 <= code <= 0xFE0F:
            found = "cjk"
    return found


def set_text(lbl, text):
    """Sets label text, switching to a CJK-capable font only when the text needs one
    (pyglet does not fall back per glyph, so names like 柯洁 would otherwise be boxes)."""
    base = getattr(lbl, "base_font", SANS)
    font = base
    script = _script(text)
    if script == "korean":
        font = CJK_FONTS["korean"]
    elif script == "cjk":
        font = CJK_FONTS["serif" if base is SERIF else "sans"]
    if lbl.font_name != font:
        lbl.font_name = font
    if lbl.text != text:
        lbl.text = text


def groups(base):
    return Group(order=base), Group(order=base + 1), Group(order=base + 2)


class Panel:
    """A frosted, softly-bordered card."""

    def __init__(self, batch, base_order, radius=14):
        g0, g1, _ = groups(base_order)
        self.radius = radius
        self.edge = shapes.RoundedRectangle(0, 0, 10, 10, radius, color=PANEL_EDGE, batch=batch, group=g0)
        self.fill = shapes.RoundedRectangle(0, 0, 10, 10, radius - 1, color=PANEL, batch=batch, group=g1)

    def set_rect(self, x, y, w, h):
        self.edge.position = (x - 1, y - 1)
        self.edge.width, self.edge.height = w + 2, h + 2
        self.fill.position = (x, y)
        self.fill.width, self.fill.height = w, h

    def set_edge(self, color):
        self.edge.color = color

    @property
    def visible(self):
        return self.fill.visible

    @visible.setter
    def visible(self, value):
        self.fill.visible = self.edge.visible = value

    def delete(self):
        self.edge.delete()
        self.fill.delete()


class Button:
    STYLES = {
        "normal": ((32, 38, 56, 215), (48, 56, 80, 235), (233, 197, 122, 60), TEXT),
        "primary": ((150, 112, 52, 235), (182, 138, 66, 245), (255, 222, 150, 150), (255, 248, 232)),
        "danger": ((92, 34, 38, 225), (128, 46, 50, 240), (230, 120, 110, 110), (255, 232, 228)),
        "ghost": ((0, 0, 0, 0), (255, 255, 255, 22), (0, 0, 0, 0), MUTED),
    }

    def __init__(self, text, callback, batch, base_order, style="normal", font_size=12):
        g0, g1, g2 = groups(base_order)
        self.callback = callback
        self.style = style
        self.enabled = True
        self.selected = False
        self.hover = False
        self._visible = True
        self.x = self.y = 0
        self.w, self.h = 120, 36
        self.edge = shapes.RoundedRectangle(0, 0, 10, 10, 9, batch=batch, group=g0)
        self.fill = shapes.RoundedRectangle(0, 0, 10, 10, 8, batch=batch, group=g1)
        self.text = label(text, 0, 0, font_size, batch, g2, anchor_x="center", anchor_y="center")
        self._refresh()

    def set_rect(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.edge.position = (x - 1, y - 1)
        self.edge.width, self.edge.height = w + 2, h + 2
        self.fill.position = (x, y)
        self.fill.width, self.fill.height = w, h
        r = min(9, h / 2)
        self.edge.radius, self.fill.radius = r + 1, r
        self.text.position = (x + w / 2, y + h / 2 + 1, 0)

    def set_text(self, text):
        if self.text.text != text:
            self.text.text = text

    def _refresh(self):
        base, hover, edge, text_color = self.STYLES[self.style]
        if self.selected:
            base, edge, text_color = (120, 92, 46, 230), (255, 222, 150, 170), (255, 246, 226)
        fill = hover if (self.hover and self.enabled) else base
        alpha_scale = 1.0 if self.enabled else 0.45
        self.fill.color = (*fill[:3], int(fill[3] * alpha_scale))
        self.edge.color = (*edge[:3], int(edge[3] * alpha_scale))
        self.text.color = (*text_color[:3], int(255 * (1.0 if self.enabled else 0.5)))

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        self._visible = value
        self.edge.visible = self.fill.visible = self.text.visible = value

    def contains(self, x, y):
        return self._visible and self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    def on_mouse_motion(self, x, y):
        hover = self.contains(x, y)
        if hover != self.hover:
            self.hover = hover
            self._refresh()

    def on_mouse_press(self, x, y):
        if self.contains(x, y) and self.enabled:
            self.callback()
            return True
        return False

    def set_enabled(self, enabled):
        if enabled != self.enabled:
            self.enabled = enabled
            self._refresh()

    def set_selected(self, selected):
        if selected != self.selected:
            self.selected = selected
            self._refresh()

    def set_style(self, style):
        if style != self.style:
            self.style = style
            self._refresh()

    def delete(self):
        self.edge.delete()
        self.fill.delete()
        self.text.delete()


class TextField:
    def __init__(self, placeholder, batch, base_order, password=False, on_submit=None, max_length=80,
                 font_size=13):
        g0, g1, g2 = groups(base_order)
        self.placeholder = placeholder
        self.password = password
        self.max_length = max_length
        self.on_submit = on_submit
        self.value = ""
        self.focused = False
        self.x = self.y = 0
        self.w, self.h = 200, 40
        self.edge = shapes.RoundedRectangle(0, 0, 10, 10, 9, color=(233, 197, 122, 50), batch=batch, group=g0)
        self.fill = shapes.RoundedRectangle(0, 0, 10, 10, 8, color=(8, 10, 18, 230), batch=batch, group=g1)
        self.text = label("", 0, 0, font_size, batch, g2, anchor_y="center")
        self.caret = shapes.Rectangle(0, 0, 2, font_size + 7, color=GOLD, batch=batch, group=g2)
        self._render()

    def set_rect(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.edge.position = (x - 1, y - 1)
        self.edge.width, self.edge.height = w + 2, h + 2
        self.fill.position = (x, y)
        self.fill.width, self.fill.height = w, h
        self.text.position = (x + 14, y + h / 2, 0)
        self._render()

    def _render(self):
        shown = ("•" * len(self.value)) if self.password else self.value
        if shown:
            # Long input scrolls: keep the end (where you are typing) in view.
            room = self.w - 30
            start = 0
            set_text(self.text, shown)
            while self.text.content_width > room and start < len(shown) - 1:
                start += max(1, (len(shown) - start) // 8)
                set_text(self.text, "…" + shown[start:])
            self.text.color = (*TEXT, 255)
        else:
            set_text(self.text, self.placeholder)
            self.text.color = (*MUTED, 150)
        self.edge.color = (233, 197, 122, 150 if self.focused else 50)
        caret_x = self.x + 14 + (self.text.content_width if shown else 0) + 1
        self.caret.position = (caret_x, self.y + (self.h - self.caret.height) / 2)

    def clear(self):
        self.value = ""
        self._render()

    def update(self, t):
        self.caret.visible = self.focused and (t * 1.6) % 1 < 0.6

    def set_focus(self, focused):
        self.focused = focused
        self._render()

    def contains(self, x, y):
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    def on_text(self, text):
        if not self.focused:
            return
        text = "".join(ch for ch in text if ch.isprintable() and ch not in "\r\n\t")
        if text and len(self.value) < self.max_length:
            self.value = (self.value + text)[: self.max_length]
            self._render()

    def on_text_motion(self, motion):
        if self.focused and motion == pyglet.window.key.MOTION_BACKSPACE and self.value:
            self.value = self.value[:-1]
            self._render()

    def set_visible(self, visible):
        for part in (self.edge, self.fill, self.text):
            part.visible = visible
        if not visible:
            self.caret.visible = False

    def delete(self):
        for part in (self.edge, self.fill, self.text, self.caret):
            part.delete()


class ListView:
    """A scrolling list of two-line rows. Items are dicts with 'title', 'detail', 'value'."""

    def __init__(self, batch, base_order, on_pick, row_height=52, empty_text=""):
        self.batch = batch
        self.g0, self.g1, self.g2 = groups(base_order)
        self.on_pick = on_pick
        self.row_height = row_height
        self.items = []
        self.offset = 0
        self.hover = -1
        self.x = self.y = 0
        self.w = self.h = 10
        self.rows = []
        self.empty = label(empty_text, 0, 0, 11, batch, self.g2, color=MUTED, anchor_x="center")

    def set_rect(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
        count = max(0, int(h // self.row_height))
        while len(self.rows) < count:
            bg = shapes.RoundedRectangle(0, 0, 10, 10, 8, color=(255, 255, 255, 0), batch=self.batch, group=self.g1)
            title = label("", 0, 0, 12, self.batch, self.g2)
            detail = label("", 0, 0, 10, self.batch, self.g2, color=MUTED)
            self.rows.append((bg, title, detail))
        while len(self.rows) > count:
            for part in self.rows.pop():
                part.delete()
        self.empty.position = (x + w / 2, y + h - 40, 0)
        self._render()

    def set_items(self, items):
        self.items = items
        self.offset = max(0, min(self.offset, len(items) - len(self.rows)))
        self._render()

    def _render(self):
        top = self.y + self.h
        for i, (bg, title, detail) in enumerate(self.rows):
            index = self.offset + i
            ry = top - (i + 1) * self.row_height
            bg.position = (self.x, ry + 3)
            bg.width, bg.height = self.w, self.row_height - 6
            if index < len(self.items):
                item = self.items[index]
                title.text = fit_text(item["title"], title, self.w - 28)
                detail.text = fit_text(item.get("detail", ""), detail, self.w - 28)
                title.position = (self.x + 14, ry + self.row_height * 0.55, 0)
                detail.position = (self.x + 14, ry + self.row_height * 0.22, 0)
                bg.color = (233, 197, 122, 34) if index == self.hover else (255, 255, 255, 10)
                title.visible = detail.visible = bg.visible = True
            else:
                title.visible = detail.visible = bg.visible = False
        self.empty.visible = not self.items

    def contains(self, x, y):
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    def _index_at(self, x, y):
        if not self.contains(x, y):
            return -1
        i = int((self.y + self.h - y) // self.row_height)
        index = self.offset + i
        return index if i < len(self.rows) and index < len(self.items) else -1

    def on_mouse_motion(self, x, y):
        hover = self._index_at(x, y)
        if hover != self.hover:
            self.hover = hover
            self._render()

    def on_mouse_press(self, x, y):
        index = self._index_at(x, y)
        if index >= 0:
            self.on_pick(self.items[index]["value"])
            return True
        return False

    def on_mouse_scroll(self, x, y, scroll_y):
        if self.contains(x, y) and scroll_y:
            limit = max(0, len(self.items) - len(self.rows))
            self.offset = max(0, min(limit, self.offset - int(math.copysign(1, scroll_y))))
            self.hover = self._index_at(x, y)
            self._render()


class ChatLog:
    """A word-wrapped, scrollable message log, newest at the bottom.

    Each entry is a small document label with the speaker's name coloured; only the
    entries that fit are laid out, so there is no GL clipping (which misbehaves on
    high-DPI displays)."""

    LIMIT = 400

    def __init__(self, batch, base_order, empty_text="", font_size=11):
        self.batch = batch
        self.group = Group(order=base_order)
        self.font_size = font_size
        self.entries = []
        self.labels = []
        self.scroll = 0  # entries hidden below the bottom edge
        self.x = self.y = 0
        self.w = self.h = 10
        self.empty = label(empty_text, 0, 0, 10, batch, self.group, color=MUTED, anchor_x="center",
                           anchor_y="center")
        self.more = label("", 0, 0, 9, batch, self.group, color=GOLD, anchor_x="right")

    def set_rect(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, max(40, w), max(0, h)
        self.empty.position = (x + w / 2, y + h / 2, 0)
        self._render()

    def set_empty_text(self, text):
        self.empty.text = text

    def add(self, name, text, name_color=GOLD, text_color=TEXT, render=True):
        self.entries.append((name, text, name_color, text_color))
        if len(self.entries) > self.LIMIT:
            del self.entries[: len(self.entries) - self.LIMIT]
        if self.scroll:
            self.scroll += 1  # keep the reader's place while they look back
        if render:
            self._render()

    def set_entries(self, entries):
        self.entries = list(entries)[-self.LIMIT:]
        self.scroll = min(self.scroll, max(0, len(self.entries) - 1))
        self._render()

    def _make_label(self, name, text, name_color, text_color):
        head = f"{name}  " if name else ""
        # Keep one very long message from crowding out the whole log.
        lines = text.split("\n")
        if len(lines) > 8:
            text = "\n".join(lines[:8]) + " …"
        if len(text) > 700:
            text = text[:700] + "…"
        text = breakable(text)
        doc = pyglet.text.document.FormattedDocument(head + text)
        script = _script(head + text)
        font = CJK_FONTS["korean"] if script == "korean" else CJK_FONTS["sans"] if script else SANS
        doc.set_style(0, len(doc.text), {"font_name": font, "font_size": self.font_size,
                                         "color": (*text_color[:3], 235)})
        if head:
            doc.set_style(0, len(head), {"color": (*name_color[:3], 255), "bold": True})
        return pyglet.text.DocumentLabel(doc, width=int(self.w), multiline=True, batch=self.batch,
                                         group=self.group, anchor_y="bottom")

    def _render(self):
        for lbl in self.labels:
            lbl.delete()
        self.labels = []
        y = self.y
        top = self.y + self.h
        index = len(self.entries) - 1 - self.scroll
        while index >= 0:
            lbl = self._make_label(*self.entries[index])
            height = lbl.content_height
            if y + height > top:
                lbl.delete()
                break
            lbl.position = (self.x, y, 0)
            self.labels.append(lbl)
            y += height + 5
            index -= 1
        self.empty.visible = not self.entries
        self.more.text = f"{self.scroll} newer ↓" if self.scroll else ""
        self.more.position = (self.x + self.w, self.y - 12, 0)

    def contains(self, x, y):
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    def on_mouse_scroll(self, x, y, scroll_y):
        if self.contains(x, y) and scroll_y:
            step = 2 if scroll_y > 0 else -2
            self.scroll = max(0, min(len(self.entries) - 1, self.scroll + step))
            self._render()


def breakable(text, every=20):
    """Lets pyglet wrap very long words (URLs) by adding invisible zero-width spaces."""
    words = []
    for word in text.split(" "):
        if len(word) > every + 4:
            word = "\u200b".join(word[i:i + every] for i in range(0, len(word), every))
        words.append(word)
    return " ".join(words)


def fit_text(text, lbl, max_width):
    """Truncates text with an ellipsis so the label fits max_width."""
    set_text(lbl, text)
    if lbl.content_width <= max_width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        set_text(lbl, text[:mid] + "…")
        if lbl.content_width <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"
