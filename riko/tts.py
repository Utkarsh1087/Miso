"""Her voice: turn her reply into WAV files with ultra-low latency."""
import io
import os
import re
import sys

import requests
import numpy as np
import soundfile as sf

from riko.config import ROOT, need_key

VOICE_DIR = ROOT / "client" / "audio"
VOICE_FILE = VOICE_DIR / "riko.wav"


class SentenceSegmenter:
    """Incremental streaming sentence segmenter for TTS."""

    def __init__(self):
        self.buffer = ""

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        self.buffer += chunk
        return self._extract(flush=False)

    def push(self, chunk: str) -> list[str]:
        return self.feed(chunk)

    def flush(self) -> list[str]:
        return self._extract(flush=True)

    def finish(self) -> list[str]:
        return self.flush()

    def _extract(self, flush: bool = False) -> list[str]:
        emitted = []
        buf = self.buffer
        i = 0
        last_start = 0
        bracket_depth = 0

        # Abbreviations: Mr. Mrs. Ms. Dr. Prof. Sr. Jr. vs. etc. e.g. i.e. v1. $3. Item 1.
        ABBR_RE = re.compile(r"(?i)\b(mr|mrs|ms|dr|prof|sr|jr|vs|etc|e\.g|i\.e|v\d+|\$\d+)\.$")
        DIGIT_DOT_RE = re.compile(r"(?:^|\s)(?:item\s+)?\d+\.$", re.IGNORECASE)

        while i < len(buf):
            ch = buf[i]
            if ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth = max(0, bracket_depth - 1)

            if bracket_depth == 0:
                is_end = False
                end_pos = i + 1

                if ch in ("。", "！", "？", "।"):
                    if i + 1 == len(buf):
                        if flush:
                            is_end = True
                    else:
                        is_end = True
                elif ch in (".", "!", "?"):
                    while end_pos < len(buf) and buf[end_pos] in (".", "!", "?"):
                        end_pos += 1

                    if end_pos < len(buf):
                        if buf[end_pos] in (" ", "\t", "\n", "\r"):
                            candidate = buf[last_start:end_pos].strip()
                            if not ABBR_RE.search(candidate) and not DIGIT_DOT_RE.search(candidate):
                                is_end = True
                    elif flush:
                        is_end = True
                elif ch == "\n":
                    is_end = True

                if is_end:
                    s = buf[last_start:end_pos].strip()
                    if s:
                        emitted.append(s)
                    i = end_pos
                    while i < len(buf) and buf[i] in (" ", "\t", "\n", "\r"):
                        i += 1
                    last_start = i
                    continue

            i += 1

        if flush:
            rem = buf[last_start:].strip()
            if rem:
                emitted.append(rem)
            self.buffer = ""
        else:
            self.buffer = buf[last_start:]

        return emitted


def check(cfg):
    if cfg["tts"] == "fish":
        need_key("FISH_API_KEY", "tts: fish")
        return
    ref_audio = ROOT / cfg["sovits"]["ref_audio_path"]
    if not ref_audio.exists():
        sys.exit(f"[setup] Voice sample not found: {ref_audio}")
    try:
        requests.head(cfg["sovits"]["url"], timeout=3)
    except requests.ConnectionError:
        sys.exit(f"[setup] GPT-SoVITS is not running at {cfg['sovits']['url']}. "
                 "Start its API first (python api_v2.py in your GPT-SoVITS folder), or use --tts fish.")
    print(f"[setup] GPT-SoVITS is running at {cfg['sovits']['url']}")


