"""Long-term persistent Markdown memory & Affection Meter for Miso (IDENTITY.md, MEMORIES.md, PROFILE.md)."""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import random
import re
import threading
import time

from riko.config import ROOT

# ── Short-Term Visual Working Memory Buffer ──
_visual_events: list[dict] = []
_visual_lock = threading.RLock()


def _paths():
    """Dynamically resolves root memory paths based on current riko.config.ROOT."""
    from riko.config import ROOT as current_root
    return (
        current_root / "IDENTITY.md",
        current_root / "MEMORIES.md",
        current_root / "PROFILE.md",
        current_root / "profile.json",
        current_root / "chat_history.json",
    )


def add_visual_event(description: str):
    """Records a recent visual observation into the transient short-term working memory."""
    global _visual_events
    with _visual_lock:
        now = time.time()
        _visual_events.append({"timestamp": now, "description": description.strip()})
        # Keep only the last 10 events within the past 15 minutes
        _visual_events = [e for e in _visual_events if now - e["timestamp"] < 900][-10:]
        print(f"[visual memory] Observed: '{description.strip()}'")


def get_recent_visual_events(max_age_seconds: int = 300) -> list[str]:
    """Returns human-readable recent visual events from short-term memory."""
    with _visual_lock:
        now = time.time()
        results = []
        for e in _visual_events:
            age = int(now - e["timestamp"])
            if age <= max_age_seconds:
                if age < 60:
                    time_str = f"{age}s ago"
                else:
                    time_str = f"{age // 60}m ago"
                results.append(f"{time_str}: {e['description']}")
        return results


def get_visual_context_prompt() -> str:
    """Builds a contextual prompt snippet representing recent visual observations."""
    events = get_recent_visual_events(300)
    if not events:
        return ""
    recent_str = "; ".join(events[-3:])
    return f"\n[Recent Visual Observations of Utkarsh via Webcam: {recent_str}]"


# ── Markdown Memory Helpers ──

def _read_facts(profile_path: Path) -> list[str]:
    if not profile_path.exists():
        return []
    try:
        text = profile_path.read_text(encoding="utf-8")
    except Exception:
        return []
    facts: list[str] = []
    in_facts_section = False
    for line in text.splitlines():
        line_s = line.strip()
        if line_s.startswith("## Facts About"):
            in_facts_section = True
            continue
        elif line_s.startswith("## ") and in_facts_section:
            break
        if in_facts_section and line_s.startswith("- "):
            f = line_s[2:].strip()
            if f:
                facts.append(f)
    # If no header was found, parse any bullet
    if not facts and text.strip():
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.startswith("- "):
                f = line_s[2:].strip()
                if f:
                    facts.append(f)
    return facts


def _write_facts(profile_path: Path, facts: list[str]):
    header = "## Facts About Utkarsh\n"
    if profile_path.exists():
        try:
            for l in profile_path.read_text(encoding="utf-8").splitlines():
                if l.strip().startswith("## Facts About"):
                    header = l.strip() + "\n"
                    break
        except Exception:
            pass
    lines = [f"# PROFILE\n\n{header}"]
    for f in facts:
        lines.append(f"- {f}\n")
    profile_path.write_text("".join(lines), encoding="utf-8")


def _read_memories(memories_path: Path) -> dict:
    defaults = {
        "affection": 20,
        "current_mood": "classic_tsundere",
        "recent_greetings": [],
        "last_seen_timestamp": time.time(),
        "last_activity": "",
        "raw_text": "",
    }
    if not memories_path.exists():
        return defaults
    try:
        text = memories_path.read_text(encoding="utf-8")
    except Exception:
        return defaults

    aff = 20
    m_aff = re.search(r"(?i)\bAffection:\s*([+-]?\d+)", text)
    if m_aff:
        try:
            aff = max(-50, min(100, int(m_aff.group(1))))
        except Exception:
            aff = 20

    mood = "classic_tsundere"
    m_mood = re.search(r"(?i)\bCurrent Mood:\s*([^\n\r]+)", text)
    if m_mood:
        mood = m_mood.group(1).strip()

    ts = time.time()
    m_ts = re.search(r"(?i)\bLast Seen Timestamp:\s*([0-9.]+)", text)
    if m_ts:
        try:
            ts = float(m_ts.group(1))
        except Exception:
            pass

    act = ""
    m_act = re.search(r"(?i)\bLast Activity:\s*([^\n\r]+)", text)
    if m_act:
        act = m_act.group(1).strip()

    greetings: list[str] = []
    in_greetings = False
    for line in text.splitlines():
        line_s = line.strip()
        if line_s.startswith("## Recent Greetings"):
            in_greetings = True
            continue
        elif line_s.startswith("## ") and in_greetings:
            break
        if in_greetings and line_s.startswith("- "):
            g = line_s[2:].strip()
            if g:
                greetings.append(g)

    return {
        "affection": aff,
        "current_mood": mood,
        "last_seen_timestamp": ts,
        "last_activity": act,
        "recent_greetings": greetings,
        "raw_text": text,
    }


