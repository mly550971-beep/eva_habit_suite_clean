"""EVA local brain using Ollama (Gemma 4) with native tool calling."""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from memory import ConversationMemory
from profile import LongTermProfile
from tools import ToolExecutor
from notifier import notify

MAX_TOOL_ITERATIONS = 7

class RateLimitedError(Exception):
    pass

class OllamaError(RuntimeError):
    pass

class EvaBrain:
    def __init__(self, config, logger, audit_logger=None, ui_callbacks: dict = None):
        self.logger = logger
        self.base_url = config.get("local_model", "base_url", default="http://127.0.0.1:11434").rstrip("/")
        self.model_name = config.get("model", "name", default="gemma4:e2b")
        self.temperature = config.get("model", "temperature", default=0.2)
        self.system_instruction = config.get("system_instruction", default="You are EVA, a personal AI assistant.")
        self.request_timeout = int(config.get("local_model", "request_timeout", default=300))
        self.context_window = int(config.get("local_model", "context_window", default=32768))
        self.top_p = float(config.get("model", "top_p", default=0.95))
        self.keep_alive = config.get("local_model", "keep_alive", default="30m")

        self.memory = ConversationMemory(self.base_url, config, logger)
        self.profile = LongTermProfile(config, logger)
        self.modes = config.get("modes", default={})
        self.current_mode = "default"

        tool_context = {
            "client": None,
            "model_name": self.model_name,
            "profile": self.profile,
            "notifier": notify,
            "logger": logger,
            "audit_logger": audit_logger,
            "brain": self,
            "ui_callbacks": ui_callbacks or {},
        }
        self.tools = ToolExecutor(config, logger, tool_context)
        tool_context["tool_executor"] = self.tools

        self.min_seconds_between_requests = config.get("rate_limit", "min_seconds_between_requests", default=0.25)
        self._last_request_ts = 0.0
        self.last_response_text = ""
        self._consecutive_local_failures = 0
        self.api_failure_threshold = config.get("health_check", "consecutive_api_failure_threshold", default=3)

    def set_mode(self, mode_name: str) -> bool:
        if mode_name != "default" and mode_name not in self.modes:
            return False
        self.current_mode = mode_name
        return True

    def _effective_system_instruction(self) -> str:
        if self.current_mode == "default":
            return self.system_instruction
        suffix = self.modes.get(self.current_mode, "")
        return f"{self.system_instruction}\n{suffix}" if suffix else self.system_instruction

    def _enforce_rate_limit(self):
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.min_seconds_between_requests:
            time.sleep(self.min_seconds_between_requests - elapsed)
        self._last_request_ts = time.time()

    def _tool_schemas(self) -> list[dict]:
        return [decl.to_ollama() for decl in self.tools.declarations() if hasattr(decl, "to_ollama")]

    def _chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float | None = None) -> dict:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "top_p": self.top_p,
                "num_ctx": self.context_window,
            },
            "keep_alive": self.keep_alive,
        }
        if tools:
            payload["tools"] = tools
        last_exc = None
        for attempt in range(3):
            try:
                r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.request_timeout)
                r.raise_for_status()
                data = r.json()
                if not isinstance(data, dict) or "message" not in data:
                    raise OllamaError(f"Unexpected Ollama response: {data!r}")
                return data
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise OllamaError(f"Ollama request failed after retries: {last_exc}") from last_exc

    def generate_developer_text(self, prompt: str, temperature: float = 0.1) -> str:
        messages = [
            {"role": "system", "content": "You are EVA's local software-engineering subsystem. Return only the requested artifact. Never execute code yourself."},
            {"role": "user", "content": prompt},
        ]
        data = self._chat(messages, tools=None, temperature=temperature)
        return ((data.get("message") or {}).get("content") or "").strip()

    def generate_vision_text(self, prompt: str, image_path: str | None = None, temperature: float | None = None) -> str:
        """One-off generation for tools that need a fresh model call outside
        the main tool-calling loop (read_screen, locate_on_screen,
        copy_text_from_screen, summarize_conversations, read_text_aloud's
        from_screen mode). No tools, no conversation memory - just a single
        prompt (optionally with a screenshot) in, text out. This is the
        Ollama-native replacement for the old Gemini `client.files.upload` +
        `client.models.generate_content` calls those tools used to make."""
        self._enforce_rate_limit()
        message = self._build_user_message(prompt, image_path)
        data = self._chat([message], tools=None, temperature=self.temperature if temperature is None else temperature)
        return self._message_content(data)

    @staticmethod
    def _message_content(response: dict) -> str:
        return ((response.get("message") or {}).get("content") or "").strip()

    @staticmethod
    def _tool_calls(response: dict) -> list[tuple[str, dict]]:
        calls = []
        for call in ((response.get("message") or {}).get("tool_calls") or []):
            fn = call.get("function") or {}
            name = fn.get("name")
            args = fn.get("arguments") or {}
            if name:
                calls.append((name, args if isinstance(args, dict) else {}))
        return calls

    def _build_user_message(self, text: str, image_path: str | None = None) -> dict:
        msg: dict[str, Any] = {"role": "user", "content": text}
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                msg["images"] = [base64.b64encode(f.read()).decode("ascii")]
        return msg

    def analyze(self, prompt: str, image_path: str = None, on_chunk=None, voice_verified: bool = True) -> str:
        self._enforce_rate_limit()
        try:
            memory_context = self.memory.get_context(prompt or "")
            facts_context = self.profile.as_context()
            base_prompt = prompt if prompt else "Analyze the scene in front of me in detail and tell me the most important things you see."
            messages = [{"role": "system", "content": self._effective_system_instruction()}]
            if facts_context:
                messages.append({"role": "system", "content": facts_context})
            if memory_context:
                messages.append({"role": "system", "content": memory_context})
            messages.append(self._build_user_message(base_prompt, image_path))

            tool_schemas = self._tool_schemas()
            response = self._chat(messages, tool_schemas)
            iterations = 0
            while iterations < MAX_TOOL_ITERATIONS:
                calls = self._tool_calls(response)
                if not calls:
                    break
                with ThreadPoolExecutor(max_workers=max(1, len(calls))) as executor:
                    futures = [executor.submit(self.tools.execute, name, args, voice_verified) for name, args in calls]
                    results = [f.result() for f in futures]
                assistant_message = response.get("message") or {"role": "assistant", "content": ""}
                messages.append(assistant_message)
                for (name, _args), result_text in zip(calls, results):
                    messages.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": str(result_text),
                    })
                response = self._chat(messages, tool_schemas)
                iterations += 1

            final_text = self._message_content(response) or "I could not generate a clear answer, please try again."
            if on_chunk:
                threading.Thread(target=self._simulate_streaming, args=(final_text, on_chunk), daemon=True).start()
            self.memory.add_exchange(prompt or "(image with no accompanying text)", final_text)
            self.last_response_text = final_text
            self._consecutive_local_failures = 0
            return final_text
        except Exception as exc:
            self._consecutive_local_failures += 1
            self.logger.exception("Local model error")
            if self._consecutive_local_failures >= self.api_failure_threshold:
                notify("Eva - local model unavailable", "Make sure Ollama is running and the configured model is installed.", self.logger)
                self._consecutive_local_failures = 0
            return f"I couldn't reach my local model right now. {exc}"

    @staticmethod
    def _simulate_streaming(text: str, on_chunk, delay: float = 0.012):
        for i, word in enumerate(text.split(" ")):
            on_chunk(word if i == 0 else " " + word)
            time.sleep(delay)
