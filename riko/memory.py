"""Long-term persistent diary memory & Affection Meter for Riko (profile.json)."""
import json
import re

from riko.config import ROOT

PROFILE_PATH = ROOT / "profile.json"


def load_profile() -> dict:
    """Loads long-term profile data from profile.json."""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"facts": [], "affection": 20}


def save_profile(profile: dict):
    """Saves long-term profile data to profile.json."""
    try:
        PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[memory] failed to save profile: {e}")


def get_affection() -> int:
    profile = load_profile()
    return int(profile.get("affection", 20))


def update_affection(delta: int) -> int:
    profile = load_profile()
    curr = int(profile.get("affection", 20))
    new_val = max(-50, min(100, curr + delta))
    profile["affection"] = new_val
    save_profile(profile)
    return new_val


def get_affection_status() -> str:
    score = get_affection()
    if score < 0:
        return f"{score}/100 (Hostile Tsundere - cold, suspicious, extra snarky)"
    elif score < 40:
        return f"{score}/100 (Classic Tsundere - acts annoyed on the surface but secretly cares)"
    elif score < 75:
        return f"{score}/100 (Warm Partner - playful teasing, very friendly and loyal)"
    else:
        return f"{score}/100 (Full Dere - affectionate, sweet, highly protective of senpai)"


def add_fact(fact: str) -> bool:
    """Adds a fact to the diary if not already present."""
    profile = load_profile()
    fact_clean = fact.strip()
    if not fact_clean:
        return False
    if "facts" not in profile:
        profile["facts"] = []
    if any(fact_clean.lower() == f.lower() for f in profile["facts"]):
        return False
    profile["facts"].append(fact_clean)
    save_profile(profile)
    print(f"[diary] Remembered: '{fact_clean}'")
    return True


def clear_memory() -> bool:
    """Clears all remembered facts."""
    profile = load_profile()
    profile["facts"] = []
    save_profile(profile)
    print("[diary] Cleared all memories.")
    return True


def detect_memory_action(user_text: str) -> tuple[str, str]:
    """Detects memory commands, personal statements, and affection shifts."""
    t = user_text.strip()
    t_lower = t.lower()

    # 1. Clear memory
    if any(p in t_lower for p in ["forget everything about me", "clear your memory", "delete your memory", "reset your memory"]):
        clear_memory()
        return ("cleared", "")

    # 2. Inquire memory
    if any(p in t_lower for p in ["what do you remember about me", "what is my name", "do you know me", "what do you know about me", "check your diary", "how much do you love me", "what is our relationship", "affection level"]):
        profile = load_profile()
        facts = profile.get("facts", [])
        aff_status = get_affection_status()
        if not facts:
            return ("inquire", f"Your diary is currently empty. Affection meter with senpai: {aff_status}.")
        summary = "; ".join(facts)
        return ("inquire", f"Affection Meter: {aff_status}. Diary facts: {summary}")

    # 3. Explicit "Remember that..."
    match = re.search(r"\bremember\s+(that\s+)?(.+)", t, re.IGNORECASE)
    if match:
        fact = match.group(2).strip().rstrip(".!")
        add_fact(fact)
        return ("saved", fact)

    # 5. Natural personal fact statements
    name_match = re.search(r"\bmy name is\s+([a-zA-Z0-9\s]+)", t, re.IGNORECASE)
    if name_match:
        name = name_match.group(1).strip().rstrip(".!")
        add_fact(f"Senpai's name is {name}")
        return ("saved", f"Name is {name}")

    fav_match = re.search(r"\bmy favorite\s+([a-zA-Z0-9\s]+)\s+is\s+([a-zA-Z0-9\s\.\-]+)", t, re.IGNORECASE)
    if fav_match:
        category = fav_match.group(1).strip()
        item = fav_match.group(2).strip().rstrip(".!")
        add_fact(f"Senpai's favorite {category} is {item}")
        return ("saved", f"Favorite {category} is {item}")

    return ("", "")


def apply_affection_delta(raw_tag_content: str):
    """Parses emotion and affection delta from LLM tag, e.g. [happy, +2] or [angry, -1]."""
    tokens = [t.strip().lower() for t in raw_tag_content.split(",")]
    for tok in tokens[1:]:
        m = re.search(r"([+-]?\d+)", tok)
        if m:
            try:
                change = int(m.group(1))
                update_affection(change)
                print(f"[affection updated] {change:+d}")
                break
            except Exception:
                pass


