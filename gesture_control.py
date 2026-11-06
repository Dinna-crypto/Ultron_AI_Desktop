"""
gesture_control.py
Uses your webcam + MediaPipe's HandLandmarker (Tasks API) to recognize
gestures and map them to real OS actions via pyautogui:

  - Two hands apart/together          -> Zoom in / Zoom out (Ctrl + scroll)
  - One-hand pinch (thumb+index)      -> Zoom in / Zoom out (fallback if only one hand is visible)
  - Open palm moving left/right fast  -> Swipe (Alt+Tab style / arrow keys)
  - Fist held                         -> Pause gesture recognition (safety)

NOTE: MediaPipe removed the old mp.solutions.hands API in recent
releases (0.10.30+). This uses the current replacement: the Tasks API
(mediapipe.tasks.python.vision.HandLandmarker), which needs a small
model file. It's downloaded automatically on first run (~10MB).
"""

import os
import time
import math
import urllib.request

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("GLOG_minloglevel", "3")

import cv2
import numpy as np
import pyautogui
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

pyautogui.FAILSAFE = True

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]


def ensure_model():
    if not os.path.exists(MODEL_PATH):
        print(f"Downloading hand-landmark model to {MODEL_PATH} (one-time, ~10MB)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Model downloaded.")


class GestureController:
    def __init__(self, on_state_change=None, camera_index=0):
        self.on_state_change = on_state_change
        self.camera_index = camera_index

        ensure_model()
        base_options = BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            running_mode=vision.RunningMode.VIDEO,
            min_hand_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)

        self._running = False
        self._pinch_state = None
        self._twohand_state = None
        self._prev_palm_x = None
        self._last_action_time = {"pinch": 0.0, "swipe": 0.0}
        self._action_cooldown = 0.6
        self._pinch_closed_thresh = 0.35
        self._pinch_open_thresh = 0.55
        self._twohand_closed_thresh = 0.25
        self._twohand_open_thresh = 0.50

    def _set_state(self, state):
        if self.on_state_change:
            self.on_state_change(state)

    def _distance(self, p1, p2):
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    def _cooldown_ok(self, key):
        now = time.time()
        if now - self._last_action_time[key] > self._action_cooldown:
            self._last_action_time[key] = now
            return True
        return False

    def _is_fist(self, lm):
        wrist = lm[0]
        tips = [8, 12, 16, 20]
        mcps = [5, 9, 13, 17]
        curled = 0
        for t, m in zip(tips, mcps):
            d_tip = self._distance(lm[t], wrist)
            d_mcp = self._distance(lm[m], wrist)
            if d_tip < d_mcp * 1.15:
                curled += 1
        return curled >= 4

    def _draw_landmarks(self, frame, lm):
        h, w, _ = frame.shape
        points = [(int(p.x * w), int(p.y * h)) for p in lm]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, points[a], points[b], (0, 255, 120), 2)
        for x, y in points:
            cv2.circle(frame, (x, y), 4, (0, 200, 255), -1)

    def run(self):
        cap = cv2.VideoCapture(self.camera_index)
        self._running = True
        self._set_state("gesture_active")
        start_time = time.time()

        while self._running and cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int((time.time() - start_time) * 1000)

            result = self.landmarker.detect_for_video(mp_image, timestamp_ms)

            if result.hand_landmarks:
                num_hands = len(result.hand_landmarks)

                if num_hands == 2:
                    self._draw_landmarks(frame, result.hand_landmarks[0])
                    self._draw_landmarks(frame, result.hand_landmarks[1])
                    self._pinch_state = None
                    self._prev_palm_x = None

                    wrist1 = result.hand_landmarks[0][0]
                    wrist2 = result.hand_landmarks[1][0]
                    spread = self._distance(wrist1, wrist2)

                    cv2.putText(frame, f"two-hand spread: {spread:.2f}", (20, 460),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

                    if spread < self._twohand_closed_thresh:
                        new_state = "closed"
                    elif spread > self._twohand_open_thresh:
                        new_state = "open"
                    else:
                        new_state = self._twohand_state

                    if (new_state != self._twohand_state and self._twohand_state is not None
                            and self._cooldown_ok("pinch")):
                        if new_state == "open":
                            pyautogui.hotkey("ctrl", "+")
                            cv2.putText(frame, "ZOOM IN", (20, 40),
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        elif new_state == "closed":
                            pyautogui.hotkey("ctrl", "-")
                            cv2.putText(frame, "ZOOM OUT", (20, 40),
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                    self._twohand_state = new_state

                elif num_hands == 1:
                    self._twohand_state = None
                    lm = result.hand_landmarks[0]
                    self._draw_landmarks(frame, lm)

                    if self._is_fist(lm):
                        cv2.putText(frame, "PAUSED (fist)", (20, 40),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        self._pinch_state = None
                        self._prev_palm_x = None
                    else:
                        pinch_dist = self._distance(lm[4], lm[8])
                        hand_scale = self._distance(lm[0], lm[5]) or 1e-6
                        pinch_ratio = pinch_dist / hand_scale

                        cv2.putText(frame, f"pinch: {pinch_ratio:.2f}", (20, 460),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

                        if pinch_ratio < self._pinch_closed_thresh:
                            new_state = "closed"
                        elif pinch_ratio > self._pinch_open_thresh:
                            new_state = "open"
                        else:
                            new_state = self._pinch_state

                        if (new_state != self._pinch_state and self._pinch_state is not None
                                and self._cooldown_ok("pinch")):
                            if new_state == "open":
                                pyautogui.hotkey("ctrl", "+")
                                cv2.putText(frame, "ZOOM IN", (20, 40),
                                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                            elif new_state == "closed":
                                pyautogui.hotkey("ctrl", "-")
                                cv2.putText(frame, "ZOOM OUT", (20, 40),
                                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                        self._pinch_state = new_state

                        palm_x = lm[0].x
                        if self._prev_palm_x is not None and self._cooldown_ok("swipe"):
                            move = palm_x - self._prev_palm_x
                            if move > 0.08:
                                pyautogui.hotkey("alt", "tab")
                                cv2.putText(frame, "SWIPE RIGHT -> Alt+Tab", (20, 80),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 200, 0), 2)
                            elif move < -0.08:
                                pyautogui.hotkey("win", "tab")
                                cv2.putText(frame, "SWIPE LEFT -> Task View", (20, 80),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 200, 0), 2)
                        self._prev_palm_x = palm_x

            cv2.imshow("ULTRON - Gesture Vision (press Q to close)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()
        self._set_state("idle")

    def stop(self):
        self._running = False


if __name__ == "__main__":
    GestureController().run()
