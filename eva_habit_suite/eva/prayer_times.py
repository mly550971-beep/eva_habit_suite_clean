"""
prayer_times.py
---------------
Daily prayer times for one location, built to keep working when the
internet doesn't:

  1. Cache (data/prayer_times.json) - a whole month is saved at once.
  2. aladhan.com public API (free, no key). Default calculation method 5 =
     Egyptian General Authority of Survey.
  3. Built-in astronomical calculation (Egyptian angles: Fajr 19.5 deg,
     Isha 17.5 deg, Asr shafi'i). Used ONLY when there is no cached/API
     value for that day; it is typically within 1-3 minutes of the
     published tables, and it is flagged as approximate.

get() never touches the network (so the scheduler loop can call it every
few seconds); refresh() does the network work and is meant for a
background thread.

Config (all optional - defaults target Asyut, Egypt):
    prayer_times:
      city: "Asyut"
      country: "Egypt"
      latitude: 27.18        # used for the offline calculation and, if
      longitude: 31.19       # use_coordinates is true, for the API too
      use_coordinates: false
      method: 5              # 5 = Egyptian General Authority of Survey
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from datetime import date, datetime, timedelta

import requests

PRAYERS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
API_KEYS = {"fajr": "Fajr", "dhuhr": "Dhuhr", "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}
ARABIC_NAMES = {"fajr": "الفجر", "dhuhr": "الظهر", "asr": "العصر", "maghrib": "المغرب", "isha": "العشاء"}

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------ offline calculation ---
# Standard solar-position method (same formulas the widely used
# "praytimes" library uses).

def _rad(d):
    return math.radians(d)


def _deg(r):
    return math.degrees(r)


def _fix_angle(a):
    return a - 360.0 * math.floor(a / 360.0)


def _fix_hour(h):
    return h - 24.0 * math.floor(h / 24.0)


def _julian(y, m, d):
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def _sun_position(jd):
    d = jd - 2451545.0
    g = _fix_angle(357.529 + 0.98560028 * d)
    q = _fix_angle(280.459 + 0.98564736 * d)
    L = _fix_angle(q + 1.915 * math.sin(_rad(g)) + 0.020 * math.sin(_rad(2 * g)))
    e = 23.439 - 0.00000036 * d
    ra = _deg(math.atan2(math.cos(_rad(e)) * math.sin(_rad(L)), math.cos(_rad(L)))) / 15.0
    eqt = q / 15.0 - _fix_hour(ra)
    decl = _deg(math.asin(math.sin(_rad(e)) * math.sin(_rad(L))))
    return decl, eqt


def compute_times(day: date, lat: float, lng: float, tz_hours: float,
                  fajr_angle: float = 19.5, isha_angle: float = 17.5) -> dict:
    """{'fajr': 'HH:MM', ...} for `day` at (lat, lng), local timezone offset tz_hours."""
    jd = _julian(day.year, day.month, day.day) - lng / (15.0 * 24.0)
    decl, eqt = _sun_position(jd + 0.5)
    noon = _fix_hour(12 - eqt) + (tz_hours - lng / 15.0)

    def before_noon(angle):
        x = (-math.sin(_rad(angle)) - math.sin(_rad(decl)) * math.sin(_rad(lat))) / \
            (math.cos(_rad(decl)) * math.cos(_rad(lat)))
        return noon - _deg(math.acos(max(-1.0, min(1.0, x)))) / 15.0

    def after_noon(angle):
        x = (-math.sin(_rad(angle)) - math.sin(_rad(decl)) * math.sin(_rad(lat))) / \
            (math.cos(_rad(decl)) * math.cos(_rad(lat)))
        return noon + _deg(math.acos(max(-1.0, min(1.0, x)))) / 15.0

    asr_angle = -_deg(math.atan(1.0 / (1 + math.tan(_rad(abs(lat - decl))))))  # shafi'i: shadow = 1x
    raw = {
        "fajr": before_noon(fajr_angle),
        "dhuhr": noon + 1.0 / 60.0,   # +1 minute after zenith, as most tables do
        "asr": after_noon(asr_angle),
        "maghrib": after_noon(0.833),
        "isha": after_noon(isha_angle),
    }
    out = {}
    for k, h in raw.items():
        h = _fix_hour(h + 0.5 / 60.0)  # round to nearest minute
        out[k] = f"{int(h):02d}:{int((h - int(h)) * 60):02d}"
    return out


def _tz_hours_for(day: date) -> float:
    off = datetime(day.year, day.month, day.day, 12).astimezone().utcoffset()
    return (off.total_seconds() / 3600.0) if off is not None else 2.0


# ------------------------------------------------------------ service ---

def parse_hhmm(value: str):
    """'04:37 (EET)' -> '04:37' or None."""
    m = _HHMM.search(str(value or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return f"{h:02d}:{mi:02d}"


def parse_calendar_json(payload: dict) -> dict:
    """aladhan month response -> {'YYYY-MM-DD': {'fajr': 'HH:MM', ...}}.
    Days that don't contain all five prayers are dropped."""
    days = {}
    for item in (payload or {}).get("data", []) or []:
        try:
            dd, mm, yy = str(item["date"]["gregorian"]["date"]).split("-")
            key = f"{int(yy):04d}-{int(mm):02d}-{int(dd):02d}"
            timings = item["timings"]
        except Exception:
            continue
        row = {}
        for k, api_key in API_KEYS.items():
            t = parse_hhmm(timings.get(api_key))
            if t:
                row[k] = t
        if len(row) == 5:
            days[key] = row
    return days


