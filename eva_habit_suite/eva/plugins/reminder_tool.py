import threading
from plugins.base import BasePlugin

_active_lock = threading.Lock()
_active_count = 0  # currently-pending (not yet fired) reminders, across all calls


class ReminderPlugin(BasePlugin):
    """Schedules a desktop notification N minutes from now. Runs in-process,
    so reminders only fire while the app is open."""
    name = "set_reminder"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "reminders", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Sets a reminder that will show a desktop notification after a number of minutes.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "minutes": {"type": "NUMBER", "description": "How many minutes from now to remind the user"},
                    "message": {"type": "STRING", "description": "What to remind the user about"},
                },
                "required": ["minutes", "message"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        global _active_count
        if not self.is_enabled(config):
            return "The reminders permission is disabled. Enable it via permissions.reminders.enabled in config.yaml."

        try:
            minutes = float(args.get("minutes"))
        except (TypeError, ValueError):
            return "The reminder time must be a number of minutes."
        message = (args.get("message") or "").strip() or "Reminder"

        if minutes <= 0:
            return "The reminder time must be greater than zero."

        max_minutes = config.get("permissions", "reminders", "max_minutes", default=43200)  # 30 days
        if minutes > max_minutes:
            return f"That's too far out - reminders are capped at {max_minutes:g} minutes ahead."

        max_active = config.get("permissions", "reminders", "max_active", default=20)
        with _active_lock:
            if _active_count >= max_active:
                return (
                    f"There are already {max_active} reminders waiting to fire - that's the "
                    f"current limit. Wait for some to go off before setting more."
                )
            _active_count += 1

        assistant_name = config.get("assistant_name", default="Eva")
        notifier = context.get("notifier")
        logger = context.get("logger")

        def fire():
            global _active_count
            try:
                if notifier:
                    notifier(f"{assistant_name} reminder", message, logger)
            finally:
                with _active_lock:
                    _active_count -= 1

        timer = threading.Timer(minutes * 60, fire)
        timer.daemon = True
        timer.start()

        return f"Reminder set for {minutes:g} minute(s) from now: {message}"


PLUGIN = ReminderPlugin()
