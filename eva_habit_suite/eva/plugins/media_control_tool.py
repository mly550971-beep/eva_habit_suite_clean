from plugins.base import BasePlugin

_KEY_MAP = {
    "volume_up": "volumeup",
    "volume_down": "volumedown",
    "mute": "volumemute",
    "play_pause": "playpause",
    "next_track": "nexttrack",
    "previous_track": "prevtrack",
}


class MediaControlPlugin(BasePlugin):
    """Simulates hardware media keys. Affects whatever app currently owns
    system media focus (like pressing the physical keys on a keyboard)."""
    name = "control_media"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "media_control", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Controls system media/volume: volume up/down, mute, play/pause, next/previous track.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "description": "One of: volume_up, volume_down, mute, play_pause, next_track, previous_track",
                    }
                },
                "required": ["action"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The media-control permission is disabled. Enable it via permissions.media_control.enabled in config.yaml."
        action = (args.get("action") or "").strip().lower()
        key = _KEY_MAP.get(action)
        if not key:
            return f"Unknown media action '{action}'. Valid options: {', '.join(_KEY_MAP)}."
        try:
            import pyautogui
            pyautogui.press(key)
            return f"Sent media command: {action}."
        except ImportError:
            return "The pyautogui library is not installed, so media control is unavailable."
        except Exception as e:
            return f"Could not send media command: {e}"


PLUGIN = MediaControlPlugin()
