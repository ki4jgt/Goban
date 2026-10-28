"""Ambient music and stone sounds, synthesised with numpy.

The music is an 80-second loop: slow, breathing chord pads (Dmaj9 - Bm11 - Gmaj9 -
A6/9), sparse pentatonic bells, a faint wind bed and, in the second half, a quiet
fingerpicked acoustic guitar in the American folk style. Everything is placed into a circular
buffer and convolved with a circular reverb so the loop point is seamless.
It is rendered once and cached. Drop your own .ogg/.mp3/.wav/.flac files into a
`music/` folder (see paths.music_dirs) to play those instead.

If the machine has no usable audio device, the app carries on silently.
"""

import random
import threading
import wave
import numpy as np
import pyglet

from .paths import cache_dir, music_dirs

SR = 32000
CACHE_DIR = cache_dir()
MUSIC_VERSION = 3
MUSIC_EXTENSIONS = {".ogg", ".mp3", ".wav", ".flac", ".m4a"}


def _midi(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def _write_wav(path, stereo):
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(stereo.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    tmp.replace(path)


def _circular_add(buffer, start, signal):
    n = len(buffer)
    idx = (np.arange(len(signal)) + start) % n
    np.add.at(buffer, idx, signal)


def pluck(freq, seconds, rng, brightness=0.6, decay=0.9985):
    """A plucked steel string (Karplus-Strong): a noise burst circulating through a
    delay line with a gentle averaging filter, which loses treble on every pass."""
    period = max(2, int(SR / freq - 0.5))
    n = int(seconds * SR)
    buf = np.zeros(n + period + 1)
    burst = rng.uniform(-1, 1, period + 1)
    for _ in range(int((1 - brightness) * 4)):  # darker pluck: smooth the burst
        burst = 0.5 * (burst + np.roll(burst, 1))
    buf[:period + 1] = burst - burst.mean()  # no DC: the loop would preserve it forever
    i = period + 1
    while i < len(buf):  # each block depends only on the block one period earlier
        end = min(i + period, len(buf))
        buf[i:end] = decay * 0.5 * (buf[i - period:end - period] + buf[i - period - 1:end - period - 1])
        i = end
    # The loop's true period is period + 0.5 samples; resample to land exactly on pitch.
    ratio = (period + 0.5) * freq / SR
    t = np.arange(n) * ratio
    out = np.interp(t, np.arange(len(buf)), buf)
    out *= np.minimum(1, np.arange(n) / (0.002 * SR))
    return out / (np.abs(out).max() + 1e-9)


def render_guitar(chords, seg, start_chord, count, total, rng):
    """Travis-style picking: thumb alternates bass notes while fingers pick the
    upper strings, at an unhurried 66 bpm with a little human timing."""
    left, right = np.zeros(total), np.zeros(total)
    eighth = 60 / 66 / 2
    # (string index into the voicing, is_bass) for one bar of eight eighth notes
    pattern = [(0, True), (3, False), (1, True), (2, False), (0, True), (3, False), (1, True), (2, False)]
    for k in range(count):
        voicing = chords[(start_chord + k) % len(chords)]
        bar_start = (start_chord + k) * seg / SR
        steps = int((seg / SR - 1.5) / eighth)  # leave a breath before the next chord
        for step in range(steps):
            string, bass = pattern[step % len(pattern)]
            if not bass and rng.random() < 0.18:
                continue  # an occasional rest keeps it from sounding mechanical
            when = bar_start + step * eighth + rng.normal(0, 0.012) + (0.035 if step % 2 else 0)
            note = voicing[string]
            tone = pluck(_midi(note), 3.2 if bass else 2.6, rng,
                         brightness=0.35 if bass else 0.6, decay=0.9975 if bass else 0.9988)
            gain = (0.36 if bass else 0.26) * rng.uniform(0.75, 1.0)
            pan = 0.38 if bass else 0.30
            start = int(when * SR) % total
            _circular_add(left, start, tone * gain * np.sqrt(1 - pan))
            _circular_add(right, start, tone * gain * np.sqrt(pan))
    return left, right


def render_ambient(seconds_per_chord=10.0, cycles=2):
    rng = np.random.default_rng(11)
    chords = [
        [50, 57, 64, 66, 69],  # D  A  E  F# A
        [47, 54, 61, 62, 66],  # B  F# C# D  F#
        [43, 50, 57, 59, 66],  # G  D  A  B  F#
        [45, 52, 59, 61, 64],  # A  E  B  C# E
    ]
    seg = int(seconds_per_chord * SR)
    total = seg * len(chords) * cycles
    left = np.zeros(total)
    right = np.zeros(total)

    # ---- pads -----------------------------------------------------------
    attack, release = 3.5, 5.0
    length = seg + int(release * SR)
    t = np.arange(length) / SR
    env = np.ones(length)
    a = int(attack * SR)
    env[:a] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a))
    env[seg:] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, length - seg))
    for i in range(len(chords) * cycles):
        chord = chords[i % len(chords)]
        for j, note in enumerate(chord):
            f = _midi(note)
            voice = np.zeros(length)
            for cents in (-7.0, 0.0, 6.0):
                fd = f * 2 ** (cents / 1200)
                phase = rng.uniform(0, 2 * np.pi)
                for h in (1, 2, 3):
                    voice += np.sin(2 * np.pi * fd * h * t + phase * h) / h ** 1.8
            swell = 0.75 + 0.25 * np.sin(2 * np.pi * t / rng.uniform(5, 9) + rng.uniform(0, 6))
            gain = (0.55 if j == 0 else 0.30) / 3
            voice *= env * swell * gain
            pan = 0.5 + (j - 2) * 0.12
            _circular_add(left, i * seg, voice * np.sqrt(1 - pan))
            _circular_add(right, i * seg, voice * np.sqrt(pan))

    # ---- bells --------------------------------------------------------------
    scale = [74, 76, 78, 81, 83, 86, 88, 90]
    bell_len = int(4.5 * SR)
    tb = np.arange(bell_len) / SR
    partials = [(1.0, 1.0, 1.4), (2.01, 0.30, 0.9), (3.98, 0.10, 0.5), (5.43, 0.05, 0.3)]
    when = 1.5
    last = rng.integers(len(scale))
    while when < total / SR - 0.5:
        step = rng.choice([-2, -1, 1, 2, 0, 3, -3])
        last = int(np.clip(last + step, 0, len(scale) - 1))
        f = _midi(scale[last])
        tone = np.zeros(bell_len)
        for ratio, amp, decay in partials:
            tone += amp * np.sin(2 * np.pi * f * ratio * tb) * np.exp(-tb / decay)
        tone *= np.minimum(1, tb / 0.004) * rng.uniform(0.05, 0.11)
        pan = rng.uniform(0.2, 0.8)
        start = int(when * SR)
        _circular_add(left, start, tone * np.sqrt(1 - pan))
        _circular_add(right, start, tone * np.sqrt(pan))
        when += rng.choice([1.25, 1.9, 2.5, 3.2, 4.4, 5.0])

    # ---- fingerpicked guitar, second half only --------------------------------
    voicings = [
        [50, 57, 62, 66],  # D:  D A D F#
        [47, 54, 59, 62],  # Bm: B F# B D
        [43, 50, 55, 59],  # G:  G D G B
        [45, 52, 57, 61],  # A:  A E A C#
    ]
    # its own generator, so the guitar never changes the rest of the piece
    g_left, g_right = render_guitar(voicings, seg, len(chords), len(chords), total, np.random.default_rng(29))
    left += g_left
    right += g_right

    # ---- wind ---------------------------------------------------------------
    for channel in (left, right):
        noise = np.fft.rfft(rng.standard_normal(total))
        freqs = np.fft.rfftfreq(total, 1 / SR)
        noise *= 1 / (1 + (freqs / 350) ** 2)
        wind = np.fft.irfft(noise, total)
        wind /= np.abs(wind).max() + 1e-9
        tt = np.arange(total) / SR
        loop_len = total / SR
        swell = 0.5 + 0.5 * np.sin(2 * np.pi * tt * 4 / loop_len + rng.uniform(0, 6))
        channel += wind * swell * 0.035

    # ---- circular reverb --------------------------------------------------------
    rev_len = int(3.2 * SR)
    tr = np.arange(rev_len) / SR
    out = []
    for channel in (left, right):
        ir = rng.standard_normal(rev_len) * np.exp(-tr / 0.9)
        ir[0] = 0
        ir /= np.sqrt((ir ** 2).sum())
        kernel = np.zeros(total)
        kernel[:rev_len] = ir
        wet = np.fft.irfft(np.fft.rfft(channel) * np.fft.rfft(kernel), total)
        mixed = channel * 0.62 + wet * 0.55
        # gentle low-pass to keep everything soft
        spec = np.fft.rfft(mixed)
        spec *= 1 / (1 + (np.fft.rfftfreq(total, 1 / SR) / 5200) ** 2)
        out.append(np.fft.irfft(spec, total))
    stereo = np.stack(out, axis=1)
    stereo *= 0.55 / (np.abs(stereo).max() + 1e-9)
    return stereo


