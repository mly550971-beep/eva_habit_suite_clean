"""
plugins/mode_tool.py
---------------------
Lets the user switch Eva's personality/reply style at runtime (e.g. "switch
to formal mode", "be more casual", "keep it brief from now on"). The mode
stays active until changed again or the app restarts - it does not touch
any files, just an in-memory flag on the brain.
"""

from plugins.base import BasePlugin


class SetModePlugin(BasePlugin):
    name = "set_mode"

    def is_enabled(self, config) -> bool:
        return config.get("modes_enabled", default=True)

    def declaration(self, config):
        from local_types import types
        modes = list(config.get("modes", default={}).keys())
        options = ", ".join(["default"] + modes) if modes else "default"
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Switches the assistant's personality/reply style. Call this when the "
                f"user asks to change how you talk (e.g. more formal, more casual, more "
                f"concise). Available modes: {options}. Use 'default' to return to the "
                "normal personality."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "mode": {"type": "STRING", "description": f"One of: {options}"}
                },
                "required": ["mode"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        brain = context.get("brain")
        if brain is None:
            return "The brain reference is unavailable, cannot switch modes."
        mode_name = (args.get("mode") or "").strip().lower()
        if not mode_name:
            return "No mode name was provided."
        if brain.set_mode(mode_name):
            return f"Switched to '{mode_name}' mode."
        available = ", ".join(["default"] + list(config.get("modes", default={}).keys()))
        return f"Unknown mode '{mode_name}'. Available modes: {available}."


PLUGIN = SetModePlugin()
