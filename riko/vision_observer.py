"""Autonomous Continuous Vision Observer for Project Riko.
Runs the webcam in a parallel, non-blocking background thread.
Monitors the user (Senpai) for significant movement, gestures, or room events.
Logs observations to transient short-term visual memory, and uses the Vision LLM
to decide whether to react with deadpan witty commentary or stay silent without
ever interrupting an ongoing voice conversation.
"""
import base64
import re
import threading
import time
from typing import Optional

import cv2
import numpy as np

from riko import memory, tts, viewer

_observer_thread: Optional[threading.Thread] = None
_is_active = False
_latest_frame: Optional[np.ndarray] = None
_frame_lock = threading.RLock()
_last_spoken_time = 0.0
_last_motion_event_time = 0.0


def is_active() -> bool:
    """Returns True if the vision observer thread is running."""
    return _is_active


def get_latest_frame() -> Optional[np.ndarray]:
    """Returns a copy of the latest camera frame captured by the background stream.
    Used by tools and Face ID to avoid camera device lock contention.
    """
    with _frame_lock:
        if _latest_frame is not None:
            return _latest_frame.copy()
    return None


def get_latest_frame_base64() -> Optional[str]:
    """Returns the latest camera frame as a base64 encoded JPEG string."""
    frame = get_latest_frame()
    if frame is None:
        return None
    try:
        small = cv2.resize(frame, (640, 480))
        _, buffer = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode("utf-8")
    except Exception:
        return None


def start(cfg: dict):
    """Starts the parallel continuous vision observer."""
    global _observer_thread, _is_active
    observer_cfg = cfg.get("vision_observer", {})
    if not observer_cfg.get("enabled", True):
        print("[vision] Vision observer is disabled in character_config.yaml.")
        return

    if _is_active:
        return

    _is_active = True
    _observer_thread = threading.Thread(target=_observer_loop, args=(cfg,), daemon=True)
    _observer_thread.start()
    print("[vision] Parallel Continuous Vision Observer active! Watching webcam silently...")


def stop():
    """Stops the parallel continuous vision observer."""
    global _is_active
    _is_active = False
    print("[vision] Vision observer stopped.")


def _observer_loop(cfg: dict):
    global _latest_frame, _last_spoken_time, _last_motion_event_time, _is_active

    observer_cfg = cfg.get("vision_observer", {})
    motion_threshold = float(observer_cfg.get("motion_threshold", 0.08))
    speech_cooldown = float(observer_cfg.get("cooldown", 60.0))
    auto_react = bool(observer_cfg.get("auto_react", True))

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("[vision error] Could not open webcam for Vision Observer.")
        _is_active = False
        return

    # Warm up camera sensor
    for _ in range(5):
        cap.read()

    prev_gray = None
    consecutive_motion = 0

    try:
        from riko import heartbeat

        while _is_active:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.2)
                continue

            with _frame_lock:
                _latest_frame = frame

            # Lightweight downsampled grayscale frame differencing (~320x240)
            small = cv2.resize(frame, (320, 240))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_gray is None:
                prev_gray = gray
                time.sleep(0.1)
                continue

            diff = cv2.absdiff(prev_gray, gray)
            thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
            motion_ratio = np.count_nonzero(thresh) / float(thresh.size)
            prev_gray = gray

            now = time.time()
            # If significant visual movement detected
            if motion_ratio > motion_threshold:
                consecutive_motion += 1
            else:
                consecutive_motion = max(0, consecutive_motion - 1)

            # Trigger event evaluation after 2 consecutive active motion frames with debounce
            if consecutive_motion >= 2 and (now - _last_motion_event_time > 15.0):
                consecutive_motion = 0
                _last_motion_event_time = now

                # Capture clean snapshot for Vision LLM
                _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                image_b64 = base64.b64encode(buffer).decode("utf-8")

                # Process event asynchronously in a worker thread so video stream never stutters
                threading.Thread(
                    target=_evaluate_visual_event,
                    args=(image_b64, cfg, speech_cooldown, auto_react),
                    daemon=True
                ).start()

            # Pace loop at ~8 FPS (125ms per frame) for near-zero CPU footprint
            time.sleep(0.125)

    finally:
        cap.release()
        _is_active = False


def _evaluate_visual_event(image_b64: str, cfg: dict, speech_cooldown: float, auto_react: bool):
    """Evaluates the visual snapshot using Groq Vision, stores observation in short-term memory,
    and optionally reacts out loud if not interrupting an ongoing conversation.
    """
    global _last_spoken_time
    import os
    from openai import OpenAI
    from riko import heartbeat

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        return

    prompt = (
        "You are the visual observer for an AI desktop companion named Miso watching senpai (Utkarsh) through the webcam.\n"
        "Look at this image and output EXACTLY two lines in this format:\n"
        "DESCRIPTION: <1 short factual phrase of what senpai is doing, e.g. 'Utkarsh took a drink of water', 'Utkarsh stood up', 'Utkarsh returned to desk', 'Utkarsh is holding an object', 'Utkarsh is resting head'>\n"
        "ACTION: <either '[SILENT]' if it is normal/mundane/unimportant, OR '[SPEAK: <emotion>] <1 short deadpan snarky comment>' if it is noteworthy, funny, or teasing-worthy without any tildes (~)>"
    )

    try:
        client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
        res = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]
            }],
            max_tokens=150,
            temperature=0.4
        )
        content = res.choices[0].message.content.strip()

        # Parse DESCRIPTION and ACTION
        desc_match = re.search(r"DESCRIPTION:\s*(.+)", content, re.IGNORECASE)
        action_match = re.search(r"ACTION:\s*(.+)", content, re.IGNORECASE)

        description = desc_match.group(1).strip() if desc_match else ""
        action = action_match.group(1).strip() if action_match else ""

        if description:
            # 1. Log observation into transient short-term visual memory buffer
            memory.add_visual_event(description)

        # 2. Check if LLM decided to speak
        if not auto_react or "[SILENT]" in action.upper() or not action:
            return

        # STRICT CONVERSATION PRIORITY: Do NOT interrupt if senpai or Riko is currently in a turn
        if viewer.is_playing() or heartbeat.is_busy():
            print("[vision] Event logged to memory, but spoken reaction skipped (conversation active).")
            return

        # Check cooldown to prevent chatty interruptions
        now = time.time()
        if now - _last_spoken_time < speech_cooldown:
            return

        # Parse emotion and spoken remark
        speak_match = re.search(r"\[SPEAK:\s*([a-zA-Z]+)\]\s*(.+)", action, re.IGNORECASE)
        if speak_match:
            emotion = speak_match.group(1).lower()
            allowed = ["happy", "angry", "sad", "surprised", "relaxed", "neutral"]
            if emotion not in allowed:
                emotion = "relaxed"
            comment = speak_match.group(2).strip()

            # Sanitize any tildes or fillers
            comment = comment.replace("~", "").strip()
            if not comment:
                return

            # Double check idle state right before synthesizing speech
            if viewer.is_playing() or heartbeat.is_busy():
                return

            _last_spoken_time = now
            print(f"\nRiko (visual observation): [{emotion.upper()}] {comment}\n", flush=True)
            wav = tts.speak(comment, cfg)
            viewer.play(wav, emotion=emotion)
            heartbeat.mark_interaction()

    except Exception as e:
        print(f"[vision observer note] {e}")

