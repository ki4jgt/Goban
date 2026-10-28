"""Notifications, private messages and lobby chat: the state behind the messages drawer.

Server events handled here:
    notification     a game started, your move, a challenge, a friend request, ...
    private-message  a PM to or from you (history arrives the same way after chat/pm/load)
    chat-message     a line in the joined lobby room (one of OGS's global-* channels)
The UI subscribes with `listen(callback)`; callbacks receive one of
"alerts", "messages" or "lobby" when that part changes.
"""

import time
import uuid

from . import settings
from .game import format_rank
from .net import OGS, run_in_background

# OGS's public rooms (id, display name), in the website's order, from
# online-go.com src/lib/chat_manager.ts. Rooms whose scripts need text shaping
# (Arabic, Hebrew, Hindi, Nepali, Bengali, Thai) are left out: pyglet draws text
# glyph by glyph without shaping or right-to-left layout, so they would be garbled.
CHANNELS = [
    ("global-english", "English"),
    ("global-help", "Help"),
    ("global-offtopic", "Off Topic"),
    ("global-rengo", "Rengo"),
    ("global-joseki", "Joseki Explorer"),
    ("global-japanese", "日本語 · Japanese"),
    ("global-zh-hans", "中文 · Chinese (Simplified)"),
    ("global-zh-hant", "廣東話 · Cantonese"),
    ("global-korean", "한국어 · Korean"),
    ("global-russian", "Русский · Russian"),
    ("global-polish", "Polski · Polish"),
    ("global-bulgarian", "Български · Bulgarian"),
    ("global-catalan", "Català · Catalan"),
    ("global-czech", "Čeština · Czech"),
    ("global-esperanto", "Esperanto"),
    ("global-german", "Deutsch · German"),
    ("global-spanish", "Español · Spanish"),
    ("global-french", "Français · French"),
    ("global-filipino", "Filipino"),
    ("global-indonesian", "Indonesian"),
    ("global-lithuanian", "Lietuvių · Lithuanian"),
    ("global-hungarian", "Magyar · Hungarian"),
    ("global-dutch", "Nederlands · Dutch"),
    ("global-norwegian", "Norsk · Norwegian"),
    ("global-italian", "Italiano · Italian"),
    ("global-portuguese", "Português · Portuguese"),
    ("global-romanian", "Română · Romanian"),
    ("global-swedish", "Svenska · Swedish"),
    ("global-finnish", "Suomi · Finnish"),
    ("global-turkish", "Türkçe · Turkish"),
    ("global-ukrainian", "Українська · Ukrainian"),
    ("global-vietnamese", "Tiếng Việt · Vietnamese"),
]
CHANNEL_NAMES = dict(CHANNELS)
DEFAULT_CHANNEL = "global-english"
LOBBY_LIMIT = 300
# Events in the first seconds after connecting are the server replaying what is
# already pending; they fill the lists quietly instead of popping up.
BACKLOG_SECONDS = 4.0


def _name(value):
    if isinstance(value, dict):
        return value.get("username") or "someone"
    return str(value) if value else "someone"


def _humanize(kind):
    out = "".join(" " + ch.lower() if ch.isupper() else ch for ch in kind)
    return out.strip().capitalize() or "Notification"


def describe(note):
    """Returns (title, detail) for an OGS notification payload."""
    kind = note.get("type", "")
    who = _name(note.get("user"))
    players = ""
    if note.get("black") or note.get("white"):
        players = f"{_name(note.get('black'))} vs {_name(note.get('white'))}"
    name = note.get("game_name") or note.get("name") or players
    size = f"{note['width']}×{note['height']}" if note.get("width") and note.get("height") else ""

    if kind == "challenge":
        bits = [size, "ranked" if note.get("ranked") else "unranked" if "ranked" in note else ""]
        return f"Challenge from {who}", "  ·  ".join(b for b in bits if b) or "Open to accept or decline"
    if kind == "gameStarted":
        return "Game started", name or "Your game has begun"
    if kind == "yourMove":
        return "Your move", name or "A game is waiting for you"
    if kind == "gameEnded":
        outcome = note.get("outcome") or ""
        return "Game over", "  ·  ".join(b for b in (name, outcome) if b) or "A game has finished"
    if kind in ("gameOfferRejected", "gameDeclined"):
        return "Challenge declined", f"{who} declined" if note.get("user") else name
    if kind == "friendRequest":
        return "Friend request", f"from {who}"
    if kind == "friendAccepted":
        return "Friend request accepted", who
    if kind == "lateChatReceivedInGame":
        return "New chat in a finished game", name
    if kind == "aiReviewDone":
        return "AI review ready", name
    if kind.startswith("tournament"):
        return _humanize(kind), note.get("tournament", {}).get("name", "") if isinstance(note.get("tournament"), dict) else ""
    if kind.startswith("group"):
        group = note.get("group", {})
        return _humanize(kind), group.get("name", "") if isinstance(group, dict) else ""
    return _humanize(kind), name or (who if note.get("user") else "")


