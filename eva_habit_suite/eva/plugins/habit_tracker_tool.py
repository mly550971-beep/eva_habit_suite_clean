"""
plugins/habit_tracker_tool.py
-------------------------------
Lets Eva read and write directly to the SAME SQLite database the user's
separate Habit Tracker desktop app (PyQt6) uses, and (action='open')
launch that app directly - a plain subprocess of its own main.py, run
from its own folder, exactly like double-clicking it yourself. This is
NOT a merge into one program and is NOT routed through the generic
open_any_application tool: no Windows "find an installed app by name"
lookup, no permissions.open_apps allow-list, no extra confirmation
dialog - just start the sibling habit_tracker/main.py next to this
project, the same way run_both.py does.

The two stay independent processes that happen to share one file on
disk (habit_tracker.db). Anything written here shows up in the Habit
Tracker app exactly as if the user had done it there themselves - fully
visible and editable in its own UI, never kept separately "inside" Eva -
and with that app's own auto-refresh (a 2-second mtime check on the
database file), within about 2 seconds if it's already open. So "open
Habit Tracker, mark X done" opens the window (if it wasn't already open)
and writes the check-mark to the database in the same turn; the window
then shows it ticked on its own within that ~2 second window - nothing
further is needed to make that happen.

Deliberately does NOT create the database's tables itself. The real
schema (see that app's Database._create_tables /
_migrate_flexible_habits) has grown several columns over time via
migrations; duplicating and maintaining that here would drift out of
sync. Instead this assumes the Habit Tracker app has been run at least
once already (which creates/migrates the file correctly), and fails
with a clear message if the tables aren't there yet.
"""

import os
import sqlite3
import subprocess
import sys
import threading
from datetime import date

from plugins.base import BasePlugin

_lock = threading.Lock()
_proc_lock = threading.Lock()
_habit_tracker_proc = None  # tracks the process WE launched this session


def _numeric_meets_goal(value, daily_goal, direction):
    """Mirrors the Habit Tracker app's own numeric_meets_goal() exactly,
    so a numeric habit checked off here is marked done/not-done under the
    same rule the app itself would use."""
    if daily_goal is None or value is None:
        return value is not None and value > 0
    if direction == "max":
        return value <= daily_goal
    return value >= daily_goal


