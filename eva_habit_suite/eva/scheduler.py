"""
scheduler.py
------------
ONE background clock for everything Eva should do by herself at a given
time, instead of every feature starting its own thread:

  * Adhan at each prayer time (see adhan.py / prayer_times.py)
  * Optional spoken reminder N minutes before each prayer
  * Friday reminder for Surat Al-Kahf

Adding another timed feature later = add another small method that is
called from tick(). tick() takes `now` as an argument, which is also what
makes it easy to test without waiting for real prayer times.

Rules that keep it well-behaved:
  * Each event fires at most once per day (de-duplicated by key).
  * An event is only fired if we are within `grace_seconds` (default 120)
    after its time - so restarting Eva at 3 pm doesn't replay the noon
    adhan, but a short sleep/wake around the time still fires it.
  * Reminders are spoken only if Eva is idle and Privacy Mode is off;
    otherwise they are shown as text/notification instead.

Config (all optional):
    scheduler:
      enabled: true
      tick_seconds: 15
      grace_seconds: 120
      friday_reminder: {enabled: true, time: "10:00"}
    adhan:
      pre_reminder_minutes: 0     # e.g. 10 => "adhan of Asr in 10 minutes"
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import adhan as adhan_mod
from adhan import AdhanHooks, AdhanPlayer
from daily_extras import (DownloadsOrganizer, HabitEveningNudge, MorningWeatherAlert,
                          make_eye_rest_reminder, make_water_reminder)
from dnd import get_dnd
from prayer_times import ARABIC_NAMES, PRAYERS, get_service

REFRESH_EVERY_SECONDS = 6 * 3600


class Scheduler:
    def __init__(self, config, logger, hooks: AdhanHooks, speak=None, now_fn=datetime.now):
        self.config = config
        self.logger = logger
        self.hooks = hooks
        self._speak = speak          # callable(text) or None
        self._now = now_fn
        self.prayer = get_service(config, logger)
        self.adhan = AdhanPlayer(config, logger, hooks)
        adhan_mod.set_player(self.adhan)
        self.dnd = get_dnd(config)
        self._water = make_water_reminder()
        self._eyes = make_eye_rest_reminder()
        self._habit_nudge = HabitEveningNudge()
        self._weather_alert = MorningWeatherAlert()
        self._downloads = DownloadsOrganizer()
        self._fired = set()
        self._stop = threading.Event()
        self._thread = None
        self._last_refresh = 0.0

    # ---- settings ----
    def _g(self, *keys, default=None):
        return self.config.get("scheduler", *keys, default=default)

    @property
    def enabled(self) -> bool:
        return bool(self._g("enabled", default=True))

    @property
    def grace(self) -> float:
        return float(self._g("grace_seconds", default=120))

    # ---- lifecycle ----
    def start(self):
        if not self.enabled:
            self.logger.info("[Scheduler] Disabled (scheduler.enabled: false).")
            return
        self._thread = threading.Thread(target=self._loop, name="eva-scheduler", daemon=True)
        self._thread.start()
        self.logger.info("[Scheduler] Started (adhan, reminders).")

    def stop(self):
        self._stop.set()
        try:
            self.adhan.stop()
        except Exception:
            pass

    def _loop(self):
        tick = max(5.0, float(self._g("tick_seconds", default=15)))
        while not self._stop.is_set():
            try:
                self._maybe_refresh()
                self.tick(self._now())
            except Exception as exc:
                self.logger.error(f"[Scheduler] tick error: {exc}")
            self._stop.wait(tick)

    def _maybe_refresh(self):
        if time.time() - self._last_refresh < REFRESH_EVERY_SECONDS:
            return
        self._last_refresh = time.time()
        threading.Thread(target=self.prayer.refresh, name="eva-prayer-refresh", daemon=True).start()

    # ---- the clock ----
    def tick(self, now: datetime):
        today = now.date().isoformat()
        self._fired = {k for k in self._fired if k[0] == today}
        self._prayers(now)
        self._friday(now)
        self._extras(now)

    def _once(self, key) -> bool:
        if key in self._fired:
            return False
        self._fired.add(key)
        return True

    def _within_grace(self, now: datetime, target: datetime) -> bool:
        return 0 <= (now - target).total_seconds() <= self.grace

    def _prayers(self, now: datetime):
        times, source = self.prayer.get(now.date())
        pre_min = int(self.config.get("adhan", "pre_reminder_minutes", default=0) or 0)
        for key in PRAYERS:
            if not self.adhan.prayer_enabled(key):
                continue
            h, m = map(int, times[key].split(":"))
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)

            if pre_min > 0 and self._within_grace(now, t - timedelta(minutes=pre_min)):
                if self._once((now.date().isoformat(), "pre", key)):
                    self._remind(f"فاضل {pre_min} دقايق على أذان {ARABIC_NAMES[key]}.")

            if self.adhan.enabled and self._within_grace(now, t):
                if self._once((now.date().isoformat(), "adhan", key)):
                    self.logger.info(f"[Scheduler] Adhan {key} at {times[key]} (times from {source}).")
                    threading.Thread(target=self.adhan.play, args=(key,), name=f"adhan-{key}", daemon=True).start()

    def _friday(self, now: datetime):
        cfg = self._g("friday_reminder", default={}) or {}
        if not cfg.get("enabled", True) or now.weekday() != 4:
            return
        hh, mm = map(int, str(cfg.get("time", "10:00")).split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if self._within_grace(now, t) and self._once((now.date().isoformat(), "friday", "kahf")):
            self._remind("النهاردة الجمعة، متنساش سورة الكهف والصلاة على النبي.")

    def _fired_once(self, name: str) -> bool:
        return self._once((datetime.now().date().isoformat(), "extra", name))

    def _extras(self, now: datetime):
        """Water / eye-rest / habit nudge / weather / downloads - all muted
        while Do-Not-Disturb or a Pomodoro focus phase is active. Unlike
        _prayers(), DND deliberately does NOT touch the adhan."""
        try:
            import pomodoro
            session = pomodoro.get_session()
            focusing = session is not None and session.is_focus_time()
        except Exception:
            focusing = False
        if self.dnd.is_active(now) or focusing:
            return
        self._water.check(now, self.config, self._remind)
        self._eyes.check(now, self.config, self._remind)
        self._habit_nudge.check(now, self.config, self._remind, self._fired_once)
        self._weather_alert.check(now, self.config, self._remind, self._fired_once)
        self._downloads.check(now, self.config, self._remind, self._fired_once, self.logger)

    def _remind(self, text: str):
        """Speak if Eva is idle, otherwise show it as text/notification."""
        spoke = False
        try:
            busy = self.hooks.is_speaking and self.hooks.is_speaking()
            privacy = self.hooks.is_privacy_mode and self.hooks.is_privacy_mode()
            if self._speak and not busy and not privacy:
                self._speak(text)
                spoke = True
        except Exception as exc:
            self.logger.warning(f"[Scheduler] Could not speak reminder: {exc}")
        if not spoke and self.hooks.notify:
            try:
                self.hooks.notify("Eva", text)
            except Exception:
                pass
        if self.hooks.log:
            try:
                self.hooks.log(f"⏰ {text}")
            except Exception:
                pass


def build_scheduler(ui, config, logger) -> Scheduler:
    """Wires the scheduler to the real Eva window (AgentWindow)."""
    from notifier import notify

    state = {"paused_by_us": False}

    def pause_listening():
        wl = getattr(ui, "wake_word", None)
        if wl is not None and getattr(wl, "_running", False) and not getattr(wl, "_paused", False):
            wl.pause()
            state["paused_by_us"] = True

    def resume_listening():
        if not state["paused_by_us"]:
            return
        state["paused_by_us"] = False
        wl = getattr(ui, "wake_word", None)
        if wl is not None and not getattr(ui, "busy", False) and not getattr(ui, "privacy_mode", False):
            wl.resume()

    hooks = AdhanHooks(
        is_speaking=lambda: bool(ui.tts.is_speaking),
        stop_speech=lambda: ui.tts.stop(),
        pause_listening=pause_listening,
        resume_listening=resume_listening,
        is_privacy_mode=lambda: bool(getattr(ui, "privacy_mode", False)),
        log=lambda text: ui._log_safe(text),
        notify=lambda title, msg: notify(title, msg, logger),
    )
    return Scheduler(config, logger, hooks, speak=lambda text: ui.tts.speak(text))
