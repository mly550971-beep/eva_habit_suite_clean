"""
voice.py
--------
- TTSEngine: speaks text aloud, using a persistent event loop (instead of
  creating a new one each time) and supports interrupting speech immediately
  when a new request comes in.
- STTEngine: converts the user's speech to text. It tries online first
  (Google Web Speech via the SpeechRecognition library, fast and accurate,
  no API key needed), and automatically falls back to a local offline model
  (Vosk) if that fails. If both fail, it returns None with a clear log
  message instead of crashing the app.
"""

from __future__ import annotations

import os
import re
import json
import asyncio
import tempfile
import threading

import pygame
import edge_tts


def clean_text_for_speech(text: str) -> str:
    """
    Strips markdown/formatting symbols so the TTS engine speaks natural
    words instead of literally saying "asterisk asterisk" or "hashtag".
    Numbers and normal punctuation are left untouched.
    """
    if not text:
        return text
    cleaned = text
    # Bold/italic/strikethrough markers: **text**, *text*, __text__, _text_, ~~text~~
    cleaned = re.sub(r"(\*\*|__)(.*?)\1", r"\2", cleaned)
    cleaned = re.sub(r"(\*|_)(.*?)\1", r"\2", cleaned)
    cleaned = re.sub(r"~~(.*?)~~", r"\1", cleaned)
    # Inline code / code blocks
    cleaned = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", cleaned)
    # Markdown headers (#, ##, ###...)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    # Bullet/list markers at start of line (-, *, +, •)
    cleaned = re.sub(r"^\s*[\-\*\+•]\s+", "", cleaned, flags=re.MULTILINE)
    # Any leftover stray markdown symbols
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    # Collapse extra whitespace left behind
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟])\s+")


def split_into_sentences(text: str) -> list[str]:
    """Splits cleaned text into speakable chunks on sentence boundaries.
    Used to start playing the first sentence while the rest are still
    being synthesized, instead of waiting for the whole reply."""
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return parts or [text]