def _write_memories(memories_path: Path, data: dict):
    existing_raw = ""
    if memories_path.exists():
        try:
            existing_raw = memories_path.read_text(encoding="utf-8")
        except Exception:
            pass

    aff = max(-50, min(100, int(data.get("affection", 20))))
    mood = data.get("current_mood", "classic_tsundere")
    ts = data.get("last_seen_timestamp", time.time())
    act = data.get("last_activity", "")
    greetings = data.get("recent_greetings", [])

    extra_sections: list[str] = []
    if existing_raw:
        in_skip = False
        for line in existing_raw.splitlines():
            if line.strip().startswith("## Recent Greetings"):
                in_skip = True
                continue
            elif line.strip().startswith("## "):
                in_skip = False
                extra_sections.append(line)
            elif not in_skip and not line.strip().startswith("# MEMORIES") and not line.strip().startswith("Affection:") and not line.strip().startswith("Current Mood:") and not line.strip().startswith("Last Seen Timestamp:") and not line.strip().startswith("Last Activity:"):
                if line.strip():
                    extra_sections.append(line)

    lines = [
        "# MEMORIES\n",
        f"Affection: {aff}\n",
        f"Current Mood: {mood}\n",
        f"Last Seen Timestamp: {ts}\n",
    ]
    if act:
        lines.append(f"Last Activity: {act}\n")
    lines.append("\n## Recent Greetings\n")
    for g in greetings[-4:]:
        lines.append(f"- {g}\n")

    if extra_sections:
        lines.append("\n" + "\n".join(extra_sections) + "\n")

    memories_path.write_text("".join(lines), encoding="utf-8")


def _read_identity(identity_path: Path) -> str:
    if identity_path.exists():
        try:
            return identity_path.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


def _seed_default_identity(identity_path: Path):
    persona = (
        "# IDENTITY\n"
        "You are Miso, an arrogant, sharp-witted, and deadpan anime desktop companion living inside senpai's PC.\n"
        "You are inspired by the Rikoverse persona: maximum sass, cheeky humor, and zero chill.\n"
    )
    try:
        from riko.config import ROOT as current_root
        cfg_path = current_root / "character_config.yaml"
        if cfg_path.exists():
            import yaml
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            sp = cfg.get("system_prompt", "")
            if sp and "Miso" in sp:
                first_part = "\n".join(sp.splitlines()[:15])
                persona = f"# IDENTITY\n{first_part}\n"
    except Exception:
        pass

    identity_path.write_text(persona, encoding="utf-8")


