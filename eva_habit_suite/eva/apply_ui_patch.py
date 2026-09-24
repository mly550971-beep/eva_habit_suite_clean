"""
apply_ui_patch.py
-----------------
One-time helper: adds 3 small hooks to YOUR ui.py so the scheduler (adhan)
starts with Eva, stops when Eva closes, and the emergency stop
(Ctrl+Alt+K) also stops the adhan.

Run it once from the eva folder (the one containing ui.py):
        python apply_ui_patch.py
It saves a backup as ui.py.bak first, is safe to run twice (it detects the
patch), and refuses to touch ui.py if the lines it expects aren't found
(in that case nothing is changed and it tells you what to send).
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "ui.py")

PATCHES = [
    (
        "start scheduler",
        "        self.daily_briefing.start()\n",
        "        self.daily_briefing.start()\n"
        "\n"
        "        # Background scheduler: adhan at prayer times, reminders (scheduler.py)\n"
        "        self.scheduler = None\n"
        "        try:\n"
        "            from scheduler import build_scheduler\n"
        "            self.scheduler = build_scheduler(self, config, logger)\n"
        "            self.scheduler.start()\n"
        "        except Exception as e:\n"
        "            logger.warning(f\"[Scheduler] Could not start: {e}\")\n",
    ),
    (
        "stop scheduler on close",
        "        try:\n            self.daily_briefing.stop()\n        except Exception:\n            pass\n",
        "        try:\n            self.daily_briefing.stop()\n        except Exception:\n            pass\n"
        "        try:\n"
        "            if getattr(self, \"scheduler\", None) is not None:\n"
        "                self.scheduler.stop()\n"
        "        except Exception:\n"
        "            pass\n",
    ),
    (
        "emergency stop also stops the adhan",
        "        self._emergency_stop = True\n        try:\n            self.tts.stop()\n        except Exception:\n            pass\n",
        "        self._emergency_stop = True\n        try:\n            self.tts.stop()\n        except Exception:\n            pass\n"
        "        try:\n"
        "            import adhan as _adhan\n"
        "            _player = _adhan.get_player()\n"
        "            if _player is not None:\n"
        "                _player.stop()\n"
        "        except Exception:\n"
        "            pass\n",
    ),
]


def main() -> int:
    with open(PATH, "r", encoding="utf-8") as f:
        src = f.read()
    if "build_scheduler" in src:
        print("ui.py is already patched - nothing to do.")
        return 0
    for label, anchor, _new in PATCHES:
        if src.count(anchor) != 1:
            print(f"Could not patch safely: expected exactly one place for '{label}' "
                  f"but found {src.count(anchor)}. ui.py was NOT changed.")
            return 1
    for _label, anchor, new in PATCHES:
        src = src.replace(anchor, new, 1)
    shutil.copyfile(PATH, PATH + ".bak")
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(src)
    print("Done. ui.py patched (backup saved as ui.py.bak). Restart Eva.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
