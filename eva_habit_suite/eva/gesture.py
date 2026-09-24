"""
gesture.py
----------
Local, offline hand-raise detection using mediapipe. This does NOT send
frames to Gemini for detection - the detection itself is instant and free,
running entirely on the local CPU. Only once a raised hand is confirmed does
the app call Eva (via Gemini) to react.

Design choice: this module does NOT own the camera. It receives frames that
the UI is already capturing for the live preview, so there is only ever one
VideoCapture object for the whole app (avoids device conflicts).
"""

import time


class HandRaiseDetector:
    def __init__(self, config, logger, on_hand_raised):
        self.logger = logger
        self.on_hand_raised = on_hand_raised

        self.enabled = config.get("gesture", "enabled", default=True)
        self.zone_ratio = config.get("gesture", "raise_hand_zone_ratio", default=0.35)
        self.cooldown_seconds = config.get("gesture", "cooldown_seconds", default=15)

        self._last_trigger_ts = 0.0
        self._paused = False
        self._hands = None

        if self.enabled:
            self._init_mediapipe()

    def _init_mediapipe(self):
        try:
            import mediapipe as mp
            self._mp_hands = mp.solutions.hands
            self._hands = self._mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.6,
                min_tracking_confidence=0.5,
            )
            self.logger.info("[Gesture] mediapipe hand tracking initialized.")
        except ImportError:
            self.logger.warning("[Gesture] mediapipe is not installed - hand-raise detection disabled.")
            self._hands = None
        except Exception as e:
            self.logger.warning(f"[Gesture] Could not initialize mediapipe: {e}")
            self._hands = None

    @property
    def available(self) -> bool:
        return self.enabled and self._hands is not None

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def process_frame(self, frame_rgb):
        """
        Feed one RGB frame (numpy array) from the existing camera loop.
        Triggers on_hand_raised() at most once per cooldown window.
        Cheap to call at low frame rates; does nothing if unavailable/paused.
        """
        if not self.available or self._paused:
            return

        now = time.time()
        if now - self._last_trigger_ts < self.cooldown_seconds:
            return

        try:
            results = self._hands.process(frame_rgb)
        except Exception as e:
            self.logger.debug(f"[Gesture] Frame processing error (ignored): {e}")
            return

        if not results.multi_hand_landmarks:
            return

        frame_height = frame_rgb.shape[0]
        threshold_y = frame_height * self.zone_ratio

        for hand_landmarks in results.multi_hand_landmarks:
            wrist = hand_landmarks.landmark[self._mp_hands.HandLandmark.WRIST]
            wrist_y_px = wrist.y * frame_height
            if wrist_y_px < threshold_y:
                self._last_trigger_ts = now
                self.logger.info("[Gesture] Raised hand detected.")
                self.on_hand_raised()
                return

    def shutdown(self):
        if self._hands:
            try:
                self._hands.close()
            except Exception:
                pass
