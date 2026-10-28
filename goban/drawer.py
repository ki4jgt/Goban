"""The messages drawer (alerts, lobby chat, private messages) and pop-up toasts."""

import time

import pyglet
from pyglet import shapes
from pyglet.graphics import Group
from pyglet.window import key

from .messaging import CHANNELS, chat_name, describe
from .ui import GOLD, MUTED, SERIF, TEXT, Button, ChatLog, ListView, Panel, TextField, fit_text, label, set_text

DRAWER_WIDTH = 400
TOAST_WIDTH = 340
TOAST_HEIGHT = 74
TOAST_SECONDS = 7.0
ME_COLOR = (150, 205, 255)


def _ago(stamp):
    seconds = max(0, time.time() - (stamp or 0))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


class Drawer:
    def __init__(self, app):
        self.app = app
        self.model = app.messaging
        self.is_open = False
        self.view = "alerts"
        self.selected = None  # notification id with accept/decline showing
        self.x = self.y = 0
        self.w = DRAWER_WIDTH
        self.h = 100

        # chrome shared by every tab
        self.batch = pyglet.graphics.Batch()
        b = self.batch
        self.panel = Panel(b, 0, radius=16)
        self.panel.fill.color = (11, 14, 25, 252)
        self.title = label("Messages", 0, 0, 18, b, Group(order=3), color=GOLD, font=SERIF)
        self.close_btn = Button("×", self.close, b, 2, style="ghost", font_size=16)
        self.tabs = {
            "alerts": Button("Alerts", lambda: self.show("alerts"), b, 2, font_size=11),
            "lobby": Button("Lobby chat", lambda: self.show("lobby"), b, 2, font_size=11),
            "messages": Button("Messages", lambda: self.show("messages"), b, 2, font_size=11),
        }

        # alerts
        ab = self.alerts_batch = pyglet.graphics.Batch()
        self.alert_list = ListView(ab, 2, self.pick_alert, row_height=56, empty_text="You're all caught up.")
        self.clear_btn = Button("Clear all", self.model.dismiss_all, ab, 2, style="ghost", font_size=10)
        self.challenge_caption = label("", 0, 0, 11, ab, Group(order=5), color=TEXT)
        self.accept_btn = Button("Accept", lambda: self.answer(True), ab, 2, style="primary")
        self.decline_btn = Button("Decline", lambda: self.answer(False), ab, 2, style="danger")
        self.alert_status = label("", 0, 0, 10, ab, Group(order=5), color=(255, 170, 150))

        # lobby chat
        lb = self.lobby_batch = pyglet.graphics.Batch()
        self.room_btn = Button("", self.pick_room, lb, 2, font_size=11)
        self.lobby_log = ChatLog(lb, 5, empty_text="Joining the room…")
        self.lobby_input = TextField("Say something to the lobby…", lb, 2, on_submit=self.send_lobby,
                                     max_length=500, font_size=11)
        self.lobby_send = Button("Send", self.send_lobby, lb, 2, style="primary", font_size=11)

        # lobby room picker
        rb = self.rooms_batch = pyglet.graphics.Batch()
        self.rooms_caption = label("Choose a room", 0, 0, 11, rb, Group(order=5), color=MUTED)
        self.rooms_back = Button("‹ Back", lambda: self.show("lobby"), rb, 2, style="ghost", font_size=11)
        self.room_list = ListView(rb, 2, self.choose_room, row_height=50)

        # private messages: conversation list
        mb = self.list_batch = pyglet.graphics.Batch()
        self.convo_list = ListView(mb, 2, self.open_conversation, row_height=56,
                                   empty_text="No conversations yet.")
        self.to_field = TextField("Username to message…", mb, 2, on_submit=self.start_new, font_size=11)
        self.to_btn = Button("Message", self.start_new, mb, 2, font_size=11)
        self.list_status = label("", 0, 0, 10, mb, Group(order=5), color=(255, 170, 150))

        # private messages: one conversation
        cb = self.convo_batch = pyglet.graphics.Batch()
        self.back_btn = Button("‹ All", self.back, cb, 2, style="ghost", font_size=11)
        self.convo_title = label("", 0, 0, 13, cb, Group(order=5), color=TEXT)
        self.convo_log = ChatLog(cb, 5, empty_text="Loading the conversation…")
        self.pm_input = TextField("Write a message…", cb, 2, on_submit=self.send_pm, max_length=500, font_size=11)
        self.pm_send = Button("Send", self.send_pm, cb, 2, style="primary", font_size=11)
        self.convo_status = label("", 0, 0, 10, cb, Group(order=5), color=(255, 170, 150))

        self.model.listen(self.on_model_change)

    # ---------------------------------------------------------------- structure
    def _widgets(self):
        """(buttons, lists/logs, text fields) for whatever is on screen."""
        common = [self.close_btn, *self.tabs.values()]
        if self.view == "alerts":
            buttons = [self.clear_btn]
            if self.selected:
                buttons += [self.accept_btn, self.decline_btn]
            return common + buttons, [self.alert_list], []
        if self.view == "lobby":
            return common + [self.room_btn, self.lobby_send], [self.lobby_log], [self.lobby_input]
        if self.view == "rooms":
            return common + [self.rooms_back], [self.room_list], []
        if self.view == "messages":
            return common + [self.to_btn], [self.convo_list], [self.to_field]
        return common + [self.back_btn, self.pm_send], [self.convo_log], [self.pm_input]

    def showing_conversation(self, user_id):
        return self.is_open and self.view == "conversation" and self.model.open_conversation == user_id

    @property
    def tab(self):
        return {"conversation": "messages", "rooms": "lobby"}.get(self.view, self.view)

    def resize(self, w, h):
        self.w = min(DRAWER_WIDTH, w - 32)
        self.x, self.y = w - self.w - 16, 44
        self.h = h - 60
        x, y, dw, dh = self.x, self.y, self.w, self.h
        top = y + dh
        self.panel.set_rect(x, y, dw, dh)
        self.title.position = (x + 20, top - 38, 0)
        self.close_btn.set_rect(x + dw - 46, top - 50, 34, 34)
        tw = (dw - 40 - 12) / 3
        for i, btn in enumerate(self.tabs.values()):
            btn.set_rect(x + 20 + i * (tw + 6), top - 94, tw, 32)
        body_top = top - 108
        ix, iw = x + 16, dw - 32

        # alerts
        self.clear_btn.set_rect(x + dw - 100, y + 12, 84, 28)
        self.alert_status.position = (ix + 4, y + 22, 0)
        footer = 52 + (96 if self.selected else 0)
        self.challenge_caption.position = (ix + 4, y + 120, 0)
        self.accept_btn.set_rect(ix, y + 56, iw / 2 - 4, 40)
        self.decline_btn.set_rect(ix + iw / 2 + 4, y + 56, iw / 2 - 4, 40)
        self.alert_list.set_rect(ix, y + footer, iw, body_top - y - footer)

        # lobby
        self.room_btn.set_rect(ix, body_top - 34, iw, 32)
        self.lobby_input.set_rect(ix, y + 14, iw - 76, 36)
        self.lobby_send.set_rect(ix + iw - 68, y + 14, 68, 36)
        self.lobby_log.set_rect(ix + 4, y + 66, iw - 8, body_top - 48 - y - 66)

        # room picker
        self.rooms_back.set_rect(ix, body_top - 34, 72, 30)
        self.rooms_caption.position = (ix + 84, body_top - 24, 0)
        self.room_list.set_rect(ix, y + 14, iw, body_top - 46 - y - 14)

        # conversation list
        self.to_field.set_rect(ix, y + 30, iw - 98, 36)
        self.to_btn.set_rect(ix + iw - 90, y + 30, 90, 36)
        self.list_status.position = (ix + 4, y + 12, 0)
        self.convo_list.set_rect(ix, y + 80, iw, body_top - y - 80)

        # one conversation
        self.back_btn.set_rect(ix, body_top - 34, 64, 30)
        self.convo_title.position = (ix + 76, body_top - 24, 0)
        self.pm_input.set_rect(ix, y + 30, iw - 76, 36)
        self.pm_send.set_rect(ix + iw - 68, y + 30, 68, 36)
        self.convo_status.position = (ix + 4, y + 12, 0)
        self.convo_log.set_rect(ix + 4, y + 82, iw - 8, body_top - 48 - y - 82)

    # ---------------------------------------------------------------- open/close
    def show(self, view, select=None):
        if view == "messages" and self.model.open_conversation is not None:
            view = "conversation"
        if view == "conversation":
            self.model.mark_read(self.model.open_conversation)
        self.view = view
        self.is_open = True
        if view == "lobby":
            self.model.join_lobby()
        if select is not None:
            self.selected = select if self.model.notifications.get(select, {}).get("type") == "challenge" else None
            self.resize(self.app.width, self.app.height)
        self.refresh_all()

    def close(self):
        self.is_open = False
        self.blur()

    def toggle(self, view):
        if self.is_open and self.tab == view:
            self.close()
        else:
            self.show(view)

    def blur(self):
        for field in (self.lobby_input, self.to_field, self.pm_input):
            field.set_focus(False)

    def focused_field(self):
        if not self.is_open:
            return None
        return next((f for f in self._widgets()[2] if f.focused), None)

    def contains(self, x, y):
        return self.is_open and self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    # ------------------------------------------------------------------ content
    def on_model_change(self, part):
        if part == "alerts":
            if self.selected not in self.model.notifications:
                self.selected = None
            self.refresh_alerts()
        elif part == "lobby":
            self.refresh_lobby()
        elif part == "messages":
            self.refresh_messages()
        self.app.refresh_hud()

    def refresh_all(self):
        self.refresh_alerts()
        self.refresh_lobby()
        self.refresh_messages()
        for name, btn in self.tabs.items():
            btn.set_selected(name == self.tab)

    def refresh_alerts(self):
        items = []
        for note in reversed(list(self.model.notifications.values())):
            title, detail = describe(note)
            stamp = note.get("timestamp")
            when = _ago(stamp) if isinstance(stamp, (int, float)) else ""
            items.append({"title": title, "detail": "  ·  ".join(b for b in (detail, when) if b),
                          "value": note.get("id")})
        self.alert_list.set_items(items)
        note = self.model.notifications.get(self.selected)
        set_text(self.challenge_caption, describe(note)[0] if note else "")
        # Accept/Decline belong to the selected challenge only.
        self.accept_btn.visible = self.decline_btn.visible = note is not None
        self.resize(self.app.width, self.app.height)

    def refresh_lobby(self):
        fit_text(f"Room:  {self.model.channel_name}   ›", self.room_btn.text, self.w - 72)
        if not self.model.lobby_joined:
            return
        entries = []
        for line in self.model.lobby:
            mine = line.get("id") == self.model.my_id
            color = ME_COLOR if mine else GOLD
            entries.append((chat_name(line), (line.get("message") or {}).get("m", ""), color, TEXT))
        self.lobby_log.set_entries(entries)
        self.lobby_log.set_empty_text("No recent messages in this room." if self.model.lobby_ready
                                      else "Joining the room…")

    def refresh_messages(self):
        convos = sorted(self.model.conversations.items(),
                        key=lambda kv: kv[1]["messages"][-1]["t"] if kv[1]["messages"] else 0, reverse=True)
        items = []
        for user_id, convo in convos:
            last = convo["messages"][-1] if convo["messages"] else None
            name = convo["user"].get("username", "?")
            unread = f"   • {convo['unread']} new" if convo["unread"] else ""
            preview = (("You: " if last["mine"] else "") + last["m"]) if last else "No messages yet"
            items.append({"title": name + unread, "detail": preview, "value": user_id})
        self.convo_list.set_items(items)

        user_id = self.model.open_conversation
        convo = self.model.conversations.get(user_id)
        if convo:
            fit_text(convo["user"].get("username", "?"), self.convo_title, self.w - 120)
            me = (self.app.user or {}).get("username", "You")
            them = convo["user"].get("username", "?")
            self.convo_log.set_entries([(me if m["mine"] else them, m["m"], ME_COLOR if m["mine"] else GOLD, TEXT)
                                        for m in convo["messages"]])
            self.convo_log.set_empty_text("Say hello.")

    # ------------------------------------------------------------------ actions
    def pick_alert(self, note_id):
        note = self.model.notifications.get(note_id)
        if not note:
            return
        if note.get("type") == "challenge":
            self.selected = None if self.selected == note_id else note_id
            self.alert_status.text = ""
            self.refresh_alerts()
        elif note.get("game_id"):
            self.close()
            self.model.activate(note)
        else:
            self.model.dismiss(note_id)

    def answer(self, accept):
        note = self.model.notifications.get(self.selected)
        if note:
            self.alert_status.text = "Accepting…" if accept else "Declining…"
            self.model.answer_challenge(note, accept, self._alert_error)

    def _alert_error(self, text):
        self.alert_status.text = text

    def pick_room(self):
        current = self.model.channel
        self.room_list.set_items([
            {"title": name, "detail": f"#{cid}" + ("   ·   current room" if cid == current else ""), "value": cid}
            for cid, name in CHANNELS
        ])
        self.view = "rooms"
        self.lobby_input.set_focus(False)

    def choose_room(self, channel):
        self.model.set_channel(channel)
        self.show("lobby")

    def send_lobby(self):
        if not self.app.signed_in:
            self.app.show_login()
            return
        self.model.send_lobby(self.lobby_input.value)
        self.lobby_input.clear()

    def open_conversation(self, user_id):
        convo = self.model.conversations.get(user_id)
        if convo:
            self.model.start_conversation(convo["user"])
            self.view = "conversation"
            self.convo_status.text = ""
            self.refresh_messages()

    def start_new(self):
        if not self.app.signed_in:
            self.app.show_login()
            return
        username = self.to_field.value.strip()
        if not username:
            self.list_status.text = "Type a username first."
            return
        self.list_status.text = "Looking up…"

        def found(user):
            self.list_status.text = ""
            self.to_field.clear()
            self.open_user(user)

        self.model.find_user(username, found, lambda text: setattr(self.list_status, "text", text))

    def open_user(self, user):
        self.model.start_conversation(user)
        self.view = "conversation"
        self.is_open = True
        self.convo_status.text = ""
        self.refresh_all()

    def back(self):
        self.model.close_conversation()
        self.pm_input.set_focus(False)
        self.view = "messages"
        self.refresh_all()

    def send_pm(self):
        user_id = self.model.open_conversation
        if user_id is None or not self.pm_input.value.strip():
            return
        self.convo_status.text = ""
        self.model.send_pm(user_id, self.pm_input.value, lambda text: setattr(self.convo_status, "text", text))
        self.pm_input.clear()

    # -------------------------------------------------------------------- input
    def on_mouse_motion(self, x, y):
        if not self.is_open:
            return
        buttons, lists, _ = self._widgets()
        for widget in (*buttons, *lists):
            if hasattr(widget, "on_mouse_motion"):
                widget.on_mouse_motion(x, y)

    def on_mouse_press(self, x, y):
        buttons, lists, fields = self._widgets()
        for field in fields:
            field.set_focus(field.contains(x, y))
            if field.focused and not self.app.signed_in and field is not self.to_field:
                field.set_focus(False)
                self.app.show_login()
        for widget in (*buttons, *lists):
            if hasattr(widget, "on_mouse_press") and widget.on_mouse_press(x, y):
                return

    def on_mouse_scroll(self, x, y, scroll_y):
        for widget in self._widgets()[1]:
            widget.on_mouse_scroll(x, y, scroll_y)

    def on_text(self, text):
        field = self.focused_field()
        if field:
            field.on_text(text)

    def on_text_motion(self, motion):
        field = self.focused_field()
        if field:
            field.on_text_motion(motion)

    def on_key(self, symbol):
        """Returns True when the drawer used the key."""
        field = self.focused_field()
        if symbol == key.ESCAPE and self.is_open:
            if field:
                field.set_focus(False)
            else:
                self.close()
            return True
        if field and symbol in (key.ENTER, key.RETURN, key.NUM_ENTER):
            if field.on_submit:
                field.on_submit()
            return True
        return bool(field)

    # -------------------------------------------------------------------- frame
    def update(self, t):
        for field in (self.lobby_input, self.to_field, self.pm_input):
            field.update(t)
        room = self.model.channel_name.split(" · ")[0]
        placeholder = f"Message {room}…" if self.app.signed_in else "Sign in to chat"
        if self.lobby_input.placeholder != placeholder:
            self.lobby_input.placeholder = placeholder
            self.lobby_input._render()

    def draw(self):
        if not self.is_open:
            return
        self.batch.draw()
        {"alerts": self.alerts_batch, "lobby": self.lobby_batch, "rooms": self.rooms_batch,
         "messages": self.list_batch, "conversation": self.convo_batch}[self.view].draw()