def clean_for_speech(text: str) -> str:
    """Sanitizes LLM output for TTS by stripping symbol spam, emojis, tildes, and awkward phonemes."""
    # Normalize unicode quotes, dashes, and ellipses that cause mojibake and pronunciation glitches
    t = text.replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("—", ", ").replace("–", ", ").replace("…", "...")
    # Normalize semicolons and colons to periods for clean spoken pacing without pitch inflection
    t = t.replace(";", ". ").replace(":", ". ")
    # Remove any bracketed emotion / delta tags like [happy], [neutral], [caring, +2 care], [smug: 35]
    t = re.sub(r"\[[^\]]+\]", "", t).strip()
    # Strip forced anime filler noises that distort vocal register
    t = re.sub(r"(?i)\b(fufu+|fu-fu+|ara\s+ara)\b~*", "", t)
    # Strip emojis (Fish Audio phonetically pronounces emoji names like 'smiling face' or 'sparkles')
    t = re.sub(r"[\u2600-\u27BF\U00010000-\U0010FFFF]", "", t)
    # Strip asterisks & markdown formatting
    t = re.sub(r"[\*\_#`]+", "", t)
    # Strip musical notes & unpronounceable symbol spam
    t = re.sub(r"[♪♫♬♩]+", " ", t)
    # Prevent multi-hyphen stutter pitch artifacts (collapse W-W-Wait -> W-Wait)
    t = re.sub(r"\b([A-Za-z])-(?:[A-Za-z]-)+", r"\1-", t)
    # Convert trailing dots that cause slow speech down to natural breath commas
    t = re.sub(r"\.{2,}", ", ", t)
    # CRITICAL: Strip ALL tildes (~, ～, 〜) so Fish Audio speaks naturally without singing pitch glides / vowel drag
    t = re.sub(r"[~～〜]+", "", t)
    # Prevent dragged out vowels that induce melodic singing (e.g. soooo -> so, pleaaase -> please)
    t = re.sub(r"([a-zA-Z])\1{2,}", r"\1", t)
    # Collapse repetitive character spam (e.g. "......" -> "...")
    t = re.sub(r"(.)\1{3,}", r"\1\1", t)
    # Collapse repeating word spam (e.g. "la la la la la la" -> "la la")
    t = re.sub(r"(\b\w+\b)(?:\s+\1){3,}", r"\1 \1", t, flags=re.IGNORECASE)
    # Deduplicate repetitive 'senpai' tokens (allow at most one per utterance)
    t = re.sub(r"(?i)\bsenpai\b[,\s]*(?=.*\bsenpai\b)", "", t)
    t = re.sub(r"^[,\s]+", "", t)
    t = re.sub(r",\s*,+", ",", t)
    t = re.sub(r",\s*([.!?])", r"\1", t)
    # Strip any dangling commas, colons, or dashes at the end that leave TTS hanging in mid-sentence
    t = re.sub(r"[,;:\s\-]+$", "", t).strip()
    if t and t[-1] not in ".!?":
        t += "."
    t = re.sub(r"\s+", " ", t).strip()
    # Length guard: prevents runaway TTS requests (>280 chars)
    if len(t) > 280:
        cut = t[:280]
        m = re.search(r"[.!?][^.!?]*$", cut)
        t = cut[:m.end()].strip() if m else cut.strip() + "..."
    return t or "..."


def split_into_sentences(text: str) -> list[str]:
    """Splits full response text into speakable sentence chunks for low-latency streaming."""
    clean = clean_for_speech(text)
    # Split on sentence boundaries: periods, exclamation marks, question marks, newlines
    raw_sentences = re.split(r"(?<=[.!?।\n])\s+", clean)
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    return sentences or [clean]


def speak(text, cfg, filename="riko.wav"):
    """Make her say `text`. Returns the path of the generated WAV file."""
    clean_text = clean_for_speech(text)
    audio = _fish(clean_text, cfg["fish"]) if cfg["tts"] == "fish" else _sovits(clean_text, cfg["sovits"])
    data, sample_rate = sf.read(io.BytesIO(audio))

    # Smooth tail pad (350ms): ensures the final word, consonant release, and natural room decay resonate cleanly
    pad_samples = int(sample_rate * 0.35)
    # Micro anti-pop ramp (3ms) at very start of audio only
    lead_fade = min(int(sample_rate * 0.003), len(data))
    if lead_fade > 0:
        fade_in = np.linspace(0.0, 1.0, lead_fade, dtype=data.dtype)
        if data.ndim == 1:
            data[:lead_fade] *= fade_in
        else:
            data[:lead_fade, :] *= fade_in[:, None]
    silence = np.zeros((pad_samples,) if data.ndim == 1 else (pad_samples, data.shape[1]), dtype=data.dtype)
    data = np.concatenate([data, silence])

    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    target_path = VOICE_DIR / filename
    sf.write(target_path, data, sample_rate)
    duration = len(data) / sample_rate
    print(f"[tts] {cfg['tts']}: {duration:.1f}s of audio ({filename})")
    return target_path


def _sovits(text, s):
    response = requests.post(s["url"], json={
        "text": text,
        "text_lang": s["text_lang"],
        "ref_audio_path": str(ROOT / s["ref_audio_path"]),
        "prompt_text": s["prompt_text"],
        "prompt_lang": s["prompt_lang"],
    }, timeout=120)
    response.raise_for_status()
    return response.content


def _fish(text, f):
    body = {
        "text": text,
        "format": "wav",
        "latency": "balanced",
        "temperature": float(f.get("temperature", 0.2)),
        "top_p": float(f.get("top_p", 0.7)),
        "repetition_penalty": float(f.get("repetition_penalty", 1.2)),
        "normalize": bool(f.get("normalize", True))
    }
    if f.get("voice_id"):
        body["reference_id"] = f["voice_id"]
    
    speed = float(f.get("speed", 1.0))
    body["prosody"] = {"speed": speed}
    
    headers = {
        "Authorization": f"Bearer {os.getenv('FISH_API_KEY')}",
        "model": f.get("model", "s2.1-pro")
    }
    response = requests.post(
        "https://api.fish.audio/v1/tts",
        headers=headers,
        json=body,
        timeout=120,
    )
    response.raise_for_status()
    return response.content


if __name__ == "__main__":
    from riko.config import load_config
    cfg = load_config()
    if "--fish" in sys.argv:
        cfg["tts"] = "fish"
    check(cfg)
    print("Wrote", speak("If you can hear this, my voice is set up correctly.", cfg))