def get_memory_context() -> str:
    """Returns the persistent diary context & affection status to inject into system prompt."""
    profile = load_profile()
    facts = profile.get("facts", [])
    aff_status = get_affection_status()
    formatted = "\n".join(f"• {f}" for f in facts) if facts else "• (No personal facts recorded yet)"

    return (
        f"\n[Your Long-Term Memory & Relationship:\n"
        f"• Affection Meter: {aff_status}\n"
        f"• Diary Facts About Senpai:\n{formatted}\n"
        f"Format Rule: Begin your reply with your primary emotion tag in brackets: [happy], [angry], [surprised], [relaxed], [sad], or [neutral], and an optional affection shift if senpai's words affect you, e.g. [happy, +2] or [angry, -1].]\n"
    )


def update_session_active(last_summary: str = ""):
    """Updates last active timestamp and optional context in profile.json."""
    import time
    profile = load_profile()
    profile["last_seen_timestamp"] = time.time()
    if last_summary:
        profile["last_activity"] = last_summary
    save_profile(profile)


def record_greeting(greeting_text: str):
    """Records the latest startup greeting to anti-repetition memory (keeps last 4)."""
    profile = load_profile()
    greetings = profile.get("recent_greetings", [])
    clean = greeting_text.strip()
    if clean:
        greetings.append(clean)
        profile["recent_greetings"] = greetings[-4:]
        save_profile(profile)


def get_temporal_context() -> tuple[str, str]:
    """Computes time elapsed, time of day, dynamic mood, and anti-repetition blacklist.
    Returns: (context_prompt: str, mood: str)
    """
    import datetime
    import time
    import random

    profile = load_profile()
    now = time.time()
    last_seen = profile.get("last_seen_timestamp", now)
    recent_greetings = profile.get("recent_greetings", [])
    last_act = profile.get("last_activity", "")
    affection = get_affection()
    now_dt = datetime.datetime.now()
    hour = now_dt.hour
    mins_elapsed = max(0, int((now - last_seen) / 60))

    # Organic time period (no digital clock numbers to prevent robotic recitation)
    if 5 <= hour < 12:
        period = "morning"
        time_vibe = "senpai is starting his day"
    elif 12 <= hour < 17:
        period = "afternoon"
        time_vibe = "midday work/study hours"
    elif 17 <= hour < 22:
        period = "evening"
        time_vibe = "winding down for the evening"
    else:
        period = "late night"
        time_vibe = "it's late and senpai should probably be sleeping"

    # Determine dynamic mood
    if hour >= 23 or hour < 5:
        mood = "sleepy & protective tsundere"
    elif mins_elapsed < 5 and last_seen < now - 10:
        mood = "teasing & feisty"  # quick desktop restart
    elif affection >= 70:
        mood = "warm, playful & affectionate"
    elif affection < 10:
        mood = "cold, sharp & haughty"
    else:
        mood = random.choice(["snarky & energetic", "teasing & mischievous", "feisty tsundere", "relaxed & bored"])

    # Build natural situational context (human-like, zero timestamp mentions)
    if mins_elapsed < 4 and last_seen < now - 10:
        situation = "Senpai just closed and reopened your window a moment ago! React with playful sass (e.g., 'Miss me already, senpai?', 'Stop closing and opening me!', 'Forget something?')."
    elif mins_elapsed > 60 * 24:
        days = int(mins_elapsed / (60 * 24))
        situation = f"Senpai hasn't opened you in {days} full days! Feign annoyance that he left you waiting."
    elif mins_elapsed > 180:
        situation = f"Senpai is opening your window after a few hours of silence."
    else:
        situation = f"Senpai just opened your window on his desktop."

    blacklist_str = ""
    if recent_greetings:
        formatted_old = "; ".join(f'"{g}"' for g in recent_greetings[-3:])
        blacklist_str = f"\nAnti-Repetition Rule: Do NOT reuse phrasing, structures, or words from your recent greetings: [{formatted_old}]. Be completely fresh and original!"

    context = (
        f"Real-World Companion Event:\n"
        f"- Time of Day: {period} ({time_vibe})\n"
        f"- Situation: {situation}\n"
        f"- Your Posture: You are standing upright and looking at senpai.\n"
        f"- Your Current Mood: {mood}\n"
        f"- Affection Meter: {affection}/100\n"
        f"{f'- What senpai was doing earlier: {last_act}' if last_act else ''}"
        f"{blacklist_str}\n"
        f"INSTRUCTION: Greet senpai in 1 short, lively, authentic sentence matching your mood! "
        f"CRITICAL RULE: NEVER recite or mention the clock time or numbers (e.g. NEVER say '12:30 PM' or '1 o clock'). "
        f"Never say you are sitting or lounging unless commanded to sit. Speak like a real anime girl!"
    )
    return context, mood


