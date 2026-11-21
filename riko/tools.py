"""Tools for Riko: Live Internet Search, Screen Vision, App Launcher, Mood Music & Media Controls."""
import base64
import io
import re
import subprocess
import urllib.parse
from typing import Optional

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from PIL import Image

APP_MAPPINGS = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "vs code": "code",
    "vscode": "code",
    "code": "code",
    "terminal": "wt",
    "cmd": "cmd",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "downloads": "explorer shell:Downloads",
    "desktop": "explorer shell:Desktop",
    "documents": "explorer shell:Personal",
    "pictures": "explorer shell:My Pictures",
    "task manager": "taskmgr",
    "settings": "start ms-settings:",
    "spotify": "start spotify:",
    "discord": "start discord:",
    "steam": "start steam:",
    "chrome": "start chrome",
    "edge": "start msedge",
    "paint": "mspaint",
}


def control_media(text: str) -> Optional[str]:
    """Handles system volume, mute, play/pause, and track skip via Windows virtual keys (0ms latency)."""
    t = text.lower().strip()
    try:
        import ctypes
        def send_vk(vk):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)

        # Volume controls
        if any(w in t for w in ["volume up", "increase volume", "turn it up", "louder"]):
            for _ in range(5):
                send_vk(0xAF)  # VK_VOLUME_UP
            return "turned the volume up"

        if any(w in t for w in ["volume down", "decrease volume", "turn it down", "quieter", "lower volume"]):
            for _ in range(5):
                send_vk(0xAE)  # VK_VOLUME_DOWN
            return "turned the volume down"

        if any(w in t for w in ["mute audio", "mute sound", "mute", "unmute"]):
            send_vk(0xAD)  # VK_VOLUME_MUTE
            return "toggled mute"

        # System Actions
        if any(w in t for w in ["lock my pc", "lock the pc", "lock my computer", "lock screen", "lock workstation"]):
            ctypes.windll.user32.LockWorkStation()
            return "locked the computer screen"

        if any(w in t for w in ["take a screenshot and save", "save screenshot", "save a screenshot", "take screenshot and save"]):
            try:
                import datetime
                from pathlib import Path
                shots_dir = Path(__file__).resolve().parent.parent / "screenshots"
                shots_dir.mkdir(exist_ok=True)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = shots_dir / f"screenshot_{timestamp}.png"
                try:
                    import mss
                    with mss.mss() as sct:
                        sct_img = sct.grab(sct.monitors[1])
                        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                except Exception:
                    from PIL import ImageGrab
                    img = ImageGrab.grab()
                img.save(filename)
                return f"captured and saved a screenshot to screenshots/{filename.name}"
            except Exception as e:
                print(f"[tools] screenshot save note: {e}")
                return "attempted to save screenshot"

        # Media playback: Stop / Pause / Resume (strictly require full command phrase or standalone command)
        is_pause_or_stop = (
            t in ["stop", "pause", "resume", "shut up", "be quiet", "silence"] or
            any(w in t for w in [
                "stop the music", "stop music", "stop the video", "stop video",
                "stop song", "stop playing", "stop playback", "stop it", "stop that",
                "pause the music", "pause music", "pause the video", "pause video",
                "pause song", "pause it", "pause playback", "resume music", "resume playback",
                "close video", "close the video", "close tab", "close the tab",
                "kill the music", "kill music"
            ])
        )
        if is_pause_or_stop:
            # Send hardware media keys: Stop (0xB2) and Play/Pause (0xB3)
            send_vk(0xB2)  # VK_MEDIA_STOP
            send_vk(0xB3)  # VK_MEDIA_PLAY_PAUSE

            # Target active YouTube / browser tab directly
            try:
                import win32com.client
                wsh = win32com.client.Dispatch("WScript.Shell")
                if wsh.AppActivate("YouTube"):
                    import time
                    time.sleep(0.04)
                    if any(w in t for w in ["close tab", "close the tab", "close video", "stop video", "stop the video"]):
                        wsh.SendKeys("^w")  # Ctrl+W closes active tab
                    else:
                        wsh.SendKeys("k")   # 'k' is universal YouTube pause/play
                elif wsh.AppActivate("Spotify"):
                    import time
                    time.sleep(0.04)
                    wsh.SendKeys(" ")       # Spacebar pauses Spotify
            except Exception as e:
                print(f"[media] app focus note: {e}")

            if any(w in t for w in ["close tab", "close the tab", "close video", "stop video"]):
                return "closed the video tab"
            return "stopped the music and media playback"

        if any(w in t for w in ["next song", "skip song", "next track", "skip track"]):
            send_vk(0xB0)  # VK_MEDIA_NEXT_TRACK
            return "skipped to the next song"

        if any(w in t for w in ["previous song", "previous track"]):
            send_vk(0xB1)  # VK_MEDIA_PREV_TRACK
            return "went back to previous song"
    except Exception as e:
        print(f"[tools] media control note: {e}")

    return None


