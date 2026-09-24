"""
ui.py
-----
Two-window design:

1. AgentWindow (root): live camera feed, full activity log, and every
   diagnostic control (face/voice enrollment, gesture indicator).
2. UserWindow (Toplevel): clean, minimal daily-use interface with an
   animated "speaking" indicator instead of a static dot - no transcript
   shown here on purpose.

All UI updates go through a queue and run on the Main Thread only.
"""

import os
import logging
import sys
import time
import math
import random
import threading
import queue
import tempfile
import requests

try:
    import cv2
except ImportError:
    # OpenCV missing entirely (as opposed to installed-but-broken, which
    # _open_camera_device below handles separately) - camera, face
    # recognition and mood-hint are all optional features, so this alone
    # should never stop Eva from starting. cv2 stays None; every call site
    # is already reached only through _open_camera_device's stand-in below,
    # the mood-hint try/except at init, or after a successful frame read
    # (which can't happen without a real cv2), so nothing else touches it.
    cv2 = None
from PIL import Image, ImageDraw
import tkinter

import offline_commands
import customtkinter as ctk

from brain import EvaBrain
from voice import TTSEngine, STTEngine
from wake_word import WakeWordListener
from gesture import HandRaiseDetector
from daily_briefing import DailyBriefing
from face import FaceRecognizer
from voice_lock import VoiceLock
from notifier import notify

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

COLOR_BG = "#03060C"
COLOR_PANEL = "#0A1424"
COLOR_ACCENT = "#4FC3F7"
COLOR_ACCENT_DIM = "#0D47A1"
COLOR_GOLD = "#7FDBFF"
COLOR_OK = "#00FFC2"
COLOR_WARN = "#FFCC00"
COLOR_ERR = "#FF5C5C"
COLOR_LISTEN = "#1E88E5"
COLOR_TEXT = "#E4ECF7"
COLOR_TEXT_DIM = "#5E7089"


