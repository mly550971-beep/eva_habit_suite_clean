"""
plugins/computer_control_tool.py
---------------------------------
Simulated keyboard + mouse control (move/click/scroll/type/press/hotkey),
via pyautogui. This is the broadest-reach tool in the app - unlike every
other tool here, it can interact with whatever window currently has focus,
not just open/close things - so it is:

  - OFF by default (permissions.computer_control.enabled)
  - Always in SENSITIVE_TOOLS (tools.py), so voice lock gates it when enabled
  - Still subject to the hard permission_matrix blocklist in config.yaml
  - Bounded: typed text has a max length, mouse coordinates are clamped to
    the real screen size, and a short pyautogui.PAUSE is kept between
    actions so a bad multi-step call can't do 50 things instantly.

It does NOT run shell commands, does NOT delete/move files, and does NOT
do anything a physical keyboard/mouse couldn't also do by hand.
"""

import time

from plugins.base import BasePlugin

_ALLOWED_KEYS = {
    "enter", "return", "tab", "esc", "escape", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "ctrl", "alt", "shift", "win", "capslock", "insert", "printscreen",
}


class ComputerControlPlugin(BasePlugin):
    """One tool with an `action` switch, rather than five separate tools -
    keeps the function-calling surface small while still covering the
    common cases the user actually asks for by voice."""
    name = "control_computer"

    def __init__(self):
        # Separate, stricter cooldown from the general brain.py rate limit
        # (which only limits how often a whole AI *request* can be sent).
        # This limits individual mouse/keyboard *actions* within a single
        # multi-step tool call, so one bad or hijacked instruction can't
        # fire off dozens of clicks/keystrokes back-to-back.
        self._last_action_ts = 0.0

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "computer_control", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Controls the mouse and keyboard directly: move the mouse, click, "
                "double-click, drag, scroll, type text, press a single key, or a "
                "keyboard shortcut (hotkey). Affects whatever window currently has "
                "focus on the user's screen - use read_screen first if you need to "
                "know what's currently visible before deciding where to click."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "description": (
                            "One of: move_mouse, click, double_click, right_click, drag, "
                            "scroll, type_text, press_key, hotkey"
                        ),
                    },
                    "x": {"type": "INTEGER", "description": "X coordinate (for move_mouse, click, double_click, right_click, drag target)"},
                    "y": {"type": "INTEGER", "description": "Y coordinate (for move_mouse, click, double_click, right_click, drag target)"},
                    "text": {"type": "STRING", "description": "Text to type (for type_text)"},
                    "key": {"type": "STRING", "description": "Single key name to press (for press_key), e.g. 'enter', 'tab', 'esc'"},
                    "keys": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "Ordered list of keys held together (for hotkey), e.g. ['ctrl', 'c']",
                    },
                    "amount": {"type": "INTEGER", "description": "Scroll amount: positive scrolls up, negative scrolls down"},
                },
                "required": ["action"],
            },
        )

    # ------------------------------------------------------------ helpers ---

    @staticmethod
    def _clamp_point(pyautogui, x, y):
        screen_w, screen_h = pyautogui.size()
        x = max(0, min(int(x), screen_w - 1))
        y = max(0, min(int(y), screen_h - 1))
        return x, y

    # ------------------------------------------------------------- execute ---

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "Computer control is disabled. Enable it via permissions.computer_control.enabled in config.yaml."

        try:
            import pyautogui
        except ImportError:
            return "The pyautogui library is not installed, so computer control is unavailable."

        pyautogui.FAILSAFE = True  # moving the mouse to a screen corner aborts, as a manual kill-switch
        pyautogui.PAUSE = 0.08

        min_seconds_between_actions = config.get(
            "permissions", "computer_control", "min_seconds_between_actions", default=0.3
        )
        elapsed = time.time() - self._last_action_ts
        if elapsed < min_seconds_between_actions:
            time.sleep(min_seconds_between_actions - elapsed)
        self._last_action_ts = time.time()

        action = (args.get("action") or "").strip().lower()
        max_type_length = config.get("permissions", "computer_control", "max_type_length", default=500)

        try:
            if action == "move_mouse":
                x, y = self._clamp_point(pyautogui, args.get("x", 0), args.get("y", 0))
                pyautogui.moveTo(x, y, duration=0.15)
                return f"Moved mouse to ({x}, {y})."

            if action in ("click", "double_click", "right_click"):
                if "x" in args and "y" in args:
                    x, y = self._clamp_point(pyautogui, args["x"], args["y"])
                    pyautogui.moveTo(x, y, duration=0.15)
                else:
                    x, y = pyautogui.position()
                if action == "click":
                    pyautogui.click()
                elif action == "double_click":
                    pyautogui.doubleClick()
                else:
                    pyautogui.rightClick()
                return f"{action.replace('_', ' ').title()} at ({x}, {y})."

            if action == "drag":
                if "x" not in args or "y" not in args:
                    return "drag requires target x and y coordinates."
                x, y = self._clamp_point(pyautogui, args["x"], args["y"])
                pyautogui.dragTo(x, y, duration=0.3, button="left")
                return f"Dragged to ({x}, {y})."

            if action == "scroll":
                amount = int(args.get("amount", 0) or 0)
                if amount == 0:
                    return "scroll requires a non-zero amount."
                amount = max(-2000, min(amount, 2000))  # sanity bound, not a real limit users would hit
                pyautogui.scroll(amount)
                return f"Scrolled {'up' if amount > 0 else 'down'} by {abs(amount)}."

            if action == "type_text":
                text = args.get("text") or ""
                if not text:
                    return "type_text requires non-empty text."
                if len(text) > max_type_length:
                    return (
                        f"That text is {len(text)} characters, over the "
                        f"{max_type_length}-character safety limit for a single type_text call. "
                        f"Split it into smaller pieces."
                    )
                pyautogui.write(text, interval=0.01)
                return f"Typed {len(text)} character(s)."

            if action == "press_key":
                key = (args.get("key") or "").strip().lower()
                if key not in _ALLOWED_KEYS:
                    return (
                        f"'{key}' is not an allowed single key. Allowed: {', '.join(sorted(_ALLOWED_KEYS))}. "
                        f"For character keys, use type_text instead."
                    )
                pyautogui.press(key)
                return f"Pressed '{key}'."

            if action == "hotkey":
                keys = [str(k).strip().lower() for k in (args.get("keys") or [])]
                if not keys or len(keys) > 4:
                    return "hotkey requires between 1 and 4 keys."
                unknown = [k for k in keys if k not in _ALLOWED_KEYS and len(k) != 1]
                if unknown:
                    return f"Unrecognized key(s) in hotkey: {', '.join(unknown)}."
                pyautogui.hotkey(*keys)
                return f"Sent hotkey: {'+'.join(keys)}."

            return (
                f"Unknown action '{action}'. Valid actions: move_mouse, click, double_click, "
                f"right_click, drag, scroll, type_text, press_key, hotkey."
            )
        except Exception as e:
            return f"Could not perform computer-control action '{action}': {e}"


PLUGIN = ComputerControlPlugin()