def detect_and_open_app(text: str) -> Optional[str]:
    """Detects commands like 'open notepad', 'launch spotify', 'open downloads' and runs them."""
    t = text.lower().strip()
    match = re.search(r"\b(open|launch|start|run)\s+([a-zA-Z0-9\s\.\-]+)", t)
    if not match:
        return None
    target = match.group(2).strip()
    target = re.sub(r"^(the|an?)\s+", "", target)
    target = target.rstrip(".?!,")

    # Don't trigger if it was a music request
    if any(m in target for m in ["music", "song", "songs", "playlist", "track", "beats"]):
        return None

    # Known application mappings
    for name, cmd in APP_MAPPINGS.items():
        if target == name or target.startswith(name):
            try:
                subprocess.Popen(cmd, shell=True)
                return name.title()
            except Exception as e:
                print(f"[tools] failed to open {name}: {e}")
                return None

    # Known popular websites (e.g. "open youtube", "open github")
    sites = {
        "youtube": "https://www.youtube.com",
        "github": "https://www.github.com",
        "google": "https://www.google.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://www.x.com",
        "twitch": "https://www.twitch.tv",
    }
    for site, url in sites.items():
        if site in target:
            import webbrowser
            webbrowser.open(url)
            return site.title()

    # Generic safe Windows launcher
    safe_target = re.sub(r"[^a-zA-Z0-9_\-\.\s]", "", target).strip()
    if safe_target:
        try:
            subprocess.Popen(f"start {safe_target}", shell=True)
            return safe_target.title()
        except Exception:
            pass

    return None


