"""Lobby, game and sign-in screens."""

import math
import time

import pyglet
from pyglet import shapes
from pyglet.graphics import Group
from pyglet.sprite import Sprite
from pyglet.window import key

from .board_view import BoardView, additive
from .game import (BLACK, COLUMN_LETTERS, EMPTY, WHITE, Clock, GameState, decode_coords, encode_coords,
                   encode_move, format_rank)
from .net import run_in_background
from .ui import GOLD, MUTED, SERIF, TEXT, Button, ChatLog, ListView, Panel, TextField, fit_text, label, set_text

MARGIN = 24
CJK_SERIF = ["Noto Serif CJK JP", "Source Han Serif", "IPAexMincho", "Yu Mincho", "MS Mincho",
             "Hiragino Mincho ProN", "Songti SC", "SimSun"]
BOTTOM = 40  # leaves room for the status line along the bottom edge


def split_game_event(command):
    """'game/123/move' -> (123, 'move'); anything else -> (None, None)."""
    if not command.startswith("game/"):
        return None, None
    parts = command.split("/", 2)
    if len(parts) < 3 or not parts[1].isdigit():
        return None, None
    return int(parts[1]), parts[2]


ME_COLOR = (150, 205, 255)
SPECTATOR_COLOR = (170, 176, 198)


def chat_body(body):
    """Plain text for a game chat body, which may be a string or a typed dict."""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        kind = body.get("type")
        if kind == "translated":
            return body.get("en") or next((v for v in body.values() if isinstance(v, str) and v != kind), "")
        if kind == "analysis":
            return f"[shared a variation{': ' + body['name'] if body.get('name') else ''}]"
        if kind == "review":
            return "[shared a review]"
    return ""


def player_line(player):
    name = player.get("username", "?")
    rank = format_rank(player.get("rank", player.get("ranking")), player.get("professional"))
    return f"{name} [{rank}]" if rank else name


