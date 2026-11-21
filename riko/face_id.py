"""Face Identification for Riko:
Enrolls senpai's face and recognizes whether the person in front of the camera
is Utkarsh (senpai) or an unfamiliar stranger!
"""
import base64
from typing import Optional, Tuple

import cv2
import numpy as np

from riko.config import ROOT

FACE_CASCADE_PATH = (getattr(cv2, 'data', None) and getattr(cv2.data, 'haarcascades', '')) + "haarcascade_frontalface_default.xml"
ENROLLED_FACE_PATH = ROOT / "character_files" / "senpai_face.jpg"


def has_enrolled_face() -> bool:
    return ENROLLED_FACE_PATH.exists()


def get_enrolled_face_b64() -> Optional[str]:
    if not ENROLLED_FACE_PATH.exists():
        return None
    try:
        return base64.b64encode(ENROLLED_FACE_PATH.read_bytes()).decode("utf-8")
    except Exception:
        return None


def enroll_face() -> Tuple[bool, str]:
    """Captures a webcam frame and saves senpai's face."""
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            return False, "Could not access the webcam camera to see your face, senpai!"

        # Warm up camera
        frame = None
        for _ in range(8):
            ret, frame = cap.read()
        cap.release()

        if frame is None:
            return False, "Failed to capture an image from the webcam."

        ENROLLED_FACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(ENROLLED_FACE_PATH), frame)
        print(f"[face_id] Enrolled senpai's face to: {ENROLLED_FACE_PATH}")
        return True, "I have memorized your face, Utkarsh senpai! From now on, I will always recognize you whenever you appear in front of the camera~"
    except Exception as e:
        return False, f"Could not enroll face: {e}"


def identify_person_in_frame(frame: np.ndarray) -> str:
    """Detects faces in `frame` and determines if senpai is present (OpenCV 5+ compatible)."""
    try:
        if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
            return "motion_detected"

        face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
        if face_cascade.empty():
            return "motion_detected"

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

        if len(faces) == 0:
            return "no_face_detected"

        if not has_enrolled_face():
            return "face_detected_unenrolled"

        # Load enrolled face
        enrolled_img = cv2.imread(str(ENROLLED_FACE_PATH), cv2.IMREAD_GRAYSCALE)
        if enrolled_img is None:
            return "face_detected_unenrolled"

        # Compare detected face with enrolled face using normalized cross-correlation
        best_score = 0.0
        for (x, y, w, h) in faces:
            crop = gray[y:y+h, x:x+w]
            resized_crop = cv2.resize(crop, (enrolled_img.shape[1], enrolled_img.shape[0]))
            res = cv2.matchTemplate(resized_crop, enrolled_img, cv2.TM_CCOEFF_NORMED)
            score = float(res[0][0])
            best_score = max(best_score, score)

        if best_score > 0.40:
            return f"senpai_recognized (confidence: {best_score:.2f})"
        else:
            return f"stranger_detected (confidence: {best_score:.2f})"
    except Exception:
        return "motion_detected"


_face_watcher_running = False