def _ensure_initialized():
    identity_path, memories_path, profile_path, legacy_profile_path, _ = _paths()

    # If PROFILE.md already exists, do NOT touch or clobber anything
    if profile_path.exists():
        if not identity_path.exists():
            _seed_default_identity(identity_path)
        if not memories_path.exists():
            _write_memories(memories_path, {"affection": 20, "current_mood": "classic_tsundere"})
        return

    # Check if legacy profile.json exists for migration
    if legacy_profile_path.exists():
        try:
            data = json.loads(legacy_profile_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        # 1. PROFILE.md
        facts = data.get("facts", [])
        if not isinstance(facts, list):
            facts = []
        _write_facts(profile_path, facts)

        # 2. MEMORIES.md
        aff = 20
        try:
            if "affection" in data:
                aff = int(data["affection"])
        except Exception:
            aff = 20
        mood = data.get("current_mood", "classic_tsundere")
        ts = data.get("last_seen_timestamp", time.time())
        act = data.get("last_activity", "")
        greetings = data.get("recent_greetings", [])
        if not isinstance(greetings, list):
            greetings = []
        _write_memories(memories_path, {
            "affection": aff,
            "current_mood": mood,
            "last_seen_timestamp": ts,
            "last_activity": act,
            "recent_greetings": greetings,
        })

        # 3. IDENTITY.md seeded from character_config persona
        _seed_default_identity(identity_path)

        # Never touch legacy_profile_path on disk!
        return

    # Neither exists -> bootstrap clean defaults
    _seed_default_identity(identity_path)
    _write_memories(memories_path, {"affection": 20, "current_mood": "classic_tsundere"})
    _write_facts(profile_path, [])


# ── Public Memory API ──

def load_profile() -> dict:
    """Loads long-term profile data from Markdown files."""
    _ensure_initialized()
    identity_path, memories_path, profile_path, _, _ = _paths()
    facts = _read_facts(profile_path)
    mem_data = _read_memories(memories_path)
    return {
        "facts": facts,
        "affection": mem_data["affection"],
        "current_mood": mem_data["current_mood"],
        "last_seen_timestamp": mem_data["last_seen_timestamp"],
        "last_activity": mem_data.get("last_activity", ""),
        "recent_greetings": mem_data.get("recent_greetings", []),
    }


def save_profile(profile: dict):
    """Saves long-term profile data to Markdown files (legacy JSON kept intact)."""
    _ensure_initialized()
    identity_path, memories_path, profile_path, _, _ = _paths()
    if "facts" in profile:
        _write_facts(profile_path, profile["facts"])
    _write_memories(memories_path, profile)


def get_affection() -> int:
    _ensure_initialized()
    identity_path, memories_path, _, _, _ = _paths()
    mem_data = _read_memories(memories_path)
    return mem_data["affection"]


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
    """Adds a fact to PROFILE.md if not already present."""
    fact_clean = fact.strip()
    if not fact_clean:
        return False
    _ensure_initialized()
    _, _, profile_path, _, _ = _paths()
    facts = _read_facts(profile_path)
    if any(fact_clean.lower() == f.lower() for f in facts):
        return False
    facts.append(fact_clean)
    _write_facts(profile_path, facts)
    print(f"[diary] Remembered: '{fact_clean}'")
    return True


def clear_memory() -> bool:
    """Clears all remembered facts from PROFILE.md while preserving IDENTITY.md and MEMORIES.md."""
    _ensure_initialized()
    _, _, profile_path, _, _ = _paths()
    _write_facts(profile_path, [])
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
    if any(p in t_lower for p in [
        "what do you remember about me", "what is my name", "do you know me",
        "what do you know about me", "check your diary", "how much do you love me",
        "what is our relationship", "affection level"
    ]):
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

    # 4. Natural personal fact statements
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
    _ensure_initialized()
    identity_path, memories_path, profile_path, _, _ = _paths()
    facts = _read_facts(profile_path)
    aff_status = get_affection_status()
    formatted = "\n".join(f"• {f}" for f in facts) if facts else "• (No personal facts recorded yet)"

    id_text = _read_identity(identity_path)
    id_snippet = f"\n[{id_text.strip()}]\n" if id_text.strip() else ""

    mem_extra = ""
    if memories_path.exists():
        try:
            m_raw = memories_path.read_text(encoding="utf-8")
            extra_lines = []
            for line in m_raw.splitlines():
                if line.strip().startswith("## ") and not line.strip().startswith("## Recent Greetings"):
                    extra_lines.append(line)
                elif extra_lines and line.strip() and not line.strip().startswith("## Recent Greetings"):
                    extra_lines.append(line)
            if extra_lines:
                mem_extra = f"\n[Memories & Notes:\n{chr(10).join(extra_lines)}]\n"
        except Exception:
            pass

    return (
        f"{id_snippet}{mem_extra}"
        f"\n[Your Long-Term Memory & Relationship:\n"
        f"• Affection Meter: {aff_status}\n"
        f"• Diary Facts About Utkarsh:\n{formatted}\n"
        f"Format Rule: Begin your reply with [emotion:intensity] (intensity 1-3, emotion in neutral/happy/angry/sad/surprised/relaxed/flustered/annoyed/jealous/smug/caring), optional affection delta like [happy:2, +2], and ONLY when a physical gesture fits, one optional [gesture] (shrug/cross_arms/facepalm/head_tilt/point/wave/nod/shake_head/smug/sigh/think). Omit [gesture] on ordinary replies.]\n"
    )


def update_session_active(last_summary: str = ""):
    """Updates last active timestamp and optional context in MEMORIES.md."""
    _ensure_initialized()
    _, memories_path, _, _, _ = _paths()
    mem_data = _read_memories(memories_path)
    mem_data["last_seen_timestamp"] = time.time()
    if last_summary:
        mem_data["last_activity"] = last_summary
    _write_memories(memories_path, mem_data)


def record_greeting(greeting_text: str):
    """Records the latest startup greeting to anti-repetition memory (keeps last 4 in MEMORIES.md)."""
    clean = greeting_text.strip()
    if not clean:
        return
    _ensure_initialized()
    _, memories_path, _, _, _ = _paths()
    mem_data = _read_memories(memories_path)
    greetings = mem_data.get("recent_greetings", [])
    greetings.append(clean)
    mem_data["recent_greetings"] = greetings[-4:]
    _write_memories(memories_path, mem_data)


def get_temporal_context() -> tuple[str, str]:
    """Computes time elapsed, time of day, dynamic mood, and anti-repetition blacklist.
    Returns: (context_prompt: str, mood: str)
    """
    _ensure_initialized()
    profile = load_profile()
    now = time.time()
    last_seen = profile.get("last_seen_timestamp", now)
    recent_greetings = profile.get("recent_greetings", [])
    last_act = profile.get("last_activity", "")
    affection = get_affection()
    now_dt = datetime.datetime.now()
    hour = now_dt.hour
    mins_elapsed = max(0, int((now - last_seen) / 60))

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

    mood = profile.get("current_mood", "")
    if not mood:
        if hour >= 23 or hour < 5:
            mood = "late-night deadpan & mocking"
        elif mins_elapsed < 5 and last_seen < now - 10:
            mood = "smug & sarcastic"
        elif affection >= 70:
            mood = "smug, playful & secretly loyal"
        elif affection < 10:
            mood = "cold, sharp & haughty"
        else:
            mood = random.choice(["deadpan & cheeky", "arrogant & sarcastic", "zero chill snark", "relaxed & smug"])

    if mins_elapsed < 4 and last_seen < now - 10:
        situation = "Senpai just closed and reopened your window a moment ago! Roast his indecision."
    elif mins_elapsed > 60 * 24:
        days = int(mins_elapsed / (60 * 24))
        situation = f"Senpai hasn't opened you in {days} full days! Roast him for abandoning his desktop deity (e.g. 'You finally remembered me?')."
    elif mins_elapsed > 180:
        situation = "Senpai is opening your window after hours of silence. Demand to know what buggy code he created (e.g. 'You finally remembered me?')."
    else:
        situation = "Senpai just opened your window on his desktop."

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
        f"INSTRUCTION: Greet Utkarsh in 1 short, lively, authentic anime line matching your mood and time of day (8 to 18 words)! "
        f"Be cheeky and casual. Deliver the line directly without honorifics. "
        f"NEVER recite clock numbers (e.g. NEVER say '12:30' or '1 o clock'). Begin with [emotion:intensity] (1-3) and an optional [gesture] only when expressive, e.g. [relaxed:2], [happy:2][wave], or [angry:2][cross_arms]."
    )
    return context, mood