def _dim_color(hex_color: str, factor: float) -> str:
    """Returns a darkened version of a hex color (factor 0..1). Used to fake
    a soft 'glow halo' by drawing a wider, dimmer line under a thin bright
    one - no alpha blending needed, so it works identically on every
    platform/Tk build."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = int(r * factor), int(g * factor), int(b * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


class _NullCamera:
    """Stand-in for cv2.VideoCapture used when the local OpenCV install is
    broken (e.g. two opencv-* packages installed on top of each other left
    cv2 without VideoCapture at all). Without this, that install problem
    raised AttributeError straight out of __init__ and crash-looped the
    whole app instead of just running camera-less like it already does for
    "no camera detected" - a real environment problem should degrade the
    one feature that needs it, not take Eva down entirely."""

    def isOpened(self):
        return False

    def read(self):
        return False, None

    def release(self):
        pass


def _open_camera_device(index=0):
    """Opens the camera. On Windows, explicitly requests the DirectShow
    backend - the default backend on some Windows camera drivers keeps the
    device (and its LED) claimed even after .release() is called; DirectShow
    releases it cleanly and immediately."""
    if cv2 is None or not hasattr(cv2, "VideoCapture"):
        # Two distinct broken states land here: cv2 isn't installed at all
        # (cv2 is None, see the import above), or it imported but is
        # missing its core API (commonly opencv-python and
        # opencv-contrib-python both installed at once, or a corrupted
        # install of either). Either way this is an environment problem,
        # not "no camera plugged in" - log it distinctly, then hand back a
        # stand-in so startup can continue with the camera feature simply
        # unavailable instead of crash-looping the whole app.
        logging.getLogger("jarvis").error(
            "[Camera] OpenCV (cv2) is unavailable or broken - camera, face "
            "recognition and gesture detection will not work until it's "
            "reinstalled: pip uninstall opencv-python opencv-contrib-python "
            "opencv-python-headless -y && pip install opencv-contrib-python. "
            "Running without camera for now."
        )
        return _NullCamera()
    if sys.platform.startswith("win"):
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(index)


class HologramCanvas(ctk.CTkCanvas):
    """
    A dependency-free 'pseudo-3D' holographic HUD visualizer: rotating
    tilted rings (real 3D->2D projection math, not images) around a
    pulsing circular equalizer, in an Iron-Man-style look. This is drawn
    entirely with trigonometry on a normal Tkinter canvas - no game engine,
    no browser, no extra installs - so it can never break anything that
    currently works on your machine.
    """
    RING_COUNT = 3
    SEGMENTS = 64
    SPIKES = 48

    def __init__(self, master, size=260, **kwargs):
        super().__init__(master, width=size, height=size, bg=COLOR_PANEL, highlightthickness=0, **kwargs)
        self.size = size
        self.cx = size / 2
        self.cy = size / 2
        self._phase = 0.0
        self._state = "idle"  # idle | listening | speaking | busy
        self._amp_current = [4.0] * self.SPIKES
        self._running = True

    def set_state(self, state: str):
        self._state = state

    def stop(self):
        self._running = False

    def _state_color(self):
        return {
            "idle": COLOR_ACCENT,
            "listening": COLOR_LISTEN,
            "speaking": COLOR_GOLD,
            "busy": COLOR_ACCENT_DIM,
        }.get(self._state, COLOR_ACCENT)

    def _project(self, radius, tilt, rot):
        """3D->2D projection of a circle of given radius: tilt around the
        X axis, then rotate around the vertical (Y) axis, with a simple
        depth-based scale to fake perspective."""
        pts = []
        for i in range(self.SEGMENTS + 1):
            theta = 2 * math.pi * i / self.SEGMENTS
            x0, z0 = radius * math.cos(theta), radius * math.sin(theta)
            y1 = -z0 * math.sin(tilt)
            z1 = z0 * math.cos(tilt)
            x2 = x0 * math.cos(rot) + z1 * math.sin(rot)
            z2 = -x0 * math.sin(rot) + z1 * math.cos(rot)
            depth_scale = 1 + z2 / (radius * 3.2)
            pts.append((self.cx + x2 * depth_scale, self.cy + y1 * depth_scale))
        return pts

    def tick(self):
        if not self._running:
            return
        try:
            self.delete("all")
            self._phase += 0.028
            color = self._state_color()
            glow = _dim_color(color, 0.35)

            # 0) faint static radar rings in the background for depth
            for i in range(3):
                r = self.size * (0.46 - i * 0.09)
                self.create_oval(self.cx - r, self.cy - r, self.cx + r, self.cy + r,
                                  outline=COLOR_ACCENT_DIM, width=1)

            base_radius = self.size * 0.34
            for ring_i in range(self.RING_COUNT):
                radius = base_radius - ring_i * 14
                tilt = 0.9 + ring_i * 0.35
                direction = 1 if ring_i % 2 == 0 else -1
                speed_multiplier = 2.2 if self._state == "busy" else 1.0
                rot = self._phase * (0.6 + ring_i * 0.25) * direction * speed_multiplier
                pts = self._project(radius, tilt, rot)
                flat = [c for p in pts for c in p]
                base_w = 2 if ring_i == 0 else 1
                # glow halo underneath, then a crisp bright line on top
                self.create_line(*flat, fill=glow, width=base_w + 4, smooth=True)
                self.create_line(*flat, fill=color, width=base_w, smooth=True)

            eq_radius = self.size * 0.20
            for i in range(self.SPIKES):
                angle = 2 * math.pi * i / self.SPIKES
                if self._state == "speaking":
                    target = random.uniform(4, 26)
                elif self._state == "listening":
                    target = 6 + 4 * math.sin(self._phase * 3 + i * 0.3)
                elif self._state == "busy":
                    target = 5 + 3 * math.sin(self._phase * 2 + i * 0.5)
                else:
                    target = 4 + 2 * math.sin(self._phase * 1.2 + i * 0.2)
                self._amp_current[i] += (target - self._amp_current[i]) * 0.28
                length = self._amp_current[i]
                x0 = self.cx + eq_radius * math.cos(angle)
                y0 = self.cy + eq_radius * math.sin(angle)
                x1 = self.cx + (eq_radius + length) * math.cos(angle)
                y1 = self.cy + (eq_radius + length) * math.sin(angle)
                self.create_line(x0, y0, x1, y1, fill=glow, width=4)
                self.create_line(x0, y0, x1, y1, fill=color, width=2)

            core_r = 10 + (5 * abs(math.sin(self._phase * 4)) if self._state == "speaking" else 0)
            self.create_oval(self.cx - core_r - 6, self.cy - core_r - 6,
                              self.cx + core_r + 6, self.cy + core_r + 6, fill=glow, outline="")
            self.create_oval(self.cx - core_r, self.cy - core_r, self.cx + core_r, self.cy + core_r,
                              fill=color, outline="")

            # digital clock embedded inside the ring itself (real system time)
            self.create_text(self.cx, self.cy + core_r + 22, text=time.strftime("%H:%M:%S"),
                              fill=color, font=("Consolas", 13, "bold"))
        except Exception:
            self._running = False
            return
        self.after(20, self.tick)


class AnimatedBackground(ctk.CTkCanvas):
    """Ambient full-window animated backdrop for UserWindow: a pure
    starfield of small drifting, twinkling dots on a plain dark background
    - no glow band/gradient sweep. Purely decorative - it sits behind
    every other widget (via tkinter.Misc.lower, see _build_ui) and never
    intercepts clicks or keyboard focus, so it can't break anything
    already working.
    """

    PARTICLE_COUNT = 110

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, **kwargs)
        self._running = True
        self._particles = []
        self._state = "idle"  # idle | listening | speaking | busy - mirrors the hologram ball
        self.bind("<Configure>", self._on_resize)

    def set_state(self, state: str):
        self._state = state

    def _state_colors(self):
        """Same palette as the hologram ball, so the background always
        reads as one connected system with it rather than two separate
        effects."""
        return {
            "idle": (COLOR_ACCENT, COLOR_ACCENT_DIM),
            "listening": (COLOR_LISTEN, _dim_color(COLOR_LISTEN, 0.4)),
            "speaking": (COLOR_GOLD, _dim_color(COLOR_GOLD, 0.4)),
            "busy": (COLOR_ACCENT_DIM, _dim_color(COLOR_ACCENT_DIM, 0.5)),
        }.get(self._state, (COLOR_ACCENT, COLOR_ACCENT_DIM))

    def _on_resize(self, event):
        if not self._particles and event.width > 1 and event.height > 1:
            self._spawn_particles(event.width, event.height)

    def _spawn_particles(self, w, h):
        self._particles = [
            {
                "x": random.uniform(0, w),
                "y": random.uniform(0, h),
                # most stars are tiny and dim, a few are bigger/brighter -
                # that size mix is what reads as "depth" in a starfield
                # rather than a flat grid of identical dots.
                "r": random.choice([0.8, 1.0, 1.0, 1.4, 1.4, 2.2]),
                "speed": random.uniform(0.05, 0.35),
                "phase": random.uniform(0, 6.283),
            }
            for _ in range(self.PARTICLE_COUNT)
        ]

    def stop(self):
        self._running = False

    def tick(self):
        if not self._running:
            return
        try:
            w, h = self.winfo_width(), self.winfo_height()
            if w > 1 and h > 1:
                if not self._particles:
                    self._spawn_particles(w, h)
                self.delete("all")
                bright, dim = self._state_colors()
                # while speaking/listening, drift/twinkle noticeably faster -
                # gives the whole window a "reacting" feel instead of just the ball
                speed_mult = 2.0 if self._state == "speaking" else (1.4 if self._state == "listening" else 1.0)

                # drifting, twinkling particles ("stars") - the whole background
                for p in self._particles:
                    p["y"] -= p["speed"] * speed_mult
                    if p["y"] < -4:
                        p["y"] = h + 4
                        p["x"] = random.uniform(0, w)
                    p["phase"] += 0.05 * speed_mult
                    twinkle = 0.5 + 0.5 * math.sin(p["phase"])
                    color = bright if twinkle > 0.6 else dim
                    r = p["r"]
                    self.create_oval(p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r,
                                      fill=color, outline="")
        except Exception:
            self._running = False
            return
        self.after(40, self.tick)


class BootSplash(ctk.CTkToplevel):
    """One-time animated startup overlay: three pulsing rings plus a few
    lines of status text typed out in sequence, ending in "<NAME> ONLINE".
    Purely cosmetic and fully self-contained - it always destroys itself
    and calls on_complete after a fixed ~2.2s, even if the animation
    itself hits an error, so a splash-screen bug can never strand the app
    with the real windows permanently hidden."""

    LINES = ["INITIALIZING CORE SYSTEMS...", "CALIBRATING SENSORS...", "{name} ONLINE"]
    DURATION_MS = 2200

    def __init__(self, master, assistant_name: str, on_complete):
        super().__init__(master)
        self.on_complete = on_complete
        self._closed = False
        self._phase = 0.0
        self._line_index = 0
        self._char_index = 0
        self._lines = [line.format(name=assistant_name.upper()) for line in self.LINES]

        try:
            self.overrideredirect(True)
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.configure(fg_color=COLOR_BG)

        w, h = 460, 300
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self.canvas = ctk.CTkCanvas(self, width=w, height=h, bg=COLOR_BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.cx, self.cy = w / 2, h / 2 - 25

        self._tick()
        self.after(250, self._type_next_char)
        self.after(self.DURATION_MS, self._finish)

    def _tick(self):
        if self._closed:
            return
        try:
            self.canvas.delete("all")
            self._phase += 0.05
            for i in range(3):
                r = 20 + i * 22 + 18 * abs(math.sin(self._phase - i * 0.4))
                self.canvas.create_oval(self.cx - r, self.cy - r, self.cx + r, self.cy + r,
                                         outline=COLOR_ACCENT, width=2)
            self.canvas.create_text(self.cx, self.cy + 95, text=self._typed_text(),
                                     fill=COLOR_ACCENT, font=("Consolas", 13, "bold"), justify="center")
        except Exception:
            self._finish()
            return
        self.after(30, self._tick)

    def _typed_text(self) -> str:
        done_lines = self._lines[:self._line_index]
        current = self._lines[self._line_index][:self._char_index] if self._line_index < len(self._lines) else ""
        return "\n".join(done_lines + ([current] if current else []))

    def _type_next_char(self):
        if self._closed or self._line_index >= len(self._lines):
            return
        line = self._lines[self._line_index]
        if self._char_index < len(line):
            self._char_index += 1
            self.after(35, self._type_next_char)
        else:
            self._line_index += 1
            self._char_index = 0
            if self._line_index < len(self._lines):
                self.after(200, self._type_next_char)

    def _finish(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_complete:
            self.on_complete()


class AgentWindow(ctk.CTk):
    """Root window: camera feed + full activity log + diagnostics"""

    def __init__(self, config, logger, audit_logger=None):
        super().__init__()
        self.config = config
        self.logger = logger
        self.assistant_name = config.get("assistant_name", default="Eva")

        self.title(f"{self.assistant_name} — Agent View")
        self.geometry("1080x720")
        self.configure(fg_color=COLOR_BG)

        self.busy = False
        self.privacy_mode = False
        self.camera_off = False
        self._closed = False  # guards on_closing() against running twice
            # (once when the window is closed normally, again from main.py's
            # crash-cleanup finally block) which would call self.destroy()
            # on an already-destroyed Tk window and spam the log.
        self._emergency_stop = False
        self.current_frame = None
        self._cam_scan_phase = 0.0  # drives the HUD scanline sweep on the camera feed
        self.ui_queue = queue.Queue()
        self.user_window = None

        try:
            self.brain = EvaBrain(
                config, logger, audit_logger,
                ui_callbacks={
                    "now_playing": self._now_playing_safe,
                    # Lazy lookups (self.tts doesn't exist yet at this exact
                    # line) - fine, since these are only ever invoked later,
                    # well after __init__ finishes building the window.
                    "speak": lambda text, **kw: self.tts.speak(text, **kw),
                    "last_spoken_text": lambda: self.tts.last_spoken_text,
                },
            )
        except ValueError as e:
            self._fatal_error(str(e))
            return

        self.self_improve_scanner = None
        try:
            from self_improve_scanner import SelfImproveScanner
            self.self_improve_scanner = SelfImproveScanner(config, logger, self.brain)
            self.self_improve_scanner.start()
        except Exception as e:
            logger.warning(f"[SelfImproveScanner] Could not start: {e}")

        self.tts = TTSEngine(logger)
        self.stt = STTEngine(config, logger)
        self.wake_word = WakeWordListener(self.stt, config, logger, on_wake=self._on_wake_detected)
        self.gesture = HandRaiseDetector(config, logger, on_hand_raised=self._on_hand_raised)
        self.gesture_prompt = config.get(
            "gesture", "prompt",
            default="The user just raised their hand to get your attention. Greet them briefly and ask what they need."
        )

        self.daily_briefing = DailyBriefing(config, logger, on_trigger=self._on_daily_briefing)
        self.daily_briefing.start()

        # Background scheduler: adhan at prayer times, reminders (scheduler.py)
        self.scheduler = None
        try:
            from scheduler import build_scheduler
            self.scheduler = build_scheduler(self, config, logger)
            self.scheduler.start()
        except Exception as e:
            logger.warning(f"[Scheduler] Could not start: {e}")

        self.face = FaceRecognizer(config, logger)
        self.face_greet_cooldown = config.get("face_recognition", "greet_cooldown_seconds", default=300)
        self._last_face_greet_ts = 0.0
        self._last_greeted_name = None

        self.voice_lock = VoiceLock(config, logger)

        self.continuous_enabled = config.get("conversation", "continuous", default=True)
        self.followup_timeout = config.get("conversation", "follow_up_timeout_seconds", default=6)
        self.exit_phrases = [
            p.strip().lower() for p in config.get(
                "conversation", "exit_phrases",
                default=["stop listening", "that's all", "thanks eva"]
            )
        ]

        self.mood_hint_enabled = config.get("mood_hint", "enabled", default=False)
        self.mood_cooldown = config.get("mood_hint", "cooldown_seconds", default=20)
        self._last_mood_ts = 0.0
        self._smile_cascade = None
        if self.mood_hint_enabled:
            try:
                self._smile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")
            except Exception as e:
                self.logger.warning(f"[Mood] Could not load smile cascade: {e}")

        cam_interval = config.get("camera", "interval_ms", default=80)
        self.cam_interval = cam_interval
        self.cam_size = tuple(config.get("camera", "preview_size", default=[520, 390]))

        self.cap = _open_camera_device(0)
        if not self.cap.isOpened():
            self._log_safe("Warning: no camera detected. Running in text/voice-only mode.")

        self._build_ui()
        self._pulse_state = 0

        self.update_camera_feed()
        self._process_ui_queue()
        self._pulse_status_indicator()

        if not self.stt.available:
            self._log_safe("Warning: speech recognition unavailable. Voice commands and wake word are disabled.")
        else:
            self.wake_word.start()

        if not self.gesture.available:
            self._log_safe("Note: hand-raise detection unavailable (mediapipe missing or disabled).")
        if config.get("face_recognition", "enabled", default=False) and not self.face.available:
            self._log_safe("Note: face recognition unavailable (needs opencv-contrib-python).")
        if config.get("voice_lock", "enabled", default=False) and not self.voice_lock.available:
            self._log_safe("Note: voice lock unavailable (needs librosa/numpy).")

        if config.get("startup_greeting", "enabled", default=True):
            self.after(2500, self._exec_startup_greeting)

        threading.Thread(target=self._run_health_check, daemon=True).start()

        self._internet_up = True  # optimistic initial assumption; corrected by the first periodic check
        health_check_enabled = config.get("health_check", "enabled", default=True)
        if health_check_enabled:
            interval_minutes = config.get("health_check", "interval_minutes", default=30)
            self.after(interval_minutes * 60 * 1000, self._periodic_health_check)

    def _run_health_check(self):
        """Quick, one-time check of the subsystems Eva depends on, run in
        the background at startup so any problem is visible immediately in
        the log instead of surfacing later as a confusing failure."""
        results = []

        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3).close()
            results.append("✅ Internet")
        except Exception:
            results.append("❌ Internet (no connection)")

        try:
            import requests
            base_url = self.config.get("local_model", "base_url", default="http://127.0.0.1:11434")
            model_name = self.config.get("model", "name", default="gemma4:e2b")
            r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=2)
            models = {m.get("name") for m in r.json().get("models", [])}
            results.append("✅ Ollama + model found" if model_name in models else f"⚠️ Ollama up, model missing ({model_name})")
        except Exception:
            results.append("❌ Ollama unavailable (start Ollama and install the model)")
        results.append("✅ Camera" if (self.cap is not None and self.cap.isOpened()) else "⚠️ Camera unavailable")
        results.append("✅ Microphone" if self.stt.available else "⚠️ Microphone unavailable")

        self._log_safe("Startup health check: " + " | ".join(results))

    def _periodic_health_check(self):
        """Runs every `health_check.interval_minutes` for the life of the
        app (not just once at startup) and only speaks up when the
        internet connection's status actually CHANGES, so it's a useful
        early warning instead of a recurring nag every interval."""
        def check():
            import socket
            try:
                socket.create_connection(("8.8.8.8", 53), timeout=3).close()
                now_up = True
            except Exception:
                now_up = False

            if now_up != self._internet_up:
                self._internet_up = now_up
                if now_up:
                    self._log_safe("Internet connection restored.")
                    notify("Eva - back online", "Internet connection is back.", self.logger)
                else:
                    self._log_safe("Warning: internet connection appears to be down.")
                    notify("Eva - offline", "Lost internet connection - voice/AI features need it.", self.logger)

        threading.Thread(target=check, daemon=True).start()
        interval_minutes = self.config.get("health_check", "interval_minutes", default=30)
        self.after(interval_minutes * 60 * 1000, self._periodic_health_check)

    # ---------------------------------------------------------------- UI ---

    def _fatal_error(self, message: str):
        self.geometry("520x220")
        label = ctk.CTkLabel(self, text=f"Fatal error:\n{message}", text_color=COLOR_ERR,
                              font=("Consolas", 14, "bold"), wraplength=470)
        label.pack(expand=True, padx=20, pady=20)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.cam_frame = ctk.CTkFrame(self, corner_radius=18, fg_color=COLOR_PANEL,
                                       border_width=2, border_color=COLOR_ACCENT_DIM)
        self.cam_frame.grid(row=0, column=0, padx=14, pady=14, sticky="nsew")
        self.cam_frame.grid_rowconfigure(1, weight=1)
        self.cam_frame.grid_columnconfigure(0, weight=1)

        cam_title = ctk.CTkLabel(self.cam_frame, text=f"◉  {self.assistant_name.upper()} — LIVE FEED",
                                  font=("Consolas", 15, "bold"), text_color=COLOR_ACCENT)
        cam_title.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))

        self.cam_label = ctk.CTkLabel(self.cam_frame, text="Starting camera...", text_color=COLOR_TEXT_DIM)
        self.cam_label.grid(row=1, column=0, sticky="nsew", padx=18, pady=10)

        self.gesture_indicator = ctk.CTkLabel(self.cam_frame, text="", font=("Consolas", 13, "bold"),
                                               text_color=COLOR_GOLD)
        self.gesture_indicator.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 4))

        enroll_row = ctk.CTkFrame(self.cam_frame, fg_color="transparent")
        enroll_row.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 16))
        enroll_row.grid_columnconfigure((0, 1), weight=1)

        self.enroll_face_btn = ctk.CTkButton(enroll_row, text="Enroll My Face", height=32,
                                              fg_color="transparent", border_width=1, border_color=COLOR_ACCENT,
                                              text_color=COLOR_ACCENT, hover_color="#0a2a30",
                                              command=self._on_enroll_face)
        self.enroll_face_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.enroll_voice_btn = ctk.CTkButton(enroll_row, text="Enroll My Voice", height=32,
                                               fg_color="transparent", border_width=1, border_color=COLOR_LISTEN,
                                               text_color=COLOR_LISTEN, hover_color="#1a1130",
                                               command=self._on_enroll_voice)
        self.enroll_voice_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        self.privacy_btn = ctk.CTkButton(self.cam_frame, text="🔒  Privacy Mode", height=32, corner_radius=10,
                                          fg_color="transparent", border_width=1, border_color=COLOR_TEXT_DIM,
                                          text_color=COLOR_TEXT_DIM, hover_color="#1a1f2e",
                                          command=self.toggle_privacy_mode)
        self.privacy_btn.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 8))

        self.camera_toggle_btn = ctk.CTkButton(self.cam_frame, text="📷  Turn Camera Off", height=32, corner_radius=10,
                                                fg_color="transparent", border_width=1, border_color=COLOR_TEXT_DIM,
                                                text_color=COLOR_TEXT_DIM, hover_color="#1a1f2e",
                                                command=self._on_toggle_camera_btn)
        self.camera_toggle_btn.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 16))

        self.control_frame = ctk.CTkFrame(self, corner_radius=18, fg_color=COLOR_PANEL,
                                           border_width=2, border_color=COLOR_GOLD)
        self.control_frame.grid(row=0, column=1, padx=14, pady=14, sticky="nsew")
        self.control_frame.grid_rowconfigure(2, weight=1)
        self.control_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(16, 6))
        header.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(header, text="SYSTEM ONLINE", font=("Consolas", 16, "bold"),
                                          text_color=COLOR_OK)
        self.status_label.grid(row=0, column=0, sticky="w")

        self.status_dot = ctk.CTkLabel(header, text="●", font=("Consolas", 18), text_color=COLOR_OK)
        self.status_dot.grid(row=0, column=1, padx=(5, 0))

        self.clock_label = ctk.CTkLabel(header, text="", font=("Consolas", 12), text_color=COLOR_TEXT_DIM)
        self.clock_label.grid(row=0, column=2, padx=(12, 0), sticky="e")
        self._update_clock()

        subtitle = ctk.CTkLabel(self.control_frame, text="Full activity log (diagnostics)",
                                 font=("Consolas", 11), text_color=COLOR_TEXT_DIM)
        subtitle.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 6))

        self.log_box = ctk.CTkTextbox(self.control_frame, wrap="word", font=("Consolas", 12),
                                       fg_color="#020A05", text_color="#39FF6A", corner_radius=12,
                                       border_width=1, border_color=COLOR_ACCENT_DIM)
        self.log_box.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))

    def _update_clock(self):
        self.clock_label.configure(text=time.strftime("%Y-%m-%d   %H:%M:%S"))
        self.after(1000, self._update_clock)

    def _pulse_status_indicator(self):
        if not self.busy:
            colors = [COLOR_OK, "#00CC9C"]
            self._pulse_state = (self._pulse_state + 1) % len(colors)
            self.status_dot.configure(text_color=colors[self._pulse_state])
        self.after(600, self._pulse_status_indicator)

    # ------------------------------------------------------------ camera ---

    def _apply_hud_overlay(self, img: Image.Image) -> Image.Image:
        """Draws a sci-fi HUD frame directly onto the *displayed* copy of
        the camera image: four corner tracking brackets plus a scanning
        line that sweeps down and loops. Purely cosmetic and drawn fresh
        on every frame - it never touches self.current_frame or the raw
        frame_rgb array that gesture/face/mood detection actually run on,
        so it can't interfere with recognition accuracy."""
        draw = ImageDraw.Draw(img)
        w, h = img.size
        bracket = max(10, int(min(w, h) * 0.09))
        color = COLOR_ACCENT

        for x, y, dx, dy in ((0, 0, 1, 1), (w - 1, 0, -1, 1), (0, h - 1, 1, -1), (w - 1, h - 1, -1, -1)):
            draw.line([(x, y), (x + dx * bracket, y)], fill=color, width=3)
            draw.line([(x, y), (x, y + dy * bracket)], fill=color, width=3)

        self._cam_scan_phase = (self._cam_scan_phase + 0.012) % 1.0
        scan_y = int(self._cam_scan_phase * h)
        draw.line([(0, scan_y), (w, scan_y)], fill=_dim_color(color, 0.35), width=6)
        draw.line([(0, scan_y), (w, scan_y)], fill=color, width=2)
        return img

    def update_camera_feed(self):
        if self.privacy_mode or self.camera_off:
            self.after(self.cam_interval, self.update_camera_feed)
            return
        if self.cap is not None and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                self.current_frame = frame
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                img = Image.fromarray(frame_rgb)
                img = self._apply_hud_overlay(img)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=self.cam_size)
                self.cam_label.configure(image=ctk_img, text="")
                self.cam_label.image = ctk_img  # keep a real reference so Tk doesn't garbage-collect
                # the image right after this function returns (classic Tkinter crash otherwise:
                # "image pyimageN doesn't exist")

                if not self.busy:
                    if self.gesture.available:
                        threading.Thread(target=self.gesture.process_frame, args=(frame_rgb,), daemon=True).start()
                    if self.face.available:
                        threading.Thread(target=self._check_face, args=(frame.copy(),), daemon=True).start()
                    if self.mood_hint_enabled and self._smile_cascade is not None:
                        threading.Thread(target=self._check_mood, args=(frame.copy(),), daemon=True).start()
            else:
                self.cam_label.configure(text="Camera connection lost", image=None)
                self.cam_label.image = None
        self.after(self.cam_interval, self.update_camera_feed)

    def _check_face(self, frame_bgr):
        now = time.time()
        if now - self._last_face_greet_ts < self.face_greet_cooldown:
            return
        name, confidence = self.face.identify(frame_bgr)
        if name and name != self._last_greeted_name:
            self._last_face_greet_ts = now
            self._last_greeted_name = name
            self._log_safe(f"Recognized face: {name} (confidence {confidence:.1f})")
            threading.Thread(target=self._exec_greet_by_name, args=(name,), daemon=True).start()

    def _exec_greet_by_name(self, name: str):
        if self.busy:
            return
        self._set_busy(True)
        try:
            self._run_analysis(f"(system: you just recognized {name} via the camera - greet them by name briefly)")
        except Exception as e:
            self._log_safe(f"Error: {e}")
        finally:
            self._set_busy(False)

    def _check_mood(self, frame_bgr):
        now = time.time()
        if now - self._last_mood_ts < self.mood_cooldown:
            return
        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            smiles = self._smile_cascade.detectMultiScale(gray, scaleFactor=1.7, minNeighbors=22)
            if len(smiles) > 0:
                self._last_mood_ts = now
                self.logger.debug("[Mood] Smile detected (low-confidence heuristic, not a diagnosis).")
                self._tone_hint = "The user appears to be smiling - feel free to be warm and upbeat."
        except Exception as e:
            self.logger.debug(f"[Mood] Detection error (ignored): {e}")

    # --------------------------------------------------------- threading ---

    def _process_ui_queue(self):
        try:
            while True:
                action, payload = self.ui_queue.get_nowait()
                if action == "log":
                    self.log_box.insert("end", payload + "\n\n")
                    self.log_box.see("end")
                elif action == "log_append":
                    self.log_box.insert("end", payload)
                    self.log_box.see("end")
                elif action == "status":
                    text, color = payload
                    self.status_label.configure(text=text, text_color=color)
                    if self.user_window:
                        self.user_window.set_status(text, color)
                elif action == "busy":
                    if self.user_window:
                        self.user_window.set_busy(payload)
                elif action == "gesture_indicator":
                    self.gesture_indicator.configure(text=payload)
                elif action == "listen_indicator":
                    if self.user_window:
                        self.user_window.set_listen_indicator(payload)
                elif action == "speaking":
                    if self.user_window:
                        self.user_window.set_speaking(payload)
                elif action == "now_playing":
                    if self.user_window:
                        self.user_window.show_music_bar(payload)
                elif action == "greeting_flash":
                    if self.user_window:
                        self.user_window.play_greeting_animation()
        except queue.Empty:
            pass
        self.after(50, self._process_ui_queue)

    def _log_safe(self, text: str):
        self.ui_queue.put(("log", text))

    def _log_append_safe(self, text: str):
        self.ui_queue.put(("log_append", text))

    def _status_safe(self, text: str, color: str):
        self.ui_queue.put(("status", (text, color)))

    def _listen_indicator_safe(self, text: str):
        self.ui_queue.put(("listen_indicator", text))

    def _gesture_indicator_safe(self, text: str):
        self.ui_queue.put(("gesture_indicator", text))

    def _speaking_safe(self, value: bool):
        self.ui_queue.put(("speaking", value))

    def _now_playing_safe(self, title: str):
        """Thread-safe hook plugins call (e.g. play_music) to surface a
        'now playing' bar in the Eva window. Goes through the same queue as
        every other UI mutation since this can be called from a tool-
        executor worker thread, never directly from Tk."""
        self.ui_queue.put(("now_playing", title))

    def _greeting_flash_safe(self):
        self.ui_queue.put(("greeting_flash", None))

    def _set_busy(self, value: bool):
        self.busy = value
        self.ui_queue.put(("busy", value))
        if value:
            self.status_dot.configure(text_color=COLOR_WARN)
            self.wake_word.pause()
            self.gesture.pause()
        else:
            self.wake_word.resume()
            self.gesture.resume()

    # -------------------------------------------------------- actions ------

    def process_vision_request(self, prompt: str = ""):
        if self.busy or self.privacy_mode or self.camera_off:
            return
        threading.Thread(target=self._exec_vision, args=(prompt,), daemon=True).start()

    def _exec_vision(self, prompt: str):
        self._set_busy(True)
        self._status_safe("ANALYZING VISION...", COLOR_WARN)
        frame_path = None
        try:
            if self.current_frame is None:
                self._log_safe("No image available from the camera right now.")
                return
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                frame_path = tmp.name
                cv2.imwrite(frame_path, self.current_frame)
            self._run_analysis(prompt, image_path=frame_path)
        except Exception as e:
            self._log_safe(f"Error: {e}")
            self._status_safe("ERROR", COLOR_ERR)
        finally:
            if frame_path and os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except Exception:
                    pass
            self._status_safe("SYSTEM ONLINE", COLOR_OK)
            self._set_busy(False)

    def process_text_request(self, prompt: str):
        if self.busy or not prompt.strip():
            return
        threading.Thread(target=self._exec_text, args=(prompt,), daemon=True).start()

    def _exec_text(self, prompt: str):
        self._set_busy(True)
        self._status_safe("PROCESSING...", COLOR_WARN)
        try:
            # Typed text bypasses voice lock entirely (voice_verified=True) -
            # typing already requires physical keyboard access.
            self._run_analysis(prompt, voice_verified=True)
        except Exception as e:
            self._log_safe(f"Error: {e}")
            self._status_safe("ERROR", COLOR_ERR)
        finally:
            self._status_safe("SYSTEM ONLINE", COLOR_OK)
            self._set_busy(False)

    def process_voice_request(self):
        if self.busy or self.privacy_mode:
            if self.privacy_mode:
                self._log_safe("Voice command ignored: privacy mode is ON.")
            return
        threading.Thread(target=self._exec_voice_once, daemon=True).start()

    def _exec_voice_once(self):
        if not self.stt.available:
            self._log_safe("Speech recognition is not available on this device.")
            return
        self._voice_session()

    def _voice_session(self):
        """Runs one or more voice turns back-to-back. After the first
        command, if conversation.continuous is enabled, Eva keeps listening
        for follow-ups on her own (no wake word needed again) until the user
        goes quiet for follow_up_timeout_seconds or says an exit phrase."""
        self._set_busy(True)
        first_turn = True
        self._emergency_stop = False
        try:
            while True:
                if self._emergency_stop:
                    break
                if first_turn:
                    self._listen_indicator_safe(f"{self.assistant_name} is listening... say your command")
                    self._status_safe("LISTENING...", COLOR_LISTEN)
                    text = self.stt.listen_once()
                else:
                    self._listen_indicator_safe("Listening for a follow-up...")
                    self._status_safe("LISTENING...", COLOR_LISTEN)
                    text = self.stt.listen_once(timeout=self.followup_timeout, phrase_time_limit=12)
                self._listen_indicator_safe("")

                if self._emergency_stop:
                    break

                if not text:
                    if first_turn:
                        if self.stt.last_error:
                            self._log_safe(f"{self.assistant_name}: {self.stt.last_error}")
                        else:
                            self._log_safe("No voice command was understood, please try again.")
                    break

                if any(phrase in text.strip().lower() for phrase in self.exit_phrases):
                    self._log_safe(f"{self.assistant_name}: Ending conversation.")
                    break

                voice_ok = self.voice_lock.verify(self.stt.last_audio) if self.voice_lock.enabled else True
                self._status_safe("PROCESSING...", COLOR_WARN)
                try:
                    speech_done = self._run_analysis(text, voice_verified=voice_ok)
                except Exception as e:
                    self._log_safe(f"Error: {e}")
                    self._status_safe("ERROR", COLOR_ERR)
                    break

                if not self.continuous_enabled or self._emergency_stop:
                    break

                # Wait for Eva to finish talking before listening again,
                # otherwise the mic would pick up her own voice.
                speech_done.wait(timeout=60)
                first_turn = False
        finally:
            self._status_safe("SYSTEM ONLINE", COLOR_OK)
            self._set_busy(False)

    def _on_wake_detected(self):
        threading.Thread(target=self._exec_wake_command, daemon=True).start()

    def _exec_wake_command(self):
        self._voice_session()

    def _on_hand_raised(self):
        self._gesture_indicator_safe("Hand raised - checking in...")
        threading.Thread(target=self._exec_gesture_checkin, daemon=True).start()

    def _fetch_news_headlines(self, feed_url: str, max_items: int = 4) -> str:
        """Real, specific headlines from Google News' public RSS feed (no
        API key needed). A generic web search for 'top world news today'
        mostly returns each outlet's homepage description ('Reuters: Follow
        the latest...') rather than an actual dated headline - RSS <item>
        entries are the real individual stories themselves."""
        try:
            import xml.etree.ElementTree as ET
            resp = requests.get(feed_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            titles = []
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    titles.append(title_el.text.strip())
                if len(titles) >= max_items:
                    break
            if not titles:
                return "the feed returned no items right now."
            return "\n".join(f"- {t}" for t in titles)
        except Exception as e:
            return f"could not fetch headlines right now ({e})."

    def _fetch_greeting_context(self, include_news: bool = True) -> str:
        """Fetches real datetime/weather/news data by calling the tools
        directly here, instead of leaving it up to the model to decide
        whether and how to call them itself - this way the model's only
        job is to phrase already-fetched real data naturally, which is
        reliable, instead of deciding whether/how to call tools itself.

        Weather and the two news feeds are independent network calls, so
        they're run concurrently (not one after another) to cut wall-clock
        wait time roughly to the slowest single call instead of the sum of
        all of them.

        Returns a labelled text block. A tool that is disabled or that
        fails is reported as such in that block - never silently skipped
        in a way that would let the model fill the gap with an invented
        answer.
        """
        import concurrent.futures

        jobs = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            if self.config.get("permissions", "datetime", "enabled", default=False):
                jobs["datetime"] = pool.submit(self.brain.tools.execute, "get_current_datetime", {}, True)

            if self.config.get("permissions", "weather", "enabled", default=False):
                jobs["weather"] = pool.submit(self.brain.tools.execute, "get_weather", {}, True)

            if include_news and self.config.get("permissions", "web_search", "enabled", default=False):
                jobs["world_news"] = pool.submit(
                    self._fetch_news_headlines,
                    "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
                )
                jobs["egypt_news"] = pool.submit(
                    self._fetch_news_headlines,
                    "https://news.google.com/rss?hl=ar-EG&gl=EG&ceid=EG:ar",
                )

            results = {key: future.result() for key, future in jobs.items()}

        blocks = []
        if "datetime" in results:
            blocks.append(results["datetime"])
        if "weather" in results:
            blocks.append(results["weather"])
        if "world_news" in results:
            blocks.append(f"World news headlines:\n{results['world_news']}")
        if "egypt_news" in results:
            blocks.append(f"Egypt news headlines:\n{results['egypt_news']}")

        return "\n\n".join(blocks)

    def _on_daily_briefing(self, prompt: str):
        if self.busy:
            # Don't interrupt an ongoing conversation - skip silently, it will
            # simply not greet today; the next scheduled day will still fire.
            self._log_safe("Daily briefing skipped: assistant was busy.")
            return

        def run():
            context_block = self._fetch_greeting_context(include_news=True)
            full_prompt = (
                f"(system: {prompt.strip()} Using ONLY the real, already-fetched "
                "data below - do not call any tool yourself, and do not add any "
                "fact, number, or headline that isn't in it. If a section below "
                "reports a failure, just skip that part instead of inventing a "
                f"replacement.\n\n{context_block})"
            )
            self._run_analysis(full_prompt)

        threading.Thread(target=run, daemon=True).start()

    def _exec_startup_greeting(self):
        if self.busy or self.privacy_mode:
            return

        def run():
            try:
                self._greeting_flash_safe()
                self._set_busy(True)
                self._status_safe("PROCESSING...", COLOR_WARN)

                # Stage 1: greeting + date + weather, ending with the time -
                # news is deliberately left OUT of this first message and
                # only offered, never dumped straight into the spoken reply.
                context_block = self._fetch_greeting_context(include_news=False)
                prompt = (
                    "(system: the app just started up. Using ONLY the real, "
                    "already-fetched data below - do not call any tool "
                    "yourself, and do not add any fact or number that isn't "
                    "in it - speak one short, natural spoken-style message "
                    "(not a list): greet the user for the current time of "
                    "day (morning/afternoon/evening), mention today's date "
                    "and day of the week, the weather and today's forecast, "
                    "and end by stating the current time. Then, as the very "
                    "last sentence, ask whether they'd like to hear today's "
                    "top news. If any section below reports a failure, just "
                    "skip that part instead of inventing a replacement. "
                    "Speak in the same language the user normally uses with "
                    "you.\n\n"
                    f"{context_block})"
                )
                speech_done = self._run_analysis(prompt)
                speech_done.wait(timeout=30)

                # Stage 2: only now listen for the answer, and only fetch/
                # speak news if they actually said yes.
                if self._closed or not self.stt.available or self.privacy_mode:
                    return

                self._listen_indicator_safe("Listening for your answer...")
                self._status_safe("LISTENING...", COLOR_LISTEN)
                reply_text = self.stt.listen_once(timeout=self.followup_timeout, phrase_time_limit=12)
                self._listen_indicator_safe("")
                if not reply_text or not reply_text.strip():
                    return

                self._status_safe("PROCESSING...", COLOR_WARN)
                news_block = self._fetch_greeting_context(include_news=True)
                news_prompt = (
                    "(system: the user was just asked if they'd like to hear "
                    f"today's news and replied: \"{reply_text.strip()}\". If "
                    "that reply is negative or unrelated, just acknowledge it "
                    "briefly in one short sentence and stop there - do not "
                    "read any news. If it is affirmative, give a short SUMMARY "
                    "(not a raw list, a couple of natural sentences) of the "
                    "2-3 most notable world and Egypt headlines below, using "
                    "ONLY what is actually there - never invent a headline. "
                    "Speak in the same language the user just replied in.\n\n"
                    f"{news_block})"
                )
                self._run_analysis(news_prompt)
            except Exception as e:
                self._log_safe(f"Startup greeting failed: {e}")
            finally:
                self._status_safe("SYSTEM ONLINE", COLOR_OK)
                self._set_busy(False)

        threading.Thread(target=run, daemon=True).start()

    def _close_camera_hardware(self):
        """Actually releases the camera device (not just stops displaying
        it), so the physical camera LED turns off too - just skipping frame
        reads/display leaves the device claimed by the OS, which is why the
        light stays on even when the preview looks blank."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _open_camera_hardware(self):
        if self.cap is None:
            self.cap = _open_camera_device(0)
            if not self.cap.isOpened():
                self._log_safe("Warning: could not reopen the camera.")

    def toggle_privacy_mode(self):
        self.privacy_mode = not self.privacy_mode
        if self.privacy_mode:
            self.wake_word.pause()
            self.gesture.pause()
            self._log_safe(f"{self.assistant_name}: Privacy mode ON - camera hidden, microphone paused.")
            self.cam_label.configure(image=None, text="🔒  Privacy mode is ON\n(camera & microphone paused)")
            self.cam_label.image = None
            self._close_camera_hardware()
        else:
            self.wake_word.resume()
            self.gesture.resume()
            self._log_safe(f"{self.assistant_name}: Privacy mode OFF - camera & microphone resumed.")
            if not self.camera_off:
                self._open_camera_hardware()
        if hasattr(self, "privacy_btn"):
            self.privacy_btn.configure(
                text="🔓  Disable Privacy Mode" if self.privacy_mode else "🔒  Privacy Mode",
                fg_color=COLOR_ERR if self.privacy_mode else "transparent",
                text_color=COLOR_BG if self.privacy_mode else COLOR_TEXT_DIM,
            )
        if self.user_window:
            self.user_window.set_privacy_indicator(self.privacy_mode)
        return self.privacy_mode

    def toggle_camera(self):
        """Turns just the camera preview on/off (independent of full privacy
        mode, which also pauses the microphone/wake word). Useful when you
        just don't want to be seen but still want voice commands to work."""
        self.camera_off = not getattr(self, "camera_off", False)
        if self.camera_off:
            self._log_safe(f"{self.assistant_name}: Camera turned OFF.")
            self.cam_label.configure(image=None, text="📷  Camera is off")
            self.cam_label.image = None
            self._close_camera_hardware()
        else:
            self._log_safe(f"{self.assistant_name}: Camera turned ON.")
            if not self.privacy_mode:
                self._open_camera_hardware()
        if hasattr(self, "camera_toggle_btn"):
            self.camera_toggle_btn.configure(
                text="📷  Turn Camera On" if self.camera_off else "📷  Turn Camera Off",
                fg_color=COLOR_ERR if self.camera_off else "transparent",
                text_color=COLOR_BG if self.camera_off else COLOR_TEXT_DIM,
            )
        if self.user_window:
            self.user_window.set_camera_indicator(self.camera_off)
        return self.camera_off

    def _on_toggle_camera_btn(self):
        self.toggle_camera()

    def emergency_stop(self):
        """Kill-switch: instantly interrupts speech and breaks any
        in-progress voice conversation loop. Bound to a global hotkey
        (default Ctrl+Alt+K) that works even when Eva's windows aren't
        focused, so it works even if something is behaving unexpectedly."""
        self._emergency_stop = True
        try:
            self.tts.stop()
        except Exception:
            pass
        try:
            import adhan as _adhan
            _player = _adhan.get_player()
            if _player is not None:
                _player.stop()
        except Exception:
            pass
        self._log_safe(f"⛔ EMERGENCY STOP activated - {self.assistant_name} halted immediately.")
        self._status_safe("STOPPED", COLOR_ERR)
        self.after(1500, lambda: self._status_safe("SYSTEM ONLINE", COLOR_OK))

    def _exec_gesture_checkin(self):
        self._set_busy(True)
        self._status_safe("HAND DETECTED...", COLOR_GOLD)
        frame_path = None
        try:
            if self.current_frame is not None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    frame_path = tmp.name
                    cv2.imwrite(frame_path, self.current_frame)
            self._run_analysis(self.gesture_prompt, image_path=frame_path)
        except Exception as e:
            self._log_safe(f"Error: {e}")
        finally:
            if frame_path and os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except Exception:
                    pass
            self._gesture_indicator_safe("")
            self._status_safe("SYSTEM ONLINE", COLOR_OK)
            self._set_busy(False)

    def _on_enroll_face(self):
        if self.busy:
            return
        threading.Thread(target=self._exec_enroll_face, daemon=True).start()

    def _exec_enroll_face(self):
        if not self.face.available:
            self._log_safe("Face recognition is unavailable (needs opencv-contrib-python).")
            return
        self._set_busy(True)
        self._log_safe("Enrolling face - hold still and look at the camera for a few seconds...")
        samples = []
        try:
            import cv2 as _cv2
            attempts = 0
            while len(samples) < 15 and attempts < 60:
                if self.current_frame is not None:
                    gray = _cv2.cvtColor(self.current_frame, _cv2.COLOR_BGR2GRAY)
                    faces = self.face.detect_faces(gray)
                    if len(faces) > 0:
                        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                        samples.append(gray[y:y + h, x:x + w])
                attempts += 1
                time.sleep(0.2)

            name = "user"  # simple default; edit data/face_labels.json afterwards to rename
            result = self.face.enroll(name, samples)
            self._log_safe(result)
        finally:
            self._set_busy(False)

    def _on_enroll_voice(self):
        if self.busy:
            return
        threading.Thread(target=self._exec_enroll_voice, daemon=True).start()

    def _exec_enroll_voice(self):
        if not self.voice_lock.available and self.voice_lock.enabled is False:
            # try init even if not enabled yet by config, so the user can
            # enroll ahead of flipping voice_lock.enabled to true
            pass
        self._set_busy(True)
        self._listen_indicator_safe("Say a phrase now to enroll your voice...")
        self._status_safe("ENROLLING VOICE...", COLOR_LISTEN)
        text = self.stt.listen_once()
        self._listen_indicator_safe("")
        if not self.stt.last_audio:
            self._log_safe("No audio was captured - try again.")
        else:
            result = self.voice_lock.enroll_from_audio(self.stt.last_audio)
            self._log_safe(result)
        self._status_safe("SYSTEM ONLINE", COLOR_OK)
        self._set_busy(False)

    def _run_analysis(self, prompt: str, image_path: str = None, voice_verified: bool = True):
        """Runs one exchange and speaks the reply. Returns a threading.Event
        that gets set once Eva has *finished speaking* - callers that want
        to immediately listen for a follow-up (continuous conversation)
        should wait on this event first, so the microphone doesn't pick up
        Eva's own voice."""
        self._log_safe(f"You: {prompt or '(image only)'}")
        self.ui_queue.put(("log_append", f"{self.assistant_name}: "))

        def on_chunk(piece: str):
            self._log_append_safe(piece)

        self._speaking_safe(False)

        # Internal system-generated prompts (the startup greeting, the daily
        # briefing, the camera face-greeting, ...) always start with
        # "(system: ...)" and must never be checked against the offline
        # command matcher below. That matcher does plain substring matching
        # ("current time" in text), and our own instructions routinely
        # contain phrases like "the current time of day" - which used to
        # silently match the "get_time" offline command and short-circuit
        # straight to a canned "It's H:MM AM/PM." reply, without ever
        # reaching the model or using any of the real fetched weather/news
        # data. This is why the rich greeting kept collapsing back down to
        # just the time no matter what was in the prompt.
        is_system_prompt = bool(prompt) and prompt.lstrip().startswith("(system:")

        # Text-only commands are checked against the offline matcher first -
        # image-based prompts (camera greetings, gesture check-ins) always
        # need Gemini's actual vision reasoning, so they skip this entirely.
        offline_reply = (
            offline_commands.try_handle(prompt, self.config, self.logger, last_response=self.brain.last_response_text)
            if image_path is None and not is_system_prompt else None
        )
        if offline_reply is not None:
            self.logger.info("[OfflineCommands] Handled locally - no Gemini request made.")
            response = offline_reply
            self.ui_queue.put(("log_append", offline_reply))
        else:
            response = self.brain.analyze(prompt, image_path=image_path, on_chunk=on_chunk, voice_verified=voice_verified)
        self.ui_queue.put(("log_append", "\n\n"))
        self._speaking_safe(True)

        speech_done = threading.Event()

        def on_tts_end():
            self._speaking_safe(False)
            speech_done.set()

        self.tts.speak(response, on_end=on_tts_end)
        return speech_done

    def set_wake_word_enabled(self, enabled: bool):
        self.wake_word.enabled = enabled
        if enabled:
            if not self.busy:
                self.wake_word.resume()
                self.wake_word.start()
            self._log_safe("Wake word listening enabled.")
        else:
            self.wake_word.pause()
            self.wake_word.stop()
            self._log_safe("Wake word listening disabled.")

    def start_new_conversation(self):
        self.brain.start_new_conversation()
        self._log_safe("New conversation started (previous context cleared).")

    def get_history_sessions(self):
        return self.brain.memory.list_sessions()

    def get_history_session_messages(self, path: str):
        return self.brain.memory.load_session(path)

    def run_boot_sequence(self, on_complete):
        """Shows the one-time BootSplash animation, then calls on_complete.
        If anything about the splash fails (unusual window manager, etc.),
        falls straight through to on_complete so a cosmetic feature can
        never prevent Eva from actually starting."""
        try:
            BootSplash(self, self.assistant_name, on_complete)
        except Exception:
            if on_complete:
                on_complete()

    # ------------------------------------------------------------ close ----

    def on_closing(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.daily_briefing.stop()
        except Exception:
            pass
        try:
            if getattr(self, "scheduler", None) is not None:
                self.scheduler.stop()
        except Exception:
            pass
        try:
            if self.self_improve_scanner is not None:
                self.self_improve_scanner.stop()
        except Exception:
            pass
        try:
            self.wake_word.stop()
        except Exception:
            pass
        try:
            self.gesture.shutdown()
        except Exception:
            pass
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        try:
            self.tts.shutdown()
        except Exception:
            pass
        if self.user_window:
            try:
                self.user_window.destroy()
            except Exception:
                pass
        self.destroy()


class UserWindow(ctk.CTkToplevel):
    """The clean, minimal window for daily use - now with a rotating
    holographic HUD visualizer instead of flat equalizer bars."""

    def __init__(self, controller: AgentWindow):
        super().__init__(controller)
        self.controller = controller
        self.assistant_name = controller.assistant_name
        self._speaking = False
        self._listening = False
        self._busy = False

        self.title(self.assistant_name)
        self.geometry("860x600")
        self.configure(fg_color=COLOR_BG)

        self._history_window = None
        self._music_bar_after_id = None
        self._music_bar_anim_after_id = None
        self._greeting_anim_after_id = None
        self._border_pulse_phase = 0.0
        self._border_was_pulsing = False
        self._border_pulse_running = True
        self._build_ui()
        self.hologram.tick()
        self._border_pulse_tick()
        self._play_open_fade_in()

    def _build_ui(self):
        # Animated ambient backdrop - fills the whole window, sits behind
        # every other widget, and is not touched by the hologram ball.
        self.bg_canvas = AnimatedBackground(self)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        # Canvas overrides plain .lower() to mean "lower a canvas item"
        # (it's aliased to tag_lower, which requires a tagOrId argument),
        # so calling it here with no args to mean "stack this widget behind
        # its siblings" raised a TclError every single time this window was
        # built. tkinter.Misc.lower is the actual widget-stacking method -
        # calling it explicitly bypasses Canvas's shadowing override.
        tkinter.Misc.lower(self.bg_canvas)
        self.after(50, self.bg_canvas.tick)

        # Numbered telemetry ruler across the very top (HUD decoration, real ticks)
        ruler = ctk.CTkCanvas(self, height=22, bg=COLOR_BG, highlightthickness=0)
        ruler.pack(fill="x", side="top")
        self.after(50, lambda: self._draw_ruler(ruler))
        ruler.bind("<Configure>", lambda e: self._draw_ruler(ruler))

        outer = ctk.CTkFrame(self, corner_radius=22, fg_color=COLOR_PANEL,
                              border_width=2, border_color=COLOR_ACCENT_DIM)
        outer.pack(expand=True, fill="both", padx=16, pady=(4, 16))
        # Kept for the greeting light-pulse animation (border_color flicker) -
        # captured now, before the local name `outer` gets reused below for
        # the inner center column.
        self.outer_frame = outer
        outer.grid_columnconfigure(0, weight=0)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_columnconfigure(2, weight=0)
        outer.grid_rowconfigure(1, weight=1)

        top_row = ctk.CTkFrame(outer, fg_color="transparent")
        top_row.grid(row=0, column=0, columnspan=3, sticky="ew", padx=18, pady=(18, 0))
        top_row.grid_columnconfigure(0, weight=1)

        name_label = ctk.CTkLabel(top_row, text=self.assistant_name.upper(),
                                   font=("Consolas", 26, "bold"), text_color=COLOR_ACCENT)
        name_label.grid(row=0, column=0, sticky="w")

        self.top_clock = ctk.CTkLabel(top_row, text="", font=("Consolas", 10), text_color=COLOR_TEXT_DIM)
        self.top_clock.grid(row=0, column=1, sticky="e")
        self._update_top_clock()

        # ---- LEFT: live system diagnostics (real psutil data, no fake numbers) ----
        left_panel = ctk.CTkFrame(outer, width=150, corner_radius=16, fg_color="#081020",
                                   border_width=1, border_color=COLOR_ACCENT_DIM)
        left_panel.grid(row=1, column=0, sticky="ns", padx=(16, 6), pady=12)
        left_panel.grid_propagate(False)

        ctk.CTkLabel(left_panel, text="SYSTEM", font=("Consolas", 11, "bold"),
                     text_color=COLOR_ACCENT_DIM).pack(pady=(14, 10), padx=12)

        self.cpu_label, self.cpu_bar = self._make_stat_row(left_panel, "CPU")
        self.ram_label, self.ram_bar = self._make_stat_row(left_panel, "RAM")
        self.disk_label, self.disk_bar = self._make_stat_row(left_panel, "DISK")

        self.weather_label = ctk.CTkLabel(left_panel, text="Weather: --", font=("Consolas", 10),
                                           text_color=COLOR_TEXT_DIM, wraplength=120, justify="left")
        self.weather_label.pack(pady=(16, 14), padx=12)

        self._update_system_stats()
        self._update_weather_tag()

        # ---- CENTER: hologram + conversation controls (existing core UI) ----
        center_panel = ctk.CTkFrame(outer, fg_color="transparent")
        center_panel.grid(row=1, column=1, sticky="nsew", pady=12)
        root_outer = outer
        outer = center_panel  # everything below packs into the center column now

        self.hologram = HologramCanvas(outer, size=240)
        self.hologram.pack(pady=(4, 4))

        status_pill = ctk.CTkFrame(outer, corner_radius=14, fg_color="#0D3B34", height=30)
        status_pill.pack(pady=(0, 4))
        status_pill.pack_propagate(False)
        self.status_pill = status_pill
        self.status_label = ctk.CTkLabel(status_pill, text="●  ONLINE", font=("Consolas", 12, "bold"),
                                          text_color=COLOR_OK)
        self.status_label.pack(padx=16, pady=4)

        self.listen_label = ctk.CTkLabel(outer, text="", font=("Consolas", 12), text_color=COLOR_LISTEN)
        self.listen_label.pack(pady=(6, 4))

        divider = ctk.CTkFrame(outer, fg_color=COLOR_ACCENT_DIM, height=1)
        divider.pack(fill="x", padx=32, pady=(8, 14))

        self.entry = ctk.CTkEntry(outer, placeholder_text=f"Ask {self.assistant_name}...",
                                   height=42, corner_radius=14, font=("Consolas", 13))
        self.entry.pack(fill="x", padx=28, pady=(10, 14))
        self.entry.bind("<Return>", lambda e: self._on_send())

        # ---- circular HUD dock (bottom control bar) ----
        dock = ctk.CTkFrame(outer, fg_color="transparent")
        dock.pack(pady=(0, 8))

        self.voice_btn = self._make_dock_button(dock, "🎙", self._on_voice, size=52,
                                                 fg_color=COLOR_LISTEN, hover_color="#6D28D9")
        self.voice_btn.grid(row=0, column=0, padx=6)

        self.new_chat_btn = self._make_dock_button(dock, "＋", self._on_new_conversation, size=44,
                                                     fg_color="transparent", border_color=COLOR_GOLD,
                                                     text_color=COLOR_GOLD, hover_color="#2a2410")
        self.new_chat_btn.grid(row=0, column=1, padx=6)

        self.history_btn = self._make_dock_button(dock, "🕘", self._on_open_history, size=44)
        self.history_btn.grid(row=0, column=2, padx=6)

        self.privacy_btn = self._make_dock_button(dock, "🔒", lambda: self.controller.toggle_privacy_mode(), size=44)
        self.privacy_btn.grid(row=0, column=3, padx=6)

        self.camera_btn = self._make_dock_button(dock, "📷", lambda: self.controller.toggle_camera(), size=44)
        self.camera_btn.grid(row=0, column=4, padx=6)

        self.footer_clock = ctk.CTkLabel(outer, text="", font=("Consolas", 10), text_color=COLOR_TEXT_DIM)
        self.footer_clock.pack(pady=(0, 16))
        self._update_footer_clock()

        # ---- RIGHT: recent conversations (real data, from the History log) ----
        right_panel = ctk.CTkFrame(root_outer, width=190, corner_radius=16, fg_color="#081020",
                                    border_width=1, border_color=COLOR_ACCENT_DIM)
        right_panel.grid(row=1, column=2, sticky="ns", padx=(6, 16), pady=12)
        right_panel.grid_propagate(False)

        ctk.CTkLabel(right_panel, text="RECENT CHATS", font=("Consolas", 11, "bold"),
                     text_color=COLOR_ACCENT_DIM).pack(pady=(14, 10), padx=12)

        self.recent_chats_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        self.recent_chats_frame.pack(fill="both", expand=True, padx=8)
        self._refresh_recent_chats()

        # ---- "now playing" bar: hidden overlay, slides up from the bottom
        # edge of the WHOLE window (not just the center column) when a song
        # starts, and slides back down on its own after a few seconds. ----
        self.music_bar = ctk.CTkFrame(self, corner_radius=14, fg_color="#0A1424",
                                       border_width=1, border_color=COLOR_ACCENT,
                                       height=52)
        self.music_bar.grid_propagate(False)
        self._music_note_label = ctk.CTkLabel(self.music_bar, text="♪", font=("Consolas", 20),
                                               text_color=COLOR_ACCENT)
        self._music_note_label.pack(side="left", padx=(16, 10), pady=8)
        self.music_bar_label = ctk.CTkLabel(self.music_bar, text="", font=("Consolas", 12, "bold"),
                                             text_color=COLOR_TEXT, anchor="w")
        self.music_bar_label.pack(side="left", fill="x", expand=True, pady=8)
        ctk.CTkButton(self.music_bar, text="✕", width=28, height=28, corner_radius=14,
                      fg_color="transparent", text_color=COLOR_TEXT_DIM, hover_color="#1a1f2e",
                      command=self._hide_music_bar_now).pack(side="right", padx=10)

    def _make_dock_button(self, parent, text, command, size=44, fg_color="transparent",
                           border_color=COLOR_TEXT_DIM, text_color=COLOR_TEXT_DIM, hover_color="#1a1f2e"):
        """A circular HUD-style dock button (equal width/height, fully rounded)
        with a soft glow-brighten on its border on hover, on top of the
        existing fill hover_color, so every button gets a clearer 'lit up'
        feel without changing size/layout."""
        btn = ctk.CTkButton(
            parent, text=text, width=size, height=size, corner_radius=size // 2,
            fg_color=fg_color, border_width=1, border_color=border_color,
            text_color=text_color, hover_color=hover_color,
            font=("Consolas", 16), command=command,
        )
        glow_color = COLOR_ACCENT if border_color == COLOR_TEXT_DIM else border_color
        btn.bind("<Enter>", lambda e: btn.configure(border_width=2, border_color=glow_color))
        btn.bind("<Leave>", lambda e: btn.configure(border_width=1, border_color=border_color))
        return btn

    def _draw_ruler(self, canvas):
        """Purely decorative numbered telemetry ruler (01-30) across the top
        edge, like the reference HUD - real ticks, no fake data behind them."""
        try:
            canvas.delete("all")
            width = canvas.winfo_width()
            if width < 10:
                return
            count = 30
            step = width / count
            for i in range(count + 1):
                x = i * step
                canvas.create_line(x, 14, x, 22, fill=COLOR_ACCENT_DIM, width=1)
                if i % 2 == 1:
                    canvas.create_text(x, 6, text=f"{i:02d}", fill=COLOR_TEXT_DIM, font=("Consolas", 7))
        except Exception:
            pass

    def _make_stat_row(self, parent, label_text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=6)
        label = ctk.CTkLabel(row, text=f"{label_text}: --%", font=("Consolas", 11), text_color=COLOR_TEXT)
        label.pack(anchor="w")
        bar = ctk.CTkProgressBar(row, height=8, corner_radius=4, progress_color=COLOR_ACCENT,
                                  fg_color="#0D1B2E")
        bar.set(0)
        bar.pack(fill="x", pady=(4, 0))
        return label, bar

    @staticmethod
    def _stat_color(percent: float) -> str:
        if percent >= 85:
            return COLOR_ERR
        if percent >= 65:
            return COLOR_WARN
        return COLOR_ACCENT

    def _update_system_stats(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage(os.sep).percent
            self.cpu_label.configure(text=f"CPU: {cpu:.0f}%")
            self.cpu_bar.set(cpu / 100)
            self.cpu_bar.configure(progress_color=self._stat_color(cpu))
            self.ram_label.configure(text=f"RAM: {ram:.0f}%")
            self.ram_bar.set(ram / 100)
            self.ram_bar.configure(progress_color=self._stat_color(ram))
            self.disk_label.configure(text=f"DISK: {disk:.0f}%")
            self.disk_bar.set(disk / 100)
            self.disk_bar.configure(progress_color=self._stat_color(disk))
        except ImportError:
            self.cpu_label.configure(text="CPU: N/A")
            self.ram_label.configure(text="RAM: N/A")
            self.disk_label.configure(text="DISK: N/A (install psutil)")
        except Exception:
            pass
        self.after(2000, self._update_system_stats)

    def _update_weather_tag(self):
        def fetch():
            text = self._fetch_wttr_tag()
            if text is None:
                # wttr.in didn't answer - same fallback provider the
                # get_weather tool uses (Open-Meteo, also free/keyless),
                # so this small status tag doesn't sit stuck on
                # "unavailable" for as long as wttr.in's outage lasts.
                text = self._fetch_open_meteo_tag()
            if text is None:
                text = "Weather: unavailable"
            try:
                # This runs on a background thread, but self.after() (like
                # any Tkinter call) must be marshaled onto the GUI thread's
                # event loop. If this fetch finishes fast (e.g. an instant
                # connection failure with no internet) it can complete
                # before Tk's mainloop has actually started - main.py
                # builds both windows *before* calling mainloop() - and
                # Tkinter raises "main thread is not in main loop" rather
                # than queuing the call. That's harmless to skip here: this
                # is a cosmetic label update, and the next scheduled
                # refresh (10 minutes) will land fine once the loop is
                # definitely running by then.
                self.after(0, lambda: self.weather_label.configure(text=text))
            except RuntimeError:
                pass
        threading.Thread(target=fetch, daemon=True).start()
        self.after(600000, self._update_weather_tag)  # refresh every 10 minutes

    @staticmethod
    def _fetch_wttr_tag():
        try:
            resp = requests.get("https://wttr.in/?format=3", timeout=5)
            return resp.text.strip() if resp.ok else None
        except Exception:
            return None

    @staticmethod
    def _fetch_open_meteo_tag():
        """Same idea as wttr.in's ?format=3 one-liner, built from Open-Meteo
        instead: resolve the caller's location by IP (ip-api.com, free,
        keyless), then ask Open-Meteo (also free, keyless) for the current
        temperature there."""
        try:
            loc = requests.get("http://ip-api.com/json/", timeout=5).json()
            if loc.get("status") != "success":
                return None
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": loc["lat"], "longitude": loc["lon"], "current": "temperature_2m"},
                timeout=5,
            )
            r.raise_for_status()
            temp = r.json()["current"]["temperature_2m"]
            return f"{loc.get('city', 'Weather')}: {temp}°C"
        except Exception:
            return None

    def _refresh_recent_chats(self):
        for widget in self.recent_chats_frame.winfo_children():
            widget.destroy()
        sessions = self.controller.get_history_sessions()[:5]
        if not sessions:
            ctk.CTkLabel(self.recent_chats_frame, text="No conversations yet.",
                         font=("Consolas", 10), text_color=COLOR_TEXT_DIM,
                         wraplength=150).pack(pady=8)
            return
        for session in sessions:
            ts_text = time.strftime("%d %b, %H:%M", time.localtime(session["ts"]))
            btn = ctk.CTkButton(
                self.recent_chats_frame, text=f"{ts_text}\n{session['preview'][:26]}",
                anchor="w", height=44, corner_radius=8, fg_color="transparent", border_width=1,
                border_color=COLOR_ACCENT_DIM, text_color=COLOR_TEXT_DIM, hover_color="#101830",
                font=("Consolas", 9), command=lambda s=session: self._on_open_history(preselect=s),
            )
            btn.pack(fill="x", pady=3)

    def _update_top_clock(self):
        self.top_clock.configure(text=time.strftime("%a %d %b %Y   %H:%M:%S"))
        self.after(1000, self._update_top_clock)

    def _update_footer_clock(self):
        self.footer_clock.configure(text=time.strftime("%A, %d %B %Y   %H:%M"))
        self.after(1000, self._update_footer_clock)

    def set_privacy_indicator(self, active: bool):
        self.privacy_btn.configure(
            text="🔓" if active else "🔒",
            fg_color=COLOR_ERR if active else "transparent",
        )

    def set_camera_indicator(self, camera_off: bool):
        self.camera_btn.configure(
            text="📷" if not camera_off else "🚫",
            fg_color=COLOR_ERR if camera_off else "transparent",
        )

    # ---- actions ----

    def _on_send(self):
        prompt = self.entry.get().strip()
        if not prompt:
            return
        self.entry.delete(0, "end")
        self.controller.process_text_request(prompt)

    def _on_voice(self):
        self.controller.process_voice_request()

    def _on_new_conversation(self):
        self.controller.start_new_conversation()
        self.status_label.configure(text="NEW CONVERSATION STARTED", text_color=COLOR_GOLD)
        self.after(2000, lambda: self.status_label.configure(text="ONLINE", text_color=COLOR_OK))
        self._refresh_recent_chats()

    # ---- mirrored state from AgentWindow ----

    def _recompute_hologram_state(self):
        if self._speaking:
            state = "speaking"
        elif self._listening:
            state = "listening"
        elif self._busy:
            state = "busy"
        else:
            state = "idle"
        self.hologram.set_state(state)
        # keep the ambient background in sync with the ball, so the whole
        # window reads as one reacting system instead of two separate effects
        try:
            self.bg_canvas.set_state(state)
        except Exception:
            pass

    def set_status(self, text: str, color: str):
        self.status_label.configure(text=f"●  {text}", text_color=color)
        pill_bg = {
            COLOR_OK: "#0D3B34",
            COLOR_WARN: "#3B330D",
            COLOR_ERR: "#3B1414",
            COLOR_LISTEN: "#241A3B",
        }.get(color, "#151A28")
        self.status_pill.configure(fg_color=pill_bg)

    def set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.voice_btn.configure(state=state)
        self.entry.configure(state=state)
        self.new_chat_btn.configure(state=state)
        self._busy = busy
        self._recompute_hologram_state()

    def set_listen_indicator(self, text: str):
        self.listen_label.configure(text=text)
        self._listening = bool(text)
        self._recompute_hologram_state()

    def set_speaking(self, speaking: bool):
        self._speaking = speaking
        self._recompute_hologram_state()

    # ---- "now playing" bar (slide-up overlay) ----

    def show_music_bar(self, title: str):
        """Shows/refreshes the bottom 'now playing' bar with a short
        slide-up animation, then auto-hides it again after a few seconds
        (a new song restarts the timer instead of stacking)."""
        self.music_bar_label.configure(text=f"Now playing: {title}")

        if self._music_bar_after_id is not None:
            try:
                self.after_cancel(self._music_bar_after_id)
            except Exception:
                pass
        if self._music_bar_anim_after_id is not None:
            try:
                self.after_cancel(self._music_bar_anim_after_id)
            except Exception:
                pass

        self._animate_music_bar(step=0, showing=True)
        self._music_bar_after_id = self.after(8000, lambda: self._animate_music_bar(step=0, showing=False))

    def _hide_music_bar_now(self):
        if self._music_bar_after_id is not None:
            try:
                self.after_cancel(self._music_bar_after_id)
            except Exception:
                pass
        self._animate_music_bar(step=0, showing=False)

    def _animate_music_bar(self, step: int, showing: bool, total_steps: int = 10):
        """Eases `rely` (the bar's vertical position as a fraction of the
        window height) between 1.18 (fully off-screen below) and 0.97
        (resting just above the bottom edge) over `total_steps` ticks -
        a simple linear slide, cheap enough to redraw every 16ms."""
        off_screen, resting = 1.18, 0.97
        progress = min(step / total_steps, 1.0)
        rely = (off_screen - (off_screen - resting) * progress) if showing else \
               (resting + (off_screen - resting) * progress)

        if showing and step == 0:
            self.music_bar.place(relx=0.5, rely=off_screen, anchor="s", relwidth=0.86)
        self.music_bar.place_configure(rely=rely)

        if step < total_steps:
            self._music_bar_anim_after_id = self.after(
                16, lambda: self._animate_music_bar(step + 1, showing, total_steps)
            )
        elif not showing:
            self.music_bar.place_forget()

    # ---- greeting light-pulse animation ----

    def _play_open_fade_in(self):
        """Soft fade-in of the whole window on open (alpha 0 -> 1). Some
        Linux window managers ignore the -alpha attribute entirely - that's
        fine, it just means the window appears at full opacity instantly
        instead of fading, so this can never break the window itself."""
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            return

        def _step(i=0, total=12):
            try:
                self.attributes("-alpha", (i + 1) / total)
            except Exception:
                return
            if i + 1 < total:
                self.after(20, lambda: _step(i + 1, total))

        self.after(10, _step)

    def _border_pulse_tick(self):
        """Continuous soft glow-pulse on the main panel border while the
        assistant is speaking - the border 'breathes' instead of staying
        static, echoing the hologram ball's own speaking animation."""
        if not self._border_pulse_running:
            return
        # don't fight with the one-off startup greeting pulse if it's active
        if self._greeting_anim_after_id is None:
            self._border_pulse_phase += 0.12
            if self._speaking:
                brightness = 0.55 + 0.45 * math.sin(self._border_pulse_phase)
                color = COLOR_GOLD if brightness > 0.5 else _dim_color(COLOR_GOLD, 0.4)
                try:
                    self.outer_frame.configure(border_color=color, border_width=2 + round(brightness * 2))
                except Exception:
                    pass
                self._border_was_pulsing = True
            elif self._border_was_pulsing:
                try:
                    self.outer_frame.configure(border_color=COLOR_ACCENT_DIM, border_width=2)
                except Exception:
                    pass
                self._border_was_pulsing = False
        self.after(45, self._border_pulse_tick)

    def play_greeting_animation(self, step: int = 0, total_steps: int = 18):
        """A brief, light border-glow pulse on the main panel timed with
        the startup/greeting speech - purely cosmetic, gives the window a
        soft 'waking up' feel instead of just silently starting to talk."""
        if self._greeting_anim_after_id is not None:
            try:
                self.after_cancel(self._greeting_anim_after_id)
            except Exception:
                pass
        # A half sine pulse: dim -> bright -> dim, mapped onto a small set
        # of pre-existing theme colors so it never looks glitchy/off-brand.
        progress = step / total_steps
        brightness = math.sin(progress * math.pi)  # 0 -> 1 -> 0
        color = COLOR_ACCENT if brightness > 0.5 else COLOR_ACCENT_DIM
        try:
            self.outer_frame.configure(border_color=color, border_width=2 + round(brightness * 2))
        except Exception:
            pass
        if step < total_steps:
            self._greeting_anim_after_id = self.after(
                45, lambda: self.play_greeting_animation(step + 1, total_steps)
            )
        else:
            try:
                self.outer_frame.configure(border_color=COLOR_ACCENT_DIM, border_width=2)
            except Exception:
                pass

    def _on_open_history(self, preselect: dict = None):
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.focus()
        else:
            self._history_window = HistoryWindow(self)
        if preselect is not None:
            self._history_window._show_session(preselect)

    def destroy(self):
        try:
            self.hologram.stop()
        except Exception:
            pass
        try:
            self.bg_canvas.stop()
        except Exception:
            pass
        self._border_pulse_running = False
        if self._history_window is not None:
            try:
                self._history_window.destroy()
            except Exception:
                pass
        super().destroy()


class HistoryWindow(ctk.CTkToplevel):
    """Side panel listing past conversations (read-only). Sessions are
    archived automatically whenever a 'New Conversation' happens, so
    nothing here is ever the live/active chat - just a browsable log."""

    def __init__(self, user_window: "UserWindow"):
        super().__init__(user_window)
        self.user_window = user_window
        self.title("Conversation History")
        self.geometry("620x480")
        self.configure(fg_color=COLOR_BG)

        self._build_ui()
        self._load_sessions()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self.list_frame = ctk.CTkScrollableFrame(self, corner_radius=14, fg_color=COLOR_PANEL,
                                                   label_text="Past Conversations",
                                                   label_text_color=COLOR_ACCENT)
        self.list_frame.grid(row=0, column=0, padx=(14, 7), pady=14, sticky="nsew")

        self.detail_box = ctk.CTkTextbox(self, wrap="word", font=("Consolas", 12),
                                          fg_color="#0A0D16", text_color=COLOR_TEXT, corner_radius=14,
                                          state="disabled")
        self.detail_box.grid(row=0, column=1, padx=(7, 14), pady=14, sticky="nsew")

    def _load_sessions(self):
        sessions = self.user_window.controller.get_history_sessions()
        if not sessions:
            empty = ctk.CTkLabel(self.list_frame, text="No past conversations yet.",
                                  text_color=COLOR_TEXT_DIM, font=("Consolas", 12))
            empty.pack(pady=10, padx=10)
            return
        for session in sessions:
            ts_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(session["ts"]))
            btn = ctk.CTkButton(
                self.list_frame, text=f"{ts_text}\n{session['preview']}", anchor="w",
                height=48, corner_radius=10, fg_color="transparent", border_width=1,
                border_color=COLOR_ACCENT_DIM, text_color=COLOR_TEXT, hover_color="#151b2b",
                font=("Consolas", 11), command=lambda s=session: self._show_session(s),
            )
            btn.pack(fill="x", padx=6, pady=4)

    def _show_session(self, session: dict):
        messages = self.user_window.controller.get_history_session_messages(session["path"])
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        for turn in messages:
            speaker = "You" if turn.get("role") == "user" else self.user_window.assistant_name
            self.detail_box.insert("end", f"{speaker}: {turn.get('text', '')}\n\n")
        self.detail_box.configure(state="disabled")