def start_proactive_face_greeting(cfg: dict):
    """Starts a background camera monitor that proactively speaks to senpai
    whenever senpai sits down or returns to their desk!
    """
    global _face_watcher_running
    if _face_watcher_running:
        return
    _face_watcher_running = True

    import threading
    import time
    from riko import llm, tts, viewer

    def watcher_loop():
        last_greet_time = 0.0
        last_stranger_time = 0.0
        senpai_was_present = False

        while True:
            time.sleep(3)

            # Don't interrupt while avatar is talking
            if viewer.is_playing():
                continue

            try:
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    continue

                frame = None
                for _ in range(2):
                    ret, frame = cap.read()
                cap.release()

                if frame is None:
                    continue

                status = identify_person_in_frame(frame)
                now = time.time()

                if "face_detected_unenrolled" in status:
                    # Greet if senpai just sat down or hasn't been greeted for 4+ minutes
                    if not senpai_was_present or (now - last_greet_time > 240):
                        senpai_was_present = True
                        last_greet_time = now
                        print(f"\n[face_id] Person detected in camera at desk! (Unenrolled face) Initiating visual greeting...")
                        prompt = (
                            "[System Event: Senpai just sat down in front of the camera at his computer desk. "
                            "You see senpai through the webcam! Greet senpai in 1 sassy, playful tsundere sentence and tease him to say 'remember my face' so you can officially register his face!]"
                        )
                        raw_answer = llm.reply(prompt, cfg)
                        import re
                        emotion = "happy"
                        match = re.match(r"^\[([a-zA-Z]+)\]\s*", raw_answer)
                        if match:
                            tag = match.group(1).lower()
                            if tag in ["happy", "angry", "sad", "surprised", "relaxed", "neutral"]:
                                emotion = tag
                            clean_answer = raw_answer[match.end():]
                        else:
                            clean_answer = raw_answer
                        print(f"[{emotion.upper()}] Riko (camera): {clean_answer}")
                        wav = tts.speak(clean_answer, cfg)
                        viewer.play(wav, emotion=emotion)
                    else:
                        senpai_was_present = True

                elif "senpai_recognized" in status:
                    # Greet if senpai just returned (was not present) or hasn't been greeted for 5+ minutes
                    if not senpai_was_present or (now - last_greet_time > 300):
                        senpai_was_present = True
                        last_greet_time = now
                        print(f"\n[face_id] Utkarsh Senpai detected at desk ({status})! Initiating proactive greeting...")
                        prompt = (
                            "[System Event: Utkarsh Senpai just sat down in front of the camera at his computer desk. "
                            "Proactively greet senpai first in 1 short, witty, sassy tsundere sentence!]"
                        )
                        raw_answer = llm.reply(prompt, cfg)
                        import re
                        emotion = "happy"
                        match = re.match(r"^\[([a-zA-Z]+)\]\s*", raw_answer)
                        if match:
                            tag = match.group(1).lower()
                            if tag in ["happy", "angry", "sad", "surprised", "relaxed", "neutral"]:
                                emotion = tag
                            clean_answer = raw_answer[match.end():]
                        else:
                            clean_answer = raw_answer
                        print(f"[{emotion.upper()}] Riko (camera): {clean_answer}")
                        wav = tts.speak(clean_answer, cfg)
                        viewer.play(wav, emotion=emotion)
                    else:
                        senpai_was_present = True

                elif "stranger_detected" in status:
                    senpai_was_present = False
                    if now - last_stranger_time > 180:
                        last_stranger_time = now
                        print(f"\n[face_id] Unfamiliar face detected at desk ({status})! Alerting...")
                        prompt = (
                            "[System Event: An unfamiliar stranger just appeared in front of the webcam camera at Senpai's desk! "
                            "Challenge the stranger suspiciously in 1 short sentence: 'Who are you?! Where is senpai?!']"
                        )
                        raw_answer = llm.reply(prompt, cfg)
                        import re
                        emotion = "surprised"
                        match = re.match(r"^\[([a-zA-Z]+)\]\s*", raw_answer)
                        if match:
                            tag = match.group(1).lower()
                            if tag in ["happy", "angry", "sad", "surprised", "relaxed", "neutral"]:
                                emotion = tag
                            clean_answer = raw_answer[match.end():]
                        else:
                            clean_answer = raw_answer
                        print(f"[{emotion.upper()}] Riko (alert): {clean_answer}")
                        wav = tts.speak(clean_answer, cfg)
                        viewer.play(wav, emotion=emotion)

                elif "no_face_detected" in status:
                    senpai_was_present = False

            except Exception as e:
                # Silently catch transient camera access collisions
                pass

    threading.Thread(target=watcher_loop, daemon=True).start()
    print("[face_id] Proactive face greeting active (greets senpai when entering camera view)")


