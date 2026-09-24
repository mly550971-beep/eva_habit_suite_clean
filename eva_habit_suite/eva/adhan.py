"""
adhan.py
--------
Plays the adhan. Design points:

* Uses pygame's Sound/Channel API, NOT pygame.mixer.music - Eva's text-to-
  speech uses the music stream, so the adhan can never cut speech off (or
  be cut off by it) by accident.
* Audio source, in order:
    1. data/adhan/adhan_fajr.mp3 (Fajr only, if present)
    2. data/adhan/adhan.mp3      (any prayer)
    3. fallback (config adhan.fallback): "youtube" -> opens an adhan video
       in the browser, or "speak" -> only announces it by voice.
  Put your own mp3 files in data/adhan/ for an offline, ad-free adhan.
* It has priority over everything: it waits (up to 20 s) for Eva to finish
  the sentence she is saying, then plays. Wake-word listening is paused
  while it plays so Eva doesn't "hear" the adhan and respond to it.
* Stop it any time: say "وقف الأذان" / "اسكت", or press the emergency
  hotkey (Ctrl+Alt+K).

Config (all optional):
    adhan:
      enabled: true
      volume: 0.8              # 0.0 - 1.0
      fade_in_seconds: 3
      fallback: "youtube"      # or "speak"
      prayers: {fajr: true, dhuhr: true, asr: true, maghrib: true, isha: true}
      respect_privacy_mode: false   # true = text notification only while Privacy Mode is on
"""

from __future__ import annotations

import os
import threading
import time

from prayer_times import ARABIC_NAMES
from web_helpers import play_on_youtube

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADHAN_DIR = os.path.join(_BASE_DIR, "data", "adhan")


class AdhanHooks:
    """Everything the player needs from the app, as plain callables, so it
    can be tested without a window. Any hook may be None."""

    def __init__(self, is_speaking=None, stop_speech=None, pause_listening=None,
                 resume_listening=None, is_privacy_mode=None, log=None, notify=None):
        self.is_speaking = is_speaking
        self.stop_speech = stop_speech
        self.pause_listening = pause_listening
        self.resume_listening = resume_listening
        self.is_privacy_mode = is_privacy_mode
        self.log = log
        self.notify = notify


