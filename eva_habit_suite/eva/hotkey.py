"""
hotkey.py
---------
A global keyboard shortcut that works even when the app's windows aren't
focused (e.g. Ctrl+Space to start listening from anywhere). Safe no-op if
the `keyboard` library isn't installed. On some platforms this may require
running with elevated/administrator privileges to install a global hook.
"""


def start_global_hotkey(combo: str, callback, logger) -> bool:
    try:
        import keyboard
        keyboard.add_hotkey(combo, callback)
        logger.info(f"[Hotkey] Global hotkey registered: {combo}")
        return True
    except ImportError:
        logger.warning("[Hotkey] The 'keyboard' library is not installed - global hotkey disabled.")
        return False
    except Exception as e:
        logger.warning(f"[Hotkey] Could not register global hotkey '{combo}': {e}")
        return False


def stop_all_global_hotkeys(logger) -> None:
    """Unregisters every hotkey added via start_global_hotkey(). Global
    hotkeys registered with the `keyboard` library are process-wide and
    outlive any single Tk window, so this MUST be called whenever a run
    of the app ends (clean exit or crash) - otherwise a restart re-adds
    the same combos on top of the old ones, and the old callbacks (bound
    to an already-destroyed window) keep firing alongside the new ones."""
    try:
        import keyboard
        keyboard.unhook_all_hotkeys()
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"[Hotkey] Could not unhook global hotkeys: {e}")