def _connect(db_path):
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class HabitTrackerPlugin(BasePlugin):
    name = "habit_tracker"

    def _db_path(self, config) -> str:
        return (config.get("integrations", "habit_tracker", "db_path", default="") or "").strip()

    def is_enabled(self, config) -> bool:
        return bool(config.get("integrations", "habit_tracker", "enabled", default=False)) and bool(self._db_path(config))

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Opens, reads from, or writes to the user's separate Habit Tracker app. "
                "action='open': launch the Habit Tracker window itself (does nothing if it's "
                "already open). Use this whenever the user asks to open/show/launch Habit "
                "Tracker, or asks to see a habit change happen live in the app - call 'open' "
                "first, then 'check' in the same turn, so the window is on screen when the "
                "check-mark appears (within a couple of seconds). "
                "action='list': see today's habits and whether each is already done. "
                "action='check': mark a habit done for today (set undo=true to un-mark it "
                "instead); for a numeric habit (e.g. glasses of water), pass value with the "
                "number. action='add': create a brand new habit. Always use 'list' first if "
                "you're not sure of a habit's exact name before calling 'check' on it."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "enum": ["open", "list", "check", "add"]},
                    "habit_name": {
                        "type": "STRING",
                        "description": "The habit's name - required for 'check', and for 'add' this is the new habit's name.",
                    },
                    "value": {
                        "type": "NUMBER",
                        "description": "For 'check' on a numeric habit only - the number logged for today.",
                    },
                    "undo": {
                        "type": "BOOLEAN",
                        "description": "For 'check': true to UN-mark today's entry instead of marking it done.",
                    },
                    "icon": {"type": "STRING", "description": "For 'add' - a single emoji. Optional."},
                    "habit_type": {
                        "type": "STRING",
                        "enum": ["check", "numeric"],
                        "description": "For 'add'. 'check' is a plain yes/no habit (the default); 'numeric' logs a number each day.",
                    },
                    "daily_goal": {
                        "type": "NUMBER",
                        "description": "For 'add' with habit_type 'numeric' - the daily target amount.",
                    },
                    "unit": {
                        "type": "STRING",
                        "description": "For 'add' with habit_type 'numeric' - e.g. 'glasses', 'pages', 'minutes'.",
                    },
                },
                "required": ["action"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not config.get("integrations", "habit_tracker", "enabled", default=False):
            return "Habit Tracker integration is disabled (integrations.habit_tracker.enabled in config.yaml)."
        db_path = self._db_path(config)
        if not db_path:
            return (
                "Habit Tracker integration has no db_path set. Set "
                "integrations.habit_tracker.db_path in config.yaml to the full path of "
                "habit_tracker.db, next to that app's own main.py/exe."
            )

        action = (args.get("action") or "").strip().lower()
        today = date.today().isoformat()

        if action == "open":
            return self._open(db_path)

        with _lock:
            try:
                conn = _connect(db_path)
            except OSError as e:
                return f"Could not open the Habit Tracker database at '{db_path}': {e}"
            try:
                if action == "list":
                    return self._list(conn, today)
                elif action == "check":
                    return self._check(conn, args, today)
                elif action == "add":
                    return self._add(conn, args)
                else:
                    return "Unknown action - use 'open', 'list', 'check', or 'add'."
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    return (
                        "The Habit Tracker database doesn't have its tables yet - open the "
                        "Habit Tracker app once first (it creates/updates them on startup), "
                        "then try again."
                    )
                return f"Habit Tracker database is busy right now, try again in a moment ({e})."
            finally:
                conn.close()

    def _open(self, db_path: str) -> str:
        """Launches habit_tracker/main.py directly as a plain subprocess -
        the same interpreter, from that folder, exactly like running it by
        hand. No Windows app lookup, no permissions.open_apps allow-list,
        no confirmation dialog: this app ships right next to Eva in this
        same project, so opening it needs no more ceremony than opening a
        file Eva already knows the exact location of."""
        global _habit_tracker_proc
        app_dir = os.path.dirname(os.path.abspath(db_path))
        main_py = os.path.join(app_dir, "main.py")
        if not os.path.isfile(main_py):
            return (
                f"Could not find the Habit Tracker app at '{main_py}'. Check "
                "integrations.habit_tracker.db_path in config.yaml - it should point at "
                "habit_tracker.db sitting next to that app's own main.py."
            )
        with _proc_lock:
            if _habit_tracker_proc is not None and _habit_tracker_proc.poll() is None:
                return "Habit Tracker is already open."
            try:
                _habit_tracker_proc = subprocess.Popen([sys.executable, "main.py"], cwd=app_dir)
            except Exception as e:
                return f"Could not open Habit Tracker: {e}"
        return "Opened Habit Tracker."

    def _list(self, conn, today: str) -> str:
        rows = conn.execute(
            "SELECT id, name, icon, habit_type FROM habits ORDER BY display_order"
        ).fetchall()
        if not rows:
            return "No habits exist yet."

        log_rows = conn.execute(
            "SELECT habit_id, completed, value FROM habit_logs WHERE log_date=?", (today,)
        ).fetchall()
        logs = {hid: (completed, value) for hid, completed, value in log_rows}

        lines = []
        for hid, name, icon, htype in rows:
            log = logs.get(hid)
            if log is None:
                status = "not done yet today"
            elif htype == "numeric":
                status = f"done today (logged {log[1]})" if log[1] is not None else "done today"
            else:
                status = "done today" if log[0] else "not done today"
            lines.append(f"- {icon} {name}: {status}")
        return "\n".join(lines)

    def _check(self, conn, args: dict, today: str) -> str:
        habit_name = (args.get("habit_name") or "").strip()
        if not habit_name:
            return "Missing habit_name."

        row = conn.execute(
            "SELECT id, name, habit_type, daily_goal, direction FROM habits "
            "WHERE lower(name) LIKE lower(?) LIMIT 1",
            (f"%{habit_name}%",),
        ).fetchone()
        if not row:
            names = [r[0] for r in conn.execute("SELECT name FROM habits").fetchall()]
            return f"No habit matches '{habit_name}'. Existing habits: {', '.join(names) or 'none'}."
        hid, real_name, htype, daily_goal, direction = row

        if bool(args.get("undo", False)):
            conn.execute("DELETE FROM habit_logs WHERE habit_id=? AND log_date=?", (hid, today))
            conn.commit()
            return f"Un-marked '{real_name}' for today."

        if htype == "numeric":
            value = args.get("value")
            if value is None:
                return f"'{real_name}' is a numeric habit - pass value with today's number."
            completed = 1 if _numeric_meets_goal(value, daily_goal, direction) else 0
            conn.execute(
                "INSERT INTO habit_logs (habit_id, log_date, completed, value) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(habit_id, log_date) DO UPDATE SET completed=excluded.completed, "
                "value=excluded.value",
                (hid, today, completed, value),
            )
            conn.commit()
            goal_note = " - meets today's goal" if completed else " - short of today's goal"
            return f"Logged {value} for '{real_name}'{goal_note}."

        conn.execute(
            "INSERT INTO habit_logs (habit_id, log_date, completed) VALUES (?, ?, 1) "
            "ON CONFLICT(habit_id, log_date) DO UPDATE SET completed=1",
            (hid, today),
        )
        conn.commit()
        return f"Marked '{real_name}' done for today."

    def _add(self, conn, args: dict) -> str:
        name = (args.get("habit_name") or "").strip()
        if not name:
            return "Missing habit_name for the new habit."
        icon = (args.get("icon") or "⭐").strip() or "⭐"
        habit_type = (args.get("habit_type") or "check").strip().lower()
        if habit_type not in ("check", "numeric"):
            habit_type = "check"
        unit = (args.get("unit") or "").strip()
        daily_goal = args.get("daily_goal")

        order = conn.execute("SELECT COALESCE(MAX(display_order), -1) + 1 FROM habits").fetchone()[0]
        conn.execute(
            "INSERT INTO habits (name, icon, target_enabled, target_value, display_order, "
            "habit_type, direction, period, unit, daily_goal, color, category, created_at) "
            "VALUES (?, ?, 1, 20, ?, ?, 'min', 'month', ?, ?, NULL, '', ?)",
            (name, icon, order, habit_type, unit, daily_goal, date.today().isoformat()),
        )
        conn.commit()
        return f"Created new habit '{icon} {name}'."


PLUGIN = HabitTrackerPlugin()
