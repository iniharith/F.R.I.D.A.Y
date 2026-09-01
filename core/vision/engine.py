from __future__ import annotations

import cv2
import numpy as np
from mss import mss
from pathlib import Path
from core import config

class VisionEngine:
    def capture_screen(self) -> np.ndarray:
        """Captures the primary monitor."""
        with mss() as capture:
            monitor = capture.monitors[1]
            screenshot = capture.grab(monitor)
        # Convert to BGR for OpenCV compatibility
        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def capture_camera(self) -> np.ndarray | None:
        """Captures a single frame from the default webcam."""
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return None
        return frame

    def save_frame(self, frame: np.ndarray, filename: str) -> Path:
        """Saves a frame to a temporary file."""
        config.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        path = config.CAPTURES_DIR / filename
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError("OpenCV could not save the captured image")
        return path
