"""
plugins/clipboard_tool.py
--------------------------
copy_text_from_screen: takes a screenshot, asks the vision model to
extract ONE specific piece of visible text (an email, a code, a phone
number, a highlighted line...), and copies exactly that text to the
system clipboard via pyperclip. Read-only on the screen itself (same
screenshot mechanism as read_screen) - the only "write" involved is
replacing whatever was already on the clipboard, which is why this is
its own permission rather than being folded into screen_reading.
"""

import os
import tempfile
from plugins.base import BasePlugin

MAX_COPY_LENGTH = 2000  # sanity bound - this is for short strings (emails, codes...), not whole documents


class CopyTextFromScreenPlugin(BasePlugin):
    name = "copy_text_from_screen"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "clipboard_access", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Finds one specific piece of text currently visible on the screen "
                "(e.g. an email address, a code, a phone number, a highlighted line) "
                "and copies exactly that text to the clipboard, ready to paste."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "description": {
                        "type": "STRING",
                        "description": "What text to find and copy, e.g. 'the email address' or 'the confirmation code'",
                    }
                },
                "required": ["description"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "Clipboard access is disabled. Enable it via permissions.clipboard_access.enabled in config.yaml."

        brain = context.get("brain")
        if brain is None:
            return "The AI model is unavailable."

        description = (args.get("description") or "").strip()
        if not description:
            return "A description of what text to copy is required."

        try:
            import pyperclip
        except ImportError:
            return "The pyperclip library is not installed, so clipboard access is unavailable."

        screenshot_path = None
        try:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                screenshot_path = tmp.name
                screenshot.convert("RGB").save(screenshot_path, "JPEG", quality=90)

            prompt = (
                f"Look at this screenshot and find: {description}. "
                f"Reply with ONLY the exact text to copy, nothing else - no quotes, no "
                f"explanation, no punctuation added. If it truly is not visible anywhere "
                f"in the image, reply with exactly: NOT_FOUND"
            )
            extracted = brain.generate_vision_text(prompt, screenshot_path, temperature=0.1).strip()

            if not extracted or extracted == "NOT_FOUND":
                return f"Could not find '{description}' anywhere on the current screen."
            if len(extracted) > MAX_COPY_LENGTH:
                extracted = extracted[:MAX_COPY_LENGTH]

            pyperclip.copy(extracted)
            preview = extracted if len(extracted) <= 60 else extracted[:57] + "..."
            return f"Copied to clipboard: {preview}"

        except ImportError:
            return "Pillow's ImageGrab is unavailable, so screen reading is not supported on this platform."
        except Exception as e:
            return f"Could not copy text from the screen: {e}"
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except Exception:
                    pass


PLUGIN = CopyTextFromScreenPlugin()
