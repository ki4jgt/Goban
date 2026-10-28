"""Board state reconstructed from OGS gamedata, plus a few formatting helpers."""

import math
import time

EMPTY, BLACK, WHITE = 0, 1, 2
COLUMN_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"


def other(color):
    return BLACK if color == WHITE else WHITE


def decode_coords(packed):
    """'ddpp' -> [(3, 3), (15, 15)]; '..' (pass) entries are skipped."""
    coords = []
    for i in range(0, len(packed or "") - 1, 2):
        pair = packed[i:i + 2]
        if pair != "..":
            coords.append((ord(pair[0]) - 97, ord(pair[1]) - 97))
    return coords


def encode_coords(coords):
    return "".join(chr(97 + x) + chr(97 + y) for x, y in coords)


def encode_move(x, y):
    return ".." if x < 0 else chr(97 + x) + chr(97 + y)


def format_rank(rank, professional=False):
    if rank is None:
        return ""
    r = int(math.floor(rank))
    if professional and r >= 37:
        return f"{r - 36}p"
    if r < 30:
        return f"{30 - r}k"
    return f"{r - 29}d"


def format_seconds(seconds):
    seconds = max(0, seconds)
    if seconds >= 86400:
        return f"{int(seconds // 86400)}d {int(seconds % 86400 // 3600)}h"
    if seconds >= 3600:
        return f"{int(seconds // 3600)}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d}"
    if seconds < 10:
        return f"{seconds:0.1f}"
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


class GameState:
    def __init__(self, gamedata):
        self.id = gamedata.get("game_id")
        self.width = gamedata.get("width", 19)
        self.height = gamedata.get("height", 19)
        self.name = gamedata.get("game_name", "")
        self.players = gamedata.get("players", {})
        self.black_id = gamedata.get("black_player_id") or self.players.get("black", {}).get("id")
        self.white_id = gamedata.get("white_player_id") or self.players.get("white", {}).get("id")
        self.komi = gamedata.get("komi", 0)
        self.rules = gamedata.get("rules", "")
        self.handicap = gamedata.get("handicap", 0) or 0
        self.free_handicap = gamedata.get("free_handicap_placement", False)
        self.allow_self_capture = gamedata.get("allow_self_capture", False)
        self.initial_player = BLACK if gamedata.get("initial_player", "black") == "black" else WHITE
        self.phase = gamedata.get("phase", "play")
        self.outcome = gamedata.get("outcome", "")
        self.winner = gamedata.get("winner")
        self.time_control = gamedata.get("time_control", {}) or {}
        self.removed = set(decode_coords(gamedata.get("removed", "")))

        self.board = [[EMPTY] * self.width for _ in range(self.height)]
        initial = gamedata.get("initial_state") or {}
        for x, y in decode_coords(initial.get("black", "")):
            self.board[y][x] = BLACK
        for x, y in decode_coords(initial.get("white", "")):
            self.board[y][x] = WHITE

        self.moves = []
        self.captures = {BLACK: 0, WHITE: 0}
        for move in gamedata.get("moves", []):
            self.play(move[0], move[1])

    # --------------------------------------------------------------------- rules
    def color_for(self, index):
        first = self.initial_player
        if self.free_handicap and self.handicap > 1 and first == BLACK:
            if index < self.handicap:
                return BLACK
            index -= self.handicap
            first = WHITE
        return first if index % 2 == 0 else other(first)

    @property
    def to_move(self):
        return self.color_for(len(self.moves))

    @property
    def last_move(self):
        if self.moves and self.moves[-1][0] >= 0:
            return self.moves[-1][:2]
        return None

    def neighbors(self, x, y):
        if x > 0:
            yield x - 1, y
        if x < self.width - 1:
            yield x + 1, y
        if y > 0:
            yield x, y - 1
        if y < self.height - 1:
            yield x, y + 1

    def group(self, x, y):
        """Returns (stones, liberties) for the chain containing (x, y)."""
        color = self.board[y][x]
        stones, liberties, frontier = {(x, y)}, set(), [(x, y)]
        while frontier:
            cx, cy = frontier.pop()
            for nx, ny in self.neighbors(cx, cy):
                c = self.board[ny][nx]
                if c == EMPTY:
                    liberties.add((nx, ny))
                elif c == color and (nx, ny) not in stones:
                    stones.add((nx, ny))
                    frontier.append((nx, ny))
        return stones, liberties

    def play(self, x, y):
        """Applies the next move; returns (color, captured_coords)."""
        color = self.color_for(len(self.moves))
        self.moves.append((x, y, color))
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return color, []
        self.board[y][x] = color
        captured = []
        for nx, ny in self.neighbors(x, y):
            if self.board[ny][nx] == other(color):
                stones, liberties = self.group(nx, ny)
                if not liberties:
                    captured.extend(stones)
        if not captured:
            stones, liberties = self.group(x, y)
            if not liberties and self.allow_self_capture:
                captured = list(stones)
                self.captures[other(color)] += len(captured)
                for sx, sy in captured:
                    self.board[sy][sx] = EMPTY
                return color, captured
        for sx, sy in set(captured):
            self.board[sy][sx] = EMPTY
        captured = list(set(captured))
        self.captures[color] += len(captured)
        return color, captured

    # ----------------------------------------------------------------- players
    def player(self, color):
        return self.players.get("black" if color == BLACK else "white", {})

    def color_of_player(self, player_id):
        if player_id is None:
            return None
        if player_id == self.black_id:
            return BLACK
        if player_id == self.white_id:
            return WHITE
        return None

    def result_text(self):
        if self.phase != "finished":
            return ""
        if self.winner == self.black_id:
            who = "Black"
        elif self.winner == self.white_id:
            who = "White"
        else:
            return f"Game over — {self.outcome}" if self.outcome else "Game over"
        outcome = self.outcome or ""
        if outcome.lower() in ("resignation", "timeout", "disconnection", "abandonment", "cancellation"):
            return f"{who} wins by {outcome.lower()}"
        if outcome:
            return f"{who} wins by {outcome}"
        return f"{who} wins"


