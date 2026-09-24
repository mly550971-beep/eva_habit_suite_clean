"""
plugins/repeat_last_tool.py
-----------------------------
repeat_last_response: re-speaks Eva's own previous answer, slower and a
bit louder, for "say that again" / "I didn't catch that" moments -
without asking the model to regenerate the answer (which could come out
worded differently) and without the user having to re-ask their question.
"""

from plugins.base import BasePlugin


class RepeatLastResponsePlugin(BasePlugin):
    name = "repeat_last_response"

    def is_enabled(self, config) -> bool:
        return True  # purely a speech-output convenience, no external reach - always available

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Repeats Eva's own previous spoken response again, more slowly and "
                "slightly louder. Use when the user says they didn't hear/understand, "
                "or asks Eva to repeat or say something again - not for regenerating a "
                "fresh answer to a new question."
            ),
            parameters={"type": "OBJECT", "properties": {}},
        )

    def execute(self, args: dict, config, context: dict) -> str:
        brain = context.get("brain")
        speak = (context.get("ui_callbacks") or {}).get("speak")
        if brain is None or not speak:
            return "Repeating the last response is unavailable right now."

        text = getattr(brain, "last_response_text", "") or ""
        if not text:
            return "There is nothing to repeat yet - this is the first response of the conversation."

        try:
            speak(text, rate="-20%", volume="+25%")
        except Exception as e:
            return f"Could not repeat the response: {e}"

        return "Repeated the previous response, slower and louder. Give a brief acknowledgement only - do not say the content again yourself."


PLUGIN = RepeatLastResponsePlugin()
