"""E2E Tests for R1: .vrma Animations + Anime VFX + Tagging (Features F1, F2, F3)."""
from __future__ import annotations

import json
import re
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tests.e2e.helpers import (
    REPO_ROOT,
    FakeLLMStream,
    IsolatedMisoWorkspace,
    MockViewerServer,
    extract_client_module_js,
    make_minimal_glb_bytes,
    make_minimal_wav_bytes,
    require_attr,
    require_module,
    run_node_check,
    run_node_file_check,
    validate_vrma_glb,
)

CORE_VFX_ALIASES = {
    "angry": {"anger_vein", "angry", "anger", "vein"},
    "flustered": {"blush_lines", "blush", "blush_band", "flustered"},
    "happy": {"sparkles", "kira_star", "cheer_sparkles", "happy", "sparkle"},
    "annoyed": {"sweatdrop", "sweat_drop", "annoyed", "sweat"},
}


def _extract_vfx_name(state: dict) -> str | None:
    for key in ("vfx", "vfx_id", "vfx_type", "anime_vfx", "effect"):
        if key in state:
            val = state[key]
            if isinstance(val, dict):
                return val.get("name") or val.get("id") or val.get("type")
            return val
    return None


def _extract_primary_weight(state: dict) -> float:
    for key in ("blendshape_weight", "weight", "strength", "intensity_weight", "scale"):
        val = state.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
    for map_key in ("blendshapes", "expressions", "weights", "expression_weights"):
        sub = state.get(map_key)
        if isinstance(sub, dict) and sub:
            nums = [float(v) for v in sub.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums:
                return max(nums)
    nums = [
        float(v)
        for k, v in state.items()
        if k not in ("intensity", "level") and isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    if nums:
        return max(nums)
    raise AssertionError(f"Could not locate numeric blendshape weight in visual state: {state!r}")


class TestF1VrmaAssetsAndGestures(unittest.TestCase):
    """Feature F1: .vrma binary files & <=12 signature gestures."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_vrma_directory_exists_and_populated(self):
        tags = require_module(self, "riko.tags")
        gestures = require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags")
        vrma_dir = REPO_ROOT / "client" / "animations" / "vrma"
        self.assertTrue(vrma_dir.is_dir(), f"Expected .vrma directory at {vrma_dir}")
        vrma_files = list(vrma_dir.glob("*.vrma"))
        self.assertGreater(len(vrma_files), 0, "Expected at least one .vrma file in client/animations/vrma/")
        stems = {p.stem.lower() for p in vrma_files}
        for g in gestures:
            self.assertIn(g.lower(), stems, f"Configured signature gesture '{g}' has no matching .vrma file")

    def test_t1_all_vrma_files_valid_glb_and_vrmc_extension(self):
        vrma_dir = REPO_ROOT / "client" / "animations" / "vrma"
        self.assertTrue(vrma_dir.is_dir(), f"Missing .vrma directory: {vrma_dir}")
        files = sorted(vrma_dir.glob("*.vrma"))
        self.assertGreater(len(files), 0, "No .vrma files found to validate")
        for f in files:
            doc = validate_vrma_glb(f)
            self.assertEqual(doc["asset"]["version"], "2.0")
            self.assertIn("VRMC_vrm_animation", doc["extensionsUsed"])

    def test_t1_signature_gesture_count_at_most_12(self):
        tags = require_module(self, "riko.tags")
        gestures = require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags")
        self.assertGreater(len(gestures), 0, "SIGNATURE_GESTURES must not be empty")
        self.assertLessEqual(len(gestures), 12, f"Signature gesture list must be <=12, got {len(gestures)}: {gestures}")

    def test_t1_vrma_files_served_over_viewer_http(self):
        vrma_dir = REPO_ROOT / "client" / "animations" / "vrma"
        files = sorted(vrma_dir.glob("*.vrma")) if vrma_dir.is_dir() else []
        self.assertGreater(len(files), 0, "No .vrma files available to serve via MockViewerServer")
        sample_file = files[0]
        with IsolatedMisoWorkspace() as ws:
            with MockViewerServer(ws) as srv:
                resp = srv.get_bytes(f"/animations/vrma/{sample_file.name}")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.content, sample_file.read_bytes())

    def test_t1_vrma_keyframes_and_human_bones_present(self):
        vrma_dir = REPO_ROOT / "client" / "animations" / "vrma"
        files = sorted(vrma_dir.glob("*.vrma")) if vrma_dir.is_dir() else []
        self.assertGreater(len(files), 0, "No .vrma files found")
        for f in files:
            doc = validate_vrma_glb(f)
            bones = doc["extensions"]["VRMC_vrm_animation"]["humanoid"]["humanBones"]
            self.assertGreaterEqual(len(bones), 1, f"{f.name} must animate at least 1 humanBone")
            self.assertGreaterEqual(len(doc["animations"]), 1, f"{f.name} must contain >=1 animation")

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_validator_rejects_truncated_and_non_glb_buffers(self):
        with tempfile.TemporaryDirectory(prefix="miso_vrma_neg_") as td:
            bad_magic = Path(td) / "bad.vrma"
            bad_magic.write_bytes(b"NOT_GLTF" + b"\x00" * 32)
            with self.assertRaises(ValueError):
                validate_vrma_glb(bad_magic)

            truncated = Path(td) / "trunc.vrma"
            truncated.write_bytes(b"glTF\x02\x00\x00\x00\xff\x00\x00\x00JSON")
            with self.assertRaises(ValueError):
                validate_vrma_glb(truncated)

    def test_t2_validator_rejects_glb_without_vrmc_extension(self):
        with tempfile.TemporaryDirectory(prefix="miso_vrma_plain_") as td:
            plain_glb = Path(td) / "plain.vrma"
            plain_glb.write_bytes(make_minimal_glb_bytes())
            with self.assertRaises(ValueError):
                validate_vrma_glb(plain_glb)

    def test_t2_signature_gestures_unique_lowercase_no_blanks(self):
        tags = require_module(self, "riko.tags")
        gestures = list(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        self.assertEqual(len(gestures), len(set(gestures)), "SIGNATURE_GESTURES must not contain duplicates")
        for g in gestures:
            self.assertIsInstance(g, str)
            self.assertTrue(re.fullmatch(r"[a-z][a-z0-9_]*", g), f"Gesture '{g}' must be lowercase snake_case")

    def test_t2_unknown_gesture_ignored_safely(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        parsed = parse_reply_tags("[happy:2][backflip_triple_somersault] Look at this.")
        self.assertEqual(parsed.emotion, "happy")
        self.assertIsNone(parsed.gesture)
        self.assertEqual(parsed.clean_text, "Look at this.")

    def test_t2_missing_vrma_http_returns_404(self):
        with IsolatedMisoWorkspace() as ws:
            with MockViewerServer(ws) as srv:
                resp = srv.get_bytes("/animations/vrma/__definitely_missing__.vrma")
                self.assertEqual(resp.status_code, 404)


class TestF2EmotionIntensityGestureParsing(unittest.TestCase):
    """Feature F2: [emotion:intensity][gesture] & [emotion:intensity] parsing and stripping."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_parse_emotion_intensity_and_gesture(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        sample_gesture = "cross_arms" if "cross_arms" in gestures else sorted(gestures)[0]
        raw = f"[angry:2][{sample_gesture}] Because my creator did a terrible job programming me."
        parsed = parse_reply_tags(raw)
        self.assertEqual(parsed.emotion, "angry")
        self.assertEqual(parsed.intensity, 2)
        self.assertEqual(parsed.gesture, sample_gesture)
        self.assertEqual(parsed.clean_text, "Because my creator did a terrible job programming me.")

    def test_t1_parse_emotion_intensity_without_gesture(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        parsed = parse_reply_tags("[happy:3] Look at that clean build.")
        self.assertEqual(parsed.emotion, "happy")
        self.assertEqual(parsed.intensity, 3)
        self.assertIsNone(parsed.gesture)
        self.assertEqual(parsed.clean_text, "Look at that clean build.")

    def test_t1_parse_emotion_intensity_with_affection_delta(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "wave" if "wave" in gestures else sorted(gestures)[0]
        parsed = parse_reply_tags(f"[happy:2, +2][{g}] Good morning!")
        self.assertEqual(parsed.emotion, "happy")
        self.assertEqual(parsed.intensity, 2)
        self.assertEqual(parsed.gesture, g)
        self.assertEqual(parsed.affection_delta, 2)
        self.assertEqual(parsed.clean_text, "Good morning!")

    def test_t1_legacy_emotion_tag_backward_compatible(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        parsed = parse_reply_tags("[relaxed] Still works fine.")
        self.assertEqual(parsed.emotion, "relaxed")
        self.assertIn(parsed.intensity, (1, 2, 3))
        self.assertIsNone(parsed.gesture)
        self.assertEqual(parsed.clean_text, "Still works fine.")

    def test_t1_clean_for_speech_strips_emotion_and_gesture_tags(self):
        from riko import tts

        cleaned = tts.clean_for_speech("[flustered:2][facepalm] Stop staring at me!")
        self.assertNotIn("[", cleaned)
        self.assertNotIn("]", cleaned)
        self.assertNotIn("flustered", cleaned.lower())
        self.assertNotIn("facepalm", cleaned.lower())
        self.assertEqual(cleaned, "Stop staring at me!")

    def test_t1_system_prompt_documents_new_tag_format(self):
        cfg = yaml.safe_load((REPO_ROOT / "character_config.yaml").read_text(encoding="utf-8"))
        prompt = cfg.get("system_prompt", "")
        self.assertRegex(
            prompt,
            r"\[(?:emotion|happy|angry|flustered|annoyed)[^\]]*:\s*(?:intensity|[1-3])",
            "system_prompt must instruct [emotion:intensity] tag format",
        )
        self.assertIn("gesture", prompt.lower(), "system_prompt must instruct optional [gesture] tag format")

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_intensity_clamped_out_of_range(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        low = parse_reply_tags("[angry:0] Too low.")
        high = parse_reply_tags("[angry:9] Too high.")
        neg = parse_reply_tags("[angry:-3] Negative.")
        self.assertEqual(low.intensity, 1)
        self.assertEqual(high.intensity, 3)
        self.assertEqual(neg.intensity, 1)

    def test_t2_unknown_emotion_defaults_to_neutral(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "shrug" if "shrug" in gestures else sorted(gestures)[0]
        parsed = parse_reply_tags(f"[cosmic:2][{g}] Hello.")
        self.assertEqual(parsed.emotion, "neutral")
        self.assertEqual(parsed.gesture, g)
        self.assertEqual(parsed.clean_text, "Hello.")

    def test_t2_unknown_gesture_stripped_from_clean_text(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        parsed = parse_reply_tags("[happy:2][nonexistent_pose_xyz] Hi there!")
        self.assertIsNone(parsed.gesture)
        self.assertNotIn("nonexistent_pose_xyz", parsed.clean_text)
        self.assertEqual(parsed.clean_text, "Hi there!")

    def test_t2_case_insensitive_and_whitespace_between_tags(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "cross_arms" if "cross_arms" in gestures else sorted(gestures)[0]
        parsed = parse_reply_tags(f"  [ANGRY:3]   [{g.upper()}]   Fix it now.")
        self.assertEqual(parsed.emotion, "angry")
        self.assertEqual(parsed.intensity, 3)
        self.assertEqual(parsed.gesture, g)
        self.assertEqual(parsed.clean_text, "Fix it now.")

    def test_t2_malformed_or_empty_inputs_never_crash(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        for sample in ("", "   ", "[angry:abc] Text", "[unclosed tag", "Plain text without tags"):
            parsed = parse_reply_tags(sample)
            self.assertIn(parsed.intensity, (1, 2, 3))
            self.assertIsInstance(parsed.clean_text, str)

    def test_t2_viewer_api_chat_and_call_sites_strip_new_tags(self):
        tags = require_module(self, "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "cross_arms" if "cross_arms" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None)
            with FakeLLMStream(sync_replies=[f"[angry:2][{g}] Fix your broken code."]):
                with MockViewerServer(ws) as srv:
                    data = srv.post_chat("Why is this broken?")
                    self.assertEqual(data["reply"], "Fix your broken code.")
                    self.assertNotIn(f"[{g}]", data["reply"])
                    self.assertNotIn("[angry:2]", data["reply"])

        # Verify legacy single-bracket regex was replaced across backend callers
        legacy_pattern = re.compile(r're\.match\(r"\^\\\[\(\[a-zA-Z\]\+\)\\\]\\s\*"')
        for rel in (
            "main.py",
            "riko/viewer.py",
            "riko/telegram_bot.py",
            "riko/heartbeat.py",
            "riko/cowatch.py",
            "riko/face_id.py",
            "riko/sentry.py",
        ):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIsNone(
                legacy_pattern.search(src),
                f"{rel} still uses legacy bare [emotion] regex instead of riko.tags.parse_reply_tags",
            )


class TestF3IntensityBlendshapesVfxFrontend(unittest.TestCase):
    """Feature F3: Intensity 1-3 -> blendshape weights, anime VFX & frontend .vrma hooks."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_required_anime_vfx_mappings_deterministic(self):
        tags = require_module(self, "riko.tags")
        to_visual = require_attr(self, tags, "emotion_to_visual_state", "riko.tags")
        for emo, accepted_vfx in CORE_VFX_ALIASES.items():
            state = to_visual(emo, 2)
            self.assertIsInstance(state, dict)
            vfx = _extract_vfx_name(state)
            self.assertIsNotNone(vfx, f"Expected anime VFX for {emo}:2, got {state!r}")
            self.assertIn(
                str(vfx).lower(),
                accepted_vfx,
                f"Expected {emo} VFX in {accepted_vfx}, got {vfx!r}",
            )

    def test_t1_intensity_1_to_3_scales_blendshape_weights_monotonically(self):
        tags = require_module(self, "riko.tags")
        to_visual = require_attr(self, tags, "emotion_to_visual_state", "riko.tags")
        for emo in ("angry", "flustered", "happy", "annoyed"):
            w1 = _extract_primary_weight(to_visual(emo, 1))
            w2 = _extract_primary_weight(to_visual(emo, 2))
            w3 = _extract_primary_weight(to_visual(emo, 3))
            self.assertGreater(w1, 0.0, f"{emo}:1 weight must be > 0")
            self.assertLess(w1, w2, f"{emo} weight must increase from 1 to 2 ({w1} vs {w2})")
            self.assertLess(w2, w3, f"{emo} weight must increase from 2 to 3 ({w2} vs {w3})")
            self.assertLessEqual(w3, 1.0, f"{emo}:3 weight must be <= 1.0")

    def test_t1_viewer_next_payload_carries_r1_fields(self):
        tags = require_module(self, "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "cross_arms" if "cross_arms" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace() as ws:
            wav_path = ws.root / "client" / "audio" / "test_r1.wav"
            wav_path.write_bytes(make_minimal_wav_bytes(0.15))
            from riko import viewer

            with MockViewerServer(ws) as srv:
                srv.touch_page()
                viewer.play(wav_path, emotion="angry", intensity=2, gesture=g)
                clip = srv.get_next()
                self.assertEqual(clip["emotion"], "angry")
                self.assertEqual(clip["intensity"], 2)
                self.assertEqual(clip["gesture"], g)
                self.assertIn("audio", clip)

    def test_t1_client_html_importmap_vrma_mixer_and_vfx_hooks(self):
        html_path = REPO_ROOT / "client" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        importmap_match = re.search(
            r'<script\s+type=["\']importmap["\']\s*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE
        )
        self.assertIsNotNone(importmap_match, "client/index.html missing <script type='importmap'>")
        imap = json.loads(importmap_match.group(1))
        imports = imap.get("imports", {})
        self.assertIn("@pixiv/three-vrm-animation", imports, "importmap must include @pixiv/three-vrm-animation")

        js_blocks = extract_client_module_js(html_path)
        combined_js = "\n".join(js_blocks)
        for token in ("VRMAnimationLoaderPlugin", "createVRMAnimationClip", "AnimationMixer"):
            self.assertIn(token, combined_js, f"client/index.html module script missing '{token}'")

        # Check anime VFX markers exist in client JS/HTML
        lower_html = html.lower()
        for expected_vfx in ("anger", "blush", "sparkle", "sweat"):
            self.assertIn(expected_vfx, lower_html, f"client/index.html missing anime VFX logic for '{expected_vfx}'")

    def test_t1_client_module_js_syntax_valid_under_node_check(self):
        html_path = REPO_ROOT / "client" / "index.html"
        blocks = extract_client_module_js(html_path)
        self.assertGreater(len(blocks), 0, "Expected at least one <script type='module'> in client/index.html")
        for idx, block in enumerate(blocks):
            res = run_node_check(block, suffix=f".block{idx}.mjs")
            self.assertEqual(res.returncode, 0, f"node --check failed on client/index.html module {idx}:\n{res.stderr}")

        js_dir = REPO_ROOT / "client" / "js"
        if js_dir.is_dir():
            for js_file in sorted(js_dir.glob("*.js")):
                res = run_node_file_check(js_file)
                self.assertEqual(res.returncode, 0, f"node --check failed on {js_file}:\n{res.stderr}")

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_neutral_intensity_1_has_no_active_vfx(self):
        tags = require_module(self, "riko.tags")
        to_visual = require_attr(self, tags, "emotion_to_visual_state", "riko.tags")
        state = to_visual("neutral", 1)
        vfx = _extract_vfx_name(state)
        self.assertIn(vfx, (None, "", "none"), f"neutral:1 should not trigger active anime VFX, got {vfx!r}")

    def test_t2_visual_state_clamps_out_of_bounds_intensity(self):
        tags = require_module(self, "riko.tags")
        to_visual = require_attr(self, tags, "emotion_to_visual_state", "riko.tags")
        s_low = to_visual("angry", 0)
        s_one = to_visual("angry", 1)
        s_high = to_visual("angry", 99)
        s_three = to_visual("angry", 3)
        self.assertAlmostEqual(_extract_primary_weight(s_low), _extract_primary_weight(s_one), places=5)
        self.assertAlmostEqual(_extract_primary_weight(s_high), _extract_primary_weight(s_three), places=5)

    def test_t2_referenced_client_static_assets_exist(self):
        html = (REPO_ROOT / "client" / "index.html").read_text(encoding="utf-8")
        refs = re.findall(r"""['"](/+(?:animations/vrma|vfx)/[^'"?#]+)['"]""", html)
        for rel in refs:
            clean_rel = rel.lstrip("/")
            if "${" in clean_rel:
                continue
            target = REPO_ROOT / "client" / clean_rel
            self.assertTrue(target.exists(), f"client/index.html references missing asset: {target}")

    def test_t2_viewer_legacy_play_call_without_r1_kwargs_compatible(self):
        with IsolatedMisoWorkspace() as ws:
            wav_path = ws.root / "client" / "audio" / "legacy.wav"
            wav_path.write_bytes(make_minimal_wav_bytes(0.12))
            from riko import viewer

            with MockViewerServer(ws) as srv:
                srv.touch_page()
                # Legacy call signature with only (wav_path, emotion=...)
                with mock.patch.object(viewer._finished, "wait", return_value=True):
                    viewer.play(wav_path, emotion="happy")
                clip = srv.get_next()
                self.assertEqual(clip["emotion"], "happy")
                self.assertIn("audio", clip)

    def test_t2_procedural_locomotion_hooks_preserved_in_client(self):
        html = (REPO_ROOT / "client" / "index.html").read_text(encoding="utf-8")
        self.assertIn("triggerLocomotionAction", html)
        for action in ("walk", "sit", "dance", "stretch", "spin", "idle"):
            self.assertIn(action, html, f"client/index.html missing locomotion state '{action}'")


if __name__ == "__main__":
    unittest.main()