class Clock:
    """Tracks a `game/:id/clock` payload and renders each side's remaining time.

    The authoritative countdown for the player on move is `expiration - server_now`;
    the waiting player's stored values are static until they move."""

    def __init__(self):
        self.data = None
        self.offset_ms = 0.0

    def update(self, data):
        self.data = data
        if data.get("now"):
            self.offset_ms = data["now"] - time.time() * 1000

    def server_now(self):
        return time.time() * 1000 + self.offset_ms

    def text(self, color, time_control, paused=False):
        if not self.data:
            return ""
        key = "black_time" if color == BLACK else "white_time"
        entry = self.data.get(key)
        player_id = self.data.get("black_player_id" if color == BLACK else "white_player_id")
        on_move = self.data.get("current_player") == player_id
        system = (time_control or {}).get("system") or (time_control or {}).get("time_control")
        period_time = (entry or {}).get("period_time") if isinstance(entry, dict) else None
        period_time = period_time or (time_control or {}).get("period_time")

        if on_move and not paused and self.data.get("expiration"):
            remaining = (self.data["expiration"] - self.server_now()) / 1000.0
            if system == "byoyomi" and isinstance(entry, dict) and period_time:
                periods = entry.get("periods", 0)
                byo = periods * period_time
                if remaining > byo:
                    return f"{format_seconds(remaining - byo)}  +{periods}×{period_time}s"
                current = max(1, math.ceil(remaining / period_time))
                left = remaining - (current - 1) * period_time
                return f"{current}×  {format_seconds(left)}"
            return format_seconds(remaining)

        if isinstance(entry, dict):
            thinking = entry.get("thinking_time", 0) or 0
            if system == "byoyomi" and period_time:
                periods = entry.get("periods", 0)
                if thinking > 0:
                    return f"{format_seconds(thinking)}  +{periods}×{period_time}s"
                return f"{periods}×  {format_seconds(period_time)}"
            if system == "canadian" and thinking <= 0:
                return f"{format_seconds(entry.get('block_time', 0))} / {entry.get('moves_left', 0)}"
            return format_seconds(thinking)
        if isinstance(entry, (int, float)):
            if entry > 1e11:  # an absolute deadline in ms
                return format_seconds((entry - self.server_now()) / 1000.0)
            return format_seconds(entry)
        return ""

    def seconds_left_on_move(self):
        if not self.data or not self.data.get("expiration"):
            return None
        return (self.data["expiration"] - self.server_now()) / 1000.0