def chat_name(user):
    """'name [rank]' for chat lines."""
    name = user.get("username", "?")
    rank = format_rank(user.get("ranking"), user.get("professional"))
    return f"{name} [{rank}]" if rank and user.get("ranking", -100) > -100 else name


class Messaging:
    def __init__(self, app):
        self.app = app
        self.notifications = {}  # id -> payload, oldest first
        self.conversations = {}  # other user id -> {"user", "messages", "ids", "unread", "loaded"}
        self.lobby = []
        self._lobby_ids = set()
        self.lobby_joined = False
        self.lobby_ready = False  # the server has acknowledged the join
        saved = settings.load().get("lobby_channel")
        self.channel = saved if saved in CHANNEL_NAMES else DEFAULT_CHANNEL
        self.open_conversation = None  # user id whose conversation is on screen
        self.connected_at = time.time()
        self._listeners = []

    # ------------------------------------------------------------------- plumbing
    def listen(self, callback):
        self._listeners.append(callback)

    def _changed(self, part):
        for callback in self._listeners:
            callback(part)

    @property
    def in_backlog(self):
        return time.time() - self.connected_at < BACKLOG_SECONDS

    def reset(self):
        """Forget everything account-specific (sign-in or sign-out)."""
        self.notifications.clear()
        self.conversations.clear()
        self.open_conversation = None
        for part in ("alerts", "messages"):
            self._changed(part)

    @property
    def my_id(self):
        return (self.app.user or {}).get("id") if self.app.signed_in else None

    # --------------------------------------------------------------------- events
    def on_event(self, command, data):
        if command == "_connected":
            self.connected_at = time.time()  # the socket itself rejoins the lobby room
        elif command == "notification" and isinstance(data, dict):
            self._on_notification(data)
        elif command == "private-message" and isinstance(data, dict):
            self._on_private_message(data)
        elif command == "chat-join" and isinstance(data, dict) and data.get("channel") == self.channel:
            if not self.lobby_ready:
                self.lobby_ready = True
                self._changed("lobby")
        elif command == "chat-message" and isinstance(data, dict) and data.get("channel") == self.channel:
            self._on_lobby_message(data)

    def _on_notification(self, note):
        note_id = note.get("id")
        if note.get("type") == "delete":
            self.notifications.pop(note_id, None)
            self._changed("alerts")
            return
        if not note_id or note_id in self.notifications:
            return
        self.notifications[note_id] = note
        self._changed("alerts")
        if not self.in_backlog:
            title, detail = describe(note)
            urgent = note.get("type") in ("challenge", "yourMove", "gameStarted", "gameEnded", "friendRequest")
            self.app.alert(title, detail, action=lambda n=note: self.activate(n), desktop=urgent)

    def _on_private_message(self, data):
        sender, receiver, message = data.get("from") or {}, data.get("to") or {}, data.get("message") or {}
        mine = sender.get("id") == self.my_id
        other = receiver if mine else sender
        if not other.get("id"):
            return
        convo = self._conversation(other)
        if not self._add_pm(convo, message, mine):
            return
        self._changed("messages")
        if not mine and not self.in_backlog and not self.app.drawer.showing_conversation(other["id"]):
            convo["unread"] += 1
            self._changed("messages")
            self.app.alert(f"Message from {other.get('username', '?')}", message.get("m", ""),
                           action=lambda uid=other["id"]: self.app.show_conversation(uid), desktop=True)

    def _on_lobby_message(self, data):
        message = data.get("message") or {}
        key = message.get("i") or (data.get("id"), message.get("t"), message.get("m"))
        if key in self._lobby_ids:
            return
        self._lobby_ids.add(key)
        self.lobby.append(data)
        if len(self.lobby) > LOBBY_LIMIT:
            del self.lobby[: len(self.lobby) - LOBBY_LIMIT]
        self._changed("lobby")

    # --------------------------------------------------------------- notifications
    def activate(self, note):
        """What clicking a notification does."""
        if note.get("type") == "challenge":
            self.app.show_drawer("alerts", select=note.get("id"))
            return
        game_id = note.get("game_id")
        if game_id:
            self.dismiss(note.get("id"))
            self.app.open_game(game_id)
        else:
            self.app.show_drawer("alerts", select=note.get("id"))

    def dismiss(self, note_id):
        if self.notifications.pop(note_id, None) is not None:
            self.app.socket.send("notification/delete", {"notification_id": note_id})
            self._changed("alerts")

    def dismiss_all(self):
        for note_id in list(self.notifications):
            self.dismiss(note_id)

    def answer_challenge(self, note, accept, on_error):
        challenge_id = note.get("challenge_id")
        if not challenge_id:
            on_error("This notification has no challenge attached.")
            return
        rest = self.app.rest

        def call():
            if accept:
                return rest.post(f"/api/v1/me/challenges/{challenge_id}/accept", {})
            rest.delete(f"/api/v1/me/challenges/{challenge_id}")
            return None

        def done(result, error):
            if error:
                on_error(f"Could not {'accept' if accept else 'decline'}: {error}")
                return
            self.dismiss(note.get("id"))
            game_id = note.get("game_id") or (result or {}).get("game")
            if accept and game_id:
                self.app.open_game(game_id)

        run_in_background(call, done, self.app.socket.inbox)

    # ----------------------------------------------------------- private messages
    def _conversation(self, user):
        convo = self.conversations.get(user["id"])
        if convo is None:
            convo = {"user": dict(user), "messages": [], "ids": set(), "unread": 0, "loaded": False}
            self.conversations[user["id"]] = convo
        elif user.get("username"):
            convo["user"].update(user)
        return convo

    @staticmethod
    def _add_pm(convo, message, mine):
        key = message.get("i") or (message.get("t"), message.get("m"), mine)
        if key in convo["ids"]:
            return False
        convo["ids"].add(key)
        convo["messages"].append({"t": message.get("t") or time.time(), "m": message.get("m", ""), "mine": mine})
        convo["messages"].sort(key=lambda m: m["t"])
        return True

    def start_conversation(self, user):
        """Opens (and loads the history of) a conversation with {id, username}."""
        convo = self._conversation(user)
        convo["unread"] = 0
        self.open_conversation = user["id"]
        if not convo["loaded"]:
            convo["loaded"] = True
            self.app.socket.send("chat/pm/load", {"player_id": user["id"]})
        self._changed("messages")
        return convo

    def mark_read(self, user_id):
        convo = self.conversations.get(user_id)
        if convo and convo["unread"]:
            convo["unread"] = 0
            self._changed("messages")

    def close_conversation(self):
        self.open_conversation = None
        self._changed("messages")

    def find_user(self, username, on_found, on_error):
        rest = self.app.rest

        def call():
            # The exact filter is case-sensitive, so fall back to a case-insensitive prefix search.
            for params in ({"username": username}, {"username__istartswith": username, "page_size": 50}):
                r = rest.http.get(f"{OGS}/api/v1/players", params=params, timeout=15)
                r.raise_for_status()
                results = r.json().get("results", [])
                if any(u.get("username", "").lower() == username.lower() for u in results):
                    return results
            return []

        def done(results, error):
            if error:
                on_error(f"Lookup failed: {error}")
                return
            match = next((u for u in results or [] if u.get("username", "").lower() == username.lower()), None)
            if match:
                on_found({"id": match["id"], "username": match["username"]})
            else:
                on_error(f"No player called “{username}”.")

        run_in_background(call, done, self.app.socket.inbox)

    def send_pm(self, user_id, text, on_error):
        convo = self.conversations.get(user_id)
        if not convo or not text.strip():
            return

        def reply(data, error):
            if error or not isinstance(data, dict):
                on_error(f"Not delivered: {error or 'no reply from server'}")
                return
            if self._add_pm(convo, data.get("message") or {}, True):
                self._changed("messages")

        self.app.socket.send("chat/pm", {
            "player_id": user_id,
            "username": convo["user"].get("username", ""),
            "uid": uuid.uuid4().hex[:12],
            "message": text.strip(),
        }, reply)

    @property
    def unread(self):
        return sum(c["unread"] for c in self.conversations.values())

    # ------------------------------------------------------------------ lobby chat
    @property
    def channel_name(self):
        return CHANNEL_NAMES.get(self.channel, self.channel)

    def join_lobby(self):
        if not self.lobby_joined:
            self.lobby_joined = True
            self.app.socket.join_channel(self.channel)

    def set_channel(self, channel):
        """Leaves the current room and joins another; the server sends its recent backlog."""
        if channel == self.channel or channel not in CHANNEL_NAMES:
            return
        if self.lobby_joined:
            self.app.socket.leave_channel(self.channel)
        self.channel = channel
        self.lobby = []
        self._lobby_ids = set()
        self.lobby_ready = False
        settings.save(lobby_channel=channel)
        self.lobby_joined = False
        self.join_lobby()
        self._changed("lobby")

    def send_lobby(self, text):
        if text.strip():
            self.app.socket.send("chat/send", {"channel": self.channel, "uuid": uuid.uuid4().hex[:12],
                                               "message": text.strip()})
