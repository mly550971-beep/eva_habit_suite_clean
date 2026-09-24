"""
test_scheduler.py
------------------
Scheduler.tick() and PrayerTimes with the network and pygame mocked out.
Uses a fake clock (no real waiting) so it runs instantly.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adhan import AdhanHooks, AdhanPlayer  # noqa: E402
from config import Config, _DEFAULTS  # noqa: E402
from prayer_times import PrayerTimes, compute_times, format_remaining_ar, format_time_ar  # noqa: E402
from scheduler import Scheduler  # noqa: E402


def cfg(**overrides):
    data = json.loads(json.dumps(_DEFAULTS))
    data.setdefault("scheduler", {})
    data.setdefault("adhan", {"enabled": True})
    data.setdefault("prayer_times", {})
    for k, v in overrides.items():
        data[k] = v
    return Config(data)


FIXED_TIMES = {"fajr": "05:00", "dhuhr": "12:00", "asr": "15:30", "maghrib": "18:00", "isha": "19:30"}


class TestPrayerTimesCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except FileNotFoundError:
            pass

    def test_cache_roundtrip_and_location_change_invalidates(self):
        # A date always inside _save_cache()'s 3-day retention window,
        # computed relative to the real today - a hardcoded past date
        # here would silently start failing once more than 3 days had
        # passed since it was written (that's exactly what was happening
        # before this fix).
        d = date.today() - timedelta(days=1)

        svc = PrayerTimes(cfg(), mock.Mock(), cache_path=self.tmp.name)
        svc._days[d.isoformat()] = FIXED_TIMES
        svc._save_cache()
        times, source = svc.get(d)
        self.assertEqual((times, source), (FIXED_TIMES, "cache"))

        svc2 = PrayerTimes(cfg(), mock.Mock(), cache_path=self.tmp.name)
        times, source = svc2.get(d)
        self.assertEqual((times, source), (FIXED_TIMES, "cache"))

        # Different city -> cache for the old location must not leak in.
        svc3 = PrayerTimes(cfg(prayer_times={"city": "Alexandria", "country": "Egypt"}), mock.Mock(),
                           cache_path=self.tmp.name)
        _, source3 = svc3.get(d)
        self.assertEqual(source3, "calculated")

    def test_next_prayer_rolls_to_tomorrow(self):
        svc = PrayerTimes(cfg(), mock.Mock(), cache_path=self.tmp.name)
        svc._days = {"2026-09-20": FIXED_TIMES, "2026-09-21": FIXED_TIMES}
        key, when = svc.next_prayer(datetime(2026, 9, 20, 23, 0))
        self.assertEqual((key, when.strftime("%Y-%m-%d %H:%M")), ("fajr", "2026-09-21 05:00"))

    def test_parse_calendar_json_drops_incomplete_days(self):
        from prayer_times import parse_calendar_json
        payload = {"data": [
            {"date": {"gregorian": {"date": "20-09-2026"}},
             "timings": {"Fajr": "04:37 (EET)", "Dhuhr": "11:50 (EET)", "Asr": "15:16 (EET)",
                        "Maghrib": "18:12 (EET)", "Isha": "19:30 (EET)"}},
            {"date": {"gregorian": {"date": "21-09-2026"}}, "timings": {"Fajr": "04:38"}},
        ]}
        days = parse_calendar_json(payload)
        self.assertEqual(list(days), ["2026-09-20"])
        self.assertEqual(days["2026-09-20"]["fajr"], "04:37")

    def test_offline_calc_is_reasonable_and_monotonic(self):
        t = compute_times(date(2026, 9, 20), 27.18, 31.19, 3.0)
        order = [t["fajr"], t["dhuhr"], t["asr"], t["maghrib"], t["isha"]]
        self.assertEqual(order, sorted(order))
        for v in t.values():
            h, m = map(int, v.split(":"))
            self.assertTrue(0 <= h < 24 and 0 <= m < 60)

    def test_formatting(self):
        self.assertEqual(format_time_ar("04:37"), "4:37 ص")
        self.assertEqual(format_time_ar("15:16"), "3:16 م")
        from datetime import timedelta
        self.assertEqual(format_remaining_ar(timedelta(minutes=95)), "1 ساعة و35 دقيقة")
        self.assertEqual(format_remaining_ar(timedelta(minutes=45)), "45 دقيقة")


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.spoken = []
        self.notified = []
        self.logged = []
        self.hooks = AdhanHooks(
            is_speaking=lambda: False,
            stop_speech=lambda: None,
            pause_listening=lambda: None,
            resume_listening=lambda: None,
            is_privacy_mode=lambda: False,
            log=lambda t: self.logged.append(t),
            notify=lambda title, msg: self.notified.append((title, msg)),
        )
        self.config = cfg()
        self.sched = Scheduler(self.config, mock.Mock(), self.hooks, speak=lambda t: self.spoken.append(t))
        self.sched.prayer._days["2026-09-20"] = FIXED_TIMES
        self.play_calls = []
        self.sched.adhan.play = lambda key, manual=False: self.play_calls.append(key)

    def test_adhan_fires_once_within_grace_and_not_early_or_late(self):
        self.sched.tick(datetime(2026, 9, 20, 11, 59, 30))
        self.assertEqual(self.play_calls, [])
        self.sched.tick(datetime(2026, 9, 20, 12, 0, 5))
        self.assertEqual(self.play_calls, ["dhuhr"])
        self.sched.tick(datetime(2026, 9, 20, 12, 0, 30))  # same tick window: no duplicate
        self.assertEqual(self.play_calls, ["dhuhr"])
        self.sched.tick(datetime(2026, 9, 20, 12, 5, 0))  # past grace period: still no duplicate
        self.assertEqual(self.play_calls, ["dhuhr"])

    def test_missed_restart_within_grace_still_fires(self):
        # Eva was closed at 11:59 and reopened at 12:01 - still inside the
        # 120s default grace window from 12:00:00, so it should NOT be skipped.
        self.sched.tick(datetime(2026, 9, 20, 12, 1, 30))
        self.assertEqual(self.play_calls, ["dhuhr"])

    def test_too_late_after_restart_is_not_replayed(self):
        self.sched.tick(datetime(2026, 9, 20, 15, 0, 0))
        self.assertEqual(self.play_calls, [])  # dhuhr long past grace, asr not due yet

    def test_disabled_prayer_is_skipped(self):
        self.config.raw["adhan"]["prayers"] = {"dhuhr": False}
        self.sched.tick(datetime(2026, 9, 20, 12, 0, 5))
        self.assertEqual(self.play_calls, [])

    def test_pre_reminder(self):
        self.config.raw["adhan"]["pre_reminder_minutes"] = 10
        self.sched.tick(datetime(2026, 9, 20, 11, 50, 5))
        self.assertTrue(any("10 دقايق" in s for s in self.spoken))
        self.assertEqual(self.play_calls, [])

    def test_reminder_defers_to_notification_when_busy_or_privacy(self):
        self.hooks.is_speaking = lambda: True
        self.config.raw["scheduler"]["friday_reminder"] = {"enabled": True, "time": "10:00"}
        self.sched.tick(datetime(2026, 9, 18, 10, 0, 5))  # a Friday
        self.assertEqual(self.spoken, [])
        self.assertTrue(self.notified)

    def test_friday_reminder_only_on_friday(self):
        self.config.raw["scheduler"]["friday_reminder"] = {"enabled": True, "time": "10:00"}
        self.sched.tick(datetime(2026, 9, 19, 10, 0, 5))  # Saturday
        self.assertEqual(self.spoken, [])
        self.sched.tick(datetime(2026, 9, 18, 10, 0, 5))  # Friday
        self.assertTrue(any("الكهف" in s for s in self.spoken))

    def test_fired_set_resets_across_days(self):
        self.sched.tick(datetime(2026, 9, 20, 12, 0, 5))
        self.sched.prayer._days["2026-09-21"] = FIXED_TIMES
        self.sched.tick(datetime(2026, 9, 21, 12, 0, 5))
        self.assertEqual(self.play_calls, ["dhuhr", "dhuhr"])


class TestAdhanPlayer(unittest.TestCase):
    def setUp(self):
        self.spoken_off = False
        self.logged = []
        self.notified = []
        self.hooks = AdhanHooks(
            is_speaking=lambda: False, stop_speech=lambda: None,
            pause_listening=lambda: None, resume_listening=lambda: None,
            is_privacy_mode=lambda: False,
            log=lambda t: self.logged.append(t),
            notify=lambda title, msg: self.notified.append((title, msg)),
        )
        self.player = AdhanPlayer(cfg(), mock.Mock(), self.hooks)

    def test_no_file_falls_back_to_youtube(self):
        with mock.patch.object(self.player, "find_audio", return_value=None), \
             mock.patch("adhan.play_on_youtube") as yt:
            result = self.player.play("fajr")
        self.assertEqual(result, "youtube")
        yt.assert_called_once()
        self.assertTrue(any("الفجر" in t for t, _ in self.notified) or
                        any("الفجر" in m for _, m in self.notified))

    def test_disabled_prayer_is_skipped_when_not_manual(self):
        self.player.config.raw["adhan"]["prayers"] = {"dhuhr": False}
        self.assertEqual(self.player.play("dhuhr"), "skipped")

    def test_manual_play_ignores_prayer_toggle(self):
        self.player.config.raw["adhan"]["prayers"] = {"dhuhr": False}
        with mock.patch.object(self.player, "find_audio", return_value=None), \
             mock.patch("adhan.play_on_youtube"):
            self.assertEqual(self.player.play("dhuhr", manual=True), "youtube")

    def test_privacy_mode_skips_when_configured(self):
        self.player.config.raw["adhan"]["respect_privacy_mode"] = True
        self.hooks.is_privacy_mode = lambda: True
        self.assertEqual(self.player.play("dhuhr"), "skipped")

    def test_busy_returns_busy(self):
        self.player._playing.set()
        self.assertEqual(self.player.play("dhuhr"), "busy")


if __name__ == "__main__":
    unittest.main()