class PrayerTimes:
    def __init__(self, config, logger, cache_path: str = None):
        self.logger = logger
        g = lambda *k, default=None: config.get("prayer_times", *k, default=default)
        self.city = g("city", default="Asyut")
        self.country = g("country", default="Egypt")
        self.lat = float(g("latitude", default=27.18))
        self.lng = float(g("longitude", default=31.19))
        self.use_coordinates = bool(g("use_coordinates", default=False))
        self.method = int(g("method", default=5))
        self.cache_path = cache_path or os.path.join(_BASE_DIR, "data", "prayer_times.json")
        self._lock = threading.Lock()
        self._days = {}          # 'YYYY-MM-DD' -> {'fajr': 'HH:MM', ...} (from API)
        self._load_cache()

    # location key: cached data is only valid for the location it was fetched for
    @property
    def _loc_key(self) -> str:
        if self.use_coordinates:
            return f"coords:{self.lat:.3f},{self.lng:.3f}:m{self.method}"
        return f"city:{self.city},{self.country}:m{self.method}"

    def _load_cache(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("location") == self._loc_key:
                self._days = dict(data.get("days", {}))
        except Exception:
            self._days = {}

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            # keep only recent days so the file stays tiny
            keep_from = (date.today() - timedelta(days=3)).isoformat()
            days = {k: v for k, v in self._days.items() if k >= keep_from}
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"location": self._loc_key, "days": days}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.cache_path)
        except Exception as exc:
            self.logger.debug(f"[PrayerTimes] Could not save cache: {exc}")

    # ---- reading (never networks) ----
    def get(self, day: date):
        """(times_dict, source) where source is 'cache' or 'calculated'."""
        with self._lock:
            row = self._days.get(day.isoformat())
        if row:
            return dict(row), "cache"
        return compute_times(day, self.lat, self.lng, _tz_hours_for(day)), "calculated"

    def next_prayer(self, now: datetime):
        """(key, datetime) of the next prayer after `now` (today, else tomorrow's fajr)."""
        for offset in (0, 1):
            d = (now + timedelta(days=offset)).date()
            times, _src = self.get(d)
            for k in PRAYERS:
                h, m = map(int, times[k].split(":"))
                t = datetime(d.year, d.month, d.day, h, m)
                if t > now:
                    return k, t
        return None, None

    def ensure_today(self):
        """For spoken questions: if today isn't cached yet, try the API once
        (short timeout) before answering; otherwise answers use the offline
        calculation. Runs at most once per day."""
        key = date.today().isoformat()
        if key in self._days or getattr(self, "_tried_day", None) == key:
            return
        self._tried_day = key
        try:
            self.refresh()
        except Exception:
            pass

    # ---- network (background thread) ----
    def _month_url(self, year: int, month: int):
        base = "https://api.aladhan.com/v1"
        if self.use_coordinates:
            return f"{base}/calendar/{year}/{month}", {
                "latitude": self.lat, "longitude": self.lng, "method": self.method}
        return f"{base}/calendarByCity/{year}/{month}", {
            "city": self.city, "country": self.country, "method": self.method}

    def fetch_month(self, year: int, month: int) -> int:
        """Downloads one month into the cache. Returns how many days were stored."""
        url, params = self._month_url(year, month)
        r = requests.get(url, params=params, headers={"User-Agent": "EvaAssistant/1.0"}, timeout=10)
        r.raise_for_status()
        days = parse_calendar_json(r.json())
        if days:
            with self._lock:
                self._days.update(days)
            self._save_cache()
        return len(days)

    def refresh(self) -> bool:
        """Makes sure this month (and next month, when near the end) is cached.
        Returns True if the needed days are available from the API/cache."""
        from calendar import monthrange

        today = date.today()
        targets = [(today.year, today.month)]
        if today.day >= 24:
            nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            targets.append((nxt.year, nxt.month))
        ok = True
        for y, m in targets:
            last = f"{y:04d}-{m:02d}-{monthrange(y, m)[1]:02d}"
            must_have = [last] + ([today.isoformat()] if (y, m) == (today.year, today.month) else [])
            if all(k in self._days for k in must_have):
                continue
            try:
                n = self.fetch_month(y, m)
                self.logger.info(f"[PrayerTimes] Cached {n} day(s) for {y}-{m:02d} ({self._loc_key}).")
                ok = ok and n > 0
            except Exception as exc:
                self.logger.warning(f"[PrayerTimes] Could not fetch {y}-{m:02d}: {exc} - using calculated times.")
                ok = False
        return ok


def format_time_ar(hhmm: str) -> str:
    """'15:26' -> '3:26 م' / '04:37' -> '4:37 ص'."""
    h, m = map(int, hhmm.split(":"))
    suffix = "ص" if h < 12 else "م"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def format_remaining_ar(delta: timedelta) -> str:
    mins = max(0, int(delta.total_seconds() // 60))
    h, m = divmod(mins, 60)
    if h and m:
        return f"{h} ساعة و{m} دقيقة"
    if h:
        return f"{h} ساعة"
    return f"{m} دقيقة"


# One shared instance per process (scheduler + voice commands use the same cache).
_SERVICE = None


def get_service(config, logger) -> PrayerTimes:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PrayerTimes(config, logger)
    return _SERVICE
