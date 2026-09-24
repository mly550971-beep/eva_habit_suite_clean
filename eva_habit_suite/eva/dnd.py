"""
dnd.py
------
Do-Not-Disturb: silences the *non-critical* reminders added in
daily_extras.py (water, eye rest, habit nudge, weather alert, downloads).
It deliberately does NOT silence the adhan (see scheduler.py, which checks
DND itself only for the extras, not for adhan.play) - prayer time isn't
something a "don't nag me" mode should suppress.

Two ways DND turns on:
  * Manually: "متزعجنيش" / "وضع مش مزعج" (until "زعجني تاني" or midnight,
    whichever first - so it can never accidentally stay on for days).
  * Scheduled quiet hours from config, e.g. sleeping hours.

is_active() is what daily_extras / scheduler check before speaking.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


class DoNotDisturb:
    def __init__(self, config):
        self.config = config
        self._manual_until = None  # datetime or None

    def _quiet_hours(self):
        cfg = self.config.get("do_not_disturb", "quiet_hours", default=None)
        if not cfg or not cfg.get("enabled", False):
            return None
        return cfg.get("start", "23:00"), cfg.get("end", "07:00")

    def _in_quiet_hours(self, now: datetime) -> bool:
        window = self._quiet_hours()
        if not window:
            return False
        start, end = window
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        t = now.hour * 60 + now.minute
        s, e = sh * 60 + sm, eh * 60 + em
        return (s <= t or t < e) if s > e else (s <= t < e)

    def enable(self, now: datetime = None, hours: float = None):
        now = now or datetime.now()
        if hours is None:
            # default: until the end of the day, so it can never linger
            until = now.replace(hour=23, minute=59, second=59)
        else:
            until = now + timedelta(hours=hours)
        self._manual_until = until

    def disable(self):
        self._manual_until = None

    def is_manually_on(self, now: datetime = None) -> bool:
        now = now or datetime.now()
        return self._manual_until is not None and now < self._manual_until

    def is_active(self, now: datetime = None) -> bool:
        now = now or datetime.now()
        if self._manual_until is not None and now >= self._manual_until:
            self._manual_until = None  # auto-expire
        return self.is_manually_on(now) or self._in_quiet_hours(now)


# One instance per process, shared between the scheduler and voice commands.
_DND = None


def get_dnd(config=None) -> DoNotDisturb:
    global _DND
    if _DND is None and config is not None:
        _DND = DoNotDisturb(config)
    return _DND
