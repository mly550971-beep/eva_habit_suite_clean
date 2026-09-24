"""
plugins/export_history_tool.py
--------------------------------
Exports the full archived conversation history (data/sessions/*.json) into
a single, readable .docx file the user can review at their leisure. Uses
python-docx - lightweight, pure Python, no compiled binary dependency.
"""

import os
import time
from plugins.base import BasePlugin


class ExportHistoryPlugin(BasePlugin):
    name = "export_history"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "export_history", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Exports all past conversation history into a Word (.docx) document the user can open and review.",
            parameters={"type": "OBJECT", "properties": {}},
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The export-history permission is disabled."

        try:
            import docx
        except ImportError:
            return "The python-docx library isn't installed, so history can't be exported. Run: pip install python-docx"

        memory = context.get("brain").memory if context.get("brain") else None
        if memory is None:
            return "Could not access conversation history."

        sessions = memory.list_sessions()
        if not sessions:
            return "There is no past conversation history to export yet."

        output_dir = config.get("permissions", "export_history", "output_dir", default="data/exports")
        os.makedirs(output_dir, exist_ok=True)
        filename = f"Eva_Conversation_History_{time.strftime('%Y-%m-%d_%H%M%S')}.docx"
        filepath = os.path.join(output_dir, filename)

        document = docx.Document()
        document.add_heading("Eva - Conversation History", level=0)
        document.add_paragraph(f"Exported on {time.strftime('%Y-%m-%d %H:%M')}")

        for session in sorted(sessions, key=lambda s: s["ts"]):
            ts_text = time.strftime("%A, %d %B %Y - %H:%M", time.localtime(session["ts"]))
            document.add_heading(ts_text, level=1)
            for turn in memory.load_session(session["path"]):
                speaker = "You" if turn.get("role") == "user" else "Eva"
                p = document.add_paragraph()
                run = p.add_run(f"{speaker}: ")
                run.bold = True
                p.add_run(turn.get("text", ""))
            document.add_paragraph()

        document.save(filepath)
        abs_path = os.path.abspath(filepath)
        return f"Exported {len(sessions)} conversation(s) to: {abs_path}"


PLUGIN = ExportHistoryPlugin()