def detect_and_play_music(text: str) -> Optional[str]:
    """Detects requests to play music, videos, YouTube streams, mood music, or artists.
    Supports queries like:
    - 'play something on youtube'
    - 'then you play something on youtube'
    - 'play some fun on youtube'
    - 'play lofi'
    - 'play music'
    - 'put on some songs'
    - 'play naruto theme'
    - 'play taylor swift on youtube'
    - 'play something'
    """
    t = text.lower().strip()

    # Clean leading conversational filler phrases
    cleaned = re.sub(
        r"^(then\s+|can\s+you\s+|could\s+you\s+|please\s+|i\s+will\s+|i\'ll\s+|hey\s+riko\s+|riko\s+)+",
        "",
        t
    ).strip()

    # STRICT GUARD: If user is telling Riko to stop, pause, mute, or close, NEVER play music!
    if any(w in cleaned for w in [
        "stop", "pause", "halt", "cancel", "kill", "shut up", "quiet", "silence",
        "mute", "unmute", "close", "turn off", "end", "dont play", "don't play"
    ]):
        return None

    # Media playback requires explicit play/listen action verb
    has_play = bool(re.search(r"\b(play|put on|listen to|stream|blast)\b", cleaned))
    if not has_play:
        return None

    # Extract target / query
    m = re.search(r"\b(play|put on|listen to|stream|blast)\s+(.+)", cleaned)
    raw_target = m.group(2).strip() if m else cleaned
    raw_target = re.sub(r"[\.\?!]+$", "", raw_target).strip()

    # Determine mood & search query
    label = ""
    search_term = ""

    if any(w in raw_target for w in ["sad", "depressed", "cry", "lonely", "gloomy", "heartbroken"]):
        label = "melancholic & emotional lofi"
        search_term = "sad emotional anime acoustic lofi songs"
    elif any(w in raw_target for w in ["fun", "happy", "cheerful", "upbeat", "joy", "good mood"]):
        label = "fun & upbeat anime songs"
        search_term = "fun cheerful upbeat anime songs"
    elif any(w in raw_target for w in ["hype", "energetic", "workout", "gym", "rock", "metal"]):
        label = "hype anime workout music"
        search_term = "energetic anime rock hype battle music"
    elif any(w in raw_target for w in ["study", "focus", "work", "coding", "homework"]):
        label = "coding & study synthwave"
        search_term = "synthwave lofi coding focus concentration music"
    elif any(w in raw_target for w in ["sleep", "relax", "calm", "peaceful", "quiet"]):
        label = "calm & peaceful sleep lofi"
        search_term = "calm peaceful relaxing sleep piano lofi ambient"
    elif any(w in raw_target for w in ["jazz"]):
        label = "smooth cafe jazz"
        search_term = "smooth anime cafe jazz bar instrumental"
    else:
        # Extract artist / topic
        has_youtube = ("youtube" in t or "yt" in t)
        clean_query = re.sub(
            r"\b(on\s+youtube|from\s+youtube|on\s+yt|video|videos|song|songs|music|track|for\s+me|something|anything|please|me|some|from|by|a|an)\b",
            "",
            raw_target,
            flags=re.IGNORECASE
        ).strip()
        # Clean extra spaces
        clean_query = re.sub(r"\s+", " ", clean_query).strip()
        if clean_query:
            label = clean_query
            search_term = f"{clean_query} songs" if not has_youtube else clean_query
        else:
            label = "fun upbeat anime music" if "fun" in t else "chill anime lofi beats"
            search_term = "fun upbeat anime songs" if "fun" in t else "lofi hip hop chill beats to study and relax to"

    # Try direct YouTube search via DuckDuckGo
    direct_url = None
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(f"site:youtube.com watch {search_term}", max_results=1))
            if results and results[0].get("href"):
                href = results[0]["href"]
                if "youtube.com/watch" in href or "youtu.be" in href or "youtube.com/playlist" in href:
                    direct_url = href
                    if results[0].get("title"):
                        label = results[0]["title"]
    except Exception as e:
        print(f"[tools] direct youtube lookup note: {e}")

    # Fallback to direct YouTube search query page
    if not direct_url:
        query_encoded = urllib.parse.quote_plus(search_term)
        direct_url = f"https://www.youtube.com/results?search_query={query_encoded}"

    try:
        import webbrowser
        webbrowser.open(direct_url)
        return f"{label} on YouTube"
    except Exception as e:
        print(f"[tools] failed to play music: {e}")
        return None


def search_web(query: str, max_results: int = 3) -> str:
    """Searches the live web and returns concise snippets."""
    try:
        clean_q = query.lower()
        for prefix in ["search for", "google", "look up", "can you check", "find info on", "find", "check"]:
            if clean_q.startswith(prefix):
                clean_q = clean_q[len(prefix):].strip()
        ddgs = DDGS()
        results = list(ddgs.text(clean_q or query, max_results=max_results))
        if not results:
            return ""
        snippets = []
        for r in results:
            title = r.get("title", "").strip()
            body = r.get("body", "").strip()
            if title and body:
                snippets.append(f"• {title}: {body}")
        return "\n".join(snippets)
    except Exception as e:
        print(f"[tools] search error: {e}")
        return ""


def capture_screen_base64(max_width: int = 800) -> Optional[str]:
    """Captures the primary screen and returns a base64 JPEG string."""
    try:
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            from PIL import ImageGrab
            img = ImageGrab.grab()

        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"[tools] screen capture note: {e}")
        return None


def should_capture_screen(text: str) -> bool:
    """Checks if the user wants Riko to inspect their screen."""
    t = text.lower()
    triggers = [
        "look at my screen",
        "see my screen",
        "what is on my screen",
        "what's on my screen",
        "check my screen",
        "look at this",
        "check this out",
        "check this code",
        "look at my code",
        "what am i doing",
        "can you see this",
        "see this",
    ]
    return any(trig in t for trig in triggers)


