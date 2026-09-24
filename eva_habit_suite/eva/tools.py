"""
tools.py
--------
ToolExecutor now auto-discovers plugins from the plugins/ folder instead of
hard-coding every tool here. Adding a new capability is just adding a file
to plugins/ that defines a `PLUGIN` (or `PLUGINS` list) - nothing in this
file needs to change.

Also enforces the optional voice-lock gate on sensitive tools: if voice
lock is enabled and the current request came from an unverified voice
(or from typed text, which voice lock intentionally does not cover),
sensitive tools are refused rather than executed.
"""

from __future__ import annotations

import os
import json
import importlib
import pkgutil
import threading

import plugins as plugins_package

# Tools broad enough in real-world reach that voice lock (if enabled) gates them.
SENSITIVE_TOOLS = {
    "open_any_application",
    "open_any_url",
    "control_browser_tab",
    "send_whatsapp_message",
    "control_media",
    # The broadest-reach tool in the app: real keyboard/mouse input to
    # whatever window has focus. Always gated when voice lock is enabled.
    "control_computer",
}


def _discover_plugins(logger=None):
    discovered = []
    failed = []
    for _, module_name, _ in pkgutil.iter_modules(plugins_package.__path__):
        if module_name in ("base",):
            continue
        try:
            module = importlib.import_module(f"plugins.{module_name}")
        except Exception as e:
            # Previously this was a silent `continue`: a plugin with a broken
            # import just vanished from the tool list with no trace anywhere,
            # which is indistinguishable from "that tool was never written".
            failed.append(f"{module_name} ({e})")
            continue
        if hasattr(module, "PLUGIN"):
            discovered.append(module.PLUGIN)
        if hasattr(module, "PLUGINS"):
            discovered.extend(module.PLUGINS)
    if failed and logger is not None:
        logger.warning(f"[Tools] {len(failed)} plugin(s) failed to load: {'; '.join(failed)}")
    return discovered


