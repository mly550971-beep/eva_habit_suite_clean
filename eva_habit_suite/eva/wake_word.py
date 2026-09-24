"""
wake_word.py
------------
A simple wake word implemented via short periodic listening (keyword
spotting) using STTEngine, instead of relying on a dedicated wake-word
engine (like Porcupine) that requires an API key.

Idea: it listens for a few seconds repeatedly, and if the recognized text
contains the wake phrase, it calls a callback to notify the rest of the app
that it's time to execute a command.

Important: listening must be paused while Jarvis is speaking or processing
a request, otherwise it would hear itself and enter an infinite loop.
"""

import threading
import time


class WakeWordListener:
    def __init__(self, stt_engine, config, logger, on_wake):
        self.stt = stt_engine
        self.logger = logger
        self.on_wake = on_wake

        self.enabled = config.get("wake_word", "enabled", default=True)
        self.phrase = config.get("wake_word", "phrase", default="eva").strip().lower()
        self.chunk_seconds = config.get("wake_word", "listen_chunk_seconds", default=3)

        self._running = False
        self._paused = False
        self._thread = None

    def start(self):
        if not self.enabled:
            self.logger.info("[WakeWord] Feature is disabled in settings.")
            return
        if not self.stt.available:
            self.logger.warning("[WakeWord] Cannot start: STT engine unavailable.")
            return
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.logger.info(f"[WakeWord] Started listening for wake phrase: '{self.phrase}'")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            if self._paused:
                time.sleep(0.2)
                continue
            try:
                text = self.stt.listen_once(timeout=2, phrase_time_limit=self.chunk_seconds)
                if text and self.phrase in text.strip().lower():
                    self.logger.info(f"[WakeWord] Wake phrase detected in: '{text}'")
                    self.pause()  # pause listening until the command is executed and resumed from outside
                    self.on_wake()
            except Exception as e:
                self.logger.debug(f"[WakeWord] Ignoring temporary error in loop: {e}")
                time.sleep(0.5)