def capture_camera_base64(max_width: int = 640) -> Optional[str]:
    """Captures a live frame from the webcam and returns a base64 JPEG string."""
    try:
        import cv2
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            print("[camera] No webcam detected.")
            return None

        # Warm up 2 frames for auto-exposure adjustment
        cap.read()
        success, frame = cap.read()
        cap.release()

        if not success or frame is None:
            return None

        # Check facial recognition
        try:
            from riko import face_id
            person_status = face_id.identify_person_in_frame(frame)
            if "senpai_recognized" in person_status:
                print(f"[face_id] Recognition match: Utkarsh Senpai confirmed! ({person_status})")
            elif "stranger" in person_status:
                print(f"[face_id] Unfamiliar face detected! ({person_status})")
        except Exception as e:
            print(f"[face_id check note] {e}")

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb_frame)

        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"[tools] camera capture note: {e}")
        return None


def should_capture_camera(text: str) -> bool:
    """Checks if the user wants Riko to look at them through the webcam."""
    t = text.lower()
    # Explicit screen requests should not trigger camera
    if any(w in t for w in ["screen", "monitor", "display", "code", "window", "tab"]):
        return False

    triggers = [
        "wearing", "clothes", "outfit", "shirt", "dress", "holding",
        "look at me", "can you see me", "see me", "watch me", "how do i look",
        "check my camera", "look through my camera", "look through the camera",
        "open camera and look", "take a look at me", "what am i wearing",
        "what i am wearing", "what do i look like", "look at my face",
        "look at this in my hand", "can you see what i have", "look at what i'm holding",
        "check me out", "peek through my camera", "turn on camera"
    ]
    return any(trig in t for trig in triggers)


def should_search_web(text: str) -> bool:
    """Checks if the user query benefits from live web search."""
    t = text.lower()
    search_keywords = [
        "search for",
        "google",
        "look up",
        "who won",
        "weather in",
        "weather today",
        "price of",
        "stock price",
        "latest news",
        "what happened to",
        "score of",
        "tell me the news",
        "who is",
        "what happened with",
    ]
    return any(k in t for k in search_keywords)


def detect_minigame(text: str) -> Optional[str]:
    """Detects commands to play minigames like Rock-Paper-Scissors, Coin Flip, or Dice Roll."""
    import random
    t = text.lower().strip()

    # 1. Rock Paper Scissors
    if any(k in t for k in ["rock paper scissors", "rock, paper, scissors", "rps"]):
        user_choice = None
        for move in ["rock", "paper", "scissors"]:
            if move in t:
                user_choice = move
                break
        riko_choice = random.choice(["rock", "paper", "scissors"])
        if not user_choice:
            return f"Riko challenges you: 'I choose {riko_choice.upper()}! What is your move, senpai?'"

        if user_choice == riko_choice:
            return f"Both chose {riko_choice}! It's a draw! Great minds think alike, senpai."
        win_conditions = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if win_conditions[user_choice] == riko_choice:
            return f"Senpai chose {user_choice} and Riko chose {riko_choice}. Senpai won! Pure luck, obviously!"
        else:
            return f"Senpai chose {user_choice} and Riko chose {riko_choice}. Riko won! Hehe, bow to my supremacy, senpai!"

    # 2. Coin Flip
    if any(k in t for k in ["flip a coin", "coin flip", "heads or tails", "toss a coin"]):
        outcome = random.choice(["Heads", "Tails"])
        return f"Flipped a coin: it landed on {outcome}!"

    # 3. Dice Roll
    if any(k in t for k in ["roll a die", "roll a dice", "roll dice"]):
        roll = random.randint(1, 6)
        return f"Rolled a 6-sided die: it landed on {roll}!"

    return None


def detect_avatar_switch(text: str) -> Optional[str]:
    """Detects requests to switch the VRM model/outfit."""
    t = text.lower().strip()
    m = re.search(r"\b(change|switch|swap)\s+(?:avatar|model|outfit|character|skin)\s+(?:to\s+|into\s+)?([a-zA-Z0-9_\-\.\s]+)", t)
    if not m:
        return None
    target = m.group(2).strip()
    if not target.endswith(".vrm"):
        target = f"{target}.vrm"
    return target