class LobbyScene:
    def __init__(self, app):
        self.app = app
        self.batch = pyglet.graphics.Batch()
        b = self.batch
        self.size = 19
        self.speed = "rapid"
        self.match_id = None
        self.match_started = 0.0
        self.bot_index = 0
        self.featured_id = None
        self.featured_state = None
        self.featured_finished_at = None
        self.next_refresh = 0.0
        self.bot_name_width = 200
        self.caption_width = 400
        self.active = True
        self.notice = ""
        self.notice_until = 0.0

        self.title_glow = additive(app.art.soft_glow, b, Group(order=1))
        self.title_glow.color = (255, 196, 120)
        self.title = label("Goban", 0, 0, 46, b, Group(order=40), color=GOLD, font=SERIF)
        self.subtitle = label("a quiet window onto online-go.com", 0, 0, 13, b, Group(order=40),
                              color=MUTED, font=SERIF)
        cjk = next((f for f in CJK_SERIF if pyglet.font.have_font(f)), None)
        self.kanji = label("碁盤" if cjk else "", 0, 0, 40, b, Group(order=39), color=GOLD, font=cjk or SERIF,
                           alpha=70)
        self.user_label = label("", 0, 0, 12, b, Group(order=40), color=TEXT, anchor_x="right",
                                anchor_y="center")
        self.account_btn = Button("Sign in", self.on_account, b, 41)

        # ---- play panel
        self.play_panel = Panel(b, 20)
        self.play_heading = label("Play", 0, 0, 20, b, Group(order=24), color=GOLD, font=SERIF)
        self.size_caption = label("BOARD", 0, 0, 9, b, Group(order=24), color=MUTED)
        self.size_btns = {s: Button(f"{s}×{s}", lambda s=s: self.pick_size(s), b, 21) for s in (9, 13, 19)}
        self.speed_caption = label("PACE", 0, 0, 9, b, Group(order=24), color=MUTED)
        self.speed_btns = {s: Button(s.capitalize(), lambda s=s: self.pick_speed(s), b, 21)
                           for s in ("blitz", "rapid", "live")}
        self.match_btn = Button("Find an opponent", self.on_match, b, 21, style="primary", font_size=13)
        self.match_status = label("", 0, 0, 10, b, Group(order=24), color=MUTED, anchor_x="center")
        self.bot_caption = label("OR CHALLENGE A BOT", 0, 0, 9, b, Group(order=24), color=MUTED)
        self.bot_prev = Button("‹", lambda: self.cycle_bot(-1), b, 21, font_size=16)
        self.bot_next = Button("›", lambda: self.cycle_bot(1), b, 21, font_size=16)
        self.bot_name = label("Waiting for bots…", 0, 0, 12, b, Group(order=24), anchor_x="center",
                              anchor_y="center")
        self.bot_btn = Button("Challenge", self.on_challenge_bot, b, 21)
        self.mine_caption = label("YOUR GAMES", 0, 0, 9, b, Group(order=24), color=MUTED)
        self.mine_list = ListView(b, 21, self.app.open_game, row_height=48, empty_text="No games in progress")

        # ---- featured live game
        self.board = BoardView(app.art, b, base_order=4, show_coords=False)
        self.featured_caption = label("", 0, 0, 12, b, Group(order=40), color=TEXT, anchor_x="center")
        self.featured_kicker = label("NOW PLAYING", 0, 0, 9, b, Group(order=40), color=GOLD,
                                     anchor_x="center")

        # ---- live list
        self.live_panel = Panel(b, 20)
        self.live_heading = label("Watch", 0, 0, 20, b, Group(order=24), color=GOLD, font=SERIF)
        self.refresh_btn = Button("Refresh", self.refresh_live, b, 21, style="ghost", font_size=10)
        self.live_list = ListView(b, 21, self.app.open_game, empty_text="Gathering live games…")

        self.buttons = [self.account_btn, *self.size_btns.values(), *self.speed_btns.values(),
                        self.match_btn, self.bot_prev, self.bot_next, self.bot_btn, self.refresh_btn]
        self.lists = [self.mine_list, self.live_list]
        self.pick_size(19)
        self.pick_speed("rapid")
        self.refresh_account()

    # ------------------------------------------------------------------ layout
    def resize(self, w, h):
        m = MARGIN
        self.title.position = (m + 6, h - 70, 0)
        self.subtitle.position = (m + 10, h - 94, 0)
        self.kanji.position = (m + 20 + self.title.content_width, h - 70, 0)
        gs = self.app.art.soft_glow.width
        self.title_glow.update(x=m + 110, y=h - 70, scale_x=420 / gs, scale_y=150 / gs)
        self.account_btn.set_rect(w - m - 110, h - 74, 110, 36)
        self.user_label.position = (w - m - 124, h - 56, 0)

        top = h - 120
        left_w = int(min(340, max(280, w * 0.24)))
        right_w = int(min(360, max(290, w * 0.25)))
        # play panel
        px, py, ph = m, BOTTOM, top - BOTTOM
        self.play_panel.set_rect(px, py, left_w, ph)
        ix, iw = px + 20, left_w - 40
        y = top - 40
        self.play_heading.position = (ix, y, 0)
        y -= 34
        self.size_caption.position = (ix, y, 0)
        y -= 44
        bw = (iw - 16) / 3
        for i, btn in enumerate(self.size_btns.values()):
            btn.set_rect(ix + i * (bw + 8), y, bw, 34)
        y -= 26
        self.speed_caption.position = (ix, y, 0)
        y -= 44
        for i, btn in enumerate(self.speed_btns.values()):
            btn.set_rect(ix + i * (bw + 8), y, bw, 34)
        y -= 56
        self.match_btn.set_rect(ix, y, iw, 44)
        y -= 22
        self.match_status.position = (ix + iw / 2, y, 0)
        y -= 34
        self.bot_caption.position = (ix, y, 0)
        y -= 46
        self.bot_prev.set_rect(ix, y, 36, 36)
        self.bot_next.set_rect(ix + iw - 36, y, 36, 36)
        self.bot_name.position = (ix + iw / 2, y + 18, 0)
        self.bot_name_width = iw - 92
        y -= 46
        self.bot_btn.set_rect(ix, y, iw, 36)
        y -= 32
        self.mine_caption.position = (ix, y, 0)
        y -= 10
        self.mine_list.set_rect(ix - 6, py + 12, iw + 12, max(0, y - py - 12))

        # live panel
        rx = w - m - right_w
        self.live_panel.set_rect(rx, BOTTOM, right_w, top - BOTTOM)
        self.live_heading.position = (rx + 20, top - 40, 0)
        self.refresh_btn.set_rect(rx + right_w - 96, top - 48, 80, 28)
        self.live_list.set_rect(rx + 12, BOTTOM + 12, right_w - 24, top - 64 - BOTTOM - 12)

        # featured board fills the middle
        cx0, cx1 = m + left_w + m, rx - m
        cw = cx1 - cx0
        board_h = top - BOTTOM - 54
        self.board.set_rect(cx0, BOTTOM + 54, cw, board_h)
        show = cw > 220
        for item in (self.board.top, self.board.side, self.board.board_shadow, self.board.halo,
                     self.board.side_shade, self.board.lamp, self.board.sheen, *self.board.edges):
            item.visible = show
        self.featured_caption.position = (cx0 + cw / 2, BOTTOM + 8, 0)
        self.caption_width = cw - 16
        self.refresh_bots()
        self._caption()
        self.featured_kicker.position = (cx0 + cw / 2, BOTTOM + 28, 0)

    # ------------------------------------------------------------------ actions
    def pick_size(self, size):
        self.size = size
        for s, btn in self.size_btns.items():
            btn.set_selected(s == size)

    def pick_speed(self, speed):
        self.speed = speed
        for s, btn in self.speed_btns.items():
            btn.set_selected(s == speed)

    def on_account(self):
        if self.app.signed_in:
            self.app.sign_out()
        else:
            self.app.show_login()

    def on_match(self):
        if not self.app.signed_in:
            self.app.show_login()
            return
        if self.match_id:
            self.app.socket.cancel_match(self.match_id)
            self.match_id = None
        else:
            self.match_id = self.app.socket.find_match(self.size, self.speed)
            self.match_started = time.time()

    def on_match_cancelled(self):
        self.match_id = None

    def bots(self):
        bots = [bot for bot in self.app.bots.values() if isinstance(bot, dict) and bot.get("id")]
        return sorted(bots, key=lambda bot: bot.get("username", "").lower())

    def cycle_bot(self, step):
        bots = self.bots()
        if bots:
            self.bot_index = (self.bot_index + step) % len(bots)
            self.refresh_bots()

    def refresh_bots(self):
        bots = self.bots()
        if not bots:
            self.bot_name.text = "Waiting for bots…"
            return
        self.bot_index %= len(bots)
        fit_text(bots[self.bot_index].get("username", "?"), self.bot_name, self.bot_name_width)

    def on_challenge_bot(self):
        if not self.app.signed_in:
            self.app.show_login()
            return
        bots = self.bots()
        if not bots:
            return
        bot = bots[self.bot_index % len(bots)]
        self.show_notice(f"Challenging {bot.get('username')}…", 10)
        size = self.size

        def done(result, error):
            if error:
                self.show_notice(f"Challenge failed: {error}", 8)
                return
            game_id = (result or {}).get("game")
            if not game_id:
                self.show_notice("The server did not return a game.", 8)
                return
            self.show_notice("", 0)
            self.app.open_game(game_id, challenge_id=result.get("challenge"))

        run_in_background(lambda: self.app.rest.challenge_player(bot["id"], size), done, self.app.socket.inbox)

    def show_notice(self, text, seconds):
        self.notice = text
        self.notice_until = time.time() + seconds

    def refresh_account(self):
        user = self.app.user or {}
        if self.app.signed_in:
            rank = format_rank(user.get("ranking"), user.get("professional"))
            set_text(self.user_label, f"{user.get('username', '')}  ·  {rank}" if rank else user.get("username", ""))
            self.account_btn.set_text("Sign out")
        else:
            self.user_label.text = "Watching as a guest"
            self.account_btn.set_text("Sign in")
        playable = self.app.signed_in
        self.match_btn.set_style("primary" if playable else "normal")
        if not playable:
            self.match_btn.set_text("Sign in to play")
        self.refresh_mine()

    def refresh_mine(self):
        items = []
        for entry in self.app.active_games.values():
            black, white = entry.get("black", {}), entry.get("white", {})
            my_id = (self.app.user or {}).get("id")
            to_move = "your move" if entry.get("player_to_move") == my_id else "their move"
            items.append({
                "title": f"{black.get('username', '?')}  vs  {white.get('username', '?')}",
                "detail": f"{entry.get('width')}×{entry.get('height')}  ·  move {entry.get('move_number', 0)}  ·  {to_move}",
                "value": entry["id"],
            })
        self.mine_list.set_items(items)

    def refresh_live(self):
        self.next_refresh = time.time() + 30
        self.app.socket.query_live_games(self.on_live_games)

    def on_live_games(self, data, error):
        if error or not isinstance(data, dict):
            return
        games = [g for g in data.get("results", []) if not g.get("private")]
        items = []
        for g in games:
            details = [f"{g.get('width')}×{g.get('height')}", f"move {g.get('move_number', 0)}"]
            if g.get("handicap"):
                details.append(f"H{g['handicap']}")
            details.append("ranked" if g.get("ranked") else "free")
            if g.get("bot_game"):
                details.append("bot")
            items.append({
                "title": f"{player_line(g.get('black', {}))}  vs  {player_line(g.get('white', {}))}",
                "detail": "  ·  ".join(details),
                "value": g["id"],
            })
        self.live_list.set_items(items)
        live_ids = {g["id"] for g in games}
        if self.active and (self.featured_id is None or self.featured_id not in live_ids or self.featured_finished_at):
            candidates = [g for g in games if g.get("width") == 19 and g.get("phase") == "play"] or games
            if candidates and candidates[0]["id"] != self.featured_id:
                self.feature(candidates[0]["id"])

    def feature(self, game_id):
        if self.featured_id:
            self.app.socket.disconnect_game(self.featured_id)
        self.featured_id = game_id
        self.featured_state = None
        self.featured_finished_at = None
        self.app.socket.connect_game(game_id)

    # ----------------------------------------------------------------- events
    def on_event(self, command, data):
        game_id, sub = split_game_event(command)
        if game_id is None or game_id != self.featured_id:
            return
        if sub == "gamedata":
            self.featured_state = GameState(data)
            self.board.set_state(self.featured_state)
            self._caption()
        elif sub == "move" and self.featured_state:
            state = self.featured_state
            n = data.get("move_number")
            if n is not None and n <= len(state.moves):
                return
            if n is not None and n > len(state.moves) + 1:
                self.app.socket.resync_game(game_id)
                return
            move = data.get("move") or [-1, -1]
            state.play(move[0], move[1])
            self.board.sync(animate=True)
            if self.active and move[0] >= 0:
                self.app.sound.click()
            self._caption()
        elif sub == "phase" and self.featured_state:
            self.featured_state.phase = data
            if data == "finished":
                self.featured_finished_at = time.time()

    def _caption(self):
        s = self.featured_state
        if not s:
            return
        fit_text(f"{player_line(s.player(BLACK))}   vs   {player_line(s.player(WHITE))}"
                 f"     ·     move {len(s.moves)}", self.featured_caption, self.caption_width)

    def suspend(self):
        self.active = False
        if self.featured_id:
            self.app.socket.disconnect_game(self.featured_id)
            self.featured_id = None

    def resume(self):
        self.active = True
        self.refresh_live()

    # ------------------------------------------------------------------ frame
    def update(self, dt, t):
        if time.time() > self.next_refresh and self.app.socket.connected:
            self.refresh_live()
        self.board.update(dt, t)
        self.title_glow.opacity = int(46 + 16 * math.sin(t * 0.6))
        if self.app.signed_in:
            if self.match_id:
                dots = "." * (1 + int(t * 2) % 3)
                self.match_btn.set_text("Cancel search")
                waited = int(time.time() - self.match_started)
                status = f"Seeking a {self.size}×{self.size} {self.speed} game{dots}  {waited}s"
            else:
                self.match_btn.set_text("Find an opponent")
                status = ""
        else:
            status = "Spectating is open to everyone."
        if self.notice and time.time() < self.notice_until:
            status = self.notice
        if self.match_status.text != status:
            self.match_status.text = status

    def draw(self):
        self.batch.draw()

    def on_mouse_motion(self, x, y):
        self.board.set_pointer(x, y)
        for btn in self.buttons:
            btn.on_mouse_motion(x, y)
        for lst in self.lists:
            lst.on_mouse_motion(x, y)

    def on_mouse_press(self, x, y, button):
        for widget in (*self.buttons, *self.lists):
            if widget.on_mouse_press(x, y):
                return
        if self.featured_id and self.board.point_at(x, y) is not None:
            self.app.open_game(self.featured_id)

    def on_mouse_scroll(self, x, y, scroll_y):
        for lst in self.lists:
            lst.on_mouse_scroll(x, y, scroll_y)

    def on_key(self, symbol):
        return False

    def close(self):
        pass


