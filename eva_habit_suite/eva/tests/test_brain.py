"""
test_brain.py
-------------
Unit tests for the Ollama-backed EvaBrain and ConversationMemory. Mocks
`requests.post` instead of calling a real Ollama server, so these run
without a local model installed or Ollama running.

Replaces the old test_brain_gemini_legacy.py, which mocked the Gemini SDK
client that brain.py no longer uses since the move to a local Ollama/Gemma
backend.
"""

import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, _DEFAULTS  # noqa: E402
import logging  # noqa: E402


def make_test_config(tmp_path, overrides=None):
    data = json.loads(json.dumps(_DEFAULTS))  # deep copy
    data["memory"]["file"] = os.path.join(tmp_path, "memory.json")
    data["logging"]["file"] = os.path.join(tmp_path, "test.log")
    data["permissions"]["datetime"]["enabled"] = True
    if overrides:
        data.update(overrides)
    return Config(data)


def silent_logger():
    logger = logging.getLogger("jarvis-test")
    logger.addHandler(logging.NullHandler())
    return logger


def ollama_chat_response(text: str) -> MagicMock:
    """Builds a fake `requests.post` response shaped like Ollama's
    /api/chat reply: .raise_for_status() is a no-op and .json() returns
    the {"message": {...}} structure brain.py expects."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"message": {"role": "assistant", "content": text}}
    return resp


class TestConversationMemory(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.config = make_test_config(self.tmp_dir)
        self.logger = silent_logger()

    @patch("memory.requests.post")
    def test_add_and_retrieve_recent_context(self, mock_post):
        from memory import ConversationMemory

        mock_post.side_effect = Exception("no embeddings in test")

        mem = ConversationMemory("http://127.0.0.1:11434", self.config, self.logger)
        mem.add_exchange("hello", "welcome")
        mem.add_exchange("how are you", "doing great, thanks")

        context = mem.get_context("a new question")
        self.assertIn("hello", context)
        self.assertIn("doing great, thanks", context)

    @patch("memory.requests.post")
    def test_clear_removes_persisted_file(self, mock_post):
        from memory import ConversationMemory

        mock_post.side_effect = Exception("no embeddings in test")

        mem = ConversationMemory("http://127.0.0.1:11434", self.config, self.logger)
        mem.add_exchange("test", "response")
        self.assertTrue(os.path.exists(self.config.get("memory", "file")))

        mem.clear()
        self.assertFalse(os.path.exists(self.config.get("memory", "file")))
        self.assertEqual(mem.turns, [])


class TestEvaBrain(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.config = make_test_config(self.tmp_dir)
        self.logger = silent_logger()

    @patch("brain.requests.post")
    def test_analyze_returns_text_and_updates_memory(self, mock_post):
        from brain import EvaBrain

        mock_post.return_value = ollama_chat_response("test reply from eva")

        brain = EvaBrain(self.config, self.logger)
        result = brain.analyze("test question")

        self.assertEqual(result, "test reply from eva")
        self.assertEqual(len(brain.memory.turns), 2)

    @patch("brain.time.sleep")  # skip the real retry backoff delays
    @patch("brain.requests.post")
    def test_analyze_reports_error_on_ollama_failure(self, mock_post, mock_sleep):
        import requests
        from brain import EvaBrain

        mock_post.side_effect = requests.ConnectionError("connection refused")

        brain = EvaBrain(self.config, self.logger)
        # analyze() never raises for a backend failure - it logs and
        # returns a user-facing message instead, so voice/UI callers
        # always get something speakable back.
        result = brain.analyze("test question")

        self.assertIn("couldn't reach my local model", result)
        self.assertEqual(mock_post.call_count, 3)  # exhausted all retries


if __name__ == "__main__":
    unittest.main()
