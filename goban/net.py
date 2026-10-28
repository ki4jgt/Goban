"""Networking for online-go.com: REST login/challenges and the realtime socket.

The realtime protocol is plain JSON over a websocket:
    client -> server:  [command, data]  or  [command, data, request_id]
    server -> client:  [command, data]  or  [request_id, data, error]

Everything received is handed back to the UI thread through `RealtimeSocket.poll`,
so pyglet objects are never touched from the network thread.
"""

import json
import queue
import random
import threading
import time
import uuid

import certifi
import requests
import websocket

OGS = "https://online-go.com"
WS_URL = "wss://online-go.com/"
USER_AGENT = "PygletGoban/1.0"


class OGSError(Exception):
    pass


def _error_text(response):
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:160]}"
    if isinstance(body, dict):
        for key in ("error", "detail", "errors", "message"):
            if key in body:
                value = body[key]
                if isinstance(value, list):
                    value = " ".join(str(v) for v in value)
                return str(value)
    return f"HTTP {response.status_code}: {str(body)[:160]}"


class RestSession:
    """A cookie session against the OGS web API (the same one the website uses)."""

    def __init__(self):
        self.http = requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT
        self.config = None

    def _headers(self):
        return {"X-CSRFToken": self.http.cookies.get("csrftoken", ""), "Referer": OGS + "/"}

    def fetch_config(self):
        """Returns the UI config, which carries the user record and a socket JWT.
        Anonymous visitors get a guest JWT, which is enough to spectate."""
        r = self.http.get(f"{OGS}/api/v1/ui/config", timeout=15)
        if r.status_code >= 400:
            raise OGSError(_error_text(r))
        self.config = r.json()
        return self.config

    def login(self, username, password):
        if not self.http.cookies.get("csrftoken"):
            self.fetch_config()
        r = self.http.post(
            f"{OGS}/api/v0/login",
            json={"username": username, "password": password},
            headers=self._headers(),
            timeout=20,
        )
        if r.status_code >= 400:
            raise OGSError(_error_text(r))
        config = self.fetch_config()
        if config.get("user", {}).get("anonymous", True):
            raise OGSError("Login was not accepted by the server.")
        return config

    def post(self, path, payload):
        r = self.http.post(OGS + path, json=payload, headers=self._headers(), timeout=20)
        if r.status_code >= 400:
            raise OGSError(_error_text(r))
        return r.json() if r.content else {}

    def delete(self, path):
        r = self.http.delete(OGS + path, headers=self._headers(), timeout=20)
        if r.status_code >= 400:
            raise OGSError(_error_text(r))

    def challenge_player(self, player_id, size, rules="japanese"):
        """Sends a direct, unranked, live challenge. Returns {"challenge": id, "game": id}."""
        time_control = {
            "system": "byoyomi",
            "time_control": "byoyomi",
            "speed": "live",
            "main_time": 300,
            "period_time": 30,
            "periods": 5,
            "pause_on_weekends": False,
        }
        payload = {
            "initialized": False,
            "min_ranking": -1000,
            "max_ranking": 1000,
            "challenger_color": "automatic",
            "game": {
                "name": "Pyglet Goban game",
                "rules": rules,
                "ranked": False,
                "width": size,
                "height": size,
                "handicap": 0,
                "komi_auto": "automatic",
                "komi": None,
                "disable_analysis": False,
                "pause_on_weekends": False,
                "initial_state": None,
                "private": False,
                "time_control": "byoyomi",
                "time_control_parameters": time_control,
            },
        }
        return self.post(f"/api/v1/players/{player_id}/challenge", payload)

    def cancel_challenge(self, challenge_id):
        self.delete(f"/api/v1/me/challenges/{challenge_id}")


def run_in_background(fn, on_done, inbox):
    """Runs fn() on a worker thread; on_done(result, error) is later invoked from
    the UI thread via the socket inbox."""

    def worker():
        try:
            result, error = fn(), None
        except Exception as exc:  # surfaced to the UI as text
            result, error = None, exc
        inbox.put(("_call", lambda: on_done(result, error)))

    threading.Thread(target=worker, daemon=True).start()


