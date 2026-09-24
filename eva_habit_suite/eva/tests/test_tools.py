"""
test_tools.py
-------------
Verifies that the permission system rejects any disabled tool, and only
executes enabled tools.
"""

import os
import sys
import json
import logging
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, _DEFAULTS  # noqa: E402
from tools import ToolExecutor  # noqa: E402


def silent_logger():
    logger = logging.getLogger("jarvis-tools-test")
    logger.addHandler(logging.NullHandler())
    return logger


def make_config(permissions_overrides):
    data = json.loads(json.dumps(_DEFAULTS))
    data["permissions"].update(permissions_overrides)
    return Config(data)


class TestToolPermissions(unittest.TestCase):
    def test_disabled_tool_is_rejected_with_helpful_message(self):
        config = make_config({"datetime": {"enabled": False}})
        executor = ToolExecutor(config, silent_logger())

        result = executor.execute("get_current_datetime", {})
        self.assertIn("disabled", result)
        self.assertIn("config.yaml", result)

    def test_enabled_datetime_tool_returns_value(self):
        config = make_config({"datetime": {"enabled": True}})
        executor = ToolExecutor(config, silent_logger())

        result = executor.execute("get_current_datetime", {})
        self.assertIn("Current time", result)

    def test_open_application_rejects_unknown_app(self):
        config = make_config({"open_apps": {"enabled": True, "allowed": {"notepad": "notepad.exe"}}})
        executor = ToolExecutor(config, silent_logger())

        result = executor.execute("open_application", {"app_name": "unknown_program"})
        self.assertIn("not in the allowed list", result)
        self.assertIn("config.yaml", result)

    def test_declarations_only_include_enabled_permissions(self):
        config = make_config({
            "datetime": {"enabled": True},
            "web_search": {"enabled": False},
            "open_apps": {"enabled": False, "allowed": {}},
            "open_websites": {"enabled": False, "allowed": {}},
        })
        executor = ToolExecutor(config, silent_logger())
        decls = executor.declarations()

        names = [d.name for d in decls]
        self.assertIn("get_current_datetime", names)
        self.assertNotIn("web_search", names)
        self.assertNotIn("open_application", names)


if __name__ == "__main__":
    unittest.main()