class TTSEngine:
    def __init__(self, logger):
        self.logger = logger
        pygame.mixer.init()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._speaking = False
        self._generation = 0  # bumped on every speak()/stop() so a superseded
        # (interrupted) speech's own cleanup can't stomp on a newer one's state
        self.last_spoken_text: str | None = None  # used by the repeat_last_response tool

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @staticmethod
    def _voice_for(text: str) -> str:
        has_arabic = any('\u0600' <= c <= '\u06FF' for c in text)
        return "ar-EG-SalmaNeural" if has_arabic else "en-US-AriaNeural"

    async def _synthesize(self, sentence: str, rate: str = "+0%", volume: str = "+0%") -> str:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            path = fp.name
        try:
            await edge_tts.Communicate(sentence, self._voice_for(sentence), rate=rate, volume=volume).save(path)
            return path
        except Exception as e:
            # edge-tts calls Microsoft's cloud voice service - it NEEDS
            # internet. If that's unreachable, fall back to a fully
            # offline, on-device voice (pyttsx3/SAPI5 on Windows) so Eva
            # can still speak - more robotic, but still an answer instead
            # of dead silence.
            self.logger.warning(f"[TTS] edge-tts unavailable ({e}) - falling back to offline voice.")
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            offline_path = path.rsplit(".", 1)[0] + ".wav"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._synthesize_offline_sync, sentence, offline_path)
            return offline_path

    @staticmethod
    def _synthesize_offline_sync(sentence: str, path: str) -> None:
        """Blocking - always called via run_in_executor, never on the
        asyncio loop thread. Creates a fresh pyttsx3 engine per call
        (pyttsx3 engines aren't safe to reuse across calls/threads)."""
        import pyttsx3

        engine = pyttsx3.init()
        try:
            engine.save_to_file(sentence, path)
            engine.runAndWait()
        finally:
            engine.stop()

    async def _play_file(self, path: str, generation: int):
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if generation != self._generation:
                pygame.mixer.music.stop()
                break
            await asyncio.sleep(0.05)
        pygame.mixer.music.unload()

    async def _speak_pipelined(self, text: str, generation: int, on_start=None, on_end=None,
                                rate: str = "+0%", volume: str = "+0%"):
        """Speaks sentence-by-sentence, synthesizing the NEXT sentence while
        the CURRENT one is still playing. This means the reply starts being
        heard as soon as just the first sentence is ready, rather than
        waiting for the entire (possibly long) response to finish
        synthesizing first. `rate`/`volume` use edge-tts's percentage
        syntax (e.g. "-20%", "+15%") and default to normal speech."""
        temp_files = []
        try:
            sentences = split_into_sentences(text)
            if not sentences:
                return

            first_path = await self._synthesize(sentences[0], rate, volume)
            temp_files.append(first_path)
            if generation != self._generation:
                return  # a newer speak() call already superseded this one

            self._speaking = True
            if on_start:
                on_start()

            next_synth_task = (
                asyncio.ensure_future(self._synthesize(sentences[1], rate, volume)) if len(sentences) > 1 else None
            )

            for i in range(len(sentences)):
                if generation != self._generation:
                    if next_synth_task is not None:
                        next_synth_task.cancel()
                    break
                path = first_path if i == 0 else temp_files[i]
                await self._play_file(path, generation)
                if next_synth_task is not None:
                    next_path = await next_synth_task
                    temp_files.append(next_path)
                    upcoming = i + 2
                    next_synth_task = (
                        asyncio.ensure_future(self._synthesize(sentences[upcoming], rate, volume))
                        if upcoming < len(sentences) else None
                    )
        except Exception as e:
            self.logger.error(f"[TTS] Error while generating/playing audio: {e}")
        finally:
            if generation == self._generation:
                self._speaking = False
                if on_end:
                    on_end()
            for path in temp_files:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    def speak(self, text: str, on_start=None, on_end=None, rate: str = "+0%", volume: str = "+0%"):
        if not text:
            return
        self.stop()
        self._generation += 1
        generation = self._generation
        spoken_text = clean_text_for_speech(text)
        self.last_spoken_text = spoken_text
        asyncio.run_coroutine_threadsafe(
            self._speak_pipelined(spoken_text, generation, on_start, on_end, rate, volume), self._loop
        )

    def stop(self):
        """Interrupts the current speech immediately."""
        self._generation += 1
        try:
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception:
            pass

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def shutdown(self):
        self.stop()
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


