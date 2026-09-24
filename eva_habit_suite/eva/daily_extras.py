"""
daily_extras.py
----------------
Small, independent scheduled features that all plug into the same
scheduler.py clock (see Scheduler._prayers/_friday for the pattern this
follows). Each one is a plain function called once per tick with `now`;
each keeps its own "already fired" state so adding a new feature never
risks breaking an existing one.

Features:
  * WaterReminder      - "اشرب مية" every N minutes, only inside work hours
  * EyeRestReminder     - 20-20-20 rule: every 20 min, look away for 20 sec
  * HabitEveningNudge   - once a day, lists today's NOT-YET-done habits from
                          the Habit Tracker app's own database (read-only,
                          same file plugins/habit_tracker_tool.py uses)
  * MorningWeatherAlert - once a day, ONLY speaks up if tomorrow-ish
                          conditions are notable (rain or extreme heat) -
                          silent otherwise, so it's not a daily noise source
  * DownloadsOrganizer  - weekly, sorts loose files in ~/Downloads into
                          Images/Videos/Documents/Archives/Installers/Other

All of these respect Do-Not-Disturb (dnd.py) except nothing here is safety
critical, so DND silences all of them (unlike the adhan, which DND does
NOT silence - see scheduler.py).
"""

from __future__ import annotations

import os
import shutil
import threading
from datetime import date, datetime, timedelta

import requests

# ------------------------------------------------------------- helpers ---


def _g(config, section, *keys, default=None):
    return config.get(section, *keys, default=default)


def _in_window(now: datetime, start: str, end: str) -> bool:
    """True if now's clock time is within [start, end) - both 'HH:MM'.
    Handles a window that crosses midnight (e.g. 22:00-06:00)."""
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    t = now.hour * 60 + now.minute
    s, e = sh * 60 + sm, eh * 60 + em
    if s <= e:
        return s <= t < e
    return t >= s or t < e


# --------------------------------------------------------- water / eyes ---

class IntervalReminder:
    """Fires at most once every `interval_minutes`, only inside a daily
    time window, only on a real clock (so restarting Eva mid-interval
    doesn't immediately fire) - tracks the next due time itself."""

    def __init__(self, section: str, default_minutes: int, message: str):
        self.section = section
        self.default_minutes = default_minutes
        self.message = message
        self._next_due = None

    def _enabled(self, config) -> bool:
        return bool(_g(config, self.section, "enabled", default=True))

    def _interval(self, config) -> int:
        return int(_g(config, self.section, "interval_minutes", default=self.default_minutes))

    def _window(self, config):
        return (_g(config, self.section, "start", default="09:00"),
                _g(config, self.section, "end", default="23:00"))

    def check(self, now: datetime, config, remind_fn):
        if not self._enabled(config):
            self._next_due = None
            return
        start, end = self._window(config)
        if not _in_window(now, start, end):
            self._next_due = None  # re-arm cleanly for the next window
            return
        if self._next_due is None:
            self._next_due = now + timedelta(minutes=self._interval(config))
            return
        if now >= self._next_due:
            self._next_due = now + timedelta(minutes=self._interval(config))
            remind_fn(self.message)


def make_water_reminder() -> IntervalReminder:
    return IntervalReminder("water_reminder", 60, "خد بريك واشرب شوية مية 💧")


def make_eye_rest_reminder() -> IntervalReminder:
    return IntervalReminder(
        "eye_rest_reminder", 20,
        "قاعدة العشرين: بص بعيد عن الشاشة على حاجة على بعد 20 قدم لمدة 20 ثانية 👀",
    )


# ---------------------------------------------------------- habit nudge ---

def _habit_db_path(config) -> str:
    return (config.get("integrations", "habit_tracker", "db_path", default="") or "").strip()


def pending_habits_today(db_path: str, today: date = None):
    """[names] of today's habits not yet marked done. [] if the DB/tables
    don't exist yet or the feature just has nothing pending - callers can't
    tell those apart from an empty list, which is fine: both mean 'say
    nothing'. Raises only for programmer errors, never for a missing file."""
    import sqlite3

    if not db_path or not os.path.isfile(db_path):
        return []
    today = today or date.today()
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name FROM habits ORDER BY display_order")
            habits = cur.fetchall()
            if not habits:
                return []
            cur.execute(
                "SELECT habit_id FROM habit_logs WHERE log_date = ? AND completed = 1",
                (today.isoformat(),),
            )
            done_ids = {row[0] for row in cur.fetchall()}
            return [name for hid, name in habits if hid not in done_ids]
        finally:
            conn.close()
    except Exception:
        return []