VOICE_PRESETS = {
    "riko": ("5b05bc2a296046b3ac67577cb787dddc", "Riko (Energetic & Sassy)"),
    "tsundere": ("fb4598c9ac0d4c54ba75f6eb0759439d", "Tsundere Anime Girl"),
    "furina": ("bd08be872bc440918674af072944ba12", "Furina"),
    "hu tao": ("2879aac2931e450f8159d2f65cd918f4", "Hu Tao"),
    "sweet": ("d8f3b4c1199f4568a767ec54112d2b17", "Sweet Anime Girl"),
    "egirl": ("98655a12fa944e26b274c535e5e03842", "E-Girl"),
}


def detect_voice_switch(text: str, cfg: dict) -> Optional[str]:
    """Detects requests to switch Riko's voice model on the fly."""
    t = text.lower().strip()
    if not any(k in t for k in ["voice", "sound like", "speak like"]):
        return None
    if not any(w in t for w in ["change", "switch", "swap", "set", "use"]):
        return None

    matched_name = None
    for name in VOICE_PRESETS:
        if name in t:
            matched_name = name
            break

    if not matched_name:
        return None

    vid, title = VOICE_PRESETS[matched_name]
    cfg["fish"]["voice_id"] = vid

    # Update character_config.yaml in place
    try:
        from riko.config import ROOT
        cfg_file = ROOT / "character_config.yaml"
        if cfg_file.exists():
            content = cfg_file.read_text(encoding="utf-8")
            updated = re.sub(r"(\s*voice_id:\s*)[a-zA-Z0-9_\-]+", rf"\g<1>{vid}", content)
            cfg_file.write_text(updated, encoding="utf-8")
    except Exception as e:
        print(f"[tools] failed to persist voice change: {e}")

    return f"switched voice to {title}"


def detect_sentry_command(text: str, cfg: dict) -> Optional[str]:
    """Detects commands to enable or disable autonomous room security sentry mode."""
    t = text.lower().strip()
    if any(k in t for k in ["sentry mode", "security mode", "security camera", "guard my room", "watch my room"]):
        from riko import sentry
        if any(w in t for w in ["stop", "disable", "exit", "off", "cancel", "stand down"]):
            return sentry.stop_sentry()
        else:
            return sentry.start_sentry(cfg)
    return None


def detect_workout_command(text: str, cfg: dict) -> Optional[str]:
    """Detects commands to start or stop AI workout rep counter mode."""
    t = text.lower().strip()
    if any(k in t for k in ["workout mode", "workout", "count my pushups", "count pushups", "count squats", "rep counter"]):
        from riko import workout
        if any(w in t for w in ["stop", "end", "finish", "done", "cancel"]):
            return workout.stop_workout(cfg)
        else:
            exercise = "squats" if "squat" in t else ("curls" if "curl" in t else "pushups")
            return workout.start_workout(cfg, exercise=exercise)
    return None


def detect_face_command(text: str) -> Optional[str]:
    """Detects commands to enroll or remember senpai's face."""
    t = text.lower().strip()
    if any(k in t for k in ["remember my face", "learn my face", "register my face", "save my face", "memorize my face", "enroll my face"]):
        from riko import face_id
        ok, msg = face_id.enroll_face()
        return msg
    return None


def detect_voice_command(text: str, audio_input: Optional[object] = None) -> Optional[str]:
    """Detects commands to enroll or remember senpai's voice."""
    t = text.lower().strip()
    if any(k in t for k in ["remember my voice", "learn my voice", "register my voice", "save my voice", "memorize my voice", "enroll my voice"]):
        from riko import voice_id
        ok, msg = voice_id.enroll_voice(audio_input)
        return msg
    return None


