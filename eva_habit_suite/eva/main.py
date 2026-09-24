
import faulthandler
import os
import sys
import time
from dotenv import load_dotenv

# Native crashes (an access violation inside mediapipe/OpenCV/PortAudio, for
# example) kill the interpreter outright: no Python exception is raised, so
# main()'s retry loop never sees them and the process just disappears with an
# empty console. faulthandler dumps the C-level stack instead, into
# logs/crash.log, so those failures are diagnosable rather than invisible.
try:
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"), exist_ok=True)
    _crash_log = open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "crash.log"),
        "a", encoding="utf-8", buffering=1,
    )
    faulthandler.enable(file=_crash_log, all_threads=True)
except Exception:
    faulthandler.enable(all_threads=True)

# Resolve paths relative to this file, not the current working directory -
# otherwise launching Eva via a shortcut, a scheduled task, or `python
# C:\...\main.py` from some other folder fails to find config.yaml/.env
# even though the project is set up correctly.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

from config import load_config, ConfigValidationError
from logger_setup import setup_logger
from audit_log import setup_audit_logger
from ui import AgentWindow, UserWindow
from tray import start_tray
from hotkey import start_global_hotkey, stop_all_global_hotkeys
from notifier import notify

MAX_CRASH_RESTARTS = 3
# If the app stayed up at least this long before crashing, treat it as a
# fresh, unrelated incident and reset the restart counter - otherwise 3
# crashes that are hours or days apart (nothing to do with each other)
# would permanently use up the retry budget and refuse to restart again
# the 4th time, even though nothing is actually broken.
HEALTHY_UPTIME_SECONDS = 120

# Only the very first launch gets the boot-sequence animation; a
# crash-restart inside main()'s retry loop skips it and reveals the
# windows immediately - a 2-second splash every time Eva recovers from a
# crash would make an already-bad moment (a crash) feel slower, not better.
_boot_sequence_shown = False


def _make_dpi_aware():
    """Windows only. Without this, a Python process is DPI-unaware by
    default, which on any display using >100% scaling makes ImageGrab
    screenshots and pyautogui's mouse coordinates disagree about how big
    the screen is - the single biggest cause of control_computer clicking
    in the wrong place. Best-effort: locate_on_screen's own real_w/real_h
    rescaling still corrects for this even if the OS/Python version makes
    this call unavailable, but doing both is more robust than either alone."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            pass


def run_once():
    global _boot_sequence_shown
    _make_dpi_aware()
    load_dotenv()
    config = load_config("config.yaml")
    logger = setup_logger(config)
    audit_logger = setup_audit_logger(config)

    assistant_name = config.get("assistant_name", default="Eva")
    logger.info("=" * 50)
    logger.info(f"{assistant_name} is starting...")

    agent_window = None
    user_window = None
    tray_icon = None

    try:
        agent_window = AgentWindow(config, logger, audit_logger)
        user_window = UserWindow(agent_window)
        agent_window.user_window = user_window

        agent_window.protocol("WM_DELETE_WINDOW", agent_window.on_closing)
        user_window.protocol("WM_DELETE_WINDOW", agent_window.on_closing)

        if config.get("tray", "enabled", default=False):
            def show_user():
                user_window.deiconify()
                user_window.lift()

            def show_agent():
                agent_window.deiconify()
                agent_window.lift()

            def quit_app():
                agent_window.on_closing()

            tray_icon = start_tray(assistant_name, logger, show_user, show_agent, quit_app)

        if config.get("hotkey", "enabled", default=False):
            combo = config.get("hotkey", "combo", default="ctrl+space")
            start_global_hotkey(combo, agent_window.process_voice_request, logger)

        kill_switch_combo = config.get("hotkey", "kill_switch_combo", default="ctrl+alt+k")
        if not start_global_hotkey(kill_switch_combo, agent_window.emergency_stop, logger):
            # This is the manual override for anything control_computer is doing -
            # if it didn't register (missing 'keyboard' lib, no admin rights on
            # Windows, etc.), the user needs to know now, not just find a warning
            # buried in logs/eva.log after the fact.
            notify(
                f"{assistant_name} - kill switch inactive",
                f"The '{kill_switch_combo}' emergency-stop hotkey could not be registered. "
                f"It will NOT work until this is fixed (see logs/eva.log for why).",
                logger,
            )

        privacy_combo = config.get("hotkey", "privacy_combo", default="ctrl+alt+p")
        if not start_global_hotkey(privacy_combo, agent_window.toggle_privacy_mode, logger):
            notify(
                f"{assistant_name} - privacy hotkey inactive",
                f"The '{privacy_combo}' privacy-mode hotkey could not be registered. "
                f"Use the lock icon in the window instead (see logs/eva.log for why).",
                logger,
            )

        if config.get("boot_sequence", "enabled", default=True) and not _boot_sequence_shown:
            _boot_sequence_shown = True
            agent_window.withdraw()
            user_window.withdraw()

            def _reveal_main_windows():
                agent_window.deiconify()
                user_window.deiconify()
                user_window.lift()

            agent_window.run_boot_sequence(_reveal_main_windows)

        agent_window.mainloop()
        logger.info(f"{assistant_name} has been closed.")
    finally:
        # CRITICAL: whether we exited cleanly or an exception blew out of
        # mainloop(), every background thread this run started (wake word,
        # gesture/face detection, daily briefing, TTS, camera capture) must
        # be torn down and the Tk windows destroyed *before* the retry loop
        # in main() creates a brand-new AgentWindow. Otherwise those threads
        # keep running against a now-dead Tk interpreter and its images,
        # which is what produced the "image pyimageN doesn't exist" crash
        # on restart.
        if agent_window is not None:
            try:
                agent_window.on_closing()
            except Exception:
                pass
        # Global hotkeys (via the `keyboard` lib) are process-wide and are
        # NOT tied to the Tk windows, so on_closing() doesn't touch them -
        # without this they'd stay registered and pile up (double-firing
        # old callbacks) across every restart.
        stop_all_global_hotkeys(logger)
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass


def main():
    restarts = 0
    while True:
        started_at = time.time()
        try:
            run_once()
            break  # normal, user-initiated exit
        except (ConfigValidationError, ValueError) as e:
            # These are configuration/setup problems, not random crashes -
            # restarting won't fix them, so fail fast with one clear message
            # instead of wasting 3 restart cycles on the same broken config.
            print(f"\nFatal error: {e}\n")
            sys.exit(1)
        except Exception as e:
            uptime = time.time() - started_at
            if uptime >= HEALTHY_UPTIME_SECONDS:
                restarts = 0
            restarts += 1
            print(f"\nEva crashed unexpectedly after {uptime:.0f}s: {e}\n")
            if restarts > MAX_CRASH_RESTARTS:
                print("Too many crashes in a row - not restarting again. Please check logs/eva.log.")
                sys.exit(1)
            print(f"Restarting Eva ({restarts}/{MAX_CRASH_RESTARTS})...")
            time.sleep(2)


if __name__ == "__main__":
    main()