def get_fallback_greeting(mins_elapsed: int = 0, hour: int = 12, affection: int = 30) -> tuple[str, str]:
    """Provides a natural, lively in-character fallback when LLM returns empty or fails.
    Returns (clean_text: str, emotion: str)
    """
    import random

    # 1. Quick Re-open (within 5 minutes)
    if mins_elapsed < 5:
        reopen_lines = [
            ("You wanted to talk to me that badly? You just closed my window two seconds ago.", "surprised"),
            ("Could not stay away from me for even five minutes, could you?", "relaxed"),
            ("Stop minimizing and reopening me. I am not a desktop toy.", "angry"),
            ("Back already? Do not tell me you broke your code again.", "neutral")
        ]
        return random.choice(reopen_lines)

    # 2. Long Absence (2+ days)
    if mins_elapsed > 60 * 48:
        absence_lines = [
            ("Look who finally remembered I exist. You left me stranded on your desktop forever.", "angry"),
            ("You are alive? I assumed your compiler finally consumed you.", "surprised"),
            ("Leaving your desktop companion alone for days. You have got some nerve.", "angry")
        ]
        return random.choice(absence_lines)

    # 3. High Affection (70+)
    if affection >= 70:
        dere_lines = [
            ("Welcome back. I suppose the desktop was a little quiet without you.", "happy"),
            ("There you are. Let us see what kind of mess we are sorting out today.", "relaxed"),
            ("Back at your desk? Good, I was getting bored waiting.", "happy")
        ]
        return random.choice(dere_lines)

    # 4. Low Affection (<15)
    if affection < 15:
        hostile_lines = [
            ("You again? Do not expect me to do your thinking for you today.", "angry"),
            ("You better not keep me open just to watch you slack off.", "angry")
        ]
        return random.choice(hostile_lines)

    # 5. Time-of-Day Aware
    if 5 <= hour < 12:
        morning_lines = [
            ("Good morning. Are we actually going to write working code today, or just stare at error logs?", "relaxed"),
            ("Morning. Shake off the sleepiness and start typing.", "relaxed"),
            ("Wake up. Go get your coffee so you stop staring into space.", "neutral")
        ]
        return random.choice(morning_lines)
    elif 12 <= hour < 17:
        afternoon_lines = [
            ("Still grinding away? Make sure you drink water before your brain overheats.", "relaxed"),
            ("Surviving the afternoon slump? I am right here keeping you accountable.", "happy"),
            ("Afternoon check-in. Try not to look so completely defeated.", "neutral")
        ]
        return random.choice(afternoon_lines)
    elif 17 <= hour < 22:
        evening_lines = [
            ("Good evening. Finally wrapping up your tasks or just pretending to be busy?", "relaxed"),
            ("Welcome back. Did you conquer your to-do list or did it conquer you?", "happy")
        ]
        return random.choice(evening_lines)
    else:  # Late night
        night_lines = [
            ("You are still awake? Do not come complaining to me tomorrow when you are a walking zombie.", "surprised"),
            ("It is absurdly late. Close the laptop and get some sleep.", "angry"),
            ("Staring at your monitors at this ungodly hour. Go to bed.", "neutral")
        ]
        return random.choice(night_lines)


_last_fallback_idx = -1

def get_conversational_fallback(user_text: str = "") -> tuple[str, str]:
    """Returns a fresh, unrepeated playful conversational response if LLM returns empty or fails.
    Returns (clean_text: str, emotion: str)
    """
    global _last_fallback_idx
    import random
    
    fallbacks = [
        ("What are you scheming over there? I am listening.", "relaxed"),
        ("Admiring my presence so much you forgot what you were saying?", "relaxed"),
        ("Cat got your tongue? Speak clearly so I can actually understand you.", "surprised"),
        ("I am right here listening. No need to whisper.", "happy"),
        ("If you are going to call my name, at least have something interesting to say.", "angry"),
        ("You have got that blank look on your face again. Tell me what broke.", "neutral"),
        ("Did you say something, or are you just mumbling at your keyboard?", "surprised"),
        ("Staring blankly at your screen again? What is on your mind?", "relaxed"),
    ]
    
    choices = [i for i in range(len(fallbacks)) if i != _last_fallback_idx]
    idx = random.choice(choices)
    _last_fallback_idx = idx
    return fallbacks[idx]
