"""Unified reply tag parsing and deterministic emotion/intensity visual mapping."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

DEFAULT_EMOTION: Final[str] = "neutral"
DEFAULT_INTENSITY: Final[int] = 2

# <= 12 canonical signature gestures (plus idle.vrma as the base resting loop)
SIGNATURE_GESTURES: Final[tuple[str, ...]] = (
    "shrug",
    "cross_arms",
    "facepalm",
    "head_tilt",
    "point",
    "wave",
    "nod",
    "shake_head",
    "smug",
    "sigh",
    "think",
)
SIGNATURE_GESTURE_SET: Final[frozenset[str]] = frozenset(SIGNATURE_GESTURES)

GESTURE_ALIASES: Final[dict[str, str]] = {
    "arms_crossed": "cross_arms",
    "crossed_arms": "cross_arms",
    "palms_up_shrug": "shrug",
    "shrugging": "shrug",
    "face_palm": "facepalm",
    "right_face_palm": "facepalm",
    "tilt": "head_tilt",
    "headtilt": "head_tilt",
    "surprised_head_tilt": "head_tilt",
    "pointing": "point",
    "finger_point": "point",
    "waving": "wave",
    "wave_hello": "wave",
    "nodding": "nod",
    "double_nod": "nod",
    "head_shake": "shake_head",
    "shake": "shake_head",
    "smug_heh": "smug",
    "sighing": "sigh",
    "deflated_sigh": "sigh",
    "thinking": "think",
    "thinking_chin_rest": "think",
}

SUPPORTED_EMOTIONS: Final[tuple[str, ...]] = (
    "neutral",
    "happy",
    "angry",
    "sad",
    "surprised",
    "relaxed",
    "flustered",
    "annoyed",
    "jealous",
    "smug",
    "caring",
)
SUPPORTED_EMOTION_SET: Final[frozenset[str]] = frozenset(SUPPORTED_EMOTIONS)

EMOTION_ALIASES: Final[dict[str, str]] = {
    "joy": "happy",
    "excited": "happy",
    "cheerful": "happy",
    "anger": "angry",
    "mad": "angry",
    "furious": "angry",
    "sadness": "sad",
    "gloom": "sad",
    "disappointed": "sad",
    "shocked": "surprised",
    "alarm": "surprised",
    "calm": "relaxed",
    "content": "relaxed",
    "embarrassed": "flustered",
    "embarrassment": "flustered",
    "shy": "flustered",
    "blush": "flustered",
    "annoyance": "annoyed",
    "irritated": "annoyed",
    "nervous": "annoyed",
    "envy": "jealous",
    "confident": "smug",
    "teasing": "smug",
    "love": "caring",
    "affection": "caring",
    "warm": "caring",
}

# Deterministic (emotion, intensity 1..3) -> VRM expression blendshapes
_BLENDSHAPE_TABLE: Final[dict[str, dict[int, dict[str, float]]]] = {
    "neutral": {
        1: {"neutral": 1.0},
        2: {"neutral": 1.0},
        3: {"neutral": 1.0},
    },
    "happy": {
        1: {"happy": 0.45},
        2: {"happy": 0.75},
        3: {"happy": 1.0},
    },
    "angry": {
        1: {"angry": 0.45},
        2: {"angry": 0.75},
        3: {"angry": 1.0},
    },
    "sad": {
        1: {"sad": 0.35},
        2: {"sad": 0.60},
        3: {"sad": 0.85},
    },
    "surprised": {
        1: {"surprised": 0.40},
        2: {"surprised": 0.70},
        3: {"surprised": 1.0},
    },
    "relaxed": {
        1: {"relaxed": 0.35},
        2: {"relaxed": 0.65},
        3: {"relaxed": 0.95},
    },
    "flustered": {
        1: {"happy": 0.30, "surprised": 0.20},
        2: {"happy": 0.50, "surprised": 0.35},
        3: {"happy": 0.70, "surprised": 0.50},
    },
    "annoyed": {
        1: {"angry": 0.25, "sad": 0.15},
        2: {"angry": 0.45, "sad": 0.25},
        3: {"angry": 0.65, "sad": 0.35},
    },
    "jealous": {
        1: {"angry": 0.35, "sad": 0.20},
        2: {"angry": 0.60, "sad": 0.35},
        3: {"angry": 0.85, "sad": 0.50},
    },
    "smug": {
        1: {"relaxed": 0.40, "happy": 0.20},
        2: {"relaxed": 0.65, "happy": 0.35},
        3: {"relaxed": 0.90, "happy": 0.50},
    },
    "caring": {
        1: {"relaxed": 0.35, "happy": 0.25},
        2: {"relaxed": 0.60, "happy": 0.45},
        3: {"relaxed": 0.85, "happy": 0.65},
    },
}

# Deterministic emotion -> anime VFX id (None when no overlay is desired)
EMOTION_VFX_MAP: Final[dict[str, str | None]] = {
    "neutral": None,
    "relaxed": None,
    "angry": "anger_vein",
    "flustered": "blush_lines",
    "happy": "sparkles",
    "annoyed": "sweatdrop",
    "sad": "gloom_lines",
    "surprised": "shock_marks",
    "caring": "heart_pop",
    "smug": "kira_star",
    "jealous": "annoyed_scribble",
}

_VFX_SCALE_BY_INTENSITY: Final[dict[int, float]] = {1: 0.75, 2: 1.0, 3: 1.25}
_VFX_OPACITY_BY_INTENSITY: Final[dict[int, float]] = {1: 0.65, 2: 0.85, 3: 1.0}

_LEADING_TAG_RE = re.compile(r"^\s*\[([^\]]+)\]")
_UNCLOSED_LEADING_TAG_RE = re.compile(r"^\s*\[[^\]]*$")
_EMOTION_TOKEN_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9_\s-]*?)(?:\s*:\s*([+-]?\d+))?$")
_DELTA_RE = re.compile(r"([+-]?\d+)")


@dataclass(frozen=True, slots=True)
class ParsedReply:
    emotion: str
    intensity: int
    gesture: str | None
    affection_delta: int
    clean_text: str
    vfx: str | None
    raw_emotion_tag: str = ""


def clamp_intensity(value: object, default: int = DEFAULT_INTENSITY) -> int:
    """Parse intensity and clamp deterministically to 1..3."""
    if isinstance(value, bool) or value is None:
        return max(1, min(3, int(default)))
    if isinstance(value, (int, float)):
        return max(1, min(3, int(value)))
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"[+-]?\d+", stripped):
            return max(1, min(3, int(stripped)))
    return max(1, min(3, int(default)))


def _canonical_token(value: str) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().lower())


def normalize_emotion(value: str | None, default: str = DEFAULT_EMOTION) -> str:
    """Normalize emotion string against SUPPORTED_EMOTIONS and EMOTION_ALIASES."""
    fallback = default if default in SUPPORTED_EMOTION_SET else DEFAULT_EMOTION
    if not value or not isinstance(value, str):
        return fallback
    key = _canonical_token(value)
    if key in SUPPORTED_EMOTION_SET:
        return key
    if key in EMOTION_ALIASES:
        return EMOTION_ALIASES[key]
    return fallback


def _is_known_emotion_token(value: str) -> bool:
    key = _canonical_token(value)
    return key in SUPPORTED_EMOTION_SET or key in EMOTION_ALIASES


def normalize_gesture(value: str | None) -> str | None:
    """Normalize gesture string against SIGNATURE_GESTURES and GESTURE_ALIASES."""
    if not value or not isinstance(value, str):
        return None
    key = _canonical_token(value)
    if key in SIGNATURE_GESTURE_SET:
        return key
    return GESTURE_ALIASES.get(key)


def emotion_to_visual_state(emotion: str, intensity: int = DEFAULT_INTENSITY) -> dict:
    """Return deterministic blendshape weights and anime VFX spec for (emotion, intensity)."""
    emo = normalize_emotion(emotion, default=DEFAULT_EMOTION)
    lvl = clamp_intensity(intensity, default=1 if emo == "neutral" else DEFAULT_INTENSITY)
    blendshapes = dict(_BLENDSHAPE_TABLE[emo][lvl])
    vfx = EMOTION_VFX_MAP[emo]
    if vfx is None:
        vfx_scale = 0.0
        vfx_opacity = 0.0
    else:
        vfx_scale = _VFX_SCALE_BY_INTENSITY[lvl]
        vfx_opacity = _VFX_OPACITY_BY_INTENSITY[lvl]
    return {
        "emotion": emo,
        "intensity": lvl,
        "blendshapes": blendshapes,
        "vfx": vfx,
        "vfx_scale": vfx_scale,
        "vfx_opacity": vfx_opacity,
    }


def parse_reply_tags(
    raw_text: str | None,
    *,
    default_emotion: str = DEFAULT_EMOTION,
    default_intensity: int | None = None,
) -> ParsedReply:
    """Parse leading [emotion:intensity][gesture] tags and strip them from spoken/display text."""
    norm_default_emo = normalize_emotion(default_emotion, default=DEFAULT_EMOTION)
    if not raw_text or not isinstance(raw_text, str):
        init_intensity = clamp_intensity(
            default_intensity if default_intensity is not None else (1 if norm_default_emo == "neutral" else DEFAULT_INTENSITY)
        )
        visual = emotion_to_visual_state(norm_default_emo, init_intensity)
        return ParsedReply(
            emotion=visual["emotion"],
            intensity=visual["intensity"],
            gesture=None,
            affection_delta=0,
            clean_text="",
            vfx=visual["vfx"],
            raw_emotion_tag="",
        )

    rest = raw_text
    emotion = norm_default_emo
    intensity: int | None = None
    gesture: str | None = None
    affection_delta = 0
    raw_emotion_tag = ""
    saw_emotion = False

    while True:
        match = _LEADING_TAG_RE.match(rest)
        if not match:
            break
        block = match.group(1).strip()
        rest = rest[match.end():]

        if not block:
            continue

        parts = [p.strip() for p in block.split(",") if p.strip()]
        if not parts:
            continue

        head = parts[0]
        has_delta_parts = len(parts) > 1
        emo_match = _EMOTION_TOKEN_RE.match(head)

        if emo_match:
            head_name = emo_match.group(1).strip()
            raw_lvl = emo_match.group(2)
            has_colon = raw_lvl is not None
            is_emo = _is_known_emotion_token(head_name)
            gest_candidate = normalize_gesture(head_name)

            # Treat as gesture when:
            # - it has no `:intensity` and no `, +delta` AND either:
            #   (a) it is a gesture and NOT an emotion (e.g. [cross_arms], [shrug]), OR
            #   (b) we already parsed an emotion tag (handles [relaxed:2][smug]).
            if not has_colon and not has_delta_parts and gest_candidate is not None and (not is_emo or saw_emotion):
                if gesture is None:
                    gesture = gest_candidate
                continue

            if is_emo and not saw_emotion:
                emotion = normalize_emotion(head_name, default=norm_default_emo)
                intensity = clamp_intensity(raw_lvl, default=DEFAULT_INTENSITY) if has_colon else DEFAULT_INTENSITY
                saw_emotion = True
                raw_emotion_tag = block
                for extra in parts[1:]:
                    dm = _DELTA_RE.search(extra)
                    if dm:
                        affection_delta = int(dm.group(1))
                        break
                continue

            # If a second emotion-like tag appears (unlikely) or unknown tag, ignore cleanly
            if gest_candidate is not None and not has_colon and gesture is None:
                gesture = gest_candidate
                continue
        else:
            gest_candidate = normalize_gesture(head)
            if gest_candidate is not None and gesture is None:
                gesture = gest_candidate

    # Handle truncated unclosed leading bracket like "[angry:2"
    if _UNCLOSED_LEADING_TAG_RE.match(rest):
        rest = ""

    clean_text = rest.lstrip()
    if not saw_emotion:
        if default_intensity is not None:
            resolved_intensity = clamp_intensity(default_intensity)
        else:
            resolved_intensity = 1 if emotion == "neutral" else DEFAULT_INTENSITY
    else:
        resolved_intensity = intensity if intensity is not None else DEFAULT_INTENSITY

    visual = emotion_to_visual_state(emotion, resolved_intensity)
    return ParsedReply(
        emotion=visual["emotion"],
        intensity=visual["intensity"],
        gesture=gesture,
        affection_delta=affection_delta,
        clean_text=clean_text,
        vfx=visual["vfx"],
        raw_emotion_tag=raw_emotion_tag,
    )


def strip_reply_tags(raw_text: str | None) -> str:
    """Strip leading [emotion:intensity][gesture] tags from raw LLM text."""
    return parse_reply_tags(raw_text).clean_text
