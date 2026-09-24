"""
run_both.py
-----------
Launches EVA and the Habit Tracker app together, as two separate
processes, from this one merged project.

Why two processes and not one: EVA's UI runs on Tkinter/customtkinter's
mainloop, and Habit Tracker runs on PyQt6's own event loop. Two different
GUI toolkits cannot share a single event loop / a single process, so each
app keeps running exactly as it always did - this script just starts them
side by side and gives you one place to stop both.

They are not merged into one codebase and don't need to be: they already
talk to each other through the shared habit_tracker.db file (see
eva/plugins/habit_tracker_tool.py and eva/config.yaml ->
integrations.habit_tracker). Anything Eva does to a habit (check it off,
add a new one) shows up in the Habit Tracker window's own auto-refresh
within a couple of seconds, and vice versa.

Usage:
    python run_both.py

Stop both with Ctrl+C in this terminal (or just close both windows).
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
EVA_DIR = os.path.join(ROOT, "eva")
HABIT_DIR = os.path.join(ROOT, "habit_tracker")


def _launch(label, directory, script="main.py"):
    print(f"[run_both] Starting {label} ({os.path.join(directory, script)}) ...")
    # cwd matters: both apps resolve their own config/db files relative to
    # their own folder (see BASE_DIR / APP_DIR in each main.py), not to
    # wherever run_both.py happens to be invoked from.
    return subprocess.Popen([sys.executable, script], cwd=directory)


def main():
    if not os.path.isfile(os.path.join(HABIT_DIR, "habit_tracker.db")):
        print(
            "[run_both] Note: habit_tracker.db doesn't exist yet under "
            f"{HABIT_DIR} - Habit Tracker will create it on this first run. "
            "Eva's habit_tracker tool will work once that file exists "
            "(i.e. after Habit Tracker has started at least once)."
        )

    # Start Habit Tracker first so its database file/tables exist by the
    # time Eva's habit_tracker tool might be asked to use them, then Eva.
    procs = []
    try:
        procs.append(("Habit Tracker", _launch("Habit Tracker", HABIT_DIR)))
        time.sleep(1.5)
        procs.append(("Eva", _launch("Eva", EVA_DIR)))

        print("[run_both] Both apps launched. Press Ctrl+C here to stop both.")
        while True:
            time.sleep(1)
            for label, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"[run_both] {label} exited (code {code}).")
                    procs.remove((label, proc))
            if not procs:
                print("[run_both] Both apps have exited.")
                break
    except KeyboardInterrupt:
        print("\n[run_both] Stopping both apps...")
    finally:
        for label, proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for label, proc in procs:
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
