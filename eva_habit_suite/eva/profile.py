"""
profile.py
----------
Long-term facts/preferences about the user, separate from the rolling
conversation memory. Facts persist forever (until cleared) and are injected
into every request's context, regardless of topic - e.g. "home_address" is
still known even in a conversation that started about the weather.

Facts are only ever added when the model explicitly calls the
`remember_fact` tool (see plugins/memory_tool.py) - there is no automatic
background extraction, so nothing is stored without an explicit trigger.
"""

from __future__ import annotations

import os
import json

import secure_storage


class LongTermProfile:
    def __init__(self, config, logger):
        self.logger = logger
        self.enabled = config.get("long_term_facts", "enabled", default=True)
        self.file_path = config.get("long_term_facts", "file", default="data/profile.json")
        # Hard cap so an open-ended "remember lots of things" session (or a
        # source repeatedly triggering remember_fact) can't grow this file -
        # which gets injected into EVERY future request - without bound.
        self.max_facts = config.get("long_term_facts", "max_facts", default=300)
        self.facts: dict = {}
        self._load()

    def _load(self):
        if not self.enabled:
            return
        try:
            self.facts = secure_storage.load_json(self.file_path, self.logger, default={}) or {}
        except Exception as e:
            self.logger.warning(f"Could not load profile facts, starting empty: {e}")
            self.facts = {}

    def _save(self):
        if not self.enabled:
            return
        try:
            secure_storage.save_json(self.file_path, self.facts, self.logger)
        except Exception as e:
            self.logger.warning(f"Could not save profile facts: {e}")

    def set(self, key: str, value: str):
        if not self.enabled:
            return
        key = (key or "").strip()
        if not key:
            return
        is_new_key = key not in self.facts
        self.facts[key] = (value or "").strip()
        # If a brand-new key pushed us over the cap, drop the oldest entries
        # first (dict preserves insertion order) rather than refusing to
        # store the newest fact or growing unbounded.
        if is_new_key:
            while len(self.facts) > self.max_facts:
                oldest_key = next(iter(self.facts))
                del self.facts[oldest_key]
        self._save()

    def forget(self, key: str) -> bool:
        """Removes a single stored fact by key. Returns True if it existed."""
        if not self.enabled:
            return False
        key = (key or "").strip()
        if key in self.facts:
            del self.facts[key]
            self._save()
            return True
        return False

    def as_context(self) -> str:
        if not self.enabled or not self.facts:
            return ""
        lines = ["Known facts about the user (always true, use when relevant):"]
        for k, v in self.facts.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def clear(self):
        self.facts = {}
        if self.enabled and os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except Exception as e:
                self.logger.warning(f"Could not delete profile file: {e}")