def detect_alarm_command(text: str, cfg: dict) -> Optional[str]:
    """Detects commands to set wake-up alarms or timers."""
    t = text.lower().strip()
    from riko import alarms
    # Silence active alarm
    if any(k in t for k in ["stop alarm", "cancel alarm", "turn off alarm", "i'm awake", "i am awake", "silence alarm", "okay i'm up"]):
        if alarms.is_ringing():
            return alarms.stop_ringing()

    # Timer: e.g. "set a timer for 10 minutes" or "set timer for 30 seconds"
    m_timer = re.search(r"\b(?:timer|countdown)\s+(?:for\s+)?(\d+)\s*(minute|second|min|sec|hour|hr)s?\b", t)
    if m_timer:
        qty = int(m_timer.group(1))
        unit = m_timer.group(2)
        multiplier = 60 if unit in ["minute", "min"] else (3600 if unit in ["hour", "hr"] else 1)
        total_seconds = qty * multiplier
        alarms.start(cfg)
        return alarms.set_timer_seconds(total_seconds)

    # Wake-up Alarm: e.g. "set alarm for 7:30 am" or "wake me up at 8 am"
    m_alarm = re.search(r"\b(?:alarm|wake\s+me\s+up)\s+(?:for|at)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", t)
    if m_alarm:
        time_target = m_alarm.group(1)
        alarms.start(cfg)
        return alarms.set_alarm_time(time_target)

    return None


def detect_cowatch_command(text: str, cfg: dict) -> Optional[str]:
    """Detects commands to enable or disable anime/video co-watching mode."""
    t = text.lower().strip()
    if any(k in t for k in ["watch anime with me", "watch this with me", "watch youtube with me", "co-watch", "co watch", "watch video with me"]):
        from riko import cowatch
        if any(w in t for w in ["stop", "disable", "end", "off", "cancel"]):
            return cowatch.stop_cowatch()
        else:
            return cowatch.start_cowatch(cfg)
    return None


def detect_locomotion_command(text: str) -> Optional[str]:
    """Detects commands to change Riko's locomotion or movement (walk, sit, stand, dance, stretch, spin)."""
    t = text.lower().strip()
    if t.startswith("[") or "situation" in t:
        return None

    from riko import viewer

    # Hop to specific desktop / monitor number (e.g. "come on desktop 2", "desktop 1", "monitor 2")
    m_desk = re.search(r"\b(?:come\s+(?:on|to)|go\s+to|switch\s+to|hop\s+to|move\s+to)?\s*(?:desktop|screen|monitor)\s*([1-9])\b", t)
    if m_desk:
        idx = int(m_desk.group(1)) - 1
        viewer.trigger_action(f"switch_display:{idx}")
        return f"hopped over to desktop {idx + 1}"

    # Come to active screen where senpai is working
    if re.search(r"\b(come here|come to my screen|come on my screen|come where i am|come to where i am working|where i'm working|follow me|come to this screen|come to this monitor|come on desktop|come to desktop|come to my desktop)\b", t):
        viewer.trigger_action("come_to_cursor")
        return "hopped right over to the screen where senpai is currently working"

    # Switch display / other screen
    if re.search(r"\b(switch screen|other screen|second screen|switch monitor|other monitor|second monitor|move to my other screen|jump to next screen|switch display)\b", t):
        viewer.trigger_action("switch_display")
        return "hopped over to senpai's other screen"

    # Stop / Still / Stand
    if re.search(r"\b(stop moving|stop walking|stop dancing|stand up|stand|get up)\b", t):
        viewer.trigger_action("idle")
        return "stood up and returned to attentive idle stance"

    # Walk / Pace
    if re.search(r"\b(walk around|start walking|take a walk|pace around|go for a walk|start pacing|walk)\b", t):
        viewer.trigger_action("walk")
        return "started walking and pacing across senpai's desktop"

    # Sit down
    if re.search(r"\b(sit down|take a seat|sit on my taskbar|sit)\b", t):
        viewer.trigger_action("sit")
        return "sat down comfortably right above senpai's taskbar"

    # Dance
    if re.search(r"\b(dance for me|do a dance|start dancing|dance)\b", t):
        viewer.trigger_action("dance")
        return "started doing a cute anime side-step dance routine"

    # Stretch / Yawn
    if re.search(r"\b(stretch|yawn|wake up and stretch|do a stretch)\b", t):
        viewer.trigger_action("stretch")
        return "stretched both arms up high and took a refreshing deep breath"

    # Spin / Twirl
    if re.search(r"\b(do a spin|spin around|twirl|do a twirl|pirouette)\b", t):
        viewer.trigger_action("spin")
        return "did a graceful 360-degree twirl to show off her outfit"

    return None

    return None




