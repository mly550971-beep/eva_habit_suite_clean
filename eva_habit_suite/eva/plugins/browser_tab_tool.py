from plugins.base import BasePlugin


class BrowserTabPlugin(BasePlugin):
    """
    Sends a Ctrl+T / Ctrl+W hotkey to whichever window currently has focus.
    This is a real limitation of hotkey automation: it cannot target a
    specific browser and does nothing useful if a browser isn't focused.
    """
    name = "control_browser_tab"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "browser_tab_control", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Opens a new browser tab or closes the current tab, in whichever window is currently focused.",
            parameters={
                "type": "OBJECT",
                "properties": {"action": {"type": "STRING", "description": "'new_tab' or 'close_tab'"}},
                "required": ["action"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The browser-tab-control permission is disabled. Enable it via permissions.browser_tab_control.enabled in config.yaml."
        action = (args.get("action") or "").strip().lower()
        try:
            import pyautogui
        except ImportError:
            return "The pyautogui library is not installed, so tab control is unavailable."

        if action == "new_tab":
            pyautogui.hotkey("ctrl", "t")
            return "Sent 'new tab' to the currently focused window."
        elif action == "close_tab":
            pyautogui.hotkey("ctrl", "w")
            return "Sent 'close tab' to the currently focused window."
        return f"Unknown action '{action}'. Use 'new_tab' or 'close_tab'."


PLUGIN = BrowserTabPlugin()
