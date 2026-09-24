"""
plugins/summary_tool.py
-------------------------
summarize_conversations: builds a short summary of archived conversation
sessions (see memory.py's list_sessions/load_session) from today or the
past week, by feeding their text to the same model in one extra
generate_content call. Sessions are only archived when a "New
Conversation" happens (memory.clear()), so this summarizes finished
conversations, not whatever is currently in progress.
"""

import time
from plugins.base import BasePlugin

MAX_SESSIONS = 25          # don't feed an unbounded number of sessions into one prompt
MAX_CHARS_PER_SESSION = 800  # keep each session's contribution short so long chats don't dominate


class SummarizeConversationsPlugin(BasePlugin):
    name = "summarize_conversations"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "conversation_summary", "enabled", default=True)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Summarizes past conversations from today or the last 7 days into a few "
                "short bullet points of the main topics discussed. Use for requests like "
                "'what did we talk about today' or 'give me a summary of this week'."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "period": {"type": "STRING", "description": "One of: today, week. Defaults to today."}
                },
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "Conversation summaries are disabled. Enable via permissions.conversation_summary.enabled in config.yaml."

        brain = context.get("brain")
        if brain is None:
            return "Conversation history is unavailable right now."

        period = (args.get("period") or "today").strip().lower()
        window_seconds = 7 * 86400 if period == "week" else 86400
        cutoff = time.time() - window_seconds

        sessions = [s for s in brain.memory.list_sessions() if s.get("ts", 0) >= cutoff][:MAX_SESSIONS]
        if not sessions:
            return f"No archived conversations were found for '{period}' (conversations are archived when a new one starts)."

        chunks = []
        for session in sessions:
            turns = brain.memory.load_session(session["path"])
            text_parts = [f"{t.get('role')}: {t.get('text', '')}" for t in turns]
            session_text = "\n".join(text_parts)[:MAX_CHARS_PER_SESSION]
            chunks.append(session_text)

        combined = "\n---\n".join(chunks)
        prompt = (
            "Summarize the key topics discussed across these conversation excerpts into "
            "3-6 short bullet points, in the same language predominantly used in them. "
            "Be concise - this will be read aloud.\n\n" + combined
        )

        try:
            summary = brain.generate_vision_text(prompt).strip()
            if not summary:
                return "Could not generate a summary from the archived conversations."
            return summary
        except Exception as e:
            return f"Could not generate the summary: {e}"


PLUGIN = SummarizeConversationsPlugin()