class AdhanPlayer:
    def __init__(self, config, logger, hooks: AdhanHooks = None):
        self.config = config
        self.logger = logger
        self.hooks = hooks or AdhanHooks()
        self._channel = None
        self._sound = None
        self._lock = threading.Lock()
        self._playing = threading.Event()
        self._cancel = threading.Event()

    # ---- settings ----
    def _g(self, *keys, default=None):
        return self.config.get("adhan", *keys, default=default)

    @property
    def enabled(self) -> bool:
        return bool(self._g("enabled", default=True))

    def prayer_enabled(self, key: str) -> bool:
        return bool(self._g("prayers", key, default=True))

    @property
    def is_playing(self) -> bool:
        return self._playing.is_set()

    # ---- helpers ----
    def find_audio(self, prayer_key: str):
        candidates = []
        if prayer_key == "fajr":
            candidates.append(os.path.join(ADHAN_DIR, "adhan_fajr.mp3"))
        candidates.append(os.path.join(ADHAN_DIR, "adhan.mp3"))
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    def _say(self, text: str):
        if self.hooks.log:
            try:
                self.hooks.log(text)
            except Exception:
                pass

    def _wait_for_quiet(self, max_seconds: float = 20.0):
        """Lets Eva finish her sentence; after `max_seconds` takes over anyway."""
        h = self.hooks
        if not h.is_speaking:
            return
        try:
            waited = 0.0
            while h.is_speaking() and waited < max_seconds:
                time.sleep(0.5)
                waited += 0.5
            if h.is_speaking() and h.stop_speech:
                h.stop_speech()
        except Exception:
            pass

    # ---- main entry ----
    def play(self, prayer_key: str, manual: bool = False) -> str:
        """Plays the adhan for `prayer_key`. Blocks until it finishes (call
        from a worker thread). Returns a short status string:
        'played' | 'youtube' | 'spoken' | 'skipped' | 'busy'."""
        name = ARABIC_NAMES.get(prayer_key, "")
        if not manual and (not self.enabled or not self.prayer_enabled(prayer_key)):
            return "skipped"
        if self.is_playing:
            return "busy"

        privacy = False
        try:
            privacy = bool(self.hooks.is_privacy_mode and self.hooks.is_privacy_mode())
        except Exception:
            pass
        if privacy and not manual and self._g("respect_privacy_mode", default=False):
            self._notify(f"حان موعد أذان {name}", "Privacy Mode شغال فمتشغلش الصوت.")
            return "skipped"

        self._notify("Eva", f"حان الآن موعد أذان {name}")
        self._say(f"🕌 حان الآن موعد أذان {name}")

        path = self.find_audio(prayer_key)
        if path:
            return self._play_file(path)

        if str(self._g("fallback", default="youtube")).lower() == "youtube":
            query = "أذان الفجر" if prayer_key == "fajr" else "أذان الحرم المكي"
            try:
                play_on_youtube(query)
                self._say("(مفيش ملف أذان في data/adhan - فتحت أذان على يوتيوب)")
                return "youtube"
            except Exception as exc:
                self.logger.warning(f"[Adhan] YouTube fallback failed: {exc}")
        return "spoken"

    def _notify(self, title, message):
        if self.hooks.notify:
            try:
                self.hooks.notify(title, message)
            except Exception:
                pass

    def _play_file(self, path: str) -> str:
        import pygame

        with self._lock:
            if self._playing.is_set():
                return "busy"
            self._playing.set()
            self._cancel.clear()
        paused_listening = False
        try:
            self._wait_for_quiet()
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._sound = pygame.mixer.Sound(path)
            volume = max(0.0, min(1.0, float(self._g("volume", default=0.8))))
            self._sound.set_volume(volume)
            fade_ms = int(float(self._g("fade_in_seconds", default=3)) * 1000)
            if self.hooks.pause_listening:
                try:
                    self.hooks.pause_listening()
                    paused_listening = True
                except Exception:
                    pass
            self._channel = self._sound.play(fade_ms=fade_ms)
            if self._channel is None:
                self.logger.warning("[Adhan] No free mixer channel - adhan not played.")
                return "spoken"
            self.logger.info(f"[Adhan] Playing {os.path.basename(path)} (volume {volume}).")
            while self._channel is not None and self._channel.get_busy() and not self._cancel.is_set():
                time.sleep(0.3)
            return "played"
        except Exception as exc:
            self.logger.warning(f"[Adhan] Could not play '{path}': {exc}")
            return "spoken"
        finally:
            try:
                if self._channel is not None:
                    self._channel.stop()
            except Exception:
                pass
            self._channel = None
            self._sound = None
            self._playing.clear()
            if paused_listening and self.hooks.resume_listening:
                try:
                    self.hooks.resume_listening()
                except Exception:
                    pass

    def stop(self) -> bool:
        """Stops the adhan if it is playing. Returns True if something was stopped."""
        was = self._playing.is_set()
        self._cancel.set()
        try:
            if self._channel is not None:
                self._channel.fadeout(800)
        except Exception:
            pass
        return was


# One player per process, so voice commands and the scheduler share state.
_PLAYER = None


def set_player(player: AdhanPlayer):
    global _PLAYER
    _PLAYER = player


def get_player(config=None, logger=None):
    """The shared player, creating a standalone one (no UI hooks) if the
    scheduler hasn't been started - enough for "شغل الأذان" to work."""
    global _PLAYER
    if _PLAYER is None and config is not None and logger is not None:
        _PLAYER = AdhanPlayer(config, logger)
    return _PLAYER
