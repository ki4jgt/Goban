"""The application window: owns the network, sound, backdrop and the active scene."""

import os
import sys

import pyglet
from pyglet.graphics import Group
from pyglet.window import key

from .art import Art
from .audio import Sound
from .backdrop import Backdrop
from .drawer import Drawer, Toasts
from .messaging import Messaging
from .net import RealtimeSocket, RestSession, run_in_background
from .notify import desktop_notify
from .paths import ICON_DIR
from .scenes import GameScene, LobbyScene, LoginOverlay
from .ui import MUTED, Button, label

WINDOW_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
MIN_SIZE = (960, 640)


def gl_configs():
    """Configs to try, best first. pyglet 2 needs an OpenGL 3.3 context; macOS only
    grants a modern (core) context when asked for a forward-compatible one."""
    core = dict(major_version=3, minor_version=3, double_buffer=True)
    if sys.platform == "darwin":
        core["forward_compatible"] = True
    return [pyglet.gl.Config(sample_buffers=1, samples=4, **core), pyglet.gl.Config(**core), None]


def window_size():
    """1440x900 where it fits, otherwise most of the screen (small laptops, high-DPI scaling)."""
    try:
        screen = pyglet.canvas.get_display().get_default_screen()
        sw, sh = screen.width, screen.height
    except Exception:
        return 1280, 800
    return max(MIN_SIZE[0], min(1440, int(sw * 0.92))), max(MIN_SIZE[1], min(900, int(sh * 0.86)))


