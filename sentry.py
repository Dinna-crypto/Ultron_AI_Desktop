"""
sentry.py
Security sentry mode: while active, quietly watches the webcam using a
lightweight face detector. When a face appears, it snaps a photo, saves
it locally, and hands it off to a callback (wired to push it to your
phone as an image notification via ntfy in main.py).

Uses OpenCV's built-in Haar cascade face detector, no extra model
download needed, it ships inside the opencv-python package already.
Checks only once every couple of seconds (not full video framerate)
since this is meant to be a quiet background watcher, not gesture
control, and shouldn't burn CPU while it's just standing by.
"""

import os
import time
import datetime
import cv2

CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
SNAPSHOT_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Ultron Sentry")


class SentryController:
    def __init__(self, on_alert=None, on_state_change=None, camera_index=0,
                 check_interval=2.0, alert_cooldown=300):
        self.on_alert = on_alert
        self.on_state_change = on_state_change
        self.camera_index = camera_index
        self.check_interval = check_interval
        self.alert_cooldown = alert_cooldown
        self._running = False
        self._face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    def _set_state(self, state):
        if self.on_state_change:
            self.on_state_change(state)

    def run(self):
        self._running = True
        self._set_state("sentry")
        cap = cv2.VideoCapture(self.camera_index)
        last_alert = 0

        try:
            while self._running:
                ok, frame = cap.read()
                if ok:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = self._face_cascade.detectMultiScale(
                        gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60)
                    )
                    if len(faces) > 0 and (time.time() - last_alert) > self.alert_cooldown:
                        last_alert = time.time()
                        filename = f"sentry_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                        filepath = os.path.join(SNAPSHOT_DIR, filename)
                        cv2.imwrite(filepath, frame)
                        print(f"[sentry] face detected, snapshot saved to {filepath}")
                        if self.on_alert:
                            self.on_alert(filepath)
                time.sleep(self.check_interval)
        finally:
            cap.release()
            self._set_state("idle")

    def stop(self):
        self._running = False
