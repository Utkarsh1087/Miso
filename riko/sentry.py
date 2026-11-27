"""Autonomous Room Security Sentry Mode for Riko:
Watches the webcam in a zero-latency background thread. When someone enters the room
or moves, she identifies what is happening and calls out an alert or sarcastic roast!
"""
import base64
import threading
import time
from typing import Optional

import cv2
import numpy as np

from riko import tags, tts, viewer

_sentry_thread: Optional[threading.Thread] = None
_sentry_active = False
_last_alert_time = 0.0


def is_sentry_active() -> bool:
    return _sentry_active


def start_sentry(cfg: dict):
    global _sentry_thread, _sentry_active
    if _sentry_active:
        return "Sentry mode is already active and guarding your room, senpai!"

    _sentry_active = True
    _sentry_thread = threading.Thread(target=_sentry_loop, args=(cfg,), daemon=True)
    _sentry_thread.start()
    print("[sentry] Security Sentry mode ACTIVATED! Guarding your room...")
    return "Security Sentry mode activated! I am watching your room, senpai. Nobody sneaks past me!"


def stop_sentry():
    global _sentry_active
    if not _sentry_active:
        return "Sentry mode was not active."
    _sentry_active = False
    print("[sentry] Security Sentry mode DEACTIVATED.")
    return "Sentry mode deactivated. Standing down, senpai!"


def _sentry_loop(cfg: dict):
    global _last_alert_time, _sentry_active
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[sentry error] Could not access webcam for sentry mode.")
        _sentry_active = False
        return

    # Warmup camera
    for _ in range(5):
        cap.read()

    prev_gray = None
    motion_counter = 0

    try:
        from riko import face_id, heartbeat, viewer

        while _sentry_active:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.5)
                continue

            # Do not interrupt if Riko is speaking or user is currently in a voice turn
            if viewer.is_playing() or heartbeat.is_busy():
                time.sleep(0.5)
                continue

            # Downsample for ultra-fast, zero-overhead background processing
            small = cv2.resize(frame, (320, 240))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_gray is None:
                prev_gray = gray
                time.sleep(0.2)
                continue

            diff = cv2.absdiff(prev_gray, gray)
            thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
            motion_ratio = np.count_nonzero(thresh) / thresh.size
            prev_gray = gray

            now = time.time()
            # If significant motion detected (> 8.0% of frame moved, e.g. someone standing up or entering room)
            if motion_ratio > 0.08:
                motion_counter += 1
            else:
                motion_counter = max(0, motion_counter - 1)

            # Requires 2 consecutive motion frames and 60s cooldown to prevent alert loops
            if motion_counter >= 2 and (now - _last_alert_time > 60.0):
                # Voice Conversation Priority: NEVER interrupt if senpai is in a turn or audio is playing
                if viewer.is_playing() or heartbeat.is_busy():
                    motion_counter = 0
                    time.sleep(0.5)
                    continue

                motion_counter = 0
                _last_alert_time = now
                print(f"[sentry] Motion detected at laptop (ratio: {motion_ratio:.2%})! Checking identity...")

                # Offline local face verification (0ms, 0 API calls, zero quota burned)
                person_status = "motion_detected"
                try:
                    from riko import face_id
                    person_status = face_id.identify_person_in_frame(frame)
                except Exception as e:
                    person_status = "motion_detected"
                print(f"[sentry] Identity check: {person_status}")

                # Encode frame for vision LLM
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                b64 = base64.b64encode(buffer).decode('utf-8')

                threading.Thread(target=_analyze_and_alert, args=(b64, cfg, person_status), daemon=True).start()

            time.sleep(0.35)
    finally:
        cap.release()


def _analyze_and_alert(image_b64: str, cfg: dict, person_status: str = ""):
    try:
        import os
        from openai import OpenAI

        groq_key = os.getenv("GROQ_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        if "senpai_recognized" in person_status:
            prompt = (
                "You are Miso, an arrogant, sharp-witted anime desktop companion. "
                "You just noticed your creator (Utkarsh) return to his desk! "
                "Welcome him back in 1 short, deadpan, witty sentence with zero tildes or forced giggles. Start with [relaxed:2] or [happy:2]!"
            )
        elif "stranger_detected" in person_status:
            prompt = (
                "You are Miso, an AI guarding Utkarsh's computer. "
                "An UNFAMILIAR STRANGER just approached the desk! "
                "Sound a sharp, witty warning in 1 short punchy sentence telling them to step away from senpai's PC. Start with [angry:2] or [surprised:2]!"
            )
        else:
            prompt = (
                "You are Miso, an arrogant, sharp-witted anime desktop companion. "
                "You just caught motion on the camera in the room. Give a witty, deadpan 1-sentence observation on whatever is happening without tildes or robotic fillers. Start with [surprised:2], [happy:2], or [neutral:1]!"
            )

        reply_text = ""
        if groq_key:
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
                max_tokens=80,
                temperature=0.7
            )
            reply_text = res.choices[0].message.content.strip()
        elif openai_key:
            client = OpenAI(api_key=openai_key)
            res = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                    ]
                }],
                max_tokens=80
            )
            reply_text = res.choices[0].message.content.strip()

        if reply_text:
            parsed = tags.parse_reply_tags(reply_text, default_emotion="surprised")
            print(f"[sentry alert] Miso: {parsed.clean_text} [{parsed.emotion}:{parsed.intensity}]")
            wav = tts.speak(parsed.clean_text, cfg, filename="sentry_alert.wav")
            viewer.play(wav, emotion=parsed.emotion, intensity=parsed.intensity, gesture=parsed.gesture, text=parsed.clean_text)
    except Exception as e:
        print(f"[sentry alert error] {e}")