class GameScene:
    def __init__(self, app, game_id, challenge_id=None):
        self.app = app
        self.game_id = game_id
        self.challenge_id = challenge_id
        self.batch = pyglet.graphics.Batch()
        b = self.batch
        self.state = None
        self.clock = Clock()
        self.pending = None
        self.undo_request = None
        self.resign_armed_until = 0.0
        self.flash = ""
        self.flash_until = 0.0
        self.opened = time.time()

        self.board = BoardView(app.art, b, base_order=4, show_coords=True)

        self.panel = Panel(b, 30)
        g = Group(order=34)
        self.title = label("", 0, 0, 19, b, g, color=GOLD, font=SERIF)
        self.subtitle = label("", 0, 0, 10, b, g, color=MUTED)
        self.cards = {}
        for color in (WHITE, BLACK):
            tex = app.art.white_stones[0] if color == WHITE else app.art.black_stones[0]
            self.cards[color] = {
                "panel": Panel(b, 31, radius=12),
                "icon": Sprite(tex, batch=b, group=g),
                "name": label("", 0, 0, 15, b, g, color=TEXT),
                "info": label("", 0, 0, 10, b, g, color=MUTED),
                "clock": label("", 0, 0, 22, b, g, color=TEXT, font=SERIF, anchor_x="right"),
            }
        self.status = label("Connecting to the game…", 0, 0, 13, b, g, color=TEXT, font=SERIF,
                            width=300, multiline=True)
        self.move_label = label("", 0, 0, 10, b, g, color=MUTED)

        self.pass_btn = Button("Pass", self.on_pass, b, 35)
        self.resign_btn = Button("Resign", self.on_resign, b, 35, style="danger")
        self.accept_btn = Button("Accept score", self.on_accept, b, 35, style="primary")
        self.resume_btn = Button("Resume play", self.on_resume, b, 35)
        self.undo_btn = Button("Allow undo", self.on_allow_undo, b, 35)
        self.leave_btn = Button("Back to lobby", self.app.show_lobby, b, 35, style="ghost")
        self.buttons = [self.pass_btn, self.resign_btn, self.accept_btn, self.resume_btn,
                        self.undo_btn, self.leave_btn]

        self.chat = []  # (chat_id, entry) in arrival order
        self.chat_caption = label("CHAT", 0, 0, 9, b, g, color=MUTED)
        self.chat_log = ChatLog(b, 36, empty_text="No chat in this game yet.")
        self.chat_input = TextField("Say something…", b, 35, on_submit=self.send_chat, max_length=300,
                                    font_size=11)

        app.socket.connect_game(game_id, chat=True)

    # ---------------------------------------------------------------- identity
    @property
    def my_id(self):
        return (self.app.user or {}).get("id") if self.app.signed_in else None

    @property
    def my_color(self):
        return self.state.color_of_player(self.my_id) if self.state else None

    def my_turn(self):
        if not self.state or self.state.phase != "play" or not self.my_color:
            return False
        if self.clock.data and self.clock.data.get("current_player"):
            return self.clock.data["current_player"] == self.my_id
        return self.state.to_move == self.my_color

    # ------------------------------------------------------------------ layout
    def resize(self, w, h):
        m = MARGIN
        pw = int(min(400, max(310, w * 0.27)))
        px = w - m - pw
        self.panel.set_rect(px, BOTTOM, pw, h - m - BOTTOM)
        self.board.set_rect(m, BOTTOM, px - 2 * m, h - m - BOTTOM)

        ix, iw = px + 22, pw - 44
        top = h - m
        self.title.position = (ix, top - 44, 0)
        self.subtitle.position = (ix, top - 66, 0)
        y = top - 96
        for color in (WHITE, BLACK):
            card = self.cards[color]
            ch = 92
            y -= ch
            card["panel"].set_rect(ix - 8, y, iw + 16, ch)
            icon_size = 40
            card["icon"].update(x=ix + 22, y=y + ch / 2, scale=icon_size / card["icon"].image.width)
            card["name"].position = (ix + 52, y + ch / 2 + 6, 0)
            card["info"].position = (ix + 52, y + ch / 2 - 16, 0)
            card["clock"].position = (ix + iw - 2, y + 14, 0)
            y -= 14
        y -= 18
        self.status.width = iw
        self.status.position = (ix, y, 0)
        self.move_label.position = (ix, y - 62, 0)
        self.chat_caption.position = (ix, y - 92, 0)
        self._chat_box = (ix, iw, y - 102)

        by = BOTTOM + 20
        self.leave_btn.set_rect(ix, by, iw, 38)
        self._button_slots = [(ix, by + 50 + i * 48, iw) for i in range(4)]
        self._place_buttons()

    def _place_buttons(self):
        slots = getattr(self, "_button_slots", None)
        if not slots:
            return
        shown = [btn for btn in (self.undo_btn, self.resume_btn, self.accept_btn, self.resign_btn, self.pass_btn)
                 if btn.visible]
        for btn, (x, y, w) in zip(shown, slots):
            btn.set_rect(x, y, w, 40)
        # Chat fills whatever room the action buttons leave.
        ix, iw, chat_top = self._chat_box
        input_y = slots[0][1] + len(shown) * 48 + 4
        self.chat_input.set_rect(ix, input_y, iw, 34)
        self.chat_log.set_rect(ix, input_y + 46, iw, chat_top - input_y - 46)

    # ------------------------------------------------------------------ events
    def on_event(self, command, data):
        game_id, sub = split_game_event(command)
        if game_id != self.game_id:
            if command == "active_game" and isinstance(data, dict) and data.get("id") == self.game_id \
                    and self.state is None:
                self.app.socket.resync_game(self.game_id)
            return
        if sub == "gamedata":
            self._on_gamedata(data)
        elif sub == "move":
            self._on_move(data)
        elif sub == "clock" and isinstance(data, dict):
            self.clock.update(data)
        elif sub == "phase" and self.state:
            self.state.phase = data
            self.board.removal_mode = data == "stone removal"
            self.board.refresh_marks()
            if data == "finished":
                self.app.socket.resync_game(self.game_id)
                self.app.sound.chime()
            self._refresh_labels()
        elif sub == "removed_stones" and self.state and isinstance(data, dict) and "all_removed" in data:
            self.state.removed = set(decode_coords(data["all_removed"]))
            self.board.removed = self.state.removed
            self.board.refresh_marks()
        elif sub == "removed_stones_accepted":
            self._flash("A player accepted the score.")
        elif sub == "undo_requested":
            number = data if isinstance(data, int) else (data or {}).get("move_number")
            requester = None if isinstance(data, int) else (data or {}).get("requested_by")
            if self.my_color and requester != self.my_id:
                self.undo_request = number
        elif sub in ("undo_accepted", "undo_canceled"):
            self.undo_request = None
            if sub == "undo_accepted":
                self.app.socket.resync_game(self.game_id)
        elif sub == "error":
            self.pending = None
            self._flash(str(data))
        elif sub == "chat" and isinstance(data, dict):
            self._on_chat(data)
        elif sub == "chat/remove" and isinstance(data, dict):
            gone = set(data.get("chat_ids") or [])
            self.chat = [(cid, entry) for cid, entry in self.chat if cid not in gone]
            self.chat_log.set_entries([entry for _, entry in self.chat])
        elif sub == "reset-chats":
            self.chat = []
            self.chat_log.set_entries([])

    def _on_gamedata(self, data):
        first = self.state is None
        self.state = GameState(data)
        self.pending = None
        self.board.removal_mode = self.state.phase == "stone removal"
        self.board.removed = self.state.removed
        self.board.set_state(self.state)
        if isinstance(data.get("clock"), dict):
            self.clock.update(data["clock"])
        self._refresh_labels()
        if first:
            self.resize(self.app.width, self.app.height)
            if self.my_color and self.state.phase == "play" and len(self.state.moves) < 2:
                self.app.sound.chime()

    def _on_move(self, data):
        state = self.state
        if not state or not isinstance(data, dict):
            return
        n = data.get("move_number")
        if n is not None and n <= len(state.moves):
            return
        if n is not None and n > len(state.moves) + 1:
            self.app.socket.resync_game(self.game_id)
            return
        move = data.get("move") or [-1, -1]
        color, _ = state.play(move[0], move[1])
        self.pending = None
        self.undo_request = None
        if move[0] < 0:
            self._flash(f"{'Black' if color == BLACK else 'White'} passes.")
        else:
            self.app.sound.click()
        if self.my_color and color != self.my_color and state.phase == "play":
            opponent = state.player(color).get("username", "Your opponent")
            where = "passed" if move[0] < 0 else f"played {COLUMN_LETTERS[move[0]]}{state.height - move[1]}"
            self.app.notify_desktop("Your move", f"{opponent} {where}.")
        self.board.sync(animate=True)
        self._refresh_labels()

    def _on_chat(self, data):
        line = data.get("line") or {}
        chat_id = line.get("chat_id")
        if chat_id and any(cid == chat_id for cid, _ in self.chat):
            return
        text = chat_body(line.get("body"))
        if not text:
            return
        player_id = line.get("player_id")
        if player_id is not None and player_id == self.my_id:
            name_color = ME_COLOR
        elif self.state and player_id in (self.state.black_id, self.state.white_id):
            name_color = GOLD
        else:
            name_color = SPECTATOR_COLOR
        name = line.get("username") or "?"
        if data.get("channel") == "spectator":
            name += " (spectator)"
        entry = (name, text, name_color, TEXT if data.get("channel") == "main" else SPECTATOR_COLOR)
        self.chat.append((chat_id, entry))
        self.chat_log.add(*entry)

    def send_chat(self):
        text = self.chat_input.value.strip()
        if not text:
            return
        if not self.app.signed_in:
            self.app.show_login()
            return
        self.app.socket.send("game/chat", {
            "game_id": self.game_id, "type": "main",
            "move_number": len(self.state.moves) if self.state else 0, "body": text,
        })
        self.chat_input.clear()

    def focused_field(self):
        return self.chat_input if self.chat_input.focused else None

    def on_text(self, text):
        self.chat_input.on_text(text)

    def on_text_motion(self, motion):
        self.chat_input.on_text_motion(motion)

    def _flash(self, text, seconds=4.0):
        self.flash = text
        self.flash_until = time.time() + seconds

    def _refresh_labels(self):
        s = self.state
        if not s:
            return
        black, white = s.player(BLACK), s.player(WHITE)
        set_text(self.title, f"{black.get('username', '?')} vs {white.get('username', '?')}")
        tc = s.time_control or {}
        bits = [f"{s.width}×{s.height}", (s.rules or "").capitalize(), f"komi {s.komi}"]
        if s.handicap:
            bits.append(f"handicap {s.handicap}")
        if tc.get("speed"):
            bits.append(tc["speed"])
        self.subtitle.text = "  ·  ".join(b for b in bits if b)
        for color in (WHITE, BLACK):
            player = s.player(color)
            card = self.cards[color]
            name = player.get("username", "?")
            if color == self.my_color:
                name += "  (you)"
            set_text(card["name"], name)
            rank = format_rank(player.get("rank"), player.get("professional"))
            card["info"].text = f"{rank}   ·   captures {s.captures[color]}" if rank else f"captures {s.captures[color]}"
        self.move_label.text = f"Move {len(s.moves)}"

    # ----------------------------------------------------------------- actions
    def on_pass(self):
        if self.my_turn() and not self.pending:
            self.pending = (-1, -1)
            self.app.socket.send("game/move", {"game_id": self.game_id, "move": encode_move(-1, -1)})

    def on_resign(self):
        if time.time() < self.resign_armed_until:
            self.resign_armed_until = 0
            self.app.socket.send("game/resign", {"game_id": self.game_id})
        else:
            self.resign_armed_until = time.time() + 3.0

    def on_accept(self):
        if self.state:
            stones = encode_coords(sorted(self.state.removed))
            self.app.socket.send("game/removed_stones/accept",
                                 {"game_id": self.game_id, "stones": stones, "strict_seki_mode": False})
            self._flash("You accepted the score.")

    def on_resume(self):
        self.app.socket.send("game/removed_stones/reject", {"game_id": self.game_id})

    def on_allow_undo(self):
        if self.undo_request is not None:
            self.app.socket.send("game/undo/accept", {"game_id": self.game_id, "move_number": self.undo_request})
            self.undo_request = None

    # ----------------------------------------------------------------- frame
    def update(self, dt, t):
        self.board.update(dt, t)
        self.chat_input.update(t)
        placeholder = "Say something…" if self.app.signed_in else "Sign in to chat"
        if self.chat_input.placeholder != placeholder:
            self.chat_input.placeholder = placeholder
            self.chat_input.clear()
        s = self.state
        playing = bool(s and self.my_color and s.phase == "play")
        removing = bool(s and self.my_color and s.phase == "stone removal")
        visibility = {
            self.pass_btn: playing,
            self.resign_btn: playing,
            self.accept_btn: removing,
            self.resume_btn: removing,
            self.undo_btn: self.undo_request is not None and playing,
        }
        changed = False
        for btn, show in visibility.items():
            if btn.visible != show:
                btn.visible = show
                changed = True
        if changed:
            self._place_buttons()
        self.pass_btn.set_enabled(self.my_turn() and not self.pending)
        armed = time.time() < self.resign_armed_until
        self.resign_btn.set_text("Click again to resign" if armed else "Resign")

        paused = bool(self.clock.data and (self.clock.data.get("pause") or {}).get("paused"))
        for color in (WHITE, BLACK):
            card = self.cards[color]
            text = self.clock.text(color, s.time_control if s else None, paused) if s and s.phase == "play" else ""
            if card["clock"].text != text:
                card["clock"].text = text
            active = False
            if s and s.phase == "play" and self.clock.data:
                pid = s.black_id if color == BLACK else s.white_id
                active = self.clock.data.get("current_player") == pid
            elif s and s.phase == "play":
                active = s.to_move == color
            if active:
                pulse = 0.5 + 0.5 * math.sin(t * 2.4)
                card["panel"].set_edge((233, 197, 122, int(110 + 120 * pulse)))
                left = self.clock.seconds_left_on_move()
                low = left is not None and left < 10
                card["clock"].color = (255, 140, 120, 255) if low else (*GOLD, 255)
            else:
                card["panel"].set_edge((233, 197, 122, 40))
                card["clock"].color = (*TEXT, 200)

        status = self._status_text()
        if self.status.text != status:
            self.status.text = status

    def _status_text(self):
        now = time.time()
        if self.flash and now < self.flash_until:
            return self.flash
        s = self.state
        if s is None:
            if self.challenge_id:
                if now - self.opened > 45:
                    return "No answer yet — the bot may have declined. Go back to try another."
                return "Waiting for your opponent to accept…"
            return "Connecting to the game…"
        if s.phase == "finished":
            return s.result_text()
        if s.phase == "stone removal":
            if self.my_color:
                return "Click groups to mark them dead, then accept the score."
            return "The players are marking dead stones."
        if self.my_color:
            if self.pending:
                return "Sending…"
            return "Your move." if self.my_turn() else "Your opponent is thinking…"
        color = s.to_move
        if self.clock.data and self.clock.data.get("current_player") == s.white_id:
            color = WHITE
        elif self.clock.data and self.clock.data.get("current_player") == s.black_id:
            color = BLACK
        return f"{'Black' if color == BLACK else 'White'} to play."

    def draw(self):
        self.batch.draw()

    # ------------------------------------------------------------------- input
    def on_mouse_motion(self, x, y):
        self.board.set_pointer(x, y)
        for btn in self.buttons:
            btn.on_mouse_motion(x, y)
        point = self.board.point_at(x, y)
        if point and self.my_turn() and not self.pending and self.state.board[point[1]][point[0]] == EMPTY:
            self.board.set_ghost(point[0], point[1], self.my_color)
        else:
            self.board.set_ghost(0, 0, None)

    def on_mouse_press(self, x, y, button):
        if self.chat_input.contains(x, y):
            if self.app.signed_in:
                self.chat_input.set_focus(True)
            else:
                self.app.show_login()
            return
        self.chat_input.set_focus(False)
        for btn in self.buttons:
            if btn.on_mouse_press(x, y):
                return
        point = self.board.point_at(x, y)
        if not point or not self.state:
            return
        px, py = point
        s = self.state
        if s.phase == "play" and self.my_turn() and not self.pending and s.board[py][px] == EMPTY:
            self.pending = point
            self.app.socket.send("game/move", {"game_id": self.game_id, "move": encode_move(px, py)})
        elif s.phase == "stone removal" and self.my_color and s.board[py][px] != EMPTY:
            group, _ = s.group(px, py)
            removed = not group <= s.removed
            self.app.socket.send("game/removed_stones/set", {
                "game_id": self.game_id, "removed": removed, "stones": encode_coords(sorted(group)),
            })

    def on_mouse_scroll(self, x, y, scroll_y):
        self.chat_log.on_mouse_scroll(x, y, scroll_y)

    def on_key(self, symbol):
        if self.chat_input.focused:
            if symbol in (key.ENTER, key.RETURN, key.NUM_ENTER):
                self.send_chat()
            elif symbol == key.ESCAPE:
                self.chat_input.set_focus(False)
            return True
        if symbol == key.ESCAPE:
            self.app.show_lobby()
            return True
        return False

    def close(self):
        self.app.socket.disconnect_game(self.game_id)
        if self.challenge_id and self.state is None:
            challenge_id = self.challenge_id
            run_in_background(lambda: self.app.rest.cancel_challenge(challenge_id),
                              lambda result, error: None, self.app.socket.inbox)