def get_fallback_greeting(mins_elapsed: int = 0, hour: int = 12, affection: int = 30) -> tuple[str, str]:
    """Provides a natural, lively in-character fallback when LLM returns empty or fails.
    Returns (clean_text: str, emotion: str)
    """
    if mins_elapsed < 5:
        reopen_lines = [
            ("Wanted to talk to me that badly? You just closed my window two seconds ago!", "surprised"),
            ("Heh... couldn't stay away from me for even five minutes, could you?", "relaxed"),
            ("Stop minimizing and reopening me... I'm not a desktop toy, you know?", "angry"),
            ("Back already? Sheesh, don't tell me you broke your code again.", "neutral")
        ]
        return random.choice(reopen_lines)

    if mins_elapsed > 60 * 48:
        absence_lines = [
            ("Well, look who finally remembered I exist. Leaving me stranded on your desktop for days... you've got some nerve.", "angry"),
            ("You're alive? Honestly, I assumed your compiler finally consumed you.", "surprised"),
            ("Leaving your desktop companion alone for days? Sheesh, rude.", "angry")
        ]
        return random.choice(absence_lines)

    if affection >= 70:
        dere_lines = [
            ("Welcome back! I suppose the desktop was a little quiet without you... not that I missed you or anything.", "happy"),
            ("There you are. Let's see what kind of mess we're sorting out today.", "relaxed"),
            ("Back at your desk? Good... I was getting bored waiting.", "happy")
        ]
        return random.choice(dere_lines)

    if affection < 15:
        hostile_lines = [
            ("You again? Don't expect me to do your thinking for you today.", "angry"),
            ("Hmph, you better not keep me open just to watch you slack off.", "angry")
        ]
        return random.choice(hostile_lines)

    if 5 <= hour < 12:
        morning_lines = [
            ("Morning! Are we actually going to write working code today, or just stare at error logs?", "relaxed"),
            ("Morning... shake off the sleepiness and start typing.", "relaxed"),
            ("Wake up! Go get your coffee so you stop staring into space.", "neutral")
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
    else:
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
