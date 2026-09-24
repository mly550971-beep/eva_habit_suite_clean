"""
plugins/mood_tool.py
---------------------
A simple, honest mood journal: the user tells Eva how they're feeling in
their own words (nothing is inferred from the camera or guessed), Eva
stores it with a timestamp, and can summarize recent entries on request.
"""

import os
import json
import time
from plugins.base import BasePlugin

def _mood_log_path(config):
    return config.get("mood", "file", default="data/mood_log.json")


def _load_entries(config):
    path = _mood_log_path(config)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_entries(config, entries):
    path = _mood_log_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


class LogMoodPlugin(BasePlugin):
    name = "log_mood"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "mood_journal", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Records how the user says they are feeling right now, in a personal mood journal.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "mood": {"type": "STRING", "description": "The mood/feeling the user described, in their own words"},
                    "note": {"type": "STRING", "description": "Optional extra context the user gave about why they feel this way"},
                },
                "required": ["mood"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The mood journal permission is disabled."
        mood = (args.get("mood") or "").strip()
        if not mood:
            return "No mood was given."
        entries = _load_entries(config)
        entries.append({"ts": time.time(), "mood": mood, "note": (args.get("note") or "").strip()})
        _save_entries(config, entries)
        return f"Got it, logged your mood as '{mood}'."


class MoodSummaryPlugin(BasePlugin):
    name = "mood_summary"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "mood_journal", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Summarizes the user's recently logged moods (e.g. 'how have I been feeling lately').",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "days": {"type": "INTEGER", "description": "How many past days to summarize (default 7)"},
                },
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The mood journal permission is disabled."
        days = args.get("days") or 7
        cutoff = time.time() - days * 86400
        entries = [e for e in _load_entries(config) if e.get("ts", 0) >= cutoff]
        if not entries:
            return f"No mood entries logged in the last {days} day(s)."
        lines = [
            f"- {time.strftime('%a %d %b, %H:%M', time.localtime(e['ts']))}: {e['mood']}"
            + (f" ({e['note']})" if e.get("note") else "")
            for e in entries
        ]
        return f"Mood entries from the last {days} day(s):\n" + "\n".join(lines)


PLUGINS = [LogMoodPlugin(), MoodSummaryPlugin()]