class RealtimeSocket:
    def __init__(self):
        self.inbox = queue.Queue()
        self.connected = False
        self._jwt = None
        self._ws = None
        self._thread = None
        self._closing = False
        self._send_lock = threading.Lock()
        self._next_id = 0
        self._callbacks = {}
        self._games = {}  # game id -> wants chat
        self._channels = set()
        self._pending = []

    # ----------------------------------------------------------------- lifecycle
    def start(self, jwt):
        """Connects (or reconnects) and authenticates with the given JWT."""
        self._jwt = jwt
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        elif self._ws is not None:
            self._ws.close()  # the run loop reconnects with the new JWT

    def close(self):
        self._closing = True
        if self._ws is not None:
            self._ws.close()

    def _run(self):
        failures = 0
        while not self._closing:
            started = time.time()
            self._ws = websocket.WebSocketApp(
                WS_URL,
                header={"User-Agent": USER_AGENT},
                on_open=self._on_open,
                on_message=self._on_message,
                on_close=self._on_close,
                on_error=lambda ws, err: None,
            )
            # Use certifi's CA bundle: python.org builds on macOS ship without system certificates.
            self._ws.run_forever(ping_interval=0, sslopt={"ca_certs": certifi.where()})
            if self._closing:
                break
            failures = 0 if time.time() - started > 30 else failures + 1
            time.sleep(min(15.0, 0.5 + failures * 1.5) + random.random())

    def _on_open(self, ws):
        self._raw_send(["authenticate", {
            "jwt": self._jwt,
            "client": "pyglet-goban",
            "client_version": "1.0",
            "user_agent": USER_AGENT,
            "language": "en",
        }])
        for game_id, chat in list(self._games.items()):
            self._raw_send(["game/connect", {"game_id": game_id, "chat": chat}])
        for channel in list(self._channels):
            self._raw_send(["chat/join", {"channel": channel}])
        self.connected = True
        pending, self._pending = self._pending, []
        for message in pending:
            self._raw_send(message)
        self.inbox.put(("_connected", None))

    def _on_close(self, ws, *args):
        self.connected = False
        self.inbox.put(("_disconnected", None))

    def _on_message(self, ws, text):
        try:
            payload = json.loads(text)
        except ValueError:
            return
        if not isinstance(payload, list) or not payload:
            return
        head = payload[0]
        data = payload[1] if len(payload) > 1 else None
        if isinstance(head, int):
            callback = self._callbacks.pop(head, None)
            if callback:
                error = payload[2] if len(payload) > 2 else None
                self.inbox.put(("_call", lambda: callback(data, error)))
        else:
            self.inbox.put((head, data))

    # ------------------------------------------------------------------ messages
    def _raw_send(self, message):
        try:
            with self._send_lock:
                self._ws.send(json.dumps(message))
            return True
        except Exception:
            return False

    def send(self, command, data=None, callback=None):
        message = [command, data]
        if callback is not None:
            self._next_id += 1
            self._callbacks[self._next_id] = callback
            message.append(self._next_id)
        if not (self.connected and self._raw_send(message)):
            self._pending.append(message)

    def poll(self, handler):
        """Drains received events on the calling (UI) thread."""
        while True:
            try:
                command, data = self.inbox.get_nowait()
            except queue.Empty:
                return
            if command == "_call":
                data()
            else:
                handler(command, data)

    def ping(self):
        if self.connected:
            self._raw_send(["net/ping", {"client": int(time.time() * 1000), "drift": 0, "latency": 0}])

    # -------------------------------------------------------------- conveniences
    def connect_game(self, game_id, chat=False):
        self._games[game_id] = chat
        self.send("game/connect", {"game_id": game_id, "chat": chat})

    def disconnect_game(self, game_id):
        if self._games.pop(game_id, None) is not None:
            self.send("game/disconnect", {"game_id": game_id})

    def resync_game(self, game_id):
        """Asks the server for a fresh `gamedata` snapshot."""
        self.send("game/disconnect", {"game_id": game_id})
        self.send("game/connect", {"game_id": game_id, "chat": self._games.get(game_id, False)})

    def join_channel(self, channel):
        self._channels.add(channel)
        self.send("chat/join", {"channel": channel})

    def leave_channel(self, channel):
        if channel in self._channels:
            self._channels.discard(channel)
            self.send("chat/part", {"channel": channel})

    def query_live_games(self, callback, limit=40):
        self.send(
            "gamelist/query",
            {"list": "live", "sort_by": "rank", "where": {}, "from": 0, "limit": limit},
            callback,
        )

    def find_match(self, size, speed):
        match_id = str(uuid.uuid4())
        self.send("automatch/find_match", {
            "uuid": match_id,
            "size_speed_options": [{"size": f"{size}x{size}", "speed": speed, "system": "byoyomi"}],
            "lower_rank_diff": 3,
            "upper_rank_diff": 3,
            "rules": {"condition": "no-preference", "value": "japanese"},
            "handicap": {"condition": "no-preference", "value": "enabled"},
        })
        return match_id

    def cancel_match(self, match_id):
        self.send("automatch/cancel", {"uuid": match_id})
