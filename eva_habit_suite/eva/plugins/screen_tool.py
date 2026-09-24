import tempfile
import os
from plugins.base import BasePlugin


MAX_SCREENSHOT_WIDTH = 1568  # matches the model's effective vision input cap; larger just wastes upload time


class ReadScreenPlugin(BasePlugin):
    """Takes a screenshot and asks Gemini to describe it, answer a specific
    question, or discuss it conversationally. Self-contained: makes its own
    one-off vision call using the shared client, so it fits the existing
    tool-result interface (which only returns text) without changing the
    main analyze() flow. The recent conversation + known long-term facts
    are folded into the vision prompt so a follow-up like "and what about
    the button next to it?" is understood in context, not answered cold."""
    name = "read_screen"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "screen_reading", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Takes a screenshot of the user's screen and describes it, answers a "
                "specific question about what's on screen, or discusses it further as "
                "part of the ongoing conversation (e.g. 'what does that error mean', "
                "'read me that paragraph', 'is there anything urgent here')."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "question": {"type": "STRING", "description": "Optional specific question or discussion point about the screen content"}
                },
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "Screen reading is disabled. Enable it via permissions.screen_reading.enabled in config.yaml."

        brain = context.get("brain")
        if brain is None:
            return "The AI model is unavailable for screen reading."

        question = (args.get("question") or "").strip()
        base_ask = question or "Describe what is currently visible on this screen, focusing on anything useful or actionable."

        # Pull in the same conversational grounding the main chat model has,
        # so screen discussion doesn't feel like a disconnected one-off call.
        context_parts = []
        try:
            facts_context = brain.profile.as_context()
            if facts_context:
                context_parts.append(facts_context)
            memory_context = brain.memory.get_context(question or "screen")
            if memory_context:
                context_parts.append(memory_context)
        except Exception:
            pass  # vision call still works fine without this extra context

        prompt = (
            "\n\n".join(context_parts + [
                "You are looking at a live screenshot of the user's screen. Answer "
                "naturally and conversationally, as a continuation of the discussion "
                "above if relevant.",
                base_ask,
            ])
        )

        screenshot_path = None
        try:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            if screenshot.width > MAX_SCREENSHOT_WIDTH:
                ratio = MAX_SCREENSHOT_WIDTH / screenshot.width
                screenshot = screenshot.resize(
                    (MAX_SCREENSHOT_WIDTH, int(screenshot.height * ratio))
                )
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                screenshot_path = tmp.name
                screenshot.convert("RGB").save(screenshot_path, "JPEG", quality=90)

            answer = brain.generate_vision_text(prompt, screenshot_path)
            return answer or "Could not read the screen content."

        except ImportError:
            return "Pillow's ImageGrab is unavailable, so screen reading is not supported on this platform."
        except Exception as e:
            return f"Could not read the screen: {e}"
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except Exception:
                    pass


PLUGIN = ReadScreenPlugin()
