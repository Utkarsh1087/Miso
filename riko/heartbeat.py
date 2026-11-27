"""Proactive Heartbeat for Project Riko.
Riko proactively initiates conversation if senpai has been working or idle for a while.
"""
import datetime
import threading
import time

from riko import llm, tags, tts, viewer

_last_interaction = time.time()
_is_running = False
_is_busy = False
_lock = threading.RLock()


def mark_interaction():
    """Resets the idle timer whenever senpai speaks or interacts."""
    global _last_interaction
    with _lock:
        _last_interaction = time.time()


def set_busy(is_busy: bool):
    """Flags that Riko or Senpai is actively engaged in a conversation turn."""
    global _is_busy
    with _lock:
        _is_busy = is_busy
        if is_busy:
            _last_interaction = time.time()


def is_busy() -> bool:
    with _lock:
        return _is_busy


def start(cfg):
    """Starts the background proactive check-in thread."""
    global _is_running
    if _is_running:
        return
    _is_running = True

    # Interval in seconds (default: 15 minutes, or configured in yaml)
    interval = cfg.get("proactive_interval", 900)

    def loop():
        while True:
            time.sleep(15)
            now = time.time()
            with _lock:
                idle_time = now - _last_interaction

            if idle_time >= interval:
                # Avoid interrupting in the middle of the night (2 AM to 7 AM)
                hour = datetime.datetime.now().hour
                if 2 <= hour < 7:
                    mark_interaction()
                    continue

                # Don't speak while Riko or senpai is in an active turn, or audio is playing
                if is_busy() or viewer.is_playing():
                    mark_interaction()
                    continue

                print("\n[heartbeat] Senpai has been working quietly. Miso initiating visual check-in...")
                try:
                    mark_interaction()
                    import random
                    from riko import tools

                    # Rayen's Riko observation: alternating between screen observation and playful check-ins
                    use_screen_vision = cfg.get("proactive_vision", True) and (random.random() < 0.6)
                    screen_b64 = tools.capture_screen_base64() if use_screen_vision else None

                    if screen_b64:
                        prompt = "[Proactive Screen Observation: Look at senpai's active computer screen right now and comment on what they are doing (e.g. coding, watching videos, browsing, gaming, or procrastinating) in 1 short, snarky, or encouraging tsundere sentence!]"
                        raw_answer = llm.reply(prompt, cfg, image_b64=screen_b64)
                    else:
                        prompt = "[Proactive Check-in: Senpai has been working quietly or has been idle for a while without speaking. Proactively initiate a casual, caring, or snarky check-in with senpai in 1 short sentence!]"
                        raw_answer = llm.reply(prompt, cfg)

                    parsed = tags.parse_reply_tags(raw_answer, default_emotion="happy")
                    print(f"[{parsed.emotion.upper()}:{parsed.intensity}] Miso (proactive observation): {parsed.clean_text}")
                    wav = tts.speak(parsed.clean_text, cfg)
                    viewer.play(wav, emotion=parsed.emotion, intensity=parsed.intensity, gesture=parsed.gesture, text=parsed.clean_text)
                except Exception as e:
                    print(f"[heartbeat note] {e}")

    threading.Thread(target=loop, daemon=True).start()