class Toasts:
    """Small cards that slide in at the top right and fade away on their own."""

    def __init__(self, app):
        self.app = app
        self.batch = pyglet.graphics.Batch()
        self.items = []

    def push(self, title, body, action=None):
        b = self.batch
        panel = Panel(b, 0, radius=12)
        panel.fill.color = (16, 20, 34, 250)
        panel.set_edge((233, 197, 122, 120))
        accent = shapes.Rectangle(0, 0, 3, TOAST_HEIGHT - 20, color=GOLD, batch=b, group=Group(order=3))
        title_label = label("", 0, 0, 12, b, Group(order=3), color=GOLD, bold=True)
        body_label = label("", 0, 0, 11, b, Group(order=3), color=TEXT)
        fit_text(title, title_label, TOAST_WIDTH - 40)
        fit_text(" ".join(body.split()), body_label, TOAST_WIDTH - 40)
        self.items.insert(0, {"panel": panel, "accent": accent, "title": title_label, "body": body_label,
                              "born": time.time(), "action": action, "x": 0, "y": 0})
        while len(self.items) > 4:
            self._remove(self.items[-1])

    def _remove(self, item):
        self.items.remove(item)
        for part in (item["panel"], item["accent"], item["title"], item["body"]):
            part.delete()

    def update(self, dt):
        now = time.time()
        w, h = self.app.width, self.app.height
        right = (self.app.drawer.x - 12) if self.app.drawer.is_open else (w - 16)
        for i, item in enumerate(list(self.items)):
            age = now - item["born"]
            if age > TOAST_SECONDS:
                self._remove(item)
                continue
            slide = 1 - (1 - min(1.0, age / 0.35)) ** 3
            fade = min(1.0, (TOAST_SECONDS - age) / 0.6)
            x = right - TOAST_WIDTH + (1 - slide) * (TOAST_WIDTH + 30)
            y = h - 16 - (i + 1) * (TOAST_HEIGHT + 10)
            item["x"], item["y"] = x, y
            item["panel"].set_rect(x, y, TOAST_WIDTH, TOAST_HEIGHT)
            item["panel"].fill.opacity = int(250 * fade)
            item["panel"].edge.opacity = int(120 * fade)
            item["accent"].position = (x + 12, y + 10)
            item["accent"].opacity = int(255 * fade)
            item["title"].position = (x + 26, y + TOAST_HEIGHT - 28, 0)
            item["body"].position = (x + 26, y + 18, 0)
            item["title"].color = (*GOLD, int(255 * fade))
            item["body"].color = (*TEXT, int(235 * fade))

    def on_mouse_press(self, x, y):
        for item in self.items:
            if item["x"] <= x <= item["x"] + TOAST_WIDTH and item["y"] <= y <= item["y"] + TOAST_HEIGHT:
                action = item["action"]
                self._remove(item)
                if action:
                    action()
                return True
        return False

    def draw(self):
        self.batch.draw()
