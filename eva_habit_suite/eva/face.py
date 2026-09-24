"""
face.py
-------
Local face recognition using OpenCV's built-in LBPH recognizer (requires
opencv-contrib-python) plus a Haar cascade for face detection - lightweight,
no external model downloads, no cloud calls.

Enrollment: call enroll(name, frames) with a handful of grayscale face crops
of one person. The trained model is saved to disk so it survives restarts.

Recognition: call identify(frame_bgr) periodically (throttled by the
caller) - returns (name, confidence) or (None, None) if no known face
is found.
"""

from __future__ import annotations

import os
import json


class FaceRecognizer:
    def __init__(self, config, logger):
        self.logger = logger
        self.enabled = config.get("face_recognition", "enabled", default=False)
        self.model_path = config.get("face_recognition", "model_file", default="data/face_model.yml")
        self.labels_path = config.get("face_recognition", "labels_file", default="data/face_labels.json")
        self.confidence_threshold = config.get("face_recognition", "confidence_threshold", default=70)

        self._cv2 = None
        self._recognizer = None
        self._face_cascade = None
        self._labels: dict = {}  # {int_id: name}
        self._trained = False

        if self.enabled:
            self._init()

    def _init(self):
        try:
            import cv2
            self._cv2 = cv2
            if not hasattr(cv2, "face"):
                self.logger.warning(
                    "[Face] cv2.face is unavailable - install opencv-contrib-python "
                    "instead of opencv-python for face recognition support."
                )
                return
            self._recognizer = cv2.face.LBPHFaceRecognizer_create()
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
            self._load()
        except ImportError:
            self.logger.warning("[Face] opencv is unavailable - face recognition disabled.")
        except Exception as e:
            self.logger.warning(f"[Face] Could not initialize face recognition: {e}")

    @property
    def available(self) -> bool:
        return self.enabled and self._recognizer is not None

    def _load(self):
        if os.path.exists(self.model_path) and os.path.exists(self.labels_path):
            try:
                self._recognizer.read(self.model_path)
                with open(self.labels_path, "r", encoding="utf-8") as f:
                    self._labels = {int(k): v for k, v in json.load(f).items()}
                self._trained = True
                self.logger.info(f"[Face] Loaded a trained model with {len(self._labels)} known face(s).")
            except Exception as e:
                self.logger.warning(f"[Face] Could not load existing face model: {e}")

    def detect_faces(self, frame_gray):
        if not self.available:
            return []
        return self._face_cascade.detectMultiScale(frame_gray, scaleFactor=1.2, minNeighbors=5)

    def enroll(self, name: str, gray_face_crops: list) -> str:
        """gray_face_crops: list of grayscale numpy arrays, each a cropped face"""
        if not self.available:
            return "Face recognition is unavailable (opencv-contrib-python missing or disabled)."
        if not gray_face_crops:
            return "No face samples were captured - try again facing the camera."

        next_id = max(self._labels.keys(), default=-1) + 1
        labels_for_training = [next_id] * len(gray_face_crops)

        try:
            if self._trained:
                self._recognizer.update(gray_face_crops, __import__("numpy").array(labels_for_training))
            else:
                self._recognizer.train(gray_face_crops, __import__("numpy").array(labels_for_training))
                self._trained = True

            self._labels[next_id] = name
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            self._recognizer.save(self.model_path)
            with open(self.labels_path, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in self._labels.items()}, f, ensure_ascii=False, indent=2)

            return f"Enrolled {len(gray_face_crops)} sample(s) for '{name}'."
        except Exception as e:
            return f"Could not enroll face: {e}"

    def identify(self, frame_bgr):
        """Returns (name, confidence) for the most prominent known face, or (None, None)"""
        if not self.available or not self._trained:
            return None, None

        gray = self._cv2.cvtColor(frame_bgr, self._cv2.COLOR_BGR2GRAY)
        faces = self.detect_faces(gray)
        if len(faces) == 0:
            return None, None

        # Use the largest detected face
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        face_crop = gray[y:y + h, x:x + w]

        try:
            label_id, confidence = self._recognizer.predict(face_crop)
        except Exception as e:
            self.logger.debug(f"[Face] Prediction error (ignored): {e}")
            return None, None

        # LBPH: LOWER confidence value = better match
        if confidence <= self.confidence_threshold:
            return self._labels.get(label_id), confidence
        return None, None
