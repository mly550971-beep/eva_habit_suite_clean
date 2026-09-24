import sys
import subprocess
from plugins.base import BasePlugin

# Common Windows app names -> their real executable name. This exists because
# the AI sometimes calls the "open any app" tool with the word exactly as the
# user said it (e.g. "calculator"), and Windows can only find the real file
# name (e.g. "calc.exe"). This makes app-opening reliable regardless of which
# tool or wording gets used, instead of depending on the AI phrasing it right
# every single time.
COMMON_APP_ALIASES = {
    "calculator": "calc.exe", "calc": "calc.exe",
    "notepad": "notepad.exe",
    "paint": "mspaint.exe", "ms paint": "mspaint.exe",
    "wordpad": "write.exe",
    "cmd": "cmd.exe", "command prompt": "cmd.exe", "terminal": "cmd.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "my computer": "explorer.exe",
    "on screen keyboard": "osk.exe",
    "magnifier": "magnify.exe",
    "word": "winword.exe", "microsoft word": "winword.exe",
    "excel": "excel.exe", "microsoft excel": "excel.exe",
    "powerpoint": "powerpnt.exe", "microsoft powerpoint": "powerpnt.exe",
    "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "edge": "msedge.exe", "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
}


def _resolve_name(app_name: str, allowed: dict):
    """Returns (executable_or_name_to_launch, display_name). Checks the
    user's own config whitelist first, then the common built-in aliases,
    and only falls back to the raw spoken name if neither matches."""
    lowered = app_name.strip().lower()
    for key, value in (allowed or {}).items():
        if key.strip().lower() == lowered:
            return value, key
    if lowered in COMMON_APP_ALIASES:
        return COMMON_APP_ALIASES[lowered], app_name
    return app_name, app_name


def _launch_executable(executable_or_name: str, display_name: str) -> str:
    """Best-effort app launch. Only OPENS things - never deletes or modifies anything."""
    try:
        if sys.platform.startswith("win"):
            # IMPORTANT: never build a shell=True command string by
            # interpolating the app name into it - a name containing a
            # shell metacharacter (", &, |, ;, ...) would then be able to
            # inject and run arbitrary extra commands. Passing an argument
            # list with shell=False goes straight to CreateProcess, so the
            # name is never re-parsed by cmd.exe.
            subprocess.Popen(["cmd", "/c", "start", "", executable_or_name], shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", executable_or_name])
        else:
            import shutil
            resolved = shutil.which(executable_or_name) or executable_or_name
            subprocess.Popen([resolved])
        return f"Opened {display_name}."
    except Exception as e:
        return f"Could not open {display_name}: {e}"


class OpenApplicationPlugin(BasePlugin):
    """Opens an app from the explicit whitelist in permissions.open_apps.allowed"""
    name = "open_application"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "open_apps", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Opens a known application by name from the allowed applications list.",
            parameters={
                "type": "OBJECT",
                "properties": {"app_name": {"type": "STRING", "description": "Application name as spoken by the user"}},
                "required": ["app_name"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The open-applications permission is disabled. Enable it via permissions.open_apps.enabled in config.yaml."
        app_name = (args.get("app_name") or "").strip()
        allowed: dict = config.get("permissions", "open_apps", "allowed", default={}) or {}
        match_key = next((k for k in allowed if k.strip().lower() == app_name.lower()), None)
        if not match_key:
            return (
                f"Application '{app_name}' is not in the allowed list. "
                f"You can add it manually under permissions.open_apps.allowed in config.yaml."
            )
        return _launch_executable(allowed[match_key], match_key)


class OpenAnyApplicationPlugin(BasePlugin):
    """Opens ANY named app - broader, still permission-gated, still open-only.
    Self-corrects common spoken names (like 'calculator') to their real
    executable name before trying to launch, so it doesn't depend on the
    caller already knowing the exact file name."""
    name = "open_any_application"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "open_any_app", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Opens ANY installed application by its common name, not limited to a fixed list.",
            parameters={
                "type": "OBJECT",
                "properties": {"app_name": {"type": "STRING", "description": "Application name, e.g. 'spotify', 'chrome', 'word'"}},
                "required": ["app_name"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The open-any-application permission is disabled. Enable it via permissions.open_any_app.enabled in config.yaml."
        app_name = (args.get("app_name") or "").strip()
        if not app_name:
            return "No application name was provided."
        allowed: dict = config.get("permissions", "open_apps", "allowed", default={}) or {}
        executable, display_name = _resolve_name(app_name, allowed)
        return _launch_executable(executable, display_name)


class CloseApplicationPlugin(BasePlugin):
    """Closes a running application by name. For safety, this only accepts
    names that are already known (the open_apps whitelist or the common
    built-in aliases) - it will never terminate an arbitrary/unknown process
    by whatever name is given, to avoid accidentally killing something
    unrelated or important."""
    name = "close_application"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "open_apps", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Closes/quits a currently running application by its common name (e.g. 'notepad', 'calculator', 'chrome').",
            parameters={
                "type": "OBJECT",
                "properties": {"app_name": {"type": "STRING", "description": "Application name to close"}},
                "required": ["app_name"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The open-applications permission is disabled. Enable it via permissions.open_apps.enabled in config.yaml."
        app_name = (args.get("app_name") or "").strip()
        if not app_name:
            return "No application name was provided."
        allowed: dict = config.get("permissions", "open_apps", "allowed", default={}) or {}
        executable, display_name = _resolve_name(app_name, allowed)
        if executable == app_name and app_name.lower() not in COMMON_APP_ALIASES:
            return (
                f"'{app_name}' isn't a recognized application name, so it was not closed "
                f"(this is a safety limit - only known apps can be closed by voice)."
            )
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["taskkill", "/IM", executable, "/F"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "darwin":
                subprocess.Popen(["osascript", "-e", f'quit app "{display_name}"'])
            else:
                subprocess.Popen(["pkill", "-f", executable])
            return f"Closed {display_name}."
        except Exception as e:
            return f"Could not close {display_name}: {e}"


PLUGINS = [OpenApplicationPlugin(), OpenAnyApplicationPlugin(), CloseApplicationPlugin()]