class App(pyglet.window.Window):
    def __init__(self):
        width, height = window_size()
        settings = dict(width=width, height=height, caption="Goban · online-go.com", resizable=True)
        for config in gl_configs():
            try:
                super().__init__(config=config, **settings)
                break
            except (pyglet.window.NoSuchConfigException, pyglet.gl.ContextException):
                if config is None:
                    raise
        self.set_minimum_size(*MIN_SIZE)
        try:
            screen = self.screen
            self.set_location(screen.x + (screen.width - width) // 2,
                              screen.y + max(0, (screen.height - height) // 2))
        except Exception:
            pass
        if hasattr(self, "set_wm_class"):  # X11: lets launchers match the window to goban.desktop
            self.set_wm_class("Goban")
        self._set_icon()

        self.t = 0.0
        self.art = Art()
        self.sound = Sound()
        self.rest = RestSession()
        self.socket = RealtimeSocket()
        self.user = None
        self.bots = {}
        self.active_games = {}
        self.active = True  # window has focus; otherwise alerts also go to the desktop
        self.messaging = Messaging(self)
        self.drawer = Drawer(self)
        self.toasts = Toasts(self)

        self.backdrop = Backdrop(self.art)
        self.hud_batch = pyglet.graphics.Batch()
        self.hud = label("", 16, 12, 9, self.hud_batch, Group(order=0), color=MUTED, alpha=170)
        self.alerts_btn = Button("Alerts", lambda: self.drawer.toggle("alerts"), self.hud_batch, 2,
                                 style="ghost", font_size=10)
        self.messages_btn = Button("Messages", lambda: self.drawer.toggle("messages"), self.hud_batch, 2,
                                   style="ghost", font_size=10)
        self.chat_btn = Button("Lobby chat", lambda: self.drawer.toggle("lobby"), self.hud_batch, 2,
                               style="ghost", font_size=10)
        self.hud_buttons = [self.chat_btn, self.messages_btn, self.alerts_btn]
        self.curtain = pyglet.shapes.Rectangle(0, 0, 10, 10, color=(0, 0, 0), batch=self.hud_batch,
                                               group=Group(order=10))
        self.lobby = LobbyScene(self)
        self.scene = self.lobby
        self.overlay = None

        pyglet.clock.schedule_interval(self.update, 1 / 60)
        pyglet.clock.schedule_interval(lambda dt: self.socket.ping(), 20)
        run_in_background(self.rest.fetch_config, self._on_config, self.socket.inbox)

    def _set_icon(self):
        images = []
        for size in WINDOW_ICON_SIZES:
            path = ICON_DIR / f"goban-{size}.png"
            if path.exists():
                images.append(pyglet.image.load(str(path)))
        if images:
            self.set_icon(*images)

    # ------------------------------------------------------------------ account
    @property
    def signed_in(self):
        return bool(self.user) and not self.user.get("anonymous", True)

    def _on_config(self, config, error):
        if error:
            self.hud.text = f"Could not reach online-go.com: {error}"
            pyglet.clock.schedule_once(
                lambda dt: run_in_background(self.rest.fetch_config, self._on_config, self.socket.inbox), 10)
            return
        self._adopt(config)
        username, password = os.environ.get("OGS_USERNAME"), os.environ.get("OGS_PASSWORD")
        if username and password:
            self.login(username, password, lambda error: None)

    def _adopt(self, config):
        previous = (self.user or {}).get("id")
        self.user = config.get("user") or {}
        if self.user.get("id") != previous:
            self.messaging.reset()
        self.active_games = {}
        self.socket.start(config.get("user_jwt"))
        self.lobby.refresh_account()

    def login(self, username, password, callback):
        def done(config, error):
            if error:
                callback(str(error))
                return
            self._adopt(config)
            callback(None)

        run_in_background(lambda: self.rest.login(username, password), done, self.socket.inbox)

    def sign_out(self):
        self.rest = RestSession()
        self.user = None
        self.lobby.match_id = None
        run_in_background(self.rest.fetch_config, self._on_config, self.socket.inbox)
        self.lobby.refresh_account()

    def show_login(self):
        self.overlay = LoginOverlay(self)
        self.overlay.resize(self.width, self.height)

    def close_login(self):
        self.overlay = None

    # ------------------------------------------------------------ messages/alerts
    def alert(self, title, body, action=None, desktop=False):
        """Pops a toast (and a desktop notification when the window is in the background)."""
        self.toasts.push(title, body, action)
        self.sound.chime()
        if desktop:
            self.notify_desktop(title, body)

    def notify_desktop(self, title, body):
        if not self.active:
            desktop_notify(title, body)

    def show_drawer(self, view, select=None):
        self.drawer.show(view, select)

    def show_conversation(self, user_id):
        convo = self.messaging.conversations.get(user_id)
        if convo:
            self.drawer.open_user(convo["user"])

    def refresh_hud(self):
        alerts, unread = len(self.messaging.notifications), self.messaging.unread
        self.alerts_btn.set_text(f"Alerts  {alerts}" if alerts else "Alerts")
        self.alerts_btn.set_style("normal" if alerts else "ghost")
        self.messages_btn.set_text(f"Messages  {unread}" if unread else "Messages")
        self.messages_btn.set_style("primary" if unread else "ghost")
        for name, btn in (("alerts", self.alerts_btn), ("messages", self.messages_btn), ("lobby", self.chat_btn)):
            btn.set_selected(self.drawer.is_open and self.drawer.tab == name)

    def _layout_hud(self):
        x = self.width - 16
        for btn, w in ((self.alerts_btn, 86), (self.messages_btn, 104), (self.chat_btn, 96)):
            x -= w
            btn.set_rect(x, 8, w, 26)
            x -= 6

    # ------------------------------------------------------------------- scenes
    def open_game(self, game_id, challenge_id=None):
        if self.scene is not self.lobby:
            self.scene.close()
        else:
            self.lobby.suspend()
        self.scene = GameScene(self, game_id, challenge_id)
        self.scene.resize(self.width, self.height)

    def show_lobby(self):
        if self.scene is self.lobby:
            return
        self.scene.close()
        self.scene = self.lobby
        self.lobby.resume()
        self.lobby.resize(self.width, self.height)

    # ------------------------------------------------------------------- events
    def on_server_event(self, command, data):
        if command == "active-bots" and isinstance(data, dict):
            self.bots = data
            self.lobby.refresh_bots()
        elif command == "active_game" and isinstance(data, dict) and "id" in data:
            if data.get("phase") == "finished":
                self.active_games.pop(data["id"], None)
            else:
                self.active_games[data["id"]] = data
            self.lobby.refresh_mine()
        elif command == "automatch/start" and isinstance(data, dict):
            self.lobby.match_id = None
            self.sound.chime()
            self.open_game(data["game_id"])
        elif command == "automatch/cancel":
            self.lobby.on_match_cancelled()
        self.messaging.on_event(command, data)
        self.scene.on_event(command, data)

    def update(self, dt):
        self.t += dt
        self.socket.poll(self.on_server_event)
        self.sound.update(dt)
        self.backdrop.update(dt, self.t)
        if self.curtain.visible:
            # opening fade from black
            fade = max(0.0, 1 - max(0.0, self.t - 0.3) / 2.2)
            self.curtain.opacity = int(255 * fade ** 2)
            self.curtain.visible = fade > 0
        self.scene.update(dt, self.t)
        self.drawer.update(self.t)
        self.toasts.update(dt)
        self.refresh_hud()
        if self.overlay:
            self.overlay.update(dt, self.t)
        if not self.hud.text.startswith("Could not"):
            link = "connected" if self.socket.connected else "connecting…"
            music = "muted" if self.sound.muted else f"music {int(self.sound.volume * 100)}%"
            text = f"•  {link}     {music}  ·  M mute  ·  +/− volume  ·  F11 fullscreen"
            if self.hud.text != text:
                self.hud.text = text
            self.hud.color = (130, 220, 160, 190) if self.socket.connected else (*MUTED, 170)

    def on_draw(self):
        self.clear()
        self.backdrop.draw()
        self.scene.draw()
        self.drawer.draw()
        self.toasts.draw()
        self.hud_batch.draw()
        if self.overlay:
            self.overlay.draw()

    def on_resize(self, width, height):
        super().on_resize(width, height)
        self.backdrop.resize(width, height)
        self.curtain.width, self.curtain.height = width, height
        self.scene.resize(width, height)
        self.drawer.resize(width, height)
        self._layout_hud()
        if self.overlay:
            self.overlay.resize(width, height)

    def on_activate(self):
        self.active = True

    def on_deactivate(self):
        self.active = False

    def typing(self):
        """True while a text field has focus, so letter shortcuts stay out of the way."""
        scene_field = getattr(self.scene, "focused_field", lambda: None)()
        return bool(self.overlay or self.drawer.focused_field() or scene_field)

    def on_mouse_motion(self, x, y, dx, dy):
        self.backdrop.set_pointer(x, y)
        if self.overlay:
            self.overlay.on_mouse_motion(x, y)
            return
        for btn in self.hud_buttons:
            btn.on_mouse_motion(x, y)
        self.drawer.on_mouse_motion(x, y)
        self.scene.on_mouse_motion(x, y)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.on_mouse_motion(x, y, dx, dy)

    def on_mouse_press(self, x, y, button, modifiers):
        if self.overlay:
            self.overlay.on_mouse_press(x, y, button)
            return
        if self.toasts.on_mouse_press(x, y):
            return
        for btn in self.hud_buttons:
            if btn.on_mouse_press(x, y):
                return
        if self.drawer.contains(x, y):
            self.drawer.on_mouse_press(x, y)
            return
        self.drawer.blur()
        self.scene.on_mouse_press(x, y, button)

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if self.overlay:
            return
        if self.drawer.contains(x, y):
            self.drawer.on_mouse_scroll(x, y, scroll_y)
        else:
            self.scene.on_mouse_scroll(x, y, scroll_y)

    def on_text(self, text):
        if self.overlay:
            self.overlay.on_text(text)
        elif self.drawer.focused_field():
            self.drawer.on_text(text)
        elif hasattr(self.scene, "on_text"):
            self.scene.on_text(text)

    def on_text_motion(self, motion):
        if self.overlay:
            self.overlay.on_text_motion(motion)
        elif self.drawer.focused_field():
            self.drawer.on_text_motion(motion)
        elif hasattr(self.scene, "on_text_motion"):
            self.scene.on_text_motion(motion)

    def on_key_press(self, symbol, modifiers):
        # Cmd+Q on macOS, Ctrl+Q elsewhere.
        if symbol == key.Q and modifiers & key.MOD_ACCEL:
            self.on_close()
            return pyglet.event.EVENT_HANDLED
        if sys.platform == "darwin" and symbol == key.F and modifiers & key.MOD_COMMAND and modifiers & key.MOD_CTRL:
            self.set_fullscreen(not self.fullscreen)
            return pyglet.event.EVENT_HANDLED
        if self.overlay:
            self.overlay.on_key(symbol)
            return pyglet.event.EVENT_HANDLED
        if self.drawer.on_key(symbol):
            return pyglet.event.EVENT_HANDLED
        if self.scene.on_key(symbol):
            return pyglet.event.EVENT_HANDLED
        if self.typing():
            return pyglet.event.EVENT_HANDLED
        if symbol == key.F11:
            self.set_fullscreen(not self.fullscreen)
        elif symbol == key.M:
            self.sound.toggle_mute()
        elif symbol in (key.PLUS, key.EQUAL, key.NUM_ADD):
            self.sound.change_volume(0.1)
        elif symbol in (key.MINUS, key.NUM_SUBTRACT):
            self.sound.change_volume(-0.1)
        return pyglet.event.EVENT_HANDLED  # never let Esc close the window

    def on_close(self):
        if self.lobby.match_id:
            self.socket.cancel_match(self.lobby.match_id)
        self.scene.close()
        self.socket.close()
        super().on_close()


def main():
    if sys.platform == "win32":
        # Give the process its own taskbar identity so Windows shows our icon
        # rather than grouping the window under python.exe.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OGS.Goban")
        except (AttributeError, OSError):
            pass
    App()
    pyglet.app.run()
