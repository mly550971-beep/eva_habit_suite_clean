from datetime import datetime
from plugins.base import BasePlugin


class DateTimePlugin(BasePlugin):
    name = "get_current_datetime"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "datetime", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Returns the current date and time.",
            parameters={"type": "OBJECT", "properties": {}},
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The datetime permission is disabled. Enable it via permissions.datetime.enabled in config.yaml."
        now = datetime.now()
        return (
            f"Current time: {now.strftime('%I:%M %p')}, date: {now.strftime('%Y-%m-%d')} "
            f"({now.strftime('%A')})"
        )


PLUGIN = DateTimePlugin()
