"""Her body: web server for the 3D avatar page with streaming audio, barge-in, and avatar swapping."""
import json
import queue
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import sounddevice as sd
import soundfile as sf

from riko import tags, tts
from riko.config import ROOT

HOST, PORT = "127.0.0.1", 8080

_clips = queue.Queue()          # voice clips waiting for the page
_finished = threading.Event()   # set when the page says a clip ended
_page_last_seen = float("-inf") # when the page last polled
_avatar = None                  # active .vrm file
_active_avatar_name = "sample_avatar.vrm"
_is_speaking = False            # True while Riko is outputting speech audio


def is_playing() -> bool:
    """Returns True if Riko is currently outputting speech through speakers."""
    return _is_speaking


class _Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".vrm": "application/octet-stream",
        ".vrma": "application/octet-stream",
    }

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        global _page_last_seen, _avatar
        if self.path == "/avatar.vrm":
            if _avatar and _avatar.exists():
                return self._send(_avatar.read_bytes(), "application/octet-stream")
        if self.path == "/avatars":
            avatars_dir = ROOT / "character_files" / "avatars"
            avatars_dir.mkdir(parents=True, exist_ok=True)
            vrms = [f.name for f in avatars_dir.glob("*.vrm")]
            if (ROOT / "character_files" / "sample_avatar.vrm").exists() and "sample_avatar.vrm" not in vrms:
                vrms.insert(0, "sample_avatar.vrm")
            return self._send(json.dumps({"avatars": vrms, "current": _active_avatar_name}).encode(), "application/json")
        if self.path.startswith("/avatar_model/"):
            name = self.path[len("/avatar_model/"):]
            p = ROOT / "character_files" / "avatars" / name
            if not p.exists():
                p = ROOT / "character_files" / name
            if p.exists():
                return self._send(p.read_bytes(), "application/octet-stream")
        if self.path != "/next":
            return super().do_GET()

        _page_last_seen = time.monotonic()
        try:
            item = _clips.get_nowait()
        except queue.Empty:
            item = {"audio": None, "emotion": "neutral", "intensity": 1, "gesture": None, "vfx": None, "text": ""}
        self._send(json.dumps(item).encode(), "application/json")

    def do_POST(self):
        global _is_speaking
        if self.path == "/done":
            _is_speaking = False
            _finished.set()
            return self._send(b"{}", "application/json")
        elif self.path == "/interrupted":
            _is_speaking = False
            _finished.set()
            return self._send(b"{}", "application/json")
        elif self.path in ["/api/chat", "/api/ask"]:
            try:
                length = int(self.headers.get("content-length", 0))
                raw_data = self.rfile.read(length) if length > 0 else b"{}"
                req_json = json.loads(raw_data.decode("utf-8"))
                user_msg = req_json.get("text", "")
                if user_msg:
                    from riko import llm, config
                    cfg = config.load_config()
                    raw_reply = llm.reply(user_msg, cfg)
                    parsed = tags.parse_reply_tags(raw_reply)
                    return self._send(json.dumps({
                        "reply": parsed.clean_text,
                        "raw": raw_reply,
                        "emotion": parsed.emotion,
                        "intensity": parsed.intensity,
                        "gesture": parsed.gesture,
                        "vfx": parsed.vfx,
                    }).encode(), "application/json")
            except Exception as e:
                return self._send(json.dumps({"error": str(e)}).encode(), "application/json")
        self._send(b"{}", "application/json")

    def _send(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start(cfg):
    global _avatar, _active_avatar_name
    _avatar = ROOT / cfg["vrm_model"]
    _active_avatar_name = _avatar.name
    if not _avatar.exists():
        sys.exit(f"[setup] Avatar not found: {_avatar}. Check vrm_model in character_config.yaml.")
    try:
        server = ThreadingHTTPServer((HOST, PORT), partial(_Handler, directory=str(ROOT / "client")))
    except OSError:
        sys.exit(f"[setup] Port {PORT} is busy (is Riko already running?). Close it or change PORT in riko/viewer.py.")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[viewer] avatar: {cfg['vrm_model']}")
    print(f"[viewer] avatar page: http://{HOST}:{PORT}")


def stop_speech():
    """Barge-In: Instantly stops current speech playback on the avatar."""
    global _is_speaking
    _is_speaking = False
    while not _clips.empty():
        try:
            _clips.get_nowait()
        except queue.Empty:
            break
    _finished.set()
    _clips.put({"audio": None, "command": "stop"})


def switch_avatar(avatar_name: str) -> bool:
    """Switches the active VRM avatar dynamically."""
    global _avatar, _active_avatar_name
    p = ROOT / "character_files" / "avatars" / avatar_name
    if not p.exists():
        p = ROOT / "character_files" / avatar_name
    if not p.exists():
        return False
    _avatar = p
    _active_avatar_name = avatar_name
    _clips.put({"command": "switch_avatar", "avatar": avatar_name})
    print(f"[viewer] Switched active avatar to: {avatar_name}")
    return True


def trigger_action(action_name: str):
    """Triggers procedural locomotion or expressive movement (walk, dance, sit, stretch, idle, spin)."""
    _clips.put({"command": "action", "action": action_name})
    print(f"[viewer] Triggered avatar action: {action_name}")


def play(wav_path, emotion="neutral", intensity=None, gesture=None, text="", vfx=None):
    """Play voice on the avatar page or speakers."""
    global _is_speaking
    norm_emo = tags.normalize_emotion(emotion)
    resolved_intensity = tags.clamp_intensity(
        intensity if intensity is not None else (1 if norm_emo == "neutral" else tags.DEFAULT_INTENSITY)
    )
    visual = tags.emotion_to_visual_state(norm_emo, resolved_intensity)
    resolved_emotion = visual["emotion"]
    resolved_gesture = tags.normalize_gesture(gesture)
    resolved_vfx = vfx if vfx is not None else visual["vfx"]

    duration = sf.info(wav_path).duration
    _is_speaking = True
    try:
        if time.monotonic() - _page_last_seen < 5:
            _finished.clear()
            _clips.put({
                "audio": f"audio/{wav_path.name}?v={time.time()}",
                "emotion": resolved_emotion,
                "intensity": resolved_intensity,
                "gesture": resolved_gesture,
                "vfx": resolved_vfx,
                "text": text or "",
            })
            if not _finished.wait(timeout=duration + 1.2):
                print(f"[viewer] playback finished (auto-synced)")
        else:
            print("[viewer] no avatar page open, playing on speakers (open http://127.0.0.1:8080 and click once)")
            data, sample_rate = sf.read(wav_path)
            sd.play(data, sample_rate)
            sd.wait()
    finally:
        _is_speaking = False


def play_streaming_sentences(sentences, cfg=None, emotion="neutral", intensity=None, gesture=None, vfx=None):
    """Low-latency streaming: synthesizes and queues sentences as they arrive."""
    global _is_speaking
    _is_speaking = True
    total_dur = 0.0
    try:
        _finished.clear()
        idx = 0
        for item in sentences:
            if not _is_speaking:
                # Interrupted / barge-in
                break
            if isinstance(item, dict):
                s_text = item.get("text", "")
                s_emo = item.get("emotion", emotion)
                s_int = item.get("intensity", intensity)
                s_ges = item.get("gesture", gesture)
                s_vfx = item.get("vfx", vfx)
            elif hasattr(item, "text"):
                s_text = getattr(item, "text", "")
                s_emo = getattr(item, "emotion", emotion)
                s_int = getattr(item, "intensity", intensity)
                s_ges = getattr(item, "gesture", gesture)
                s_vfx = getattr(item, "vfx", vfx)
            else:
                s_text = str(item)
                s_emo = emotion
                s_int = intensity
                s_ges = gesture
                s_vfx = vfx

            if not s_text or not s_text.strip():
                continue

            norm_emo = tags.normalize_emotion(s_emo)
            resolved_intensity = tags.clamp_intensity(
                s_int if s_int is not None else (1 if norm_emo == "neutral" else tags.DEFAULT_INTENSITY)
            )
            visual = tags.emotion_to_visual_state(norm_emo, resolved_intensity)
            resolved_emotion = visual["emotion"]
            resolved_gesture = tags.normalize_gesture(s_ges) if idx == 0 else None
            resolved_vfx = s_vfx if s_vfx is not None else visual["vfx"]

            fname = f"stream_{int(time.time() * 1000) % 100000}_{idx}.wav"
            p = tts.speak(s_text, cfg, filename=fname)
            dur = sf.info(p).duration
            total_dur += dur

            if not _is_speaking:
                break

            if time.monotonic() - _page_last_seen < 5:
                _clips.put({
                    "audio": f"audio/{fname}?v={time.time()}",
                    "emotion": resolved_emotion,
                    "intensity": resolved_intensity,
                    "gesture": resolved_gesture,
                    "vfx": resolved_vfx,
                    "text": s_text,
                })
            else:
                data, sr = sf.read(p)
                sd.play(data, sr)
                sd.wait()
            idx += 1

        # Wait until the web client finishes playing all queued sentences
        if time.monotonic() - _page_last_seen < 5 and total_dur > 0 and _is_speaking:
            if not _finished.wait(timeout=total_dur + 5.0):
                print("[viewer] multi-sentence streaming playback finished (auto-synced)")
    finally:
        _is_speaking = False


def play_sentences(sentences, emotion="neutral", cfg=None, intensity=None, gesture=None, vfx=None):
    """Low-latency streaming: synthesizes and queues sentences one after another."""
    global _is_speaking
    if not sentences:
        return
    norm_emo = tags.normalize_emotion(emotion)
    resolved_intensity = tags.clamp_intensity(
        intensity if intensity is not None else (1 if norm_emo == "neutral" else tags.DEFAULT_INTENSITY)
    )
    visual = tags.emotion_to_visual_state(norm_emo, resolved_intensity)
    resolved_emotion = visual["emotion"]
    resolved_gesture = tags.normalize_gesture(gesture)
    resolved_vfx = vfx if vfx is not None else visual["vfx"]

    _is_speaking = True
    total_dur = 0.0
    try:
        _finished.clear()
        for idx, s in enumerate(sentences):
            try:
                fname = f"chunk_{int(time.time() * 1000) % 100000}_{idx}.wav"
                p = tts.speak(s, cfg, filename=fname)
                dur = sf.info(p).duration
                total_dur += dur
                if time.monotonic() - _page_last_seen < 5:
                    _clips.put({
                        "audio": f"audio/{fname}?v={time.time()}",
                        "emotion": resolved_emotion,
                        "intensity": resolved_intensity,
                        "gesture": resolved_gesture if idx == 0 else None,
                        "vfx": resolved_vfx,
                        "text": s,
                    })
                else:
                    data, sr = sf.read(p)
                    sd.play(data, sr)
                    sd.wait()
            except Exception as e:
                print(f"[viewer] streaming chunk note: {e}")

        # Wait until the web client finishes playing all queued sentences
        if time.monotonic() - _page_last_seen < 5 and total_dur > 0:
            if not _finished.wait(timeout=total_dur + 2.5):
                print("[viewer] multi-sentence playback finished (auto-synced)")
    finally:
        _is_speaking = False
