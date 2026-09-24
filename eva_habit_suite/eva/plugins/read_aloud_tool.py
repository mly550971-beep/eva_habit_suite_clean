"""
plugins/read_aloud_tool.py
----------------------------
read_text_aloud: speaks a longer piece of text out loud through the same
TTS engine Eva normally uses for her replies, but as its own direct
speech action - either text supplied directly (e.g. something the user
pasted or dictated) or transcribed fresh from the current screen. This is
for "read this to me" requests, as opposed to Eva's own short spoken
answers.

Note on double-speaking: after this tool runs, the model still generates
its own short final reply (e.g. "Here you go"), which gets spoken
normally afterwards via the existing pipeline. The system prompt is
worded to keep that follow-up short, so the user hears the read-aloud
content once, then a brief acknowledgement - not the content twice.
"""

import os
import tempfile
from plugins.base import BasePlugin


class ReadTextAloudPlugin(BasePlugin):
    name = "read_text_aloud"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "read_aloud", "enabled", default=True)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Reads a piece of text aloud directly through speech - either text you "
                "already have (e.g. from earlier in the conversation, or the user pasted/"
                "dictated it) or the full readable text currently visible on the screen. "
                "Use this for 'read this to me' / 'read that paragraph out loud' requests."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING", "description": "The exact text to read aloud (omit if from_screen is true)"},
                    "from_screen": {"type": "BOOLEAN", "description": "If true, transcribe and read the text currently visible on screen instead of using `text`"},
                },
            },
        )

    def _transcribe_screen(self, brain) -> str:
        screenshot_path = None
        try:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                screenshot_path = tmp.name
                screenshot.convert("RGB").save(screenshot_path, "JPEG", quality=90)
            prompt = (
                "Transcribe ALL readable body text visible in this screenshot, verbatim, "
                "in natural reading order. Skip UI chrome (menus, button labels, ads) unless "
                "that's clearly the main content. Reply with ONLY the transcribed text."
            )
            return brain.generate_vision_text(prompt, screenshot_path).strip()
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except Exception:
                    pass

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "Reading text aloud is disabled. Enable it via permissions.read_aloud.enabled in config.yaml."

        speak = (context.get("ui_callbacks") or {}).get("speak")
        if not speak:
            return "Speech output is unavailable right now."

        from_screen = bool(args.get("from_screen"))
        text = (args.get("text") or "").strip()

        if from_screen:
            if not config.get("permissions", "screen_reading", "enabled", default=False):
                return "Reading from the screen requires permissions.screen_reading.enabled to also be true."
            brain = context.get("brain")
            if brain is None:
                return "The AI model is unavailable for reading the screen."
            try:
                text = self._transcribe_screen(brain)
            except ImportError:
                return "Pillow's ImageGrab is unavailable, so screen reading is not supported on this platform."
            except Exception as e:
                return f"Could not read the screen: {e}"

        if not text:
            return "There is no text to read aloud - provide `text` or set from_screen to true."

        max_chars = config.get("permissions", "read_aloud", "max_chars", default=4000)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]

        try:
            speak(text)
        except Exception as e:
            return f"Could not start reading the text aloud: {e}"

        note = " (truncated - it was quite long)" if truncated else ""
        return f"Reading it aloud now{note}. Give a brief acknowledgement only - do not repeat the text in your reply."


PLUGIN = ReadTextAloudPlugin()