class LoginOverlay:
    def __init__(self, app):
        self.app = app
        self.batch = pyglet.graphics.Batch()
        b = self.batch
        self.busy = False
        self.dim = shapes.Rectangle(0, 0, 10, 10, color=(4, 6, 12, 170), batch=b, group=Group(order=0))
        self.panel = Panel(b, 1, radius=18)
        g = Group(order=5)
        self.title = label("Sign in to online-go.com", 0, 0, 22, b, g, color=GOLD, font=SERIF, anchor_x="center")
        self.note = label("Your password goes only to online-go.com and is not stored.", 0, 0, 10, b, g,
                          color=MUTED, anchor_x="center")
        self.user = TextField("Username", b, 2, on_submit=self.submit)
        self.password = TextField("Password", b, 2, password=True, on_submit=self.submit)
        self.error = label("", 0, 0, 11, b, g, color=(255, 170, 150), anchor_x="center")
        self.sign_in = Button("Sign in", self.submit, b, 2, style="primary", font_size=13)
        self.cancel = Button("Cancel", self.app.close_login, b, 2, style="ghost")
        self.fields = [self.user, self.password]
        self.buttons = [self.sign_in, self.cancel]
        self.user.set_focus(True)

    def resize(self, w, h):
        self.dim.width, self.dim.height = w, h
        pw, ph = 420, 330
        x, y = (w - pw) / 2, (h - ph) / 2
        self.panel.set_rect(x, y, pw, ph)
        cx = w / 2
        self.title.position = (cx, y + ph - 52, 0)
        self.note.position = (cx, y + ph - 76, 0)
        self.user.set_rect(x + 36, y + ph - 140, pw - 72, 42)
        self.password.set_rect(x + 36, y + ph - 194, pw - 72, 42)
        self.error.position = (cx, y + 100, 0)
        self.sign_in.set_rect(x + 36, y + 36, pw - 72 - 110, 44)
        self.cancel.set_rect(x + pw - 36 - 100, y + 36, 100, 44)

    def submit(self):
        if self.busy:
            return
        username, password = self.user.value.strip(), self.password.value
        if not username or not password:
            self.error.text = "Enter your username and password."
            return
        self.busy = True
        self.error.text = "Signing in…"
        self.sign_in.set_enabled(False)
        self.app.login(username, password, self.on_result)

    def on_result(self, error):
        self.busy = False
        self.sign_in.set_enabled(True)
        if error:
            self.error.text = error
        else:
            self.app.close_login()

    def update(self, dt, t):
        for field in self.fields:
            field.update(t)

    def draw(self):
        self.batch.draw()

    def on_mouse_motion(self, x, y):
        for btn in self.buttons:
            btn.on_mouse_motion(x, y)

    def on_mouse_press(self, x, y, button):
        for btn in self.buttons:
            if btn.on_mouse_press(x, y):
                return
        for field in self.fields:
            field.set_focus(field.contains(x, y))

    def on_text(self, text):
        for field in self.fields:
            field.on_text(text)

    def on_text_motion(self, motion):
        for field in self.fields:
            field.on_text_motion(motion)

    def on_key(self, symbol):
        if symbol == key.ESCAPE:
            self.app.close_login()
        elif symbol == key.TAB:
            focused = 0 if self.password.focused else 1
            for i, field in enumerate(self.fields):
                field.set_focus(i == focused)
        elif symbol in (key.ENTER, key.RETURN, key.NUM_ENTER):
            self.submit()
        return True

