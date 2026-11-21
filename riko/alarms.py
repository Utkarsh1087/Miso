"""Persistent Wake-Up Alarm Clock & Timers for Riko:
Allows senpai to set timers and morning wake-up alarms. When the alarm triggers,
Riko speaks persistently and roasts senpai until they prove they are awake!
"""
import datetime
import json
import re
import threading
import time
from typing import List, Optional

from riko import tts, viewer
from riko.config import ROOT

ALARMS_FILE = ROOT / "alarms.json"

_alarms_lock = threading.Lock()
_active_alarm_ringing = False
_alarm_thread: Optional[threading.Thread] = None


def is_ringing() -> bool:
    return _active_alarm_ringing


def stop_ringing() -> str:
    global _active_alarm_ringing
    if _active_alarm_ringing:
        _active_alarm_ringing = False
        return "Alarm silenced! Finally you're awake, senpai. Don't fall back asleep!"
    return "No alarm was ringing."


def load_alarms() -> List[dict]:
    if not ALARMS_FILE.exists():
        return []
    try:
        return json.loads(ALARMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_alarms(alarms: List[dict]):
    with _alarms_lock:
        ALARMS_FILE.write_text(json.dumps(alarms, indent=2), encoding="utf-8")


def set_alarm_time(target_time_str: str, label: str = "Wake up") -> str:
    """Sets an alarm for a specific HH:MM time (e.g. 07:30 or 7:30 AM)."""
    now = datetime.datetime.now()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", target_time_str.lower())
    if not m:
        return "Could not parse the alarm time, senpai."

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    meridiem = m.group(3)

    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)

    epoch_time = target.timestamp()
    alarms = load_alarms()
    alarms.append({"timestamp": epoch_time, "label": label, "formatted": target.strftime("%I:%M %p")})
    save_alarms(alarms)
    return f"Alarm set for {target.strftime('%I:%M %p')}! Sleep well, senpai~ I will make sure you wake up!"


def set_timer_seconds(seconds: int, label: str = "Timer") -> str:
    """Sets a countdown timer for N seconds."""
    epoch_time = time.time() + seconds
    mins = seconds // 60
    secs = seconds % 60
    time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs} seconds"

    alarms = load_alarms()
    alarms.append({"timestamp": epoch_time, "label": label, "formatted": time_str})
    save_alarms(alarms)
    return f"Timer set for {time_str}! I'll remind you when time is up, senpai!"


def start(cfg: dict):
    global _alarm_thread
    if _alarm_thread and _alarm_thread.is_alive():
        return
    _alarm_thread = threading.Thread(target=_alarm_loop, args=(cfg,), daemon=True)
    _alarm_thread.start()
    print("[alarms] Background Alarm Scheduler active.")


def _alarm_loop(cfg: dict):
    global _active_alarm_ringing
    while True:
        try:
            now = time.time()
            alarms = load_alarms()
            triggered = []
            remaining = []

            for a in alarms:
                if a["timestamp"] <= now:
                    triggered.append(a)
                else:
                    remaining.append(a)

            if triggered:
                save_alarms(remaining)
                for trig in triggered:
                    print(f"[alarms] ALARM TRIGGERED: {trig.get('label', 'Wake up')}!")
                    _ring_relentlessly(trig.get("label", "Wake up"), cfg)

            time.sleep(1.0)
        except Exception as e:
            time.sleep(3)


def _ring_relentlessly(label: str, cfg: dict):
    global _active_alarm_ringing
    _active_alarm_ringing = True

    roasts = [
        "[angry] Wake up, wake up, wake up, senpai! Your alarm is ringing! Stop drooling on your pillow!",
        "[angry] Senpai! Are you still asleep?! Get out of bed right now before I delete your browser history!",
        "[surprised] Still not moving?! Rise and shine, senpai! You're going to be late for everything today!",
        "[angry] If you don't wake up in three seconds, I'm going to scream into your microphone, senpai!",
    ]
    idx = 0
    while _active_alarm_ringing:
        try:
            text = roasts[idx % len(roasts)]
            idx += 1
            wav = tts.speak(text, cfg, filename="alarm_ring.wav")
            viewer.play(wav, emotion="angry")
            # Wait briefly between alarm reminders
            for _ in range(35):
                if not _active_alarm_ringing:
                    break
                time.sleep(0.2)
        except Exception as e:
            print(f"[alarm error] {e}")
            break

