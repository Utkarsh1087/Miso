"""Unit tests for R1 unified [emotion:intensity][gesture] tagging and backend callers."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import queue
import re
import threading
import unittest
from unittest.mock import MagicMock, patch

import yaml

from riko import llm, memory, tags, tts, viewer

ROOT = Path(__file__).resolve().parents[2]


class TestR1Tags(unittest.TestCase):
    def test_signature_gestures_inventory(self):
        self.assertLessEqual(len(tags.SIGNATURE_GESTURES), 12)
        for expected in ("shrug", "cross_arms", "facepalm", "head_tilt", "point", "wave", "nod", "shake_head"):
            self.assertIn(expected, tags.SIGNATURE_GESTURES)
        self.assertNotIn("idle", tags.SIGNATURE_GESTURES)

    def test_parse_emotion_intensity_and_gesture(self):
        parsed = tags.parse_reply_tags(
            "[angry:2][cross_arms] Because my creator did a terrible job programming me."
        )
        self.assertEqual(parsed.emotion, "angry")
        self.assertEqual(parsed.intensity, 2)
        self.assertEqual(parsed.gesture, "cross_arms")
        self.assertEqual(parsed.vfx, "anger_vein")
        self.assertEqual(parsed.clean_text, "Because my creator did a terrible job programming me.")

    def test_parse_without_gesture(self):
        parsed = tags.parse_reply_tags("[annoyed:1] Stop clicking that.")
        self.assertEqual(parsed.emotion, "annoyed")
        self.assertEqual(parsed.intensity, 1)
        self.assertIsNone(parsed.gesture)
        self.assertEqual(parsed.vfx, "sweatdrop")
        self.assertEqual(parsed.clean_text, "Stop clicking that.")

    def test_parse_with_affection_delta_and_gesture(self):
        parsed = tags.parse_reply_tags("[happy:3, +2][wave] Hey there!")
        self.assertEqual(parsed.emotion, "happy")
        self.assertEqual(parsed.intensity, 3)
        self.assertEqual(parsed.gesture, "wave")
        self.assertEqual(parsed.affection_delta, 2)
        self.assertEqual(parsed.vfx, "sparkles")
        self.assertEqual(parsed.clean_text, "Hey there!")

    def test_intensity_clamping_and_legacy_defaults(self):
        self.assertEqual(tags.parse_reply_tags("[angry:9] Too loud!").intensity, 3)
        self.assertEqual(tags.parse_reply_tags("[happy:0] Mild smile.").intensity, 1)
        self.assertEqual(tags.parse_reply_tags("[sad:-3] Sigh.").intensity, 1)
        legacy = tags.parse_reply_tags("[angry] Legacy format.")
        self.assertEqual(legacy.emotion, "angry")
        self.assertEqual(legacy.intensity, 2)
        self.assertIsNone(legacy.gesture)
        self.assertEqual(legacy.clean_text, "Legacy format.")

    def test_smug_disambiguation_and_gesture_first_order(self):
        # [relaxed:2][smug] -> emotion=relaxed, gesture=smug
        p1 = tags.parse_reply_tags("[relaxed:2][smug] Obviously.")
        self.assertEqual(p1.emotion, "relaxed")
        self.assertEqual(p1.intensity, 2)
        self.assertEqual(p1.gesture, "smug")
        self.assertEqual(p1.clean_text, "Obviously.")

        # [smug:3] -> emotion=smug, gesture=None
        p2 = tags.parse_reply_tags("[smug:3] Naturally.")
        self.assertEqual(p2.emotion, "smug")
        self.assertEqual(p2.intensity, 3)
        self.assertIsNone(p2.gesture)
        self.assertEqual(p2.vfx, "kira_star")

        # [cross_arms][angry:2] -> gesture-first still resolves both
        p3 = tags.parse_reply_tags("[cross_arms][angry:2] Seriously?")
        self.assertEqual(p3.emotion, "angry")
        self.assertEqual(p3.intensity, 2)
        self.assertEqual(p3.gesture, "cross_arms")
        self.assertEqual(p3.clean_text, "Seriously?")

    def test_unknown_gesture_untagged_and_truncated_tags(self):
        p1 = tags.parse_reply_tags("[flustered:2][unknown_flip] Wh-what?!")
        self.assertEqual(p1.emotion, "flustered")
        self.assertEqual(p1.intensity, 2)
        self.assertIsNone(p1.gesture)
        self.assertEqual(p1.vfx, "blush_lines")
        self.assertEqual(p1.clean_text, "Wh-what?!")

        p2 = tags.parse_reply_tags("Plain reply without tags")
        self.assertEqual(p2.emotion, "neutral")
        self.assertEqual(p2.intensity, 1)
        self.assertIsNone(p2.gesture)
        self.assertIsNone(p2.vfx)
        self.assertEqual(p2.clean_text, "Plain reply without tags")

        self.assertEqual(tags.strip_reply_tags("[angry:2][cross_arms]"), "")
        self.assertEqual(tags.strip_reply_tags("[angry:2"), "")

    def test_deterministic_visual_state_and_monotonic_blendshapes(self):
        expected_vfx = {
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
        for emo, vfx_id in expected_vfx.items():
            s1 = tags.emotion_to_visual_state(emo, 1)
            s2 = tags.emotion_to_visual_state(emo, 2)
            s3 = tags.emotion_to_visual_state(emo, 3)
            self.assertEqual(s1, tags.emotion_to_visual_state(emo, 1))
            self.assertEqual(s2["vfx"], vfx_id)
            if emo != "neutral":
                self.assertEqual(set(s1["blendshapes"]), set(s2["blendshapes"]))
                self.assertEqual(set(s2["blendshapes"]), set(s3["blendshapes"]))
                for k in s1["blendshapes"]:
                    self.assertLess(s1["blendshapes"][k], s2["blendshapes"][k])
                    self.assertLess(s2["blendshapes"][k], s3["blendshapes"][k])
                    self.assertGreaterEqual(s1["blendshapes"][k], 0.0)
                    self.assertLessEqual(s3["blendshapes"][k], 1.0)

    def test_tts_clean_for_speech_strips_r1_tags(self):
        cleaned = tts.clean_for_speech("[angry:2][cross_arms] Fix your own bug.")
        self.assertEqual(cleaned, "Fix your own bug.")

    def test_affection_delta_does_not_parse_intensity_as_delta(self):
        with patch.object(memory, "load_profile", return_value={"facts": [], "affection": 20}), \
             patch.object(memory, "save_profile") as mock_save:
            memory.apply_affection_delta("happy:2")
            mock_save.assert_not_called()

            memory.apply_affection_delta("happy:2, +2")
            mock_save.assert_called_once()
            saved_profile = mock_save.call_args[0][0]
            self.assertEqual(saved_profile["affection"], 22)

    def test_viewer_play_and_play_sentences_payload(self):
        fake_wav = Path("riko_test.wav")
        fake_info = MagicMock(duration=0.1)

        with patch.object(viewer, "_clips", queue.Queue()), \
             patch.object(viewer, "_page_last_seen", 10**12), \
             patch.object(viewer.sf, "info", return_value=fake_info), \
             patch.object(viewer._finished, "wait", return_value=True):
            viewer.play(fake_wav, emotion="angry", intensity=3, gesture="cross_arms", text="Hmph.")
            item = viewer._clips.get_nowait()
            self.assertEqual(item["emotion"], "angry")
            self.assertEqual(item["intensity"], 3)
            self.assertEqual(item["gesture"], "cross_arms")
            self.assertEqual(item["vfx"], "anger_vein")
            self.assertEqual(item["text"], "Hmph.")

        with patch.object(viewer, "_clips", queue.Queue()), \
             patch.object(viewer, "_page_last_seen", 10**12), \
             patch.object(viewer.sf, "info", return_value=fake_info), \
             patch.object(viewer.tts, "speak", side_effect=[Path("c0.wav"), Path("c1.wav")]), \
             patch.object(viewer._finished, "wait", return_value=True):
            viewer.play_sentences(
                ["First sentence.", "Second sentence."],
                emotion="flustered",
                intensity=2,
                gesture="head_tilt",
            )
            c0 = viewer._clips.get_nowait()
            c1 = viewer._clips.get_nowait()
            self.assertEqual(c0["gesture"], "head_tilt")
            self.assertIsNone(c1["gesture"])
            self.assertEqual(c0["vfx"], "blush_lines")
            self.assertEqual(c1["vfx"], "blush_lines")
            self.assertEqual(c0["intensity"], 2)
            self.assertEqual(c1["intensity"], 2)
            self.assertEqual(c0["text"], "First sentence.")
            self.assertEqual(c1["text"], "Second sentence.")

    def test_viewer_http_next_and_api_chat_endpoints(self):
        from functools import partial
        from http.server import ThreadingHTTPServer

        with patch.object(viewer, "_clips", queue.Queue()):
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                partial(viewer._Handler, directory=str(ROOT / "client")),
            )
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", "/next")
                resp = conn.getresponse()
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(
                    body,
                    {"audio": None, "emotion": "neutral", "intensity": 1, "gesture": None, "vfx": None, "text": ""},
                )
                conn.close()

                with patch("riko.llm.reply", return_value="[angry:2][cross_arms] Fix your bug."):
                    for ep in ("/api/chat", "/api/ask"):
                        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                        conn.request(
                            "POST",
                            ep,
                            body=json.dumps({"text": "hello"}),
                            headers={"Content-Type": "application/json"},
                        )
                        resp = conn.getresponse()
                        data = json.loads(resp.read().decode("utf-8"))
                        self.assertEqual(data["reply"], "Fix your bug.")
                        self.assertEqual(data["emotion"], "angry")
                        self.assertEqual(data["intensity"], 2)
                        self.assertEqual(data["gesture"], "cross_arms")
                        self.assertEqual(data["vfx"], "anger_vein")
                        conn.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_llm_fallback_guard_catches_tag_only_output(self):
        fake_msg = MagicMock(content="[angry:2][cross_arms]", tool_calls=None)
        fake_res = MagicMock(choices=[MagicMock(message=fake_msg)])
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_res

        cfg = yaml.safe_load((ROOT / "character_config.yaml").read_text(encoding="utf-8"))
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "GROQ_API_KEY": ""}, clear=False), \
             patch.object(llm, "OpenAI", return_value=fake_client), \
             patch("pathlib.Path.write_text") as mock_write:
            ans = llm.reply("hi", cfg)
            mock_write.assert_called_once()
        parsed = tags.parse_reply_tags(ans)
        self.assertGreaterEqual(len(parsed.clean_text), 4)

    def test_config_and_memory_prompts_and_fish_preserved(self):
        cfg = yaml.safe_load((ROOT / "character_config.yaml").read_text(encoding="utf-8"))
        self.assertIn("[emotion:intensity]", cfg["system_prompt"])
        self.assertIn("[gesture]", cfg["system_prompt"])
        self.assertEqual(cfg["fish"]["voice_id"], "5b05bc2a296046b3ac67577cb787dddc")
        self.assertEqual(cfg["fish"]["model"], "s2.1-pro")
        self.assertIn(float(cfg["fish"]["speed"]), (1.0, 0.88))

        with patch.object(memory, "load_profile", return_value={"facts": [], "affection": 20}):
            ctx = memory.get_memory_context()
            self.assertIn("[emotion:intensity]", ctx)
            tctx, _ = memory.get_temporal_context()
            self.assertIn("[emotion:intensity]", tctx)

    def test_no_legacy_duplicate_tag_regex_parsers(self):
        pattern = re.compile(r"re\.match\([^)]*\[[^\]]+\]")
        files = [ROOT / "main.py", *(ROOT / "riko").glob("*.py")]
        for f in files:
            content = f.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(content), f"Legacy tag regex left in {f}")


if __name__ == "__main__":
    unittest.main()
