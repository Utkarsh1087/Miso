"""Generate VRMC_vrm_animation 1.0 (.vrma) GLB binaries from animaPoseClip/2.0 pose specs.

Produces rooted skeletal rotation tracks at 30 Hz (excluding leftEye, rightEye,
jaw, expressions, and hips.translation animation tracks so runtime lookAt,
lip-sync, blink, blendshapes, and taskbar grounding remain intact).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_PATH = Path(__file__).resolve().parent / "vrma_pose_data.json"
DEFAULT_OUT_DIR = ROOT / "client" / "animations" / "vrma"

FPS = 30
GLB_MAGIC = b"glTF"
GLB_VERSION = 2
GLB_JSON_CHUNK_TYPE = 0x4E4F534A
GLB_BIN_CHUNK_TYPE = 0x004E4942

# Humanoid bone parent hierarchy (omits leftEye, rightEye, jaw so lookAt & jaw stay free)
HUMANOID_PARENTS: dict[str, str | None] = {
    "hips": None,
    "spine": "hips",
    "chest": "spine",
    "upperChest": "chest",
    "neck": "upperChest",
    "head": "neck",
    "leftUpperLeg": "hips",
    "leftLowerLeg": "leftUpperLeg",
    "leftFoot": "leftLowerLeg",
    "leftToes": "leftFoot",
    "rightUpperLeg": "hips",
    "rightLowerLeg": "rightUpperLeg",
    "rightFoot": "rightLowerLeg",
    "rightToes": "rightFoot",
    "leftShoulder": "upperChest",
    "leftUpperArm": "leftShoulder",
    "leftLowerArm": "leftUpperArm",
    "leftHand": "leftLowerArm",
    "rightShoulder": "upperChest",
    "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm",
    "rightHand": "rightLowerArm",
    "leftThumbMetacarpal": "leftHand",
    "leftThumbProximal": "leftThumbMetacarpal",
    "leftThumbDistal": "leftThumbProximal",
    "leftIndexProximal": "leftHand",
    "leftIndexIntermediate": "leftIndexProximal",
    "leftIndexDistal": "leftIndexIntermediate",
    "leftMiddleProximal": "leftHand",
    "leftMiddleIntermediate": "leftMiddleProximal",
    "leftMiddleDistal": "leftMiddleIntermediate",
    "leftRingProximal": "leftHand",
    "leftRingIntermediate": "leftRingProximal",
    "leftRingDistal": "leftRingIntermediate",
    "leftLittleProximal": "leftHand",
    "leftLittleIntermediate": "leftLittleProximal",
    "leftLittleDistal": "leftLittleIntermediate",
    "rightThumbMetacarpal": "rightHand",
    "rightThumbProximal": "rightThumbMetacarpal",
    "rightThumbDistal": "rightThumbProximal",
    "rightIndexProximal": "rightHand",
    "rightIndexIntermediate": "rightIndexProximal",
    "rightIndexDistal": "rightIndexIntermediate",
    "rightMiddleProximal": "rightHand",
    "rightMiddleIntermediate": "rightMiddleProximal",
    "rightMiddleDistal": "rightMiddleIntermediate",
    "rightRingProximal": "rightHand",
    "rightRingIntermediate": "rightRingProximal",
    "rightRingDistal": "rightRingIntermediate",
    "rightLittleProximal": "rightHand",
    "rightLittleIntermediate": "rightLittleProximal",
    "rightLittleDistal": "rightLittleIntermediate",
}
HUMANOID_ORDER: list[str] = list(HUMANOID_PARENTS.keys())

# ── Quaternion & Euler Math (Three.js compatible) ─────────────────────────

Quat = tuple[float, float, float, float]


def quat_normalize(q: Quat) -> Quat:
    x, y, z, w = q
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    inv = 1.0 / length
    return (x * inv, y * inv, z * inv, w * inv)


def quat_mul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_from_axis_angle(axis: tuple[float, float, float], angle_rad: float) -> Quat:
    ax, ay, az = axis
    norm = math.sqrt(ax * ax + ay * ay + az * az)
    if norm <= 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    half = angle_rad * 0.5
    s = math.sin(half) / norm
    return quat_normalize((ax * s, ay * s, az * s, math.cos(half)))


def quat_slerp(a: Quat, b: Quat, t: float) -> Quat:
    ax, ay, az, aw = quat_normalize(a)
    bx, by, bz, bw = quat_normalize(b)
    if t <= 0.0:
        return (ax, ay, az, aw)
    if t >= 1.0:
        return (bx, by, bz, bw)
    cos_half = ax * bx + ay * by + az * bz + aw * bw
    if cos_half < 0.0:
        bx, by, bz, bw = -bx, -by, -bz, -bw
        cos_half = -cos_half
    if cos_half >= 1.0 - 1e-7:
        return quat_normalize((
            ax + (bx - ax) * t,
            ay + (by - ay) * t,
            az + (bz - az) * t,
            aw + (bw - aw) * t,
        ))
    sqr_sin = max(0.0, 1.0 - cos_half * cos_half)
    sin_half = math.sqrt(sqr_sin)
    half_theta = math.atan2(sin_half, cos_half)
    ratio_a = math.sin((1.0 - t) * half_theta) / sin_half
    ratio_b = math.sin(t * half_theta) / sin_half
    return quat_normalize((
        ax * ratio_a + bx * ratio_b,
        ay * ratio_a + by * ratio_b,
        az * ratio_a + bz * ratio_b,
        aw * ratio_a + bw * ratio_b,
    ))


def euler_to_quat(rx: float, ry: float, rz: float, order: str) -> Quat:
    """Intrinsic Tait-Bryan Euler to Quaternion matching Three.js Euler orders."""
    q_axis = {
        "X": (math.sin(rx * 0.5), 0.0, 0.0, math.cos(rx * 0.5)),
        "Y": (0.0, math.sin(ry * 0.5), 0.0, math.cos(ry * 0.5)),
        "Z": (0.0, 0.0, math.sin(rz * 0.5), math.cos(rz * 0.5)),
    }
    q = q_axis[order[0]]
    q = quat_mul(q, q_axis[order[1]])
    q = quat_mul(q, q_axis[order[2]])
    return quat_normalize(q)


def quat_to_euler(q: Quat, order: str) -> tuple[float, float, float]:
    """Quaternion to intrinsic Euler matching Three.js Euler.setFromRotationMatrix."""
    x, y, z, w = quat_normalize(q)
    x2, y2, z2 = x + x, y + y, z + z
    xx, xy, xz = x * x2, x * y2, x * z2
    yy, yz, zz = y * y2, y * z2, z * z2
    wx, wy, wz = w * x2, w * y2, w * z2

    m11 = 1.0 - (yy + zz)
    m12 = xy - wz
    m13 = xz + wy
    m21 = xy + wz
    m22 = 1.0 - (xx + zz)
    m23 = yz - wx
    m31 = xz - wy
    m32 = yz + wx
    m33 = 1.0 - (xx + yy)

    def clamp1(v: float) -> float:
        return max(-1.0, min(1.0, v))

    lim = 0.9999999
    if order == "XYZ":
        ey = math.asin(clamp1(m13))
        if abs(m13) < lim:
            ex = math.atan2(-m23, m33)
            ez = math.atan2(-m12, m11)
        else:
            ex = math.atan2(m32, m22)
            ez = 0.0
    elif order == "YXZ":
        ex = math.asin(-clamp1(m23))
        if abs(m23) < lim:
            ey = math.atan2(m13, m33)
            ez = math.atan2(m21, m22)
        else:
            ey = math.atan2(-m31, m11)
            ez = 0.0
    elif order == "ZXY":
        ex = math.asin(clamp1(m32))
        if abs(m32) < lim:
            ey = math.atan2(-m31, m33)
            ez = math.atan2(-m12, m22)
        else:
            ey = 0.0
            ez = math.atan2(m21, m11)
    elif order == "ZYX":
        ey = math.asin(-clamp1(m31))
        if abs(m31) < lim:
            ex = math.atan2(m32, m33)
            ez = math.atan2(m21, m11)
        else:
            ex = 0.0
            ez = math.atan2(-m12, m22)
    elif order == "YZX":
        ez = math.asin(clamp1(m21))
        if abs(m21) < lim:
            ex = math.atan2(-m23, m22)
            ey = math.atan2(-m31, m11)
        else:
            ex = 0.0
            ey = math.atan2(m13, m33)
    elif order == "XZY":
        ez = math.asin(-clamp1(m12))
        if abs(m12) < lim:
            ex = math.atan2(m32, m22)
            ey = math.atan2(m13, m11)
        else:
            ex = math.atan2(-m23, m33)
            ey = 0.0
    else:
        raise ValueError(f"Unsupported Euler order: {order}")
    return (ex, ey, ez)


def mirror_quaternion(q: Quat) -> Quat:
    return (q[0], -q[1], -q[2], q[3])


# ── Anatomical Joint Definitions ──────────────────────────────────────────

AXIAL_DEF = {
    "order": "YXZ",
    "sided": False,
    "components": {
        "flexion": ("x", 1, 0.0),
        "lateralFlexion": ("z", -1, 0.0),
        "rotation": ("y", 1, 0.0),
    },
}

JOINT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "hips": AXIAL_DEF,
    "spine": AXIAL_DEF,
    "chest": AXIAL_DEF,
    "upperChest": AXIAL_DEF,
    "neck": AXIAL_DEF,
    "head": AXIAL_DEF,
    "shoulder": {
        "order": "ZYX",
        "sided": True,
        "components": {
            "elevation": ("z", 1, 0.0),
            "protraction": ("y", -1, 0.0),
            "rotation": ("x", 1, 0.0),
        },
    },
    "upperArm": {
        "order": "YZX",
        "sided": True,
        "components": {
            "elevation": ("z", 1, -90.0),
            "planeOfElevation": ("y", -1, 0.0),
            "rotation": ("x", -1, 0.0),
        },
    },
    "lowerArm": {
        "order": "YXZ",
        "sided": True,
        "components": {
            "flexion": ("y", -1, 0.0),
            "supination": ("x", -1, 0.0),
            "deviation": ("z", 1, 0.0),
        },
    },
    "hand": {
        "order": "ZYX",
        "sided": True,
        "components": {
            "flexion": ("z", -1, 0.0),
            "deviation": ("y", -1, 0.0),
            "rotation": ("x", 1, 0.0),
        },
    },
    "upperLeg": {
        "order": "XZY",
        "sided": True,
        "components": {
            "flexion": ("x", -1, 0.0),
            "abduction": ("z", 1, 0.0),
            "rotation": ("y", 1, 0.0),
        },
    },
    "lowerLeg": {
        "order": "XYZ",
        "sided": True,
        "components": {
            "flexion": ("x", 1, 0.0),
            "rotation": ("y", 1, 0.0),
            "deviation": ("z", 1, 0.0),
        },
    },
    "foot": {
        "order": "XZY",
        "sided": True,
        "components": {
            "dorsiflexion": ("x", -1, 0.0),
            "inversion": ("z", -1, 0.0),
            "rotation": ("y", 1, 0.0),
        },
    },
    "toes": {
        "order": "XYZ",
        "sided": True,
        "components": {
            "flexion": ("x", 1, 0.0),
            "rotation": ("y", 1, 0.0),
            "deviation": ("z", 1, 0.0),
        },
    },
    "finger": {
        "order": "ZYX",
        "sided": True,
        "components": {
            "curl": ("z", -1, 0.0),
            "splay": ("y", -1, 0.0),
            "twist": ("x", 1, 0.0),
        },
    },
    "thumb": {
        "order": "YXZ",
        "sided": True,
        "components": {
            "curl": ("y", 1, 0.0),
            "palmarAbduction": ("z", -1, 0.0),
            "twist": ("x", 1, 0.0),
        },
    },
}

SIDED_SUFFIX_TO_TYPE: dict[str, str] = {
    "Shoulder": "shoulder",
    "UpperArm": "upperArm",
    "LowerArm": "lowerArm",
    "Hand": "hand",
    "UpperLeg": "upperLeg",
    "LowerLeg": "lowerLeg",
    "Foot": "foot",
    "Toes": "toes",
    "ThumbProximal": "thumb",
    "ThumbDistal": "thumb",
    **{
        f"{digit}{seg}": "finger"
        for digit in ("Index", "Middle", "Ring", "Little")
        for seg in ("Proximal", "Intermediate", "Distal")
    },
}


def resolve_joint(joint_id: str) -> tuple[str, str | None, str] | None:
    """Return (joint_type, side, bone_name) or None."""
    if joint_id in JOINT_DEFINITIONS and not JOINT_DEFINITIONS[joint_id]["sided"]:
        return (joint_id, None, joint_id)
    for side in ("left", "right"):
        if joint_id.startswith(side):
            suffix = joint_id[len(side):]
            jtype = SIDED_SUFFIX_TO_TYPE.get(suffix)
            if jtype:
                return (jtype, side, joint_id)
    return None


def compose_joint_rotation(jtype: str, side: str | None, values: dict[str, float]) -> Quat:
    defn = JOINT_DEFINITIONS[jtype]
    angles = {"x": 0.0, "y": 0.0, "z": 0.0}
    for comp_name, (axis, sign, offset) in defn["components"].items():
        angles[axis] += sign * float(values.get(comp_name, 0.0)) + offset
    q = euler_to_quat(
        math.radians(angles["x"]),
        math.radians(angles["y"]),
        math.radians(angles["z"]),
        defn["order"],
    )
    return mirror_quaternion(q) if side == "right" else q


def decompose_joint_rotation(jtype: str, side: str | None, q: Quat) -> dict[str, float]:
    defn = JOINT_DEFINITIONS[jtype]
    local = mirror_quaternion(q) if side == "right" else quat_normalize(q)
    ex, ey, ez = quat_to_euler(local, defn["order"])
    deg_axes = {"x": math.degrees(ex), "y": math.degrees(ey), "z": math.degrees(ez)}
    return {
        comp_name: (deg_axes[axis] - offset) / sign
        for comp_name, (axis, sign, offset) in defn["components"].items()
    }


# ── Curves & Easing ───────────────────────────────────────────────────────

def ease_progress(t: float, easing: str) -> float:
    c = max(0.0, min(1.0, t))
    if easing == "linear":
        return c
    if easing == "easeInSine":
        return 1.0 - math.cos(c * math.pi / 2.0)
    if easing == "easeOutSine":
        return math.sin(c * math.pi / 2.0)
    if easing in ("easeInOutSine", "smooth"):
        return -(math.cos(math.pi * c) - 1.0) / 2.0
    if easing == "easeInCubic":
        return c * c * c
    if easing == "easeOutCubic":
        return 1.0 - (1.0 - c) ** 3
    if easing == "easeInOutCubic":
        return 4.0 * c * c * c if c < 0.5 else 1.0 - ((-2.0 * c + 2.0) ** 3) / 2.0
    return -(math.cos(math.pi * c) - 1.0) / 2.0


class ScalarTrack:
    def __init__(self, keys: list[dict[str, Any]], loop_duration: float | None):
        self.keys = keys
        self.loop_duration = loop_duration
        self.closed = (
            loop_duration is not None
            and len(keys) > 1
            and abs(keys[0]["t"]) < 1e-6
            and abs(keys[-1]["t"] - loop_duration) < 1e-6
        )
        self.slopes = [self._tangent_at(i) for i in range(len(keys))]

    def _tangent_at(self, idx: int) -> float:
        keys = self.keys
        key = keys[idx]
        if key.get("tangent", "auto") == "flat":
            return 0.0
        loop = self.loop_duration
        wrap_last = len(keys) - (2 if self.closed else 1)
        wrap_first = 1 if self.closed else 0

        if idx > 0:
            prev_k = keys[idx - 1]
        elif loop is not None:
            prev_k = {**keys[wrap_last], "t": keys[wrap_last]["t"] - loop}
        else:
            prev_k = None

        if idx < len(keys) - 1:
            next_k = keys[idx + 1]
        elif loop is not None:
            next_k = {**keys[wrap_first], "t": keys[wrap_first]["t"] + loop}
        else:
            next_k = None

        if prev_k is None or next_k is None:
            return 0.0
        h0 = key["t"] - prev_k["t"]
        h1 = next_k["t"] - key["t"]
        if h0 <= 0.0 or h1 <= 0.0:
            return 0.0
        d0 = (key["v"] - prev_k["v"]) / h0
        d1 = (next_k["v"] - key["v"]) / h1
        if d0 * d1 <= 0.0:
            return 0.0
        w0 = 2.0 * h1 + h0
        w1 = h1 + 2.0 * h0
        return (w0 + w1) / (w0 / d0 + w1 / d1)

    def _seg_index(self, time: float) -> int:
        low, high = 0, len(self.keys) - 2
        while low < high:
            mid = (low + high + 1) >> 1
            if self.keys[mid]["t"] <= time:
                low = mid
            else:
                high = mid - 1
        return low

    def _eval_seg(self, frm: dict[str, Any], to: dict[str, Any], s0: float, s1: float, t: float) -> float:
        span = to["t"] - frm["t"]
        u = (t - frm["t"]) / span if span > 0.0 else 1.0
        ease = to.get("ease", "smooth")
        if ease == "hold":
            return to["v"] if u >= 1.0 else frm["v"]
        if ease == "smooth":
            u2 = u * u
            u3 = u2 * u
            return (
                (2.0 * u3 - 3.0 * u2 + 1.0) * frm["v"]
                + (u3 - 2.0 * u2 + u) * span * s0
                + (-2.0 * u3 + 3.0 * u2) * to["v"]
                + (u3 - u2) * span * s1
            )
        return frm["v"] + (to["v"] - frm["v"]) * ease_progress(u, ease)

    def evaluate(self, time: float) -> float:
        keys = self.keys
        if len(keys) == 1:
            return keys[0]["v"]
        if self.loop_duration is not None:
            period = self.loop_duration
            wrapped = ((time % period) + period) % period
            last = keys[-1]
            if self.closed or (wrapped >= keys[0]["t"] and wrapped < last["t"]):
                idx = self._seg_index(wrapped)
                return self._eval_seg(keys[idx], keys[idx + 1], self.slopes[idx], self.slopes[idx + 1], wrapped)
            to_k = {**keys[0], "t": keys[0]["t"] + period}
            local = wrapped + period if wrapped < keys[0]["t"] else wrapped
            return self._eval_seg(last, to_k, self.slopes[-1], self.slopes[0], local)

        if time <= keys[0]["t"]:
            return keys[0]["v"]
        if time >= keys[-1]["t"]:
            return keys[-1]["v"]
        idx = self._seg_index(time)
        return self._eval_seg(keys[idx], keys[idx + 1], self.slopes[idx], self.slopes[idx + 1], time)


# ── Hand Presets ──────────────────────────────────────────────────────────

HAND_DIGITS = ("thumb", "index", "middle", "ring", "little")
HAND_DIGIT_FIELDS = {
    "thumb": ("curl", "palmarAbduction", "twist"),
    "index": ("curl", "splay"),
    "middle": ("curl", "splay"),
    "ring": ("curl", "splay"),
    "little": ("curl", "splay"),
}
HAND_DIGIT_SEGMENTS = {
    "thumb": ("proximal", "distal"),
    "index": ("proximal", "intermediate", "distal"),
    "middle": ("proximal", "intermediate", "distal"),
    "ring": ("proximal", "intermediate", "distal"),
    "little": ("proximal", "intermediate", "distal"),
}
SPREAD_WEIGHT = {"thumb": 1.0, "index": -0.65, "middle": -0.15, "ring": 0.3, "little": 0.7}
THUMB_CURL = {"fist": (65.0, 15.0), "open-together": (38.0, 0.0), "thumbs-up": (-50.0, -25.0)}

OFFSET_PRESETS = {
    "cupped": {
        "thumbFrom": "open-together",
        "digits": {
            "thumb": {"curl": [6, 10], "palmarAbduction": 14},
            "index": {"curl": [16, 22, 14], "splay": -1},
            "middle": {"curl": [18, 24, 14]},
            "ring": {"curl": [20, 26, 16], "splay": 1},
            "little": {"curl": [22, 28, 18], "splay": 3},
        },
    },
    "soft-claw": {
        "thumbFrom": "open-spread",
        "digits": {
            "thumb": {"curl": [14, 25], "palmarAbduction": 10},
            "index": {"curl": [18, 55, 40], "splay": 10},
            "middle": {"curl": [16, 58, 42], "splay": 2},
            "ring": {"curl": [18, 58, 42], "splay": -6},
            "little": {"curl": [22, 55, 40], "splay": -14},
        },
    },
    "palm-flat": {
        "thumbFrom": "open-together",
        "digits": {
            "thumb": {"curl": -4},
            "index": {"curl": [-4, -2, 0], "splay": -1},
            "middle": {"curl": [-4, -2, 0]},
            "ring": {"curl": [-4, -2, 0], "splay": 1},
            "little": {"curl": [-3, -2, 0], "splay": 2},
        },
    },
    "pinch": {
        "thumbFrom": "pinch",
        "digits": {
            "thumb": {"curl": [0, 18]},
            "index": {"curl": [40, 46, 28]},
            "middle": {"curl": [34, 48, 30], "splay": -2},
            "ring": {"curl": [42, 52, 30], "splay": -1},
            "little": {"curl": [50, 54, 30], "splay": 2},
        },
    },
    "ok": {
        "thumbFrom": "pinch",
        "digits": {
            "thumb": {"curl": [0, 18]},
            "index": {"curl": [40, 46, 28]},
            "middle": {"curl": [6, 6, 4], "splay": -4},
            "ring": {"curl": [10, 8, 4], "splay": -10},
            "little": {"curl": [14, 10, 6], "splay": -18},
        },
    },
}


def adjust_hand_quaternion(start: Quat, side: str, digit: str, adj: str, degrees: float) -> Quat:
    limit = 90.0 if adj == "curl" else 30.0
    amount = max(-limit, min(limit, float(degrees)))
    sign = -1.0 if side == "left" else 1.0
    if adj == "curl":
        axis = (0.0, -sign if digit == "thumb" else 0.0, 0.0 if digit == "thumb" else sign)
    else:
        axis = (0.0, sign if digit == "thumb" else -sign, 0.0)
    angle = amount * (SPREAD_WEIGHT[digit] if adj == "spread" else 1.0)
    return quat_normalize(quat_mul(quat_normalize(start), quat_from_axis_angle(axis, math.radians(angle))))


def _apply_digit_offset(bone_name: str, digit: str, ordinal: int, rot: Quat, offset: dict[str, Any] | None) -> Quat:
    if not offset:
        return rot
    values: dict[str, float] = {}
    for field in HAND_DIGIT_FIELDS[digit]:
        if field == "curl":
            curl_val = offset.get("curl", 0.0)
            if isinstance(curl_val, list):
                values[field] = float(curl_val[ordinal]) if ordinal < len(curl_val) else 0.0
            else:
                values[field] = float(curl_val)
        else:
            values[field] = float(offset.get(field, 0.0)) if ordinal == 0 else 0.0
    if all(v == 0.0 for v in values.values()):
        return rot
    res = resolve_joint(bone_name)
    assert res is not None
    jtype, side, _ = res
    cur = decompose_joint_rotation(jtype, side, rot)
    for k, v in values.items():
        cur[k] = cur.get(k, 0.0) + v
    return compose_joint_rotation(jtype, side, cur)


def _preset_quaternion(side: str, digit: str, seg: str, ordinal: int, bone_name: str, preset: str, relaxed_rest: dict[str, Any]) -> Quat:
    if preset in OFFSET_PRESETS:
        spec = OFFSET_PRESETS[preset]
        if digit != "thumb":
            return _apply_digit_offset(bone_name, digit, ordinal, (0.0, 0.0, 0.0, 1.0), spec["digits"][digit])
        thumb_from = "open-together" if spec["thumbFrom"] == "pinch" else spec["thumbFrom"]
        start = _preset_quaternion(side, digit, seg, ordinal, bone_name, thumb_from, relaxed_rest)
        return _apply_digit_offset(bone_name, digit, ordinal, start, spec["digits"]["thumb"])

    if preset == "relaxed":
        return tuple(float(v) for v in relaxed_rest[bone_name]["rotation"])  # type: ignore[return-value]

    if preset in ("point", "peace"):
        if digit == "index" or (preset == "peace" and digit == "middle"):
            if preset == "peace" and seg == "proximal":
                angle = (1.0 if side == "left" else -1.0) * (-15.0 if digit == "index" else 15.0)
                return quat_from_axis_angle((0.0, 1.0, 0.0), math.radians(angle))
            return (0.0, 0.0, 0.0, 1.0)
        return _preset_quaternion(side, digit, seg, ordinal, bone_name, "fist", relaxed_rest)

    if preset == "thumbs-up" and digit != "thumb":
        return _preset_quaternion(side, digit, seg, ordinal, bone_name, "fist", relaxed_rest)

    if digit == "thumb":
        prox, dist = THUMB_CURL.get(preset, (0.0, 0.0))
        return adjust_hand_quaternion((0.0, 0.0, 0.0, 1.0), side, "thumb", "curl", prox if seg == "proximal" else dist)

    result: Quat = (0.0, 0.0, 0.0, 1.0)
    if preset == "fist":
        result = adjust_hand_quaternion(result, side, digit, "curl", 60.0 if seg == "distal" else 80.0)
    if ordinal == 0:
        result = adjust_hand_quaternion(result, side, digit, "spread", 30.0 if preset == "open-spread" else 0.0)
    return result


def hand_shape_rotations(side: str, shape: dict[str, Any], relaxed_rest: dict[str, Any]) -> dict[str, Quat]:
    rotations: dict[str, Quat] = {}
    preset = shape["preset"]
    curl = shape.get("curl")
    spread = shape.get("spread")
    fingers = shape.get("fingers") or {}

    for digit in HAND_DIGITS:
        for ordinal, seg in enumerate(HAND_DIGIT_SEGMENTS[digit]):
            bone_name = f"{side}{digit.capitalize()}{seg.capitalize()}"
            rot = _preset_quaternion(side, digit, seg, ordinal, bone_name, preset, relaxed_rest)
            if curl:
                rot = adjust_hand_quaternion(rot, side, digit, "curl", float(curl))
            if spread and ordinal == 0:
                rot = adjust_hand_quaternion(rot, side, digit, "spread", float(spread))
            rot = _apply_digit_offset(bone_name, digit, ordinal, rot, fingers.get(digit))
            rotations[bone_name] = quat_normalize(rot)
    return rotations


# ── Clip Sampling & GLB Packing ───────────────────────────────────────────

def find_segment(keys: list[dict[str, Any]], t: float, loop_duration: float | None) -> tuple[int, int, float]:
    last = len(keys) - 1
    if last == 0:
        return (0, 0, 0.0)
    if loop_duration is not None and (t < keys[0]["t"] or t >= keys[last]["t"]):
        span = keys[0]["t"] + loop_duration - keys[last]["t"]
        elapsed = t - keys[last]["t"] if t >= keys[last]["t"] else t + loop_duration - keys[last]["t"]
        return (last, 0, elapsed / span if span > 0 else 1.0)
    if t <= keys[0]["t"]:
        return (0, 0, 0.0)
    if t >= keys[last]["t"]:
        return (last, last, 0.0)
    low, high = 0, last - 1
    while low < high:
        mid = (low + high + 1) >> 1
        if keys[mid]["t"] <= t:
            low = mid
        else:
            high = mid - 1
    span = keys[low + 1]["t"] - keys[low]["t"]
    return (low, low + 1, (t - keys[low]["t"]) / span if span > 0 else 1.0)


def sample_clip_frames(clip: dict[str, Any], relaxed_rest: dict[str, Any], fps: int = FPS) -> tuple[list[float], dict[str, list[Quat]]]:
    duration = float(clip["duration"])
    loop_duration = duration if clip.get("loop") else None
    beat_times = {b["id"]: float(b["time"]) for b in clip["beats"]}
    beat_eases = {b["id"]: b.get("ease") for b in clip["beats"]}

    def resolve_t(k: dict[str, Any]) -> float:
        return beat_times[k["beat"]] + float(k.get("dt", 0.0))

    def resolve_ease(k: dict[str, Any], fallback: str) -> str:
        return k.get("ease") or beat_eases.get(k["beat"]) or fallback

    # Prepare joint tracks
    joint_tracks: list[tuple[str, str | None, str, list[tuple[str, ScalarTrack | float]]]] = []
    for joint_id, comps in (clip.get("joints") or {}).items():
        resolved = resolve_joint(joint_id)
        if not resolved:
            continue
        jtype, side, bone_name = resolved
        base_rot = tuple(float(v) for v in (relaxed_rest.get(bone_name, {}).get("rotation") or [0, 0, 0, 1]))
        base_vals = decompose_joint_rotation(jtype, side, base_rot)  # type: ignore[arg-type]
        comp_tracks: list[tuple[str, ScalarTrack | float]] = []
        for comp_name in JOINT_DEFINITIONS[jtype]["components"].keys():
            raw_keys = comps.get(comp_name)
            base_val = base_vals.get(comp_name, 0.0)
            if raw_keys:
                resolved_keys = [
                    {
                        "t": resolve_t(k),
                        "v": base_val if k["v"] == "base" else float(k["v"]),
                        "tangent": k.get("tangent", "auto"),
                        "ease": resolve_ease(k, "smooth"),
                    }
                    for k in raw_keys
                ]
                comp_tracks.append((comp_name, ScalarTrack(resolved_keys, loop_duration)))
            else:
                comp_tracks.append((comp_name, base_val))
        joint_tracks.append((jtype, side, bone_name, comp_tracks))

    # Prepare hand shape tracks
    hand_tracks: list[list[dict[str, Any]]] = []
    for side, hkeys in (clip.get("hands") or {}).items():
        if not hkeys:
            continue
        timed = [
            {
                "t": resolve_t(hk),
                "ease": resolve_ease(hk, "easeInOutSine"),
                "rotations": hand_shape_rotations(side, hk, relaxed_rest),
            }
            for hk in hkeys
        ]
        hand_tracks.append(timed)

    # Sample strictly increasing timestamps [0, ..., duration]
    num_steps = max(2, int(round(duration * fps)))
    timestamps: list[float] = []
    for i in range(num_steps + 1):
        t = duration if i == num_steps else round((i / num_steps) * duration, 6)
        if timestamps and t <= timestamps[-1]:
            continue
        timestamps.append(t)

    # Track every bone in HUMANOID_ORDER so VRMAnimation rests cleanly on relaxedRest
    bone_frames: dict[str, list[Quat]] = {bone: [] for bone in HUMANOID_ORDER}

    for t in timestamps:
        eval_t = min(t, duration) if loop_duration is None else (0.0 if abs(t - duration) < 1e-6 else t)
        frame_pose: dict[str, Quat] = {
            bone: quat_normalize(tuple(float(v) for v in (relaxed_rest.get(bone, {}).get("rotation") or [0, 0, 0, 1])))  # type: ignore[arg-type]
            for bone in HUMANOID_ORDER
        }

        for timed_keys in hand_tracks:
            i_from, i_to, prog = find_segment(timed_keys, eval_t, loop_duration)
            to_ease = timed_keys[i_to]["ease"]
            if to_ease == "hold":
                eased = 1.0 if prog >= 1.0 else 0.0
            else:
                eased = ease_progress(prog, to_ease)
            r_from = timed_keys[i_from]["rotations"]
            r_to = timed_keys[i_to]["rotations"]
            for bone_name, q0 in r_from.items():
                q1 = r_to.get(bone_name, q0)
                frame_pose[bone_name] = quat_slerp(q0, q1, eased)

        for jtype, side, bone_name, comp_tracks in joint_tracks:
            vals = {
                cname: (trk if isinstance(trk, (int, float)) else trk.evaluate(eval_t))
                for cname, trk in comp_tracks
            }
            frame_pose[bone_name] = compose_joint_rotation(jtype, side, vals)

        for bone in HUMANOID_ORDER:
            bone_frames[bone].append(quat_normalize(frame_pose[bone]))

    return timestamps, bone_frames


def build_vrma_glb(clip_name: str, timestamps: list[float], bone_frames: dict[str, list[Quat]]) -> bytes:
    """Pack sampled bone rotations into a strict VRMC_vrm_animation 1.0 GLB v2 binary."""
    bone_to_idx = {bone: idx for idx, bone in enumerate(HUMANOID_ORDER)}
    children_map: dict[int, list[int]] = {i: [] for i in range(len(HUMANOID_ORDER))}
    for bone, parent in HUMANOID_PARENTS.items():
        if parent is not None:
            children_map[bone_to_idx[parent]].append(bone_to_idx[bone])

    nodes = []
    for idx, bone in enumerate(HUMANOID_ORDER):
        node: dict[str, Any] = {"name": bone}
        if bone == "hips":
            node["translation"] = [0.0, 1.0, 0.0]
        if children_map[idx]:
            node["children"] = children_map[idx]
        nodes.append(node)

    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    # BufferView 0 + Accessor 0: timestamps (SCALAR float32)
    time_bytes = struct.pack(f"<{len(timestamps)}f", *timestamps)
    buffer_views.append({"buffer": 0, "byteOffset": 0, "byteLength": len(time_bytes)})
    accessors.append({
        "bufferView": 0,
        "componentType": 5126,
        "count": len(timestamps),
        "type": "SCALAR",
        "min": [float(timestamps[0])],
        "max": [float(timestamps[-1])],
    })
    binary.extend(time_bytes)

    samplers: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []

    for bone in HUMANOID_ORDER:
        quats = bone_frames[bone]
        # Skip completely constant identity bones except hips/spine/head? Actually keeping animated
        # or non-identity relaxedRest bones ensures relaxedRest posture holds cleanly during playback.
        is_const_identity = all(
            abs(q[0]) < 1e-6 and abs(q[1]) < 1e-6 and abs(q[2]) < 1e-6 and abs(abs(q[3]) - 1.0) < 1e-6
            for q in quats
        )
        if is_const_identity:
            continue

        while len(binary) % 4 != 0:
            binary.append(0)
        offset = len(binary)
        flat = [c for q in quats for c in q]
        q_bytes = struct.pack(f"<{len(flat)}f", *flat)
        binary.extend(q_bytes)

        bv_idx = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(q_bytes)})
        acc_idx = len(accessors)
        accessors.append({
            "bufferView": bv_idx,
            "componentType": 5126,
            "count": len(quats),
            "type": "VEC4",
        })
        samp_idx = len(samplers)
        samplers.append({"input": 0, "output": acc_idx, "interpolation": "LINEAR"})
        channels.append({"sampler": samp_idx, "target": {"node": bone_to_idx[bone], "path": "rotation"}})

    while len(binary) % 4 != 0:
        binary.append(0)

    document = {
        "asset": {"version": "2.0", "generator": "Miso R1 VRMA Generator"},
        "extensionsUsed": ["VRMC_vrm_animation"],
        "extensions": {
            "VRMC_vrm_animation": {
                "specVersion": "1.0",
                "humanoid": {
                    "humanBones": {bone: {"node": bone_to_idx[bone]} for bone in HUMANOID_ORDER},
                },
            }
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "animations": [{"name": clip_name, "samplers": samplers, "channels": channels}],
    }

    json_bytes = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    padded_json = json_bytes + (b" " * json_pad)

    total_len = 12 + 8 + len(padded_json) + 8 + len(binary)
    header = struct.pack("<4sII", GLB_MAGIC, GLB_VERSION, total_len)
    json_header = struct.pack("<II", len(padded_json), GLB_JSON_CHUNK_TYPE)
    bin_header = struct.pack("<II", len(binary), GLB_BIN_CHUNK_TYPE)
    return header + json_header + padded_json + bin_header + bytes(binary)


def generate_all(data_path: Path = DEFAULT_DATA_PATH, out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
    bundle = json.loads(data_path.read_text(encoding="utf-8"))
    relaxed_rest = bundle["relaxedRest"]
    clips = bundle["clips"]

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, clip in clips.items():
        timestamps, bone_frames = sample_clip_frames(clip, relaxed_rest, fps=FPS)
        glb = build_vrma_glb(name, timestamps, bone_frames)
        target = out_dir / f"{name}.vrma"
        target.write_bytes(glb)
        written.append(target)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Bake .vrma animations from pose clip definitions.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    written = generate_all(args.data, args.out)
    for path in written:
        print(f"[vrma] generated {path.name} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