class HabitEveningNudge:
    def __init__(self):
        pass

    def check(self, now: datetime, config, remind_fn, fired_once):
        if not bool(config.get("habit_reminder", "enabled", default=True)):
            return
        target = str(config.get("habit_reminder", "time", default="21:00"))
        hh, mm = map(int, target.split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (0 <= (now - t).total_seconds() <= 120):
            return
        if not fired_once("habit_nudge"):
            return
        pending = pending_habits_today(_habit_db_path(config), now.date())
        if not pending:
            return  # everything done (or tracker not set up) - stay quiet
        names = "، ".join(pending[:5])
        extra = f" وكمان {len(pending) - 5}" if len(pending) > 5 else ""
        remind_fn(f"لسه ماعملتش: {names}{extra}.")


# -------------------------------------------------------- weather alert ---

def fetch_daily_outlook(lat: float, lng: float, timeout: float = 8.0):
    """{'max_temp': float C, 'rain_chance': int 0-100} for today, or None."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat, "longitude": lng,
                    "daily": "temperature_2m_max,precipitation_probability_max",
                    "timezone": "auto", "forecast_days": 1},
            timeout=timeout,
        )
        r.raise_for_status()
        d = r.json()["daily"]
        return {"max_temp": d["temperature_2m_max"][0], "rain_chance": d["precipitation_probability_max"][0]}
    except Exception:
        return None


def outlook_message(outlook: dict, heat_c: float, rain_pct: int):
    """Returns a spoken warning, or None if nothing is notable enough."""
    if outlook is None:
        return None
    parts = []
    if outlook.get("rain_chance") is not None and outlook["rain_chance"] >= rain_pct:
        parts.append(f"احتمال مطر {int(outlook['rain_chance'])}%")
    if outlook.get("max_temp") is not None and outlook["max_temp"] >= heat_c:
        parts.append(f"الحرارة هتوصل {round(outlook['max_temp'])} درجة")
    if not parts:
        return None
    return "تنبيه من الطقس النهاردة: " + "، ".join(parts) + "."


class MorningWeatherAlert:
    def check(self, now: datetime, config, remind_fn, fired_once):
        if not bool(config.get("weather_alert", "enabled", default=True)):
            return
        target = str(config.get("weather_alert", "time", default="07:00"))
        hh, mm = map(int, target.split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (0 <= (now - t).total_seconds() <= 120):
            return
        if not fired_once("weather_alert"):
            return
        lat = float(config.get("prayer_times", "latitude", default=27.18))
        lng = float(config.get("prayer_times", "longitude", default=31.19))
        heat_c = float(config.get("weather_alert", "heat_threshold_c", default=38))
        rain_pct = int(config.get("weather_alert", "rain_threshold_percent", default=50))

        def run():
            outlook = fetch_daily_outlook(lat, lng)
            msg = outlook_message(outlook, heat_c, rain_pct)
            if msg:
                remind_fn(msg)

        threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------- downloads organizer -

EXT_FOLDERS = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv"},
    "Documents": {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".csv", ".md"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".exe", ".msi", ".apk"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
}


def organize_folder(folder: str) -> dict:
    """Moves loose files in `folder` (not already in a category subfolder)
    into Images/Videos/Documents/.../Other. Returns {category: count}.
    Skips anything already inside one of the destination subfolders, so
    running it twice is harmless. Never raises - a per-file failure (locked
    file, permissions) is skipped and counted separately under '_errors'."""
    counts = {}
    if not os.path.isdir(folder):
        return counts
    known_dirs = set(EXT_FOLDERS) | {"Other"}
    for entry in os.listdir(folder):
        full = os.path.join(folder, entry)
        if not os.path.isfile(full):
            continue
        if entry.startswith("."):
            continue
        ext = os.path.splitext(entry)[1].lower()
        category = next((cat for cat, exts in EXT_FOLDERS.items() if ext in exts), "Other")
        dest_dir = os.path.join(folder, category)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, entry)
            if os.path.exists(dest):
                stem, ext2 = os.path.splitext(entry)
                dest = os.path.join(dest_dir, f"{stem}_{int(datetime.now().timestamp())}{ext2}")
            shutil.move(full, dest)
            counts[category] = counts.get(category, 0) + 1
        except Exception:
            counts["_errors"] = counts.get("_errors", 0) + 1
    _ = known_dirs
    return counts


class DownloadsOrganizer:
    def check(self, now: datetime, config, remind_fn, fired_once, logger=None):
        if not bool(config.get("downloads_organizer", "enabled", default=False)):
            return
        weekday = int(config.get("downloads_organizer", "weekday", default=4))  # 4 = Friday
        target = str(config.get("downloads_organizer", "time", default="12:00"))
        if now.weekday() != weekday:
            return
        hh, mm = map(int, target.split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (0 <= (now - t).total_seconds() <= 120):
            return
        if not fired_once("downloads_organizer"):
            return
        folder = config.get("downloads_organizer", "folder", default="") or \
            os.path.join(os.path.expanduser("~"), "Downloads")

        def run():
            counts = organize_folder(folder)
            total = sum(v for k, v in counts.items() if k != "_errors")
            if logger:
                logger.info(f"[DownloadsOrganizer] {folder}: {counts}")
            if total:
                parts = ", ".join(f"{v} {k}" for k, v in counts.items() if k != "_errors")
                remind_fn(f"رتبت مجلد التنزيلات: {parts}.")

        threading.Thread(target=run, daemon=True).start()
