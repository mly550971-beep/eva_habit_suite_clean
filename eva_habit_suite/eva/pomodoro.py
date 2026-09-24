"""
pomodoro.py
-----------
A minimal Pomodoro session: focus_minutes of quiet work, then a spoken
break reminder, repeated for the requested number of rounds (default 4).

Design:
  * Plain state machine + one timer thread per running session - no
    dependency on scheduler.py, so it works even if the scheduler is
    disabled.
  * While a session is "focus" phase, Eva enters Privacy-Mode-like quiet:
    the caller (voice command handler) is responsible for actually pausing
    non-adhan reminders by checking `session.is_focus_time()` - this module
    only tracks state and fires the phase-change callback.
  * Only one session at a time per process. Starting a new one while one
    is running replaces it (the old one is cancelled first).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta


class PomodoroSession:
    def __init__(self, focus_minutes: int = 25, break_minutes: int = 5, rounds: int = 4,
                 on_phase_change=None):
        self.focus_minutes = focus_minutes
        self.break_minutes = break_minutes
        self.rounds = max(1, rounds)
        self.on_phase_change = on_phase_change  # callable(phase, round_no, rounds)
        self.phase = "idle"        # idle | focus | break | done | cancelled
        self.round_no = 0
        self.phase_ends_at = None
        self._timer = None
        self._lock = threading.Lock()

    def is_focus_time(self) -> bool:
        return self.phase == "focus"

    def status_text(self) -> str:
        if self.phase in ("idle", "cancelled", "done"):
            return "مفيش جلسة تركيز شغالة دلوقتي."
        remaining = max(0, int(((self.phase_ends_at - datetime.now()).total_seconds())) // 60) + 1
        label = "شغل" if self.phase == "focus" else "راحة"
        return f"جولة {self.round_no} من {self.rounds}: وقت {label}، باقي حوالي {remaining} دقيقة."

    def start(self):
        with self._lock:
            self._cancel_timer()
            self.round_no = 1
            self.phase = "idle"
        self._begin_focus()

    def cancel(self) -> bool:
        with self._lock:
            was_running = self.phase in ("focus", "break")
            self._cancel_timer()
            self.phase = "cancelled"
        return was_running

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _fire(self, phase):
        if self.on_phase_change:
            try:
                self.on_phase_change(phase, self.round_no, self.rounds)
            except Exception:
                pass

    def _begin_focus(self):
        with self._lock:
            self.phase = "focus"
            self.phase_ends_at = datetime.now() + timedelta(minutes=self.focus_minutes)
            self._cancel_timer()
            self._timer = threading.Timer(self.focus_minutes * 60, self._on_focus_end)
            self._timer.daemon = True
            self._timer.start()
        self._fire("focus")

    def _on_focus_end(self):
        with self._lock:
            if self.phase != "focus":
                return  # cancelled meanwhile
            self.phase = "break"
            self.phase_ends_at = datetime.now() + timedelta(minutes=self.break_minutes)
            self._timer = threading.Timer(self.break_minutes * 60, self._on_break_end)
            self._timer.daemon = True
            self._timer.start()
        self._fire("break")

    def _on_break_end(self):
        with self._lock:
            if self.phase != "break":
                return
            if self.round_no >= self.rounds:
                self.phase = "done"
                done = True
            else:
                self.round_no += 1
                done = False
        if done:
            self._fire("done")
        else:
            self._begin_focus()


# One session per process, shared between voice commands.
_SESSION = None


def get_session() -> "PomodoroSession | None":
    return _SESSION


def start_session(focus_minutes=25, break_minutes=5, rounds=4, on_phase_change=None) -> PomodoroSession:
    global _SESSION
    if _SESSION is not None:
        _SESSION.cancel()
    _SESSION = PomodoroSession(focus_minutes, break_minutes, rounds, on_phase_change)
    _SESSION.start()
    return _SESSION


def cancel_session() -> bool:
    global _SESSION
    if _SESSION is None:
        return False
    return _SESSION.cancel()
