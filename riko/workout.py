"""AI Workout Coach & Rep Counter for Riko:
Tracks exercise reps (pushups, squats, curls) through webcam motion in an isolated thread,
counting out loud and motivating/roasting senpai!
"""
import threading
import time
from typing import Optional

import cv2
import numpy as np

from riko import tts, viewer

_workout_thread: Optional[threading.Thread] = None
_workout_active = False
_rep_count = 0


def is_workout_active() -> bool:
    return _workout_active


def start_workout(cfg: dict, exercise: str = "pushups"):
    global _workout_thread, _workout_active, _rep_count
    if _workout_active:
        return f"Workout mode is already running! Current reps: {_rep_count}"

    _workout_active = True
    _rep_count = 0
    _workout_thread = threading.Thread(target=_workout_loop, args=(cfg, exercise), daemon=True)
    _workout_thread.start()
    return f"Workout mode activated for {exercise}! Get in position, senpai! I'm watching every rep!"


def stop_workout(cfg: dict):
    global _workout_active, _rep_count
    if not _workout_active:
        return "Workout mode was not active."
    final_reps = _rep_count
    _workout_active = False
    return f"Workout complete! You finished {final_reps} reps, senpai! Not bad, but you can do better tomorrow!"


def _workout_loop(cfg: dict, exercise: str):
    global _workout_active, _rep_count
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[workout error] Could not access webcam.")
        _workout_active = False
        return

    prev_y = None
    direction = 0  # 1 = going down, -1 = going up
    lowest_y = 0

    print(f"[workout] Coach Riko is tracking {exercise}...")

    try:
        while _workout_active:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            small = cv2.resize(frame, (240, 180))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            # Center of motion tracking
            # Find center of gravity of thresholded movement or face
            mean_y = int(np.mean(np.where(gray < 120)[0])) if np.any(gray < 120) else 90

            if prev_y is None:
                prev_y = mean_y
                time.sleep(0.1)
                continue

            dy = mean_y - prev_y
            prev_y = mean_y

            # Rep inflection tracking
            if dy > 6:  # Moving down
                direction = 1
                lowest_y = max(lowest_y, mean_y)
            elif dy < -6 and direction == 1:  # Moving back up
                if lowest_y - mean_y > 15:  # Significant vertical stroke
                    _rep_count += 1
                    direction = 0
                    lowest_y = 0
                    print(f"[workout] Rep counted! Count: {_rep_count}")
                    threading.Thread(target=_call_out_rep, args=(_rep_count, cfg), daemon=True).start()

            time.sleep(0.08)
    finally:
        cap.release()


def _call_out_rep(count: int, cfg: dict):
    try:
        cheers = {
            1: "One! Good start, senpai!",
            3: "Three! Keep that back straight!",
            5: "Five! Don't slow down now!",
            8: "Eight! Feeling the burn yet, senpai?",
            10: "Ten reps! Look at you trying to impress me!",
            15: "Fifteen! Are your arms noodles yet?",
            20: "Twenty! Okay, you might actually have some stamina!"
        }
        text = cheers.get(count, f"{count}!")
        wav = tts.speak(text, cfg, filename="workout_rep.wav")
        viewer.play(wav, emotion="happy" if count % 5 == 0 else "neutral")
    except Exception as e:
        print(f"[workout audio note] {e}")

