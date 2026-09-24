"""
plugins/joke_tool.py
---------------------
Tells a joke ONLY when asked (never injected unprompted into replies).
Uses the free, keyless official-joke-api; falls back to a small local list
if there's no internet.
"""

import random
import requests
from plugins.base import BasePlugin

_FALLBACK_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I told my computer I needed a break, and now it won't stop sending me KitKats.",
    "Why did the developer go broke? Because he used up all his cache.",
]


class TellJokePlugin(BasePlugin):
    name = "tell_joke"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "joke", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Tells a short joke. Only call this when the user explicitly asks for a joke.",
            parameters={"type": "OBJECT", "properties": {}},
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The joke permission is disabled."
        try:
            resp = requests.get("https://official-joke-api.appspot.com/random_joke", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            setup, punchline = data.get("setup"), data.get("punchline")
            if setup and punchline:
                return f"{setup} ... {punchline}"
        except Exception:
            pass
        return random.choice(_FALLBACK_JOKES)


PLUGIN = TellJokePlugin()