class ToolExecutor:
    def __init__(self, config, logger, context: dict = None):
        self.config = config
        self.logger = logger
        self.context = context or {}
        self._plugins = _discover_plugins(logger)
        self._by_name = {p.name: p for p in self._plugins}
        self.logger.info(f"[Tools] Discovered {len(self._plugins)} tool plugin(s): {', '.join(self._by_name)}")

        # Lightweight usage counters (how many times each tool was
        # requested, regardless of whether it was allowed to run) - used by
        # the get_tool_usage_stats tool so the user can see what Eva
        # actually gets used for.
        self._stats_lock = threading.Lock()
        self._stats_file = config.get("tool_stats", "file", default="data/tool_stats.json")
        self._stats: dict[str, int] = self._load_stats()

    def _load_stats(self) -> dict:
        if os.path.exists(self._stats_file):
            try:
                with open(self._stats_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_stats(self):
        """Caller must hold self._stats_lock. Atomic write (temp + replace)
        so a crash mid-write can never corrupt the stats file."""
        try:
            os.makedirs(os.path.dirname(self._stats_file) or ".", exist_ok=True)
            tmp_path = f"{self._stats_file}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._stats, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._stats_file)
        except Exception as e:
            self.logger.debug(f"[Tools] Could not save usage stats: {e}")

    def _record_usage(self, name: str):
        with self._stats_lock:
            self._stats[name] = self._stats.get(name, 0) + 1
            self._save_stats()

    def get_usage_summary(self, top_n: int = 10) -> list[tuple[str, int]]:
        with self._stats_lock:
            items = sorted(self._stats.items(), key=lambda kv: kv[1], reverse=True)
        return items[:top_n]

    # ----------------------------------------------------- declarations ---

    def declarations(self) -> list:
        decls = []
        for plugin in self._plugins:
            try:
                if plugin.is_enabled(self.config):
                    decls.append(plugin.declaration(self.config))
            except Exception as e:
                self.logger.warning(f"[Tools] Plugin '{plugin.name}' failed to build its declaration: {e}")
        return decls

    # ------------------------------------------------- permission matrix ---

    def _check_permission_matrix(self, name: str, args: dict) -> str | None:
        """Checks every string argument (recursively) against the hard
        blocklist in config.permission_matrix.blocked_patterns. Returns the
        matched pattern if blocked, or None if the call is allowed to
        proceed. This runs BEFORE any plugin code and cannot be bypassed by
        argument phrasing, since it inspects the actual values being passed."""
        patterns = self.config.get("permission_matrix", "blocked_patterns", default=[]) or []
        if not patterns:
            return None

        def flatten_strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for v in value.values():
                    yield from flatten_strings(v)
            elif isinstance(value, (list, tuple)):
                for v in value:
                    yield from flatten_strings(v)

        haystack = " | ".join(flatten_strings(args)).lower()
        for pattern in patterns:
            if str(pattern).lower() in haystack:
                return str(pattern)
        return None

    # Argument keys that regularly carry free-form user content (a typed
    # password, a message body, a fact to remember, ...) rather than
    # structural values (an action name, a coordinate, a contact label).
    # The audit log's job is showing WHAT ran, not permanently storing
    # WHATEVER TEXT was typed/sent/remembered - especially now that
    # control_computer can type anything into any focused field, including
    # things like passwords a user dictates to fill in a form.
    _REDACTED_ARG_KEYS = {"text", "message", "value", "note"}
    # A couple of tools echo the sensitive value back in their own result
    # string (e.g. remember_fact confirms "key = value" so the user can hear
    # exactly what got stored) - redacting args alone wouldn't stop that
    # value from still ending up in the audit log via the result field.
    _REDACTED_RESULT_TOOLS = {"remember_fact"}

    @classmethod
    def _redact_for_audit(cls, args: dict) -> dict:
        redacted = {}
        for k, v in (args or {}).items():
            if k in cls._REDACTED_ARG_KEYS and isinstance(v, str) and v:
                redacted[k] = f"<redacted, {len(v)} chars>"
            else:
                redacted[k] = v
        return redacted

    # -------------------------------------------------------- execution ---

    def execute(self, name: str, args: dict, voice_verified: bool = True) -> str:
        safe_args = self._redact_for_audit(args or {})
        self.logger.info(f"[Tool] Execution requested: {name}({safe_args})")
        self._record_usage(name)

        plugin = self._by_name.get(name)
        if not plugin:
            return f"Tool '{name}' is unknown."

        blocked_reason = self._check_permission_matrix(name, args or {})
        if blocked_reason:
            self.logger.warning(f"[Tool] BLOCKED by permission matrix: {name}({safe_args}) - {blocked_reason}")
            audit_logger = self.context.get("audit_logger")
            if audit_logger:
                audit_logger.info(f"BLOCKED (permission matrix) | tool={name} | args={safe_args} | reason={blocked_reason}")
            return (
                "This action was blocked by a hard safety rule and will never be executed, "
                "regardless of how the request is phrased."
            )

        voice_lock_enabled = self.config.get("voice_lock", "enabled", default=False)
        if voice_lock_enabled and name in SENSITIVE_TOOLS and not voice_verified:
            msg = (
                f"Tool '{name}' was refused: voice lock is enabled and this request's voice "
                f"could not be verified against the enrolled voiceprint."
            )
            self.logger.warning(f"[Tool] {msg}")
            audit_logger = self.context.get("audit_logger")
            if audit_logger:
                audit_logger.info(f"REFUSED (voice lock) | tool={name} | args={safe_args}")
            return "This action requires voice verification and could not be confirmed, so it was not executed."

        try:
            result = plugin.execute(args or {}, self.config, self.context)
        except Exception as e:
            self.logger.error(f"[Tool] Error while executing {name}: {e}")
            result = f"An error occurred while executing the tool: {e}"
            notifier = self.context.get("notifier")
            if notifier:
                notifier("Eva - tool error", f"{name} failed: {e}", self.logger)

        audit_logger = self.context.get("audit_logger")
        if audit_logger:
            safe_result = "<redacted>" if name in self._REDACTED_RESULT_TOOLS else str(result)[:200]
            audit_logger.info(f"EXECUTED | tool={name} | args={safe_args} | result={safe_result}")

        return result
