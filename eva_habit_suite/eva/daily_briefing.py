"""
daily_briefing.py
------------------
Speaks a short good-morning greeting (weather-based) once per day at a
configured clock time, without the user asking. This is a lightweight
background thread - it does NOT store or track scheduled reminders (those
remain simple "N minutes from now" timers, see plugins/reminder_tool.py),
it only checks the wall clock and fires a callback once per day.
"""

import threading
from datetime import datetime


class DailyBriefing:
    def __init__(self, config, logger, on_trigger):
        self.config = config
        self.logger = logger
        self.on_trigger = on_trigger
        self._last_fired_date = None
        self._stop_event = threading.Event()
        self._thread = None

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("daily_briefing", "enabled", default=False))

    @property
    def target_time(self) -> str:
        return self.config.get("daily_briefing", "time", default="08:00")

    @property
    def prompt(self) -> str:
        return self.config.get(
            "daily_briefing", "prompt",
            default=(
                "Give the user a short, warm good-morning greeting (2-4 sentences). "
                "Call get_weather and mention today's conditions naturally as part of it."
            ),
        )

    def start(self):
        if not self.enabled:
            self.logger.info("Daily briefing is disabled (daily_briefing.enabled: false).")
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.logger.info(f"Daily briefing scheduled for {self.target_time} every day.")

    def stop(self):
        self._stop_event.set()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                if now.strftime("%H:%M") == self.target_time and self._last_fired_date != now.date():
                    self._last_fired_date = now.date()
                    self.logger.info("Daily briefing time reached - triggering greeting.")
                    self.on_trigger(self.prompt)
            except Exception as exc:
                self.logger.error(f"Daily briefing loop error: {exc}")
            self._stop_event.wait(20)
