"""
voice_lock.py
-------------
A BEST-EFFORT voice similarity check, not a secure biometric system. It
compares the average MFCC (voice timbre) features of the current audio
against a single enrolled sample using cosine similarity. This can be
fooled (e.g. by a recording of the enrolled voice) and can also reject the
real user in noisy conditions - it is a basic deterrent against a stranger
casually using sensitive voice commands, not a security guarantee.

Only gates the SENSITIVE_TOOLS list defined in tools.py, and only for
voice-originated commands (typed text bypasses it entirely, since typing
already requires physical access to the keyboard).
"""

from __future__ import annotations

import os


class VoiceLock:
    def __init__(self, config, logger):
        self.logger = logger
        self.enabled = config.get("voice_lock", "enabled", default=False)
        self.threshold = config.get("voice_lock", "similarity_threshold", default=0.85)
        self.profile_path = config.get("voice_lock", "profile_file", default="data/voiceprint.npy")
        self._reference_vector = None
        self._np = None
        self._librosa = None

        if self.enabled:
            self._init()

    def _init(self):
        try:
            import numpy as np
            import librosa
            self._np = np
            self._librosa = librosa
            if os.path.exists(self.profile_path):
                self._reference_vector = np.load(self.profile_path)
                self.logger.info("[VoiceLock] Loaded an enrolled voiceprint.")
            else:
                self.logger.warning("[VoiceLock] Enabled but no voiceprint enrolled yet - all sensitive commands will be refused until enrollment.")
        except ImportError:
            self.logger.warning("[VoiceLock] librosa/numpy unavailable - voice lock disabled.")
            self.enabled = False

    @property
    def available(self) -> bool:
        return self.enabled and self._librosa is not None

    def _extract_features(self, audio_data):
        """audio_data: a speech_recognition AudioData object"""
        wav_bytes = audio_data.get_wav_data()
        import io
        y, sr = self._librosa.load(io.BytesIO(wav_bytes), sr=16000)
        mfcc = self._librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
        return mfcc.mean(axis=1)

    def enroll_from_audio(self, audio_data) -> str:
        if not self.available:
            return "Voice lock is unavailable (librosa not installed)."
        try:
            vector = self._extract_features(audio_data)
            os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
            self._np.save(self.profile_path, vector)
            self._reference_vector = vector
            return "Voice enrolled successfully."
        except Exception as e:
            self.logger.warning(f"[VoiceLock] Enrollment failed: {e}")
            return f"Could not enroll voice: {e}"

    def verify(self, audio_data) -> bool:
        """Returns True if verification passes OR voice lock is disabled/unavailable
        (fail-open when the feature itself isn't active), False if enabled
        but the voice doesn't match or nothing is enrolled yet."""
        if not self.enabled:
            return True
        if not self.available or self._reference_vector is None or audio_data is None:
            return False
        try:
            vector = self._extract_features(audio_data)
            similarity = self._np.dot(vector, self._reference_vector) / (
                self._np.linalg.norm(vector) * self._np.linalg.norm(self._reference_vector) + 1e-9
            )
            return bool(similarity >= self.threshold)
        except Exception as e:
            self.logger.warning(f"[VoiceLock] Verification failed, defaulting to reject: {e}")
            return False