class STTEngine:
    """
    Speech recognition with automatic fallback:
    mode="auto"    -> tries online, falls back to offline on failure
    mode="online"  -> online only
    mode="offline" -> offline only
    """

    def __init__(self, config, logger):
        self.logger = logger
        self.mode = config.get("stt", "mode", default="auto")
        self.language = config.get("stt", "language", default="ar-EG")
        self.vosk_model_path = config.get("stt", "vosk_model_path", default="models/vosk-model-ar")
        self.listen_timeout = config.get("stt", "listen_timeout", default=5)
        self.phrase_time_limit = config.get("stt", "phrase_time_limit", default=8)
        self.pause_threshold = config.get("stt", "pause_threshold", default=0.8)

        self._sr = None
        self._recognizer = None
        self._vosk_model = None
        self.last_audio = None  # raw AudioData of the most recent capture (used by voice lock)
        # Human-readable reason the last listen_once() call returned None -
        # None means "nothing to report" (genuine silence/timeout). Lets
        # callers show the real cause (mic permission denied, no default
        # input device, device busy, etc.) instead of a generic "didn't
        # understand you" that looks identical whether the user said
        # nothing or the microphone never opened at all.
        self.last_error = None
        # WakeWordListener calls listen_once() in a tight loop every couple
        # of seconds, so a persistent mic failure (permission denied, no
        # device) would otherwise write the identical ERROR line to the log
        # forever. Only the first occurrence is logged at ERROR; the
        # message text also lives in self.last_error every time, so the UI
        # can still surface it on each attempt without spamming the log.
        self._mic_error_logged = False
        self._init_online()
        self._init_offline_if_needed()

    def _init_online(self):
        try:
            import speech_recognition as sr
            self._sr = sr
            self._recognizer = sr.Recognizer()
            # How long a silence has to be before a phrase is considered
            # "finished" - lower means Eva reacts faster to you stopping
            # talking, instead of waiting a long fixed time regardless of
            # your actual speech pattern.
            self._recognizer.pause_threshold = self.pause_threshold
        except ImportError:
            self.logger.warning("speech_recognition library is not installed - online recognition unavailable.")

    def _init_offline_if_needed(self):
        if self.mode not in ("auto", "offline"):
            return
        if not os.path.isdir(self.vosk_model_path):
            self.logger.warning(
                f"Vosk model not found at {self.vosk_model_path}. "
                "Offline recognition will not work until the model is downloaded and placed at this path."
            )
            return
        try:
            import vosk
            self._vosk_model = vosk.Model(self.vosk_model_path)
        except ImportError:
            self.logger.warning("vosk library is not installed - offline recognition unavailable.")
        except Exception as e:
            self.logger.warning(f"Could not load the Vosk model: {e}")

    # ------------------------------------------------------------- public API ---

    def listen_once(self, timeout=None, phrase_time_limit=None) -> str | None:
        """Records once from the microphone and returns the recognized text, or None on failure"""
        if not self._sr or not self._recognizer:
            self.logger.error("Cannot record: speech_recognition library is unavailable.")
            return None

        timeout = timeout or self.listen_timeout
        phrase_time_limit = phrase_time_limit or self.phrase_time_limit

        self.last_error = None
        try:
            with self._sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        except self._sr.WaitTimeoutError:
            # Genuinely normal: the mic opened fine, the user just didn't
            # say anything before the timeout. Nothing to report.
            self.logger.debug("[STT] No speech detected within the timeout.")
            return None
        except OSError as e:
            # This is what actually fires when Windows' microphone
            # permission is off for desktop apps, no default input device
            # is set, or another app is holding the device - PyAudioWPatch
            # surfaces all of these as OSError. Previously this was logged
            # at debug level under the same "no speech detected" message as
            # ordinary silence, so a completely-blocked microphone looked
            # identical to the user just not having said anything -
            # nothing ever showed the real cause.
            self.last_error = (
                f"Could not access the microphone ({e}). Check that "
                "Windows microphone privacy access is allowed for desktop "
                "apps (Settings > Privacy & security > Microphone), that a "
                "default input device is set, and that no other app is "
                "using it."
            )
            if not self._mic_error_logged:
                self.logger.error(f"[STT] {self.last_error}")
                self._mic_error_logged = True
            return None
        except Exception as e:
            self.last_error = f"Unexpected microphone error: {e}"
            if not self._mic_error_logged:
                self.logger.error(f"[STT] {self.last_error}")
                self._mic_error_logged = True
            return None

        self.last_audio = audio
        self._mic_error_logged = False  # a successful open clears the debounce

        if self.mode in ("auto", "online"):
            text = self._recognize_online(audio)
            if text:
                return text
            if self.mode == "online":
                return None
            self.logger.info("[STT] Online recognition failed, trying offline...")

        return self._recognize_offline(audio)

    def _recognize_online(self, audio) -> str | None:
        try:
            return self._recognizer.recognize_google(audio, language=self.language)
        except self._sr.UnknownValueError:
            self.logger.debug("[STT-Online] Could not understand the audio.")
            return None
        except self._sr.RequestError as e:
            self.logger.warning(f"[STT-Online] Could not reach the service (likely no internet): {e}")
            return None
        except Exception as e:
            self.logger.warning(f"[STT-Online] Unexpected error: {e}")
            return None

    def _recognize_offline(self, audio) -> str | None:
        if not self._vosk_model:
            self.logger.warning("[STT-Offline] Vosk model not loaded - cannot recognize speech.")
            return None
        try:
            import vosk

            raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
            recognizer = vosk.KaldiRecognizer(self._vosk_model, 16000)
            recognizer.AcceptWaveform(raw_data)
            result = json.loads(recognizer.FinalResult())
            text = result.get("text", "").strip()
            return text or None
        except Exception as e:
            self.logger.warning(f"[STT-Offline] Error during recognition: {e}")
            return None

    @property
    def available(self) -> bool:
        return self._sr is not None
