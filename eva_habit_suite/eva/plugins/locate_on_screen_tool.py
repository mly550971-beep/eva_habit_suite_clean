"""
plugins/locate_on_screen_tool.py
---------------------------------
Fixes the coordinate mismatch between what the vision model sees and what
pyautogui actually clicks on.

read_screen sends Gemini a *resized* screenshot (capped to
MAX_SCREENSHOT_WIDTH pixels wide) and returns a plain-language description -
it never returns coordinates, and even if it tried to guess them, they'd be
in the resized image's pixel grid, not the real screen's. control_computer,
on the other hand, sends whatever (x, y) it's given straight to pyautogui in
real screen-pixel space. Nothing in between ever converted from one space to
the other, so a click based on "what the model saw" would reliably land in
the wrong place - worse the larger the gap between the resized image and the
real screen resolution (e.g. any Windows display using >100% scaling).

locate_on_screen closes that gap in one place: it takes its own screenshot,
asks Gemini for a pixel position *within that exact image*, then rescales
that position by (real_screen_size / shown_image_size) before handing it
back. The model never has to reason about resizing or DPI at all - it just
calls locate_on_screen, then passes the (x, y) it gets back straight into
control_computer's move/click actions unchanged.
"""

import json
import re
import tempfile
import os
from plugins.base import BasePlugin

MAX_SHOWN_WIDTH = 1568  # keep in sync with screen_tool.MAX_SCREENSHOT_WIDTH


class LocateOnScreenPlugin(BasePlugin):
    name = "locate_on_screen"

    def is_enabled(self, config) -> bool:
        # Read-only (takes a screenshot, makes one vision call) - gated the
        # same way read_screen is, not under computer_control. It never
        # moves the mouse or types anything itself.
        return config.get("permissions", "screen_reading", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Finds a specific visual element on the current screen (a button, "
                "contact name, icon, text field, link, etc.) and returns its real "
                "screen-pixel coordinates. ALWAYS call this before control_computer's "
                "click/move/drag actions when you need to interact with something "
                "specific you can see - never guess coordinates from read_screen's "
                "description, since that description is not aligned to real screen "
                "pixels. Pass the exact (x, y) this returns straight into "
                "control_computer without adjusting it."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "description": {
                        "type": "STRING",
                        "description": "What to find, as specifically as possible, e.g. "
                                       "\"the contact named Ahmed in the chat list on the left\" "
                                       "or \"the message input box at the bottom of the chat\"",
                    }
                },
                "required": ["description"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "Screen reading is disabled. Enable it via permissions.screen_reading.enabled in config.yaml."

        brain = context.get("brain")
        if brain is None:
            return "The AI model is unavailable for locating elements on screen."

        description = (args.get("description") or "").strip()
        if not description:
            return "A description of what to find is required."

        try:
            import pyautogui
        except ImportError:
            return "pyautogui is not installed, so real screen coordinates cannot be computed."

        screenshot_path = None
        try:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            captured_w, captured_h = screenshot.width, screenshot.height

            shown = screenshot
            if shown.width > MAX_SHOWN_WIDTH:
                ratio = MAX_SHOWN_WIDTH / shown.width
                shown = shown.resize((MAX_SHOWN_WIDTH, int(shown.height * ratio)))
            shown_w, shown_h = shown.width, shown.height

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                screenshot_path = tmp.name
                shown.convert("RGB").save(screenshot_path, "JPEG", quality=90)

            prompt = (
                "This image is exactly "
                f"{shown_w}x{shown_h} pixels. Find this element: \"{description}\".\n"
                "Respond with ONLY a JSON object, no other text, no markdown fences:\n"
                '{"found": true, "x": <int center-x in this image, 0-'
                f'{shown_w}>, "y": <int center-y in this image, 0-{shown_h}>}}\n'
                'If it is not visible on screen, respond exactly: {"found": false}'
            )
            raw = brain.generate_vision_text(prompt, screenshot_path, temperature=0.1).strip()

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return f"Could not parse a location from the model's response: {raw[:200]}"
            data = json.loads(match.group(0))

            if not data.get("found"):
                return f"'{description}' was not found on the current screen."

            shown_x, shown_y = float(data["x"]), float(data["y"])

            # The one line that actually fixes the mismatch: convert from
            # "pixel in the image Gemini looked at" to "pixel pyautogui's
            # mouse APIs use" via the real screen size, regardless of any
            # resizing above or any DPI-awareness gap between ImageGrab and
            # pyautogui - both are just expressed as a ratio of the same
            # rectangle, so this cancels out either source of mismatch.
            real_w, real_h = pyautogui.size()
            real_x = round(shown_x * real_w / shown_w)
            real_y = round(shown_y * real_h / shown_h)
            real_x = max(0, min(real_x, real_w - 1))
            real_y = max(0, min(real_y, real_h - 1))

            return (
                f"Found '{description}' at real screen coordinates ({real_x}, {real_y}). "
                f"Pass these exact numbers to control_computer - do not adjust them."
            )

        except ImportError:
            return "Pillow's ImageGrab is unavailable, so screen reading is not supported on this platform."
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return f"Could not understand the model's location response: {e}"
        except Exception as e:
            return f"Could not locate the element: {e}"
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except Exception:
                    pass


PLUGIN = LocateOnScreenPlugin()
