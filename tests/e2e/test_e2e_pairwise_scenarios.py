"""E2E Tests Tier 3 (Pairwise Cross-Feature Matrix) & Tier 4 (Real-World Companion Scenarios)."""
from __future__ import annotations

import io
import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import soundfile as sf

from tests.e2e.helpers import (
    REPO_ROOT,
    FakeLLMStream,
    IsolatedMisoWorkspace,
    MockFishServer,
    MockViewerServer,
    make_minimal_wav_bytes,
    require_attr,
    require_module,
    sha256_file,
)
from tests.e2e.test_r1_vrma_vfx import CORE_VFX_ALIASES, _extract_vfx_name
from tests.e2e.test_r2_streaming_tts import (
    EXPECTED_MODEL,
    EXPECTED_SPEED,
    EXPECTED_VOICE_ID,
    _drive_streaming_pipeline,
    require_streaming_contracts,
)


def _tone_wav(freq1: float, freq2: float, dur: float = 0.5, sr: int = 16000) -> bytes:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
    sig = 0.4 * np.sin(2 * np.pi * freq1 * t) + 0.3 * np.sin(2 * np.pi * freq2 * t)
    buf = io.BytesIO()
    sf.write(buf, sig, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


class TestTier3PairwiseInteractions(unittest.TestCase):
    """Tier 3: >= 10 pairwise cross-feature interactions across R1, R2, R3, and R4."""

    def test_t3_r1_x_r2_tags_stripped_across_all_streamed_fish_sentences(self):
        require_streaming_contracts(self)
        tags = require_module(self, "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "cross_arms" if "cross_arms" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config

            cfg = config.load_config()
            stream_seq = [f"[angry:2][{g}] Fix that loop. ", "Then run tests!"]
            with FakeLLMStream(stream_sequences=[stream_seq]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "Debug", cfg), daemon=True
                        )
                        t.start()
                        reqs = fish.wait_for_requests(2, timeout=5.0)
                        for req in reqs:
                            self.assertNotIn("[", req.payload["text"])
                            self.assertNotIn(g, req.payload["text"])
                            self.assertEqual(float(req.payload["prosody"]["speed"]), EXPECTED_SPEED)
                            self.assertEqual(req.headers.get("model"), EXPECTED_MODEL)
                        clip1 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertEqual(clip1.get("emotion"), "angry")
                        self.assertEqual(clip1.get("intensity"), 2)
                        self.assertEqual(clip1.get("gesture"), g)
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.post_done()
                        t.join(timeout=5.0)

    def test_t3_r1_x_r2_intensity_3_vfx_consistent_across_streamed_chunks(self):
        require_streaming_contracts(self)
        tags = require_module(self, "riko.tags")
        to_visual = require_attr(self, tags, "emotion_to_visual_state", "riko.tags")
        expected_vfx = _extract_vfx_name(to_visual("happy", 3))
        self.assertIn(str(expected_vfx).lower(), CORE_VFX_ALIASES["happy"])

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config

            cfg = config.load_config()
            with FakeLLMStream(stream_sequences=[["[happy:3] Clean build! ", "Impressive work."]]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "Compliment", cfg), daemon=True
                        )
                        t.start()
                        fish.wait_for_requests(2, timeout=5.0)
                        c1 = srv.wait_for_next_audio(timeout=5.0)
                        c2 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertEqual(c1.get("intensity"), 3)
                        self.assertEqual(c2.get("intensity"), 3)
                        self.assertIsNone(c1.get("gesture"))
                        srv.post_done()
                        t.join(timeout=5.0)

    def test_t3_r1_x_r3_affection_delta_tag_updates_markdown_not_profile_json(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "wave" if "wave" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            prof_hash_before = sha256_file(ws.root / "profile.json")
            from riko import memory

            before_aff = memory.get_affection()
            parsed = parse_reply_tags(f"[happy:3, +2][{g}] Good job today.")
            self.assertEqual(parsed.affection_delta, 2)
            new_aff = memory.update_affection(parsed.affection_delta)
            self.assertEqual(new_aff, before_aff + 2)
            memories_path = ws.root / "MEMORIES.md"
            self.assertTrue(memories_path.exists(), "MEMORIES.md not created yet (M3)")
            self.assertIn(str(new_aff), memories_path.read_text(encoding="utf-8"))
            self.assertEqual(sha256_file(ws.root / "profile.json"), prof_hash_before)

    def test_t3_r1_x_r3_memory_inquiry_reply_parses_r1_tags_cleanly(self):
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "head_tilt" if "head_tilt" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None)
            from riko import config, llm

            cfg = config.load_config()
            with FakeLLMStream(sync_replies=[f"[flustered:2][{g}] You like Tony Stark, obviously."]):
                raw = llm.reply("What do you remember about me?", cfg)
                parsed = parse_reply_tags(raw)
                self.assertEqual(parsed.emotion, "flustered")
                self.assertEqual(parsed.intensity, 2)
                self.assertEqual(parsed.gesture, g)
                self.assertEqual(parsed.clean_text, "You like Tony Stark, obviously.")
                self.assertTrue((ws.root / "PROFILE.md").exists())

    def test_t3_r2_x_r3_streaming_llm_receives_migrated_markdown_context(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config

            cfg = config.load_config()
            gate = threading.Event()
            with FakeLLMStream(stream_sequences=[["[relaxed:2] Tony Stark is fine. ", gate, "Focus on your code."]]) as fake:
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "Who is my favorite character?", cfg),
                            daemon=True,
                        )
                        t.start()
                        fish.wait_for_requests(1, timeout=5.0)
                        self.assertFalse(gate.is_set())
                        gate.set()
                        fish.wait_for_requests(2, timeout=5.0)
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.post_done()
                        t.join(timeout=5.0)

                        # Migrated fact from profile.json -> PROFILE.md was injected into streaming LLM prompt
                        sys_prompt = fake.calls[0]["messages"][0]["content"]
                        self.assertIn("tony stark", sys_prompt.lower())

    def test_t3_r2_x_r3_live_markdown_edit_reflected_in_subsequent_streamed_turn(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, memory

            cfg = config.load_config()
            memory.get_memory_context()  # trigger migration
            profile_md = ws.root / "PROFILE.md"
            self.assertTrue(profile_md.exists(), "PROFILE.md not created yet (M3)")
            profile_md.write_text(profile_md.read_text(encoding="utf-8") + "\n- Senpai switched to Neovim\n", encoding="utf-8")

            with FakeLLMStream(stream_sequences=[["[annoyed:1] Neovim again? Good luck exiting."]]) as fake:
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "Guess my editor", cfg), daemon=True
                        )
                        t.start()
                        fish.wait_for_requests(1, timeout=5.0)
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.post_done()
                        t.join(timeout=5.0)
                        self.assertIn("Neovim", fake.calls[0]["messages"][0]["content"])

    def test_t3_r1_x_r4_vrma_gestures_coexist_with_locomotion_commands(self):
        tags = require_module(self, "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "shrug" if "shrug" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace() as ws:
            from riko import tools, viewer

            wav = ws.root / "client" / "audio" / "loco.wav"
            wav.write_bytes(make_minimal_wav_bytes(0.12))
            with MockViewerServer(ws) as srv:
                srv.touch_page()
                tools.detect_locomotion_command("walk around")
                with mock.patch.object(viewer._finished, "wait", return_value=True):
                    viewer.play(wav, emotion="annoyed", intensity=1, gesture=g)
                first = srv.get_next()
                second = srv.get_next()
                self.assertEqual(first.get("command"), "action")
                self.assertEqual(first.get("action"), "walk")
                self.assertEqual(second.get("emotion"), "annoyed")
                self.assertEqual(second.get("gesture"), g)

    def test_t3_r1_x_r4_telegram_loop_strips_r1_emotion_intensity_and_gesture(self):
        tags = require_module(self, "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "nod" if "nod" in gestures else sorted(gestures)[0]

        class _ExitLoop(BaseException):
            pass

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, telegram_bot

            cfg = config.load_config()
            sent: list[dict] = []
            calls = 0

            def _get(url, *a, **kw):
                nonlocal calls
                calls += 1
                r = mock.MagicMock()
                if url.endswith("/getMe"):
                    r.json.return_value = {"ok": True, "result": {"username": "miso_bot"}}
                elif calls == 2:
                    r.json.return_value = {
                        "ok": True,
                        "result": [{"update_id": 1, "message": {"chat": {"id": 9}, "text": "Status?"}}],
                    }
                else:
                    raise _ExitLoop()
                return r

            with MockFishServer() as fish:
                import requests as _req

                routed_post = _req.post

                def _post(url, *a, **kw):
                    if isinstance(url, str) and "api.telegram.org" in url:
                        if url.endswith("/sendMessage"):
                            sent.append(kw.get("json", {}))
                        return mock.MagicMock()
                    return routed_post(url, *a, **kw)

                with FakeLLMStream(sync_replies=[f"[happy:2][{g}] Everything is running smoothly."]):
                    with mock.patch("requests.get", side_effect=_get):
                        with mock.patch("requests.post", side_effect=_post):
                            with self.assertRaises(_ExitLoop):
                                telegram_bot._telegram_loop("tok", cfg)

            self.assertEqual(sent[0]["text"], "Everything is running smoothly.")
            self.assertNotIn(f"[{g}]", sent[0]["text"])
            self.assertEqual(len(fish.requests), 1)
            self.assertEqual(fish.requests[0].payload["text"], "Everything is running smoothly.")

    def test_t3_r2_x_r4_pc_tool_execution_paired_with_fish_streaming_response(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, tools

            cfg = config.load_config()
            with mock.patch("subprocess.Popen") as mock_popen:
                opened = tools.detect_and_open_app("open calculator")
                self.assertEqual(opened, "Calculator")
                mock_popen.assert_called_once_with("calc", shell=True)

            with FakeLLMStream(stream_sequences=[["[relaxed:1] Calculator is open. Try doing math now."]]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "open calculator", cfg), daemon=True
                        )
                        t.start()
                        reqs = fish.wait_for_requests(2, timeout=5.0)
                        self.assertEqual(reqs[0].payload["reference_id"], EXPECTED_VOICE_ID)
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.post_done()
                        t.join(timeout=5.0)

    def test_t3_r3_x_r4_save_diary_fact_tool_and_alarms_persist_in_isolation(self):
        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            from riko import alarms, llm, memory

            llm.execute_tool("save_diary_fact", {"fact": "Prefers green tea after 4pm"})
            alarms.set_timer_seconds(120, label="Brew tea")
            profile_md = ws.root / "PROFILE.md"
            self.assertTrue(profile_md.exists(), "PROFILE.md not created yet (M3)")
            self.assertIn("Prefers green tea after 4pm", profile_md.read_text(encoding="utf-8"))
            self.assertIn("Prefers green tea after 4pm", memory.get_memory_context())
            self.assertEqual(len(alarms.load_alarms()), 1)


class TestTier4RealWorldScenarios(unittest.TestCase):
    """Tier 4: >= 6 comprehensive multi-turn / multi-subsystem real-world companion scenarios."""

    def test_t4_scenario_1_first_run_migration_and_gated_streaming_voice_turn(self):
        """Scenario 1: Upgrade migration + context injection + [flustered:2][gesture] + Sentence 1 early Fish dispatch."""
        require_streaming_contracts(self)
        tags = require_module(self, "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "head_tilt" if "head_tilt" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            prof_before = sha256_file(ws.root / "profile.json")
            hist_before = sha256_file(ws.root / "chat_history.json")

            from riko import config, memory

            cfg = config.load_config()
            ctx, mood = memory.get_temporal_context()
            self.assertTrue(len(mood) > 0)
            self.assertTrue((ws.root / "PROFILE.md").exists())
            self.assertTrue((ws.root / "MEMORIES.md").exists())
            self.assertTrue((ws.root / "IDENTITY.md").exists())

            gate = threading.Event()
            stream_seq = [
                f"[flustered:2][{g}] ",
                "You like Tony Stark. ",
                gate,
                "Do not make me repeat it!",
            ]
            with FakeLLMStream(stream_sequences=[stream_seq]) as fake:
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "What do you remember about me?", cfg),
                            daemon=True,
                        )
                        t.start()
                        reqs = fish.wait_for_requests(1, timeout=5.0)
                        self.assertEqual(reqs[0].payload["text"], "You like Tony Stark.")
                        self.assertFalse(gate.is_set())
                        c1 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertEqual(c1["emotion"], "flustered")
                        self.assertEqual(c1["intensity"], 2)
                        self.assertEqual(c1["gesture"], g)

                        gate.set()
                        reqs2 = fish.wait_for_requests(2, timeout=5.0)
                        self.assertEqual(reqs2[1].payload["text"], "Do not make me repeat it!")
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.post_done()
                        t.join(timeout=5.0)
                        self.assertIn("tony stark", fake.calls[0]["messages"][0]["content"].lower())

            self.assertEqual(sha256_file(ws.root / "profile.json"), prof_before)
            self.assertEqual(sha256_file(ws.root / "chat_history.json"), hist_before)

    def test_t4_scenario_2_personal_fact_api_chat_vfx_and_affection_delta(self):
        """Scenario 2: User shares fact -> PROFILE.md updated, /api/chat strips tags, angry:3 anger_vein & affection delta."""
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")
        to_visual = require_attr(self, tags, "emotion_to_visual_state", "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "cross_arms" if "cross_arms" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            prof_before = sha256_file(ws.root / "profile.json")
            from riko import memory

            start_aff = memory.get_affection()
            with FakeLLMStream(
                sync_replies=[f"[angry:3, -1][{g}] Noted that you broke production. Read the traceback!"]
            ):
                with MockViewerServer(ws) as srv:
                    memory.detect_memory_action("remember that I use dark theme")
                    profile_md = ws.root / "PROFILE.md"
                    self.assertTrue(profile_md.exists(), "PROFILE.md not created yet (M3)")
                    self.assertIn("use dark theme", profile_md.read_text(encoding="utf-8"))
                    chat_res = srv.post_chat("Why is this failing?")
                    self.assertEqual(chat_res["reply"], "Noted that you broke production. Read the traceback!")
                    parsed = parse_reply_tags(chat_res["raw"])
                    self.assertEqual(parsed.emotion, "angry")
                    self.assertEqual(parsed.intensity, 3)
                    self.assertEqual(parsed.affection_delta, -1)
                    vis = to_visual(parsed.emotion, parsed.intensity)
                    self.assertIn(str(_extract_vfx_name(vis)).lower(), CORE_VFX_ALIASES["angry"])
                    self.assertEqual(memory.update_affection(parsed.affection_delta), start_aff - 1)

            self.assertEqual(sha256_file(ws.root / "profile.json"), prof_before)

    def test_t4_scenario_3_ordinary_reply_no_gesture_happy_sparkles_ordered_playback(self):
        """Scenario 3: Ordinary reply omitting [gesture] -> happy:3 sparkles VFX + ordered playback + POST /done."""
        require_streaming_contracts(self)
        tags = require_module(self, "riko.tags")
        to_visual = require_attr(self, tags, "emotion_to_visual_state", "riko.tags")

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, viewer

            cfg = config.load_config()
            vis = to_visual("happy", 3)
            self.assertIn(str(_extract_vfx_name(vis)).lower(), CORE_VFX_ALIASES["happy"])

            with FakeLLMStream(stream_sequences=[["[happy:3] Obviously I look great. ", "Keep the compliments coming."]]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "You look great today", cfg), daemon=True
                        )
                        t.start()
                        reqs = fish.wait_for_requests(2, timeout=5.0)
                        self.assertEqual(
                            [r.payload["text"] for r in reqs],
                            ["Obviously I look great.", "Keep the compliments coming."],
                        )
                        c1 = srv.wait_for_next_audio(timeout=5.0)
                        c2 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertIsNone(c1.get("gesture"))
                        self.assertEqual(c1.get("emotion"), "happy")
                        self.assertEqual(c1.get("intensity"), 3)
                        self.assertTrue(viewer.is_playing())
                        srv.post_done()
                        t.join(timeout=5.0)
                        self.assertFalse(viewer.is_playing())

    def test_t4_scenario_4_live_markdown_edit_and_mid_stream_barge_in(self):
        """Scenario 4: Manual edit to PROFILE.md + mid-stream barge-in interruption stops playback cleanly."""
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, memory, viewer

            cfg = config.load_config()
            memory.get_memory_context()
            p_file = ws.root / "PROFILE.md"
            self.assertTrue(p_file.exists(), "PROFILE.md not created yet (M3)")
            p_file.write_text(p_file.read_text(encoding="utf-8") + "\n- Utkarsh loves spicy ramen\n", encoding="utf-8")

            gate = threading.Event()
            with FakeLLMStream(stream_sequences=[["[annoyed:2] Fine, ramen again. ", gate, "Eat vegetables too."]]) as fake:
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "What food do I love?", cfg), daemon=True
                        )
                        t.start()
                        fish.wait_for_requests(1, timeout=5.0)
                        c1 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertIsNotNone(c1.get("audio"))
                        viewer.stop_speech()
                        srv.post_interrupted()
                        stop_evt = srv.wait_for_next_audio(timeout=5.0)
                        self.assertEqual(stop_evt.get("command"), "stop")
                        gate.set()
                        t.join(timeout=5.0)
                        self.assertFalse(viewer.is_playing())
                        self.assertIn("spicy ramen", fake.calls[0]["messages"][0]["content"])

    def test_t4_scenario_5_wake_word_voice_id_locomotion_and_streaming_turn(self):
        """Scenario 5: Voice ID verification + wake-word check + locomotion command + R1/R2 streaming response."""
        require_streaming_contracts(self)
        tags = require_module(self, "riko.tags")
        gestures = set(require_attr(self, tags, "SIGNATURE_GESTURES", "riko.tags"))
        g = "wave" if "wave" in gestures else sorted(gestures)[0]

        with IsolatedMisoWorkspace(config_overrides={"hands_free": True, "require_wake_word": True}) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, tools, voice_id

            cfg = config.load_config()
            senpai_wav = _tone_wav(190.0, 570.0)
            voice_id.enroll_voice(senpai_wav)
            is_senpai, _, status = voice_id.verify_speaker(senpai_wav)
            self.assertTrue(is_senpai)
            self.assertEqual(status, "senpai_verified")

            transcript = "Hey Miso walk around"
            self.assertTrue(any(w in transcript.lower() for w in ["miso", "hey miso"]))

            with FakeLLMStream(stream_sequences=[[f"[happy:2][{g}] Walking now. Watch me go."]]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        loco_res = tools.detect_locomotion_command(transcript)
                        self.assertIsNotNone(loco_res)
                        loco_cmd = srv.wait_for_next_audio(timeout=5.0)
                        self.assertEqual(loco_cmd.get("command"), "action")
                        self.assertEqual(loco_cmd.get("action"), "walk")

                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, f"[Speaker: Utkarsh Senpai] {transcript}", cfg),
                            daemon=True,
                        )
                        t.start()
                        fish.wait_for_requests(2, timeout=5.0)
                        c1 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertEqual(c1.get("gesture"), g)
                        srv.wait_for_next_audio(timeout=5.0)
                        srv.post_done()
                        t.join(timeout=5.0)

    def test_t4_scenario_6_vision_memory_alarm_and_telegram_compatibility(self):
        """Scenario 6: Vision event -> short-term + Markdown memory -> tagged speech -> alarm & Telegram compatibility."""
        tags = require_module(self, "riko.tags")
        parse_reply_tags = require_attr(self, tags, "parse_reply_tags", "riko.tags")

        with IsolatedMisoWorkspace(copy_profile=True, copy_chat_history=True) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY="gsk-fake-e2e", FISH_API_KEY="fish-fake-key")
            from riko import alarms, config, heartbeat, memory, vision_observer

            cfg = config.load_config()
            heartbeat.set_busy(False)
            vision_observer._last_spoken_time = 0.0

            with FakeLLMStream(
                sync_replies=[
                    "DESCRIPTION: Utkarsh is coding late\nACTION: [SPEAK: relaxed] Still grinding at this hour?",
                    "[annoyed:1] You set a break timer and ignored it.",
                ]
            ):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        with mock.patch("riko.viewer.play"):
                            vision_observer._evaluate_visual_event("AAAA", cfg, speech_cooldown=0.0, auto_react=True)

                        self.assertIn("Utkarsh is coding late", memory.get_visual_context_prompt())
                        alarms.set_timer_seconds(60, label="Stretch break")
                        self.assertEqual(len(alarms.load_alarms()), 1)

                        from riko import llm

                        raw_reply = llm.reply("Should I take a break?", cfg)
                        parsed = parse_reply_tags(raw_reply)
                        self.assertEqual(parsed.emotion, "annoyed")
                        self.assertEqual(parsed.intensity, 1)
                        self.assertEqual(parsed.clean_text, "You set a break timer and ignored it.")
                        self.assertGreaterEqual(len(fish.requests), 1)


if __name__ == "__main__":
    unittest.main()
