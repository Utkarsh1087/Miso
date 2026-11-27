"""Anime & YouTube Co-Watching Companion for Riko:
Watches anime, movies, or YouTube videos on screen with senpai, giving live reactions,
cheering for characters, or roasting plot armor!
"""
import base64
import os
import threading
import time
from typing import Optional

from PIL import Image, ImageChops

from riko import tags, tts, viewer

_cowatch_thread: Optional[threading.Thread] = None
_cowatch_active = False
_last_reaction_time = 0.0


def is_active() -> bool:
    return _cowatch_active


def start_cowatch(cfg: dict) -> str:
    global _cowatch_thread, _cowatch_active
    if _cowatch_active:
        return "Co-watching mode is already on! What are we watching, senpai?"
    _cowatch_active = True
    _cowatch_thread = threading.Thread(target=_cowatch_loop, args=(cfg,), daemon=True)
    _cowatch_thread.start()
    print("[cowatch] Anime & Video Co-Watching Companion ACTIVATED!")
    return "Co-watching mode activated! Put on the show, senpai~ I have my popcorn ready!"


def stop_cowatch() -> str:
    global _cowatch_active
    if not _cowatch_active:
        return "Co-watching mode was not active."
    _cowatch_active = False
    print("[cowatch] Anime & Video Co-Watching Companion DEACTIVATED.")
    return "Stopped co-watching mode. That was fun, senpai!"


def _cowatch_loop(cfg: dict):
    global _cowatch_active, _last_reaction_time
    prev_img = None

    while _cowatch_active:
        try:
            time.sleep(12.0)
            if not _cowatch_active:
                break

            # Capture current screen
            try:
                import mss
                with mss.mss() as sct:
                    monitor = sct.monitors[1]
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception:
                from PIL import ImageGrab
                img = ImageGrab.grab()

            # Downscale for comparison
            thumb = img.resize((160, 90), Image.Resampling.BILINEAR)
            if prev_img is not None:
                diff = ImageChops.difference(prev_img, thumb)
                # Check if video scene changed significantly
                stat = sum(diff.convert("L").getdata()) / (160 * 90)
                if stat > 12.0:  # Significant screen movement / video playback
                    now = time.time()
                    if now - _last_reaction_time > 20.0 and not viewer.is_playing():
                        _last_reaction_time = now
                        threading.Thread(target=_react_to_screen, args=(img, cfg), daemon=True).start()

            prev_img = thumb
        except Exception as e:
            time.sleep(5)


def _react_to_screen(full_img: Image.Image, cfg: dict):
    try:
        from openai import OpenAI
        import io

        # Compress to 640px JPEG for vision API
        ratio = 640.0 / float(full_img.width)
        new_h = int(float(full_img.height) * ratio)
        resized = full_img.resize((640, new_h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=75)
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = (
            "You are Riko, an anime girl sitting with senpai and co-watching whatever is on his screen right now (anime, movie, or YouTube video). "
            "React spontaneously to what is happening on screen in 1 punchy, funny, teasing, or excited sentence! "
            "Start with [emotion:intensity] like [happy:2], [surprised:2], or [angry:2] and optional [gesture]!"
        )

        groq_key = os.getenv("GROQ_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        reply = ""

        if groq_key:
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            res = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }],
                max_tokens=60,
                temperature=0.8
            )
            reply = res.choices[0].message.content.strip()
        elif openai_key:
            client = OpenAI(api_key=openai_key)
            res = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }],
                max_tokens=60
            )
            reply = res.choices[0].message.content.strip()

        if reply:
            parsed = tags.parse_reply_tags(reply, default_emotion="surprised")
            print(f"[cowatch] Riko: {parsed.clean_text} [{parsed.emotion}:{parsed.intensity}]")
            wav = tts.speak(parsed.clean_text, cfg, filename="cowatch_reaction.wav")
            viewer.play(wav, emotion=parsed.emotion, intensity=parsed.intensity, gesture=parsed.gesture, text=parsed.clean_text)
    except Exception as e:
        print(f"[cowatch error] {e}")

