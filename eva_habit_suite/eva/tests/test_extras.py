"""
test_extras.py
--------------
Covers daily_extras.py (water/eye reminders, habit nudge, weather alert,
downloads organizer), dnd.py, pomodoro.py, and their media_router voice
commands. No real network, filesystem access is via tempfile only.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import daily_extras as de  # noqa: E402
import dnd as dnd_mod  # noqa: E402
import media_router  # noqa: E402
import pomodoro  # noqa: E402
from config import Config, _DEFAULTS  # noqa: E402


def cfg(**overrides):
    data = json.loads(json.dumps(_DEFAULTS))
    for k, v in overrides.items():
        data[k] = v
    return Config(data)


def reset_singletons():
    dnd_mod._DND = None
    pomodoro._SESSION = None


class TestIntervalReminder(unittest.TestCase):
    def setUp(self):
        self.msgs = []
        self.remind = lambda t: self.msgs.append(t)

    def test_fires_after_interval_inside_window(self):
        r = de.make_water_reminder()
        c = cfg(water_reminder={"enabled": True, "interval_minutes": 60, "start": "09:00", "end": "23:00"})
        t0 = datetime(2026, 9, 20, 10, 0)
        r.check(t0, c, self.remind)           # arms, no fire yet
        self.assertEqual(self.msgs, [])
        r.check(t0 + timedelta(minutes=30), c, self.remind)
        self.assertEqual(self.msgs, [])
        r.check(t0 + timedelta(minutes=61), c, self.remind)
        self.assertEqual(len(self.msgs), 1)

    def test_outside_window_never_fires(self):
        r = de.make_eye_rest_reminder()
        c = cfg(eye_rest_reminder={"enabled": True, "interval_minutes": 20, "start": "09:00", "end": "18:00"})
        r.check(datetime(2026, 9, 20, 23, 0), c, self.remind)
        r.check(datetime(2026, 9, 21, 0, 30), c, self.remind)
        self.assertEqual(self.msgs, [])

    def test_disabled(self):
        r = de.make_water_reminder()
        c = cfg(water_reminder={"enabled": False})
        for _ in range(3):
            r.check(datetime(2026, 9, 20, 12, 0), c, self.remind)
        self.assertEqual(self.msgs, [])


class TestHabitNudge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        conn = sqlite3.connect(self.tmp.name)
        conn.execute("CREATE TABLE habits (id INTEGER PRIMARY KEY, name TEXT, display_order INTEGER)")
        conn.execute("CREATE TABLE habit_logs (habit_id INTEGER, log_date TEXT, completed INTEGER)")
        conn.executemany("INSERT INTO habits VALUES (?,?,?)",
                         [(1, "قراءة", 1), (2, "رياضة", 2), (3, "مذاكرة", 3)])
        conn.execute("INSERT INTO habit_logs VALUES (1, '2026-09-20', 1)")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_pending_excludes_completed(self):
        from datetime import date
        pending = de.pending_habits_today(self.tmp.name, date(2026, 9, 20))
        self.assertEqual(pending, ["رياضة", "مذاكرة"])

    def test_missing_db_returns_empty(self):
        self.assertEqual(de.pending_habits_today("/no/such/file.db"), [])

    def test_scheduler_speaks_only_once_and_only_at_time(self):
        nudge = de.HabitEveningNudge()
        fired = set()

        def fired_once(name):
            if name in fired:
                return False
            fired.add(name)
            return True

        msgs = []
        c = cfg(habit_reminder={"enabled": True, "time": "21:00"},
                integrations={"habit_tracker": {"db_path": self.tmp.name}})
        nudge.check(datetime(2026, 9, 20, 20, 0), c, msgs.append, fired_once)
        self.assertEqual(msgs, [])
        nudge.check(datetime(2026, 9, 20, 21, 0, 30), c, msgs.append, fired_once)
        self.assertEqual(len(msgs), 1)
        self.assertIn("رياضة", msgs[0])
        nudge.check(datetime(2026, 9, 20, 21, 1), c, msgs.append, fired_once)
        self.assertEqual(len(msgs), 1)  # not fired twice


class TestWeatherAlert(unittest.TestCase):
    def test_message_only_when_notable(self):
        self.assertIsNone(de.outlook_message({"max_temp": 30, "rain_chance": 10}, 38, 50))
        self.assertIn("مطر", de.outlook_message({"max_temp": 30, "rain_chance": 80}, 38, 50))
        self.assertIn("الحرارة", de.outlook_message({"max_temp": 42, "rain_chance": 0}, 38, 50))
        self.assertIsNone(de.outlook_message(None, 38, 50))

    def test_scheduler_fires_once_at_time(self):
        alert = de.MorningWeatherAlert()
        fired = set()
        fired_once = lambda name: fired.add(name) or True if name not in fired else False
        c = cfg(weather_alert={"enabled": True, "time": "07:00"})
        with mock.patch("daily_extras.fetch_daily_outlook", return_value={"max_temp": 40, "rain_chance": 0}):
            msgs = []
            alert.check(datetime(2026, 9, 20, 7, 0, 5), c, msgs.append, fired_once)
            import time
            time.sleep(0.05)  # the call runs in a thread
            self.assertTrue(any("الحرارة" in m for m in msgs))


class TestDownloadsOrganizer(unittest.TestCase):
    def test_moves_files_into_categories_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.jpg", "b.pdf", "c.zip", "d.xyz"):
                open(os.path.join(d, name), "w").close()
            counts = de.organize_folder(d)
            self.assertEqual(counts, {"Images": 1, "Documents": 1, "Archives": 1, "Other": 1})
            self.assertTrue(os.path.isfile(os.path.join(d, "Images", "a.jpg")))
            # second run: nothing loose left, so nothing to move
            counts2 = de.organize_folder(d)
            self.assertEqual(counts2, {})

    def test_missing_folder_is_harmless(self):
        self.assertEqual(de.organize_folder("/no/such/dir"), {})


class TestDND(unittest.TestCase):
    def test_manual_on_off(self):
        d = dnd_mod.DoNotDisturb(cfg())
        now = datetime(2026, 9, 20, 10, 0)
        self.assertFalse(d.is_active(now))
        d.enable(now=now)
        self.assertTrue(d.is_active(now))
        d.disable()
        self.assertFalse(d.is_active(now))

    def test_manual_hours_auto_expires(self):
        d = dnd_mod.DoNotDisturb(cfg())
        now = datetime(2026, 9, 20, 10, 0)
        d.enable(now=now, hours=1)
        self.assertTrue(d.is_active(now + timedelta(minutes=59)))
        self.assertFalse(d.is_active(now + timedelta(minutes=61)))

    def test_end_of_day_default_never_leaks_to_next_day(self):
        d = dnd_mod.DoNotDisturb(cfg())
        now = datetime(2026, 9, 20, 23, 0)
        d.enable(now=now)
        self.assertTrue(d.is_active(now))
        self.assertFalse(d.is_active(now + timedelta(hours=2)))

    def test_quiet_hours_crossing_midnight(self):
        c = cfg(do_not_disturb={"quiet_hours": {"enabled": True, "start": "23:00", "end": "07:00"}})
        d = dnd_mod.DoNotDisturb(c)
        self.assertTrue(d.is_active(datetime(2026, 9, 20, 23, 30)))
        self.assertTrue(d.is_active(datetime(2026, 9, 21, 3, 0)))
        self.assertFalse(d.is_active(datetime(2026, 9, 21, 10, 0)))


class TestPomodoro(unittest.TestCase):
    def test_phase_transitions_via_manual_advance(self):
        events = []
        session = pomodoro.PomodoroSession(focus_minutes=25, break_minutes=5, rounds=2,
                                           on_phase_change=lambda p, r, t: events.append((p, r, t)))
        session.start()
        self.assertEqual(session.phase, "focus")
        self.assertEqual(events[-1], ("focus", 1, 2))

        session._on_focus_end()
        self.assertEqual(session.phase, "break")
        self.assertEqual(events[-1], ("break", 1, 2))

        session._on_break_end()
        self.assertEqual(session.phase, "focus")
        self.assertEqual(session.round_no, 2)

        session._on_focus_end()
        session._on_break_end()
        self.assertEqual(session.phase, "done")
        self.assertEqual(events[-1], ("done", 2, 2))

    def test_cancel_stops_timers(self):
        session = pomodoro.PomodoroSession(focus_minutes=60)
        session.start()
        self.assertTrue(session.cancel())
        self.assertEqual(session.phase, "cancelled")
        self.assertFalse(session.cancel())  # already stopped

    def test_start_session_replaces_previous(self):
        reset_singletons()
        s1 = pomodoro.start_session(focus_minutes=60)
        s2 = pomodoro.start_session(focus_minutes=60)
        self.assertEqual(s1.phase, "cancelled")
        self.assertEqual(s2.phase, "focus")
        pomodoro.cancel_session()


class TestVoiceCommands(unittest.TestCase):
    def setUp(self):
        reset_singletons()
        self.config = cfg()
        self.logger = mock.Mock()

    def tearDown(self):
        pomodoro.cancel_session()
        reset_singletons()

    def route(self, text):
        return media_router.try_route(text, self.config, self.logger)

    def test_dnd_toggle(self):
        r = self.route("متزعجنيش")
        self.assertIn("مش مزعج", r)
        self.assertTrue(dnd_mod.get_dnd(self.config).is_active())
        r2 = self.route("زعجني تاني")
        self.assertIn("رجعت", r2)
        self.assertFalse(dnd_mod.get_dnd(self.config).is_active())

    def test_dnd_with_hours(self):
        self.route("متزعجنيش 2 ساعه")
        d = dnd_mod.get_dnd(self.config)
        self.assertTrue(d.is_active(datetime.now() + timedelta(hours=1)))
        self.assertFalse(d.is_active(datetime.now() + timedelta(hours=3)))

    def test_pomodoro_start_stop_status(self):
        with mock.patch("notifier.notify"):
            r = self.route("ابدا بومودورو")
        self.assertIn("تركيز", r)
        self.assertEqual(pomodoro.get_session().phase, "focus")
        status = self.route("فاضل قد ايه")
        self.assertIn("جولة", status)
        r2 = self.route("وقف بومودورو")
        self.assertIn("وقفت", r2)

    def test_pomodoro_custom_rounds(self):
        with mock.patch("notifier.notify"):
            self.route("ابدا بومودورو 6")
        self.assertEqual(pomodoro.get_session().rounds, 6)

    def test_organize_command(self):
        with mock.patch("daily_extras.organize_folder", return_value={"Images": 2}) as fn:
            r = self.route("رتب التنزيلات")
        self.assertIn("تنزيلات", r)
        import time
        time.sleep(0.05)
        fn.assert_called_once()

    def test_dnd_does_not_hijack_unrelated_phrases(self):
        self.assertIsNone(self.route("مش عايز ازعجك بس محتاج مساعدة"))


if __name__ == "__main__":
    unittest.main()