def render_click(rng, pitch=1.0):
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n) * np.exp(-t / 0.0025)
    body = (np.sin(2 * np.pi * 2100 * pitch * t) * np.exp(-t / 0.018)
            + 0.6 * np.sin(2 * np.pi * 1180 * pitch * t) * np.exp(-t / 0.035)
            + 0.9 * np.sin(2 * np.pi * 190 * pitch * t) * np.exp(-t / 0.03))
    s = noise * 0.5 + body * 0.6
    s *= 0.8 / np.abs(s).max()
    return np.stack([s, s], axis=1)


def render_chime():
    n = int(2.5 * SR)
    t = np.arange(n) / SR
    s = np.zeros(n)
    for k, note in enumerate((78, 83, 86)):
        start = int(k * 0.11 * SR)
        f = _midi(note)
        tone = (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * f * 2.01 * t)) * np.exp(-t / 0.9)
        s[start:] += tone[: n - start]
    s *= 0.35 / np.abs(s).max()
    return np.stack([s, s * 0.9], axis=1)


class Sound:
    """Owns the background music player and short sound effects."""

    def __init__(self):
        self.volume = 0.55
        self.muted = False
        self.player = None
        self._target = 0.0
        self._ready = None
        self._clicks = []
        self._chime = None
        try:
            self._load_effects()
        except Exception as exc:  # no audio device, unwritable cache, ...
            print(f"Sound effects disabled: {exc}")
            return
        threading.Thread(target=self._prepare_music, daemon=True).start()

    def _load_effects(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(3)
        for i, pitch in enumerate((1.0, 0.94, 1.06)):
            path = CACHE_DIR / f"click{i}.wav"
            if not path.exists():
                _write_wav(path, render_click(rng, pitch))
            self._clicks.append(pyglet.media.load(str(path), streaming=False))
        path = CACHE_DIR / "chime.wav"
        if not path.exists():
            _write_wav(path, render_chime())
        self._chime = pyglet.media.load(str(path), streaming=False)

    def _prepare_music(self):
        files = []
        for folder in music_dirs():
            if folder.is_dir():
                files = sorted(p for p in folder.iterdir() if p.suffix.lower() in MUSIC_EXTENSIONS)
                if files:
                    break
        if files:
            random.shuffle(files)
            self._ready = ("playlist", files)
            return
        path = CACHE_DIR / f"ambient_v{MUSIC_VERSION}.wav"
        if not path.exists():
            _write_wav(path, render_ambient())
            for old in CACHE_DIR.glob("ambient_v*.wav"):
                if old != path:
                    old.unlink(missing_ok=True)
        self._ready = ("loop", [path])

    def update(self, dt):
        if self._ready is not None:
            kind, paths = self._ready
            self._ready = None
            self._start_music(kind, paths)
        if self.player is not None:
            target = 0.0 if self.muted else self.volume
            step = dt * 0.15
            v = self.player.volume
            self.player.volume = min(target, v + step) if v < target else max(target, v - step * 3)

    def _start_music(self, kind, paths):
        try:
            self._start_player(kind, paths)
        except Exception as exc:
            print(f"Music disabled: {exc}")
            self.player = None

    def _start_player(self, kind, paths):
        self.player = pyglet.media.Player()
        self.player.volume = 0.0
        if kind == "loop":
            self.player.queue(pyglet.media.load(str(paths[0]), streaming=False))
            self.player.loop = True
        else:
            playlist = list(paths)

            def queue_next():
                path = playlist.pop(0)
                playlist.append(path)
                try:
                    self.player.queue(pyglet.media.load(str(path)))
                except Exception:
                    pass

            queue_next()

            @self.player.event
            def on_player_eos():
                queue_next()
                self.player.play()

        self.player.play()

    def toggle_mute(self):
        self.muted = not self.muted

    def change_volume(self, delta):
        self.volume = float(np.clip(self.volume + delta, 0.0, 1.0))
        self.muted = False

    def click(self):
        if self._clicks:
            p = random.choice(self._clicks).play()
            p.volume = 0.9

    def chime(self):
        if self._chime:
            p = self._chime.play()
            p.volume = 0.7
