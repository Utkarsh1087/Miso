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
    # Remove any bracketed emotion / delta tags like [happy], [neutral], [caring, +2 care], [smug: 35]
    t = re.sub(r"\[[^\]]+\]", "", t).strip()
    # Strip forced anime filler noises that distort vocal register
    t = re.sub(r"(?i)\b(fufu+|fu-fu+|ara\s+ara)\b~*", "", t)
    # Strip emojis (Fish Audio phonetically pronounces emoji names like 'smiling face')
    t = re.sub(r"[\U00010000-\U0010ffff]", "", t)
    # Strip asterisks & markdown formatting
    t = re.sub(r"[\*\_#`]+", "", t)
    # Strip musical notes & unpronounceable symbol spam
    t = re.sub(r"[♪♫♬♩]+", " ", t)
    # Prevent multi-hyphen stutter pitch artifacts (collapse W-W-Wait -> W-Wait)
    t = re.sub(r"\b([A-Za-z])-(?:[A-Za-z]-)+", r"\1-", t)
    # Convert trailing dots that cause slow speech down to natural breath commas
    t = re.sub(r"\.{2,}", ", ", t)
    # CRITICAL: Strip tildes (~) completely so Fish Audio speaks naturally without singing pitch glides / vowel drag
    t = t.replace("~", "")
    # Collapse repetitive character spam (e.g. "......" -> "...")
    t = re.sub(r"(.)\1{3,}", r"\1\1", t)
    # Collapse repeating word spam (e.g. "la la la la la la" -> "la la")
    t = re.sub(r"(\b\w+\b)(?:\s+\1){3,}", r"\1 \1", t, flags=re.IGNORECASE)
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

    # Smooth tail pad (120ms): prevents harsh audio cutoff clicks at the end of speech
    pad_samples = int(sample_rate * 0.12)
    fade_len = min(int(sample_rate * 0.04), len(data))
    if fade_len > 0:
        fade = np.linspace(1.0, 0.0, fade_len, dtype=data.dtype)
        if data.ndim == 1:
            data[-fade_len:] *= fade
        else:
            data[-fade_len:, :] *= fade[:, None]
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
        "latency": "balanced"
    }
    if f.get("voice_id"):
        body["reference_id"] = f["voice_id"]
    
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
