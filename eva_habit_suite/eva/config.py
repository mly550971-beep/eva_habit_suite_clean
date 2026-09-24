"""
config.py
---------
Loads the settings file (config.yaml) and exposes it as an easy-to-use object
for the rest of the project. If any key is missing from the file, a safe
default value is used instead of crashing the app.
"""

import os
import yaml

_DEFAULTS = {
    "assistant_name": "Eva",
    "model": {"name": "gemma4:e2b", "embedding_model": "embeddinggemma", "top_p": 0.95, "temperature": 0.2},
    "system_instruction": "You are EVA, a personal AI assistant.",
    "local_model": {"base_url": "http://127.0.0.1:11434", "request_timeout": 300, "embedding_timeout": 60, "context_window": 32768, "keep_alive": "30m"},
    "stt": {
        "mode": "auto",
        "language": "ar-EG",
        "vosk_model_path": "models/vosk-model-ar",
        "listen_timeout": 5,
        "phrase_time_limit": 8,
    },
    "wake_word": {"enabled": True, "phrase": "eva", "listen_chunk_seconds": 3},
    "hotkey": {"enabled": False, "combo": "ctrl+space"},
    "tray": {"enabled": False},
    "camera": {"interval_ms": 80, "preview_size": [520, 390]},
    "gesture": {
        "enabled": False,
        "raise_hand_zone_ratio": 0.35,
        "cooldown_seconds": 15,
        "prompt": "The user just raised their hand to get your attention. Greet them briefly and ask what they need.",
    },
    "mood_hint": {"enabled": False, "cooldown_seconds": 20},
    "face_recognition": {
        "enabled": False,
        "model_file": "data/face_model.yml",
        "labels_file": "data/face_labels.json",
        "confidence_threshold": 70,
        "greet_cooldown_seconds": 300,
    },
    "voice_lock": {
        "enabled": False,
        "similarity_threshold": 0.85,
        "profile_file": "data/voiceprint.npy",
    },
    "memory": {
        "enabled": True,
        "file": "data/memory.json",
        "sessions_dir": "data/sessions",
        "max_recent_turns": 12,
        "semantic_top_k": 3,
        "semantic_min_similarity": 0.45,
        "semantic_search": True,
    },
    "long_term_facts": {"enabled": True, "file": "data/profile.json", "max_facts": 300},
    "audit_log": {"file": "logs/audit.log", "max_bytes": 1048576, "backup_count": 5},
    "permissions": {
        "web_search": {"enabled": False},
        "mood_journal": {"enabled": False},
        "joke": {"enabled": False},
        "export_history": {"enabled": False, "output_dir": "data/exports"},
        "datetime": {"enabled": False},
        "open_apps": {"enabled": False, "allowed": {}},
        "open_websites": {"enabled": False, "allowed": {}},
        "open_any_app": {"enabled": False},
        "open_any_url": {"enabled": False},
        "play_music": {"enabled": False},
        "browser_tab_control": {"enabled": False},
        "site_search": {"enabled": False, "sites": {}},
        "messaging": {"enabled": False, "contacts": {}},
        "media_control": {"enabled": False},
        "screen_reading": {"enabled": False},
        # Simulates real keyboard/mouse input (typing, clicks, hotkeys,
        # scrolling). Off by default and gated by voice lock like the other
        # broad-reach tools - this is the biggest real-world-impact
        # permission in the app, since it can interact with ANY open
        # window, not just Eva's own.
        "computer_control": {"enabled": False, "max_type_length": 500, "min_seconds_between_actions": 0.3},
        # Overwrites whatever is currently on the system clipboard - off by
        # default since that's a (mild) side effect on something outside
        # the app, even though the screen reading itself is read-only.
        "clipboard_access": {"enabled": False},
        # Speaks arbitrary text aloud (on-screen or supplied) - low risk,
        # on by default, still capped in length.
        "read_aloud": {"enabled": True, "max_chars": 4000},
        "conversation_summary": {"enabled": True},
        "usage_stats": {"enabled": True},
        "reminders": {"enabled": False},
        "weather": {"enabled": True, "default_location": ""},
        "self_improve": {"enabled": True},
        "file_search": {
            "enabled": False,
            "roots": ["~/Desktop", "~/Documents", "~/Downloads"],
            "max_results": 20,
            "timeout_seconds": 5,
        },
    },
    "modes_enabled": True,
    "modes": {
        "formal": "Speak in a formal, professional, precise tone. No jokes or casual phrasing.",
        "friendly": "Speak in a warm, casual, friendly tone. Light humor is welcome.",
        "concise": "Keep every reply as short as possible - one sentence when feasible.",
    },
    "daily_briefing": {
        "enabled": False,
        "time": "08:00",
        "prompt": (
            "Give the user a short, warm good-morning greeting (2-4 sentences). Call "
            "get_weather and mention today's conditions naturally as part of it."
        ),
    },
    "rate_limit": {"min_seconds_between_requests": 1.5},
    "logging": {"file": "logs/eva.log", "level": "INFO", "max_bytes": 1048576, "backup_count": 3},
    "tool_stats": {"file": "data/tool_stats.json"},
    "mood": {"file": "data/mood_log.json"},
    "health_check": {"enabled": True, "interval_minutes": 30, "consecutive_api_failure_threshold": 3},
    "boot_sequence": {"enabled": True},
    "offline_commands": {"enabled": True, "allow_lock_screen": True, "allow_power_actions": False},
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    @property
    def raw(self) -> dict:
        return self._data


class ConfigValidationError(Exception):
    """Raised when config.yaml has a real problem (bad YAML syntax, or a
    section that should be a dict but isn't). The message is written to be
    read directly by a non-programmer, since this is what shows up if
    config.yaml gets edited incorrectly."""
    pass


def _validate_structure(file_data: dict):
    """Checks that sections expected to be dictionaries (based on the
    defaults) actually are, catching common YAML editing mistakes (like
    accidentally deleting indentation) before they cause a confusing crash
    somewhere deep in the app."""
    for key, default_value in _DEFAULTS.items():
        if key not in file_data:
            continue
        if isinstance(default_value, dict) and not isinstance(file_data[key], dict):
            raise ConfigValidationError(
                f"config.yaml problem: '{key}:' should contain indented settings (like a small list "
                f"of 'name: value' lines underneath it), but it was read as a single value "
                f"({file_data[key]!r}) instead. Check the indentation under '{key}:' in config.yaml."
            )


def load_config(path: str = "config.yaml") -> Config:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = path if os.path.isabs(path) else os.path.join(base_dir, path)

    file_data = {}
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            try:
                file_data = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                mark = getattr(e, "problem_mark", None)
                location = f" (around line {mark.line + 1})" if mark else ""
                raise ConfigValidationError(
                    f"config.yaml has invalid formatting{location}. This usually means a missing colon, "
                    f"wrong indentation, or a stray character. Details: {e}"
                ) from e
    else:
        print(f"[Config] Warning: {full_path} not found, using default values.")

    _validate_structure(file_data)

    merged = _deep_merge(_DEFAULTS, file_data)

    for section, key in [
        ("memory", "file"), ("logging", "file"), ("stt", "vosk_model_path"),
        ("long_term_facts", "file"), ("audit_log", "file"),
        ("face_recognition", "model_file"), ("face_recognition", "labels_file"),
        ("voice_lock", "profile_file"), ("tool_stats", "file"), ("mood", "file"),
    ]:
        if merged.get(section, {}).get(key):
            merged[section][key] = os.path.join(base_dir, merged[section][key])

    for folder_key in ("logging", "memory", "long_term_facts", "audit_log", "face_recognition", "voice_lock", "tool_stats", "mood"):
        for file_key in ("file", "model_file", "labels_file", "profile_file"):
            path_val = merged.get(folder_key, {}).get(file_key)
            if path_val:
                os.makedirs(os.path.dirname(path_val), exist_ok=True)

    return Config(merged)
