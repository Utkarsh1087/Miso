"""E2E Tests for R4: Preservation of PC Tools, Vision, Wake Words, ASR, Voice ID, Alarms, Telegram & Git/Browser Rules (Features F8, F9, F10)."""
from __future__ import annotations

import base64
import copy
import io
import json
import math
import struct
import subprocess
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import soundfile as sf
from PIL import Image

from tests.e2e.helpers import (
    REPO_ROOT,
    FakeLLMStream,
    IsolatedMisoWorkspace,
    MockFishServer,
    MockViewerServer,
    make_minimal_wav_bytes,
    run_node_file_check,
)

EXPECTED_HEAD_SHA = "6f12744c4f8075457fcfca1bf5b09bcb95d59c39"


def _make_tone_wav(freq1: float, freq2: float, duration_s: float = 0.8, sr: int = 16000) -> bytes:
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False, dtype=np.float32)
    sig = 0.4 * np.sin(2 * np.pi * freq1 * t) + 0.3 * np.sin(2 * np.pi * freq2 * t)
    buf = io.BytesIO()
    sf.write(buf, sig, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


class TestF8PCToolsAndLocomotionPreservation(unittest.TestCase):
    """Feature F8: Preservation of PC tools (riko/tools.py, FUNCTION_TOOLS, locomotion)."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_control_media_volume_mute_and_pause_mocked_win32(self):
        from riko import tools

        vk_calls: list[int] = []
        fake_user32 = SimpleNamespace(
            keybd_event=lambda vk, *a: vk_calls.append(vk),
            LockWorkStation=mock.MagicMock(),
        )
        fake_windll = SimpleNamespace(user32=fake_user32)
        fake_wsh = SimpleNamespace(AppActivate=lambda name: False, SendKeys=lambda k: None)
        fake_win32_client = types.ModuleType("win32com.client")
        fake_win32_client.Dispatch = lambda prog: fake_wsh
        fake_win32 = types.ModuleType("win32com")
        fake_win32.client = fake_win32_client

        with mock.patch("ctypes.windll", fake_windll, create=True):
            with mock.patch.dict(sys.modules, {"win32com": fake_win32, "win32com.client": fake_win32_client}):
                res_up = tools.control_media("turn the volume up")
                res_mute = tools.control_media("mute audio")
                res_pause = tools.control_media("pause music")
                self.assertEqual(res_up, "turned the volume up")
                self.assertEqual(res_mute, "toggled mute")
                self.assertEqual(res_pause, "stopped the music and media playback")
                # Each press sends keydown + keyup (5 * 2 = 10 keybd_event calls)
                self.assertEqual(vk_calls.count(0xAF), 10)
                self.assertIn(0xAD, vk_calls)
                self.assertIn(0xB2, vk_calls)
                self.assertIn(0xB3, vk_calls)

    def test_t1_detect_and_open_app_mocked_popen_and_browser(self):
        from riko import tools

        opened_urls: list[str] = []
        with mock.patch("subprocess.Popen") as mock_popen:
            res_app = tools.detect_and_open_app("open notepad")
            self.assertEqual(res_app, "Notepad")
            mock_popen.assert_called_once_with("notepad", shell=True)

        with mock.patch("webbrowser.open", side_effect=lambda u: opened_urls.append(u)):
            res_site = tools.detect_and_open_app("open youtube")
            self.assertEqual(res_site, "Youtube")
            self.assertEqual(opened_urls, ["https://www.youtube.com"])

    def test_t1_detect_and_play_music_and_search_web_mocked_ddgs(self):
        from riko import tools

        opened_urls: list[str] = []

        class _FakeDDGS:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def text(self, query, max_results=3):
                if "site:youtube.com" in query:
                    return [{"href": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Chill Lofi"}]
                return [{"title": "Python Docs", "body": "Official Python documentation"}]

        fake_ddgs_mod = types.ModuleType("ddgs")
        fake_ddgs_mod.DDGS = _FakeDDGS

        with mock.patch.dict(sys.modules, {"ddgs": fake_ddgs_mod}):
            with mock.patch.object(tools, "DDGS", _FakeDDGS):
                with mock.patch("webbrowser.open", side_effect=lambda u: opened_urls.append(u)):
                    music_res = tools.detect_and_play_music("play lofi on youtube")
                    self.assertIsNotNone(music_res)
                    self.assertIn("YouTube", music_res)
                    self.assertEqual(opened_urls, ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])

                search_res = tools.search_web("search for Python")
                self.assertIn("Python Docs", search_res)

    def test_t1_minigames_avatar_and_voice_switch_isolated(self):
        from riko import config, tools

        rps = tools.detect_minigame("play rock paper scissors rock")
        coin = tools.detect_minigame("flip a coin")
        dice = tools.detect_minigame("roll a dice")
        self.assertIsNotNone(rps)
        self.assertIn("Flipped a coin", coin)
        self.assertIn("Rolled a 6-sided die", dice)
        self.assertEqual(tools.detect_avatar_switch("switch avatar to nekomimi"), "nekomimi.vrm")

        with IsolatedMisoWorkspace() as ws:
            cfg = copy.deepcopy(config.load_config())
            msg = tools.detect_voice_switch("switch voice to furina", cfg)
            self.assertEqual(msg, "switched voice to Furina")
            self.assertEqual(cfg["fish"]["voice_id"], tools.VOICE_PRESETS["furina"][0])
            temp_cfg_text = (ws.root / "character_config.yaml").read_text(encoding="utf-8")
            self.assertIn(tools.VOICE_PRESETS["furina"][0], temp_cfg_text)

    def test_t1_function_tools_and_locomotion_preserved(self):
        from riko import llm, tools

        tool_names = {t["function"]["name"] for t in llm.FUNCTION_TOOLS}
        self.assertEqual(
            tool_names,
            {
                "play_youtube",
                "open_application",
                "search_internet",
                "control_system_media",
                "save_diary_fact",
                "look_through_camera",
            },
        )
        with IsolatedMisoWorkspace() as ws:
            with MockViewerServer(ws) as srv:
                for cmd, expected_action in [
                    ("walk around", "walk"),
                    ("sit down", "sit"),
                    ("do a dance", "dance"),
                    ("stretch", "stretch"),
                    ("spin around", "spin"),
                    ("come to desktop 2", "switch_display:1"),
                ]:
                    res = tools.detect_locomotion_command(cmd)
                    self.assertIsNotNone(res)
                    item = srv.get_next()
                    self.assertEqual(item.get("command"), "action")
                    self.assertEqual(item.get("action"), expected_action)

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_play_music_stop_guard_blocks_playback(self):
        from riko import tools

        with IsolatedMisoWorkspace():
            for phrase in ("stop playing music", "pause the music", "don't play anything", "mute it"):
                self.assertIsNone(tools.detect_and_play_music(phrase))

    def test_t2_open_app_skips_music_requests_and_sanitizes_target(self):
        from riko import tools

        self.assertIsNone(tools.detect_and_open_app("open some music"))
        with mock.patch("subprocess.Popen") as mock_popen:
            res = tools.detect_and_open_app("open mycustomapp; echo hi")
            self.assertIsNotNone(res)
            called_cmd = mock_popen.call_args[0][0]
            self.assertNotIn(";", called_cmd)

    def test_t2_locomotion_ignores_bracketed_system_prompts(self):
        from riko import tools

        with mock.patch("riko.viewer.trigger_action") as mock_trig:
            self.assertIsNone(tools.detect_locomotion_command("[System Event: walk around]"))
            self.assertIsNone(tools.detect_locomotion_command("situation: dance"))
            mock_trig.assert_not_called()

    def test_t2_control_media_screenshot_save_isolated(self):
        from riko import tools

        img = Image.new("RGB", (64, 64), color=(10, 20, 30))
        fake_user32 = SimpleNamespace(keybd_event=lambda *a: None, LockWorkStation=lambda: None)
        fake_windll = SimpleNamespace(user32=fake_user32)

        with IsolatedMisoWorkspace() as ws:
            saved_paths: list[Path] = []
            real_shots_dir = REPO_ROOT / "screenshots"
            before_shots = sorted(real_shots_dir.glob("*.png")) if real_shots_dir.exists() else []

            with mock.patch("ctypes.windll", fake_windll, create=True):
                with mock.patch("PIL.ImageGrab.grab", return_value=img):
                    with mock.patch.dict(sys.modules, {"mss": None}):
                        with mock.patch.object(Image.Image, "save", side_effect=lambda p, *a, **kw: saved_paths.append(Path(p))):
                            res = tools.control_media("take a screenshot and save")
                            self.assertIn("captured and saved a screenshot", res)
                            self.assertEqual(len(saved_paths), 1)
                            # Because Image.save was mocked, zero files were written to real screenshots/
            after_shots = sorted(real_shots_dir.glob("*.png")) if real_shots_dir.exists() else []
            self.assertEqual(before_shots, after_shots)

    def test_t2_llm_tier1_and_tier2_tool_execution_isolated(self):
        from riko import config, llm, memory

        with IsolatedMisoWorkspace(copy_profile=False, copy_chat_history=False) as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None)
            cfg = config.load_config()

            tool_msg = llm.execute_tool("save_diary_fact", {"fact": "Drinks black coffee"})
            self.assertIn("Saved", tool_msg)
            self.assertIn("Drinks black coffee", memory.get_memory_context())

            with mock.patch("riko.tools.search_web", return_value="• FastAPI: async web framework") as mock_search:
                with FakeLLMStream(
                    tool_calls_first_turn=[{"name": "search_internet", "arguments": {"query": "FastAPI async benchmark"}}],
                    sync_replies=["[neutral] FastAPI is an async Python web framework."],
                ):
                    ans = llm.reply("Can you compare FastAPI and Flask for async workloads?", cfg)
                    mock_search.assert_called_once_with("FastAPI async benchmark")
                    self.assertIn("FastAPI", ans)


class TestF9VisionAndBackgroundObserverPreservation(unittest.TestCase):
    """Feature F9: Preservation of live & background vision (vision_observer, face_id, cowatch, sentry, workout, heartbeat, hotkeys)."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_capture_screen_base64_and_triggers(self):
        from riko import tools

        self.assertTrue(tools.should_capture_screen("look at my screen"))
        self.assertTrue(tools.should_capture_screen("check this code"))
        self.assertFalse(tools.should_capture_screen("tell me a joke"))

        raw_img = Image.new("RGB", (1280, 720), color=(40, 80, 120))
        with mock.patch("PIL.ImageGrab.grab", return_value=raw_img):
            with mock.patch.dict(sys.modules, {"mss": None}):
                b64 = tools.capture_screen_base64(max_width=800)
                self.assertIsNotNone(b64)
                decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
                self.assertEqual(decoded.width, 800)
                self.assertEqual(decoded.height, 450)

    def test_t1_capture_camera_base64_and_triggers(self):
        from riko import tools, vision_observer

        self.assertTrue(tools.should_capture_camera("look at me"))
        self.assertTrue(tools.should_capture_camera("what am i wearing"))

        fake_frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        fake_cap = mock.MagicMock()
        fake_cap.isOpened.return_value = True
        fake_cap.read.return_value = (True, fake_frame)

        with mock.patch.object(vision_observer, "get_latest_frame", return_value=None):
            with mock.patch("cv2.VideoCapture", return_value=fake_cap):
                with mock.patch("riko.face_id.identify_person_in_frame", return_value="no_face_detected"):
                    b64 = tools.capture_camera_base64(max_width=320)
                    self.assertIsNotNone(b64)
                    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
                    self.assertEqual(decoded.width, 320)

    def test_t1_vision_observer_logs_visual_memory_and_speaks(self):
        from riko import config, heartbeat, memory, vision_observer

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(GROQ_API_KEY="gsk-fake-e2e", FISH_API_KEY="fish-fake-key")
            cfg = config.load_config()
            heartbeat.set_busy(False)
            vision_observer._last_spoken_time = 0.0

            with FakeLLMStream(
                sync_replies=["DESCRIPTION: Utkarsh sipped water\nACTION: [SPEAK: relaxed] Hydrating for once?"]
            ):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        with mock.patch("riko.viewer.play") as mock_play:
                            vision_observer._evaluate_visual_event(
                                "AAAA", cfg, speech_cooldown=0.0, auto_react=True
                            )
                            events = memory.get_recent_visual_events()
                            self.assertTrue(any("Utkarsh sipped water" in e for e in events))
                            self.assertEqual(len(fish.requests), 1)
                            mock_play.assert_called_once()

    def test_t1_face_id_enroll_and_identify_person_in_frame(self):
        from riko import face_id

        with IsolatedMisoWorkspace() as ws:
            synthetic_face = np.arange(100 * 100 * 3, dtype=np.uint8).reshape(100, 100, 3) % 250
            fake_cap = mock.MagicMock()
            fake_cap.isOpened.return_value = True
            fake_cap.read.return_value = (True, synthetic_face)

            with mock.patch("cv2.VideoCapture", return_value=fake_cap):
                ok, msg = face_id.enroll_face()
                self.assertTrue(ok)
                self.assertTrue((ws.root / "character_files" / "senpai_face.jpg").exists())
                self.assertTrue(face_id.has_enrolled_face())

            fake_cascade = mock.MagicMock()
            fake_cascade.empty.return_value = False
            fake_cascade.detectMultiScale.return_value = np.array([[0, 0, 100, 100]])

            with mock.patch("cv2.data", SimpleNamespace(haarcascades=""), create=True):
                with mock.patch("cv2.CascadeClassifier", return_value=fake_cascade, create=True):
                    status = face_id.identify_person_in_frame(synthetic_face)
                    self.assertIn("senpai_recognized", status)

    def test_t1_cowatch_sentry_workout_heartbeat_and_hotkeys_contracts(self):
        from riko import config, cowatch, heartbeat, hotkeys, sentry, workout

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY="gsk-fake-e2e", FISH_API_KEY="fish-fake-key")
            cfg = config.load_config()

            # Hotkeys
            registered: list[str] = []
            fake_kbd = SimpleNamespace(add_hotkey=lambda combo, fn: registered.append(combo))
            with mock.patch.object(hotkeys, "keyboard", fake_kbd):
                hotkeys.setup_global_hotkeys(on_inspect_screen=lambda: None, on_inspect_camera=lambda: None)
                self.assertEqual(registered, ["ctrl+alt+r", "ctrl+alt+c"])

            # Heartbeat busy state
            heartbeat.set_busy(True)
            self.assertTrue(heartbeat.is_busy())
            heartbeat.set_busy(False)
            self.assertFalse(heartbeat.is_busy())
            heartbeat.mark_interaction()

            # Cowatch, Sentry, Workout synchronous reaction/callout paths
            with MockFishServer() as fish:
                with mock.patch("riko.viewer.play") as mock_play:
                    with FakeLLMStream(sync_replies=["[surprised] What a plot twist!", "[angry] Step away from that PC!"]):
                        cowatch._react_to_screen(Image.new("RGB", (640, 360)), cfg)
                        sentry._analyze_and_alert("AAAA", cfg, "stranger_detected")
                        workout._call_out_rep(5, cfg)
                        self.assertEqual(len(fish.requests), 3)
                        self.assertEqual(mock_play.call_count, 3)

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_should_capture_camera_rejects_screen_keywords(self):
        from riko import tools

        for phrase in ("look at my screen", "watch my monitor", "look at this code window", "check my display"):
            self.assertFalse(tools.should_capture_camera(phrase))

    def test_t2_vision_observer_respects_busy_silent_and_cooldown(self):
        from riko import config, heartbeat, memory, vision_observer

        with IsolatedMisoWorkspace():
            ws_env_cfg = config.load_config()
            with mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk-fake-e2e"}):
                # 1. Busy gate skips speech while still logging observation
                heartbeat.set_busy(True)
                vision_observer._last_spoken_time = 0.0
                try:
                    with FakeLLMStream(sync_replies=["DESCRIPTION: Senpai yawned\nACTION: [SPEAK: relaxed] Sleepy already?"]):
                        with mock.patch("riko.tts.speak") as mock_speak:
                            vision_observer._evaluate_visual_event("AAAA", ws_env_cfg, speech_cooldown=0.0, auto_react=True)
                            mock_speak.assert_not_called()
                            self.assertTrue(any("Senpai yawned" in e for e in memory.get_recent_visual_events()))
                finally:
                    heartbeat.set_busy(False)

                # 2. [SILENT] skips speech
                with FakeLLMStream(sync_replies=["DESCRIPTION: Sitting still\nACTION: [SILENT]"]):
                    with mock.patch("riko.tts.speak") as mock_speak:
                        vision_observer._evaluate_visual_event("AAAA", ws_env_cfg, speech_cooldown=0.0, auto_react=True)
                        mock_speak.assert_not_called()

    def test_t2_face_id_no_face_stranger_and_missing_camera(self):
        from riko import face_id

        with IsolatedMisoWorkspace():
            closed_cap = mock.MagicMock()
            closed_cap.isOpened.return_value = False
            with mock.patch("cv2.VideoCapture", return_value=closed_cap):
                ok, _ = face_id.enroll_face()
                self.assertFalse(ok)

            # No face detected
            empty_cascade = mock.MagicMock()
            empty_cascade.empty.return_value = False
            empty_cascade.detectMultiScale.return_value = ()
            frame = np.zeros((120, 120, 3), dtype=np.uint8)
            with mock.patch("cv2.data", SimpleNamespace(haarcascades=""), create=True):
                with mock.patch("cv2.CascadeClassifier", return_value=empty_cascade, create=True):
                    self.assertEqual(face_id.identify_person_in_frame(frame), "no_face_detected")

            # Stranger detected against enrolled face
            enrolled_pattern = np.zeros((100, 100, 3), dtype=np.uint8)
            enrolled_pattern[:50, :, :] = 255
            face_id.ENROLLED_FACE_PATH.parent.mkdir(parents=True, exist_ok=True)
            import cv2

            cv2.imwrite(str(face_id.ENROLLED_FACE_PATH), enrolled_pattern)
            opposite_pattern = 255 - enrolled_pattern
            box_cascade = mock.MagicMock()
            box_cascade.empty.return_value = False
            box_cascade.detectMultiScale.return_value = np.array([[0, 0, 100, 100]])
            with mock.patch("cv2.data", SimpleNamespace(haarcascades=""), create=True):
                with mock.patch("cv2.CascadeClassifier", return_value=box_cascade, create=True):
                    status = face_id.identify_person_in_frame(opposite_pattern)
                    self.assertIn("stranger_detected", status)

    def test_t2_capture_camera_returns_none_without_webcam(self):
        from riko import tools, vision_observer

        closed_cap = mock.MagicMock()
        closed_cap.isOpened.return_value = False
        with mock.patch.object(vision_observer, "get_latest_frame", return_value=None):
            with mock.patch("cv2.VideoCapture", return_value=closed_cap):
                self.assertIsNone(tools.capture_camera_base64())

    def test_t2_cowatch_sentry_workout_stop_when_inactive(self):
        from riko import config, cowatch, sentry, workout

        with IsolatedMisoWorkspace():
            cfg = config.load_config()
            cowatch._cowatch_active = False
            sentry._sentry_active = False
            workout._workout_active = False
            self.assertIn("not active", cowatch.stop_cowatch())
            self.assertIn("not active", sentry.stop_sentry())
            self.assertIn("not active", workout.stop_workout(cfg))


class TestF10WakeWordAsrVoiceIdAlarmsTelegramGitBrowser(unittest.TestCase):
    """Feature F10: Preservation of wake words, ASR, voice ID, alarms, Telegram, git HEAD=6f12744, no browser."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_asr_transcribe_accepts_valid_english_and_hinglish(self):
        from riko import asr

        fake_client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(
                    create=lambda **kw: SimpleNamespace(text="Hey Miso, kya haal hai?")
                )
            )
        )
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk-fake-e2e"}):
            with mock.patch.object(asr, "OpenAI", return_value=fake_client):
                txt = asr.transcribe(make_minimal_wav_bytes(), {"asr": "groq", "asr_language": "en"})
                self.assertEqual(txt, "Hey Miso, kya haal hai?")

    def test_t1_voice_id_extract_enroll_and_verify_senpai_vs_stranger(self):
        from riko import voice_id

        with IsolatedMisoWorkspace() as ws:
            senpai_wav = _make_tone_wav(180.0, 540.0, duration_s=0.6)
            stranger_wav = _make_tone_wav(1100.0, 2900.0, duration_s=0.6)

            vp = voice_id.extract_voiceprint(senpai_wav)
            self.assertIsNotNone(vp)
            self.assertEqual(vp.shape, (50,))
            self.assertAlmostEqual(float(np.linalg.norm(vp)), 1.0, places=4)

            ok, _ = voice_id.enroll_voice(senpai_wav)
            self.assertTrue(ok)
            self.assertTrue((ws.root / "character_files" / "senpai_voiceprint.npy").exists())

            is_senpai, score_s, status_s = voice_id.verify_speaker(senpai_wav)
            self.assertTrue(is_senpai)
            self.assertEqual(status_s, "senpai_verified")
            self.assertGreaterEqual(score_s, 0.99)

            is_stranger_ok, _, status_x = voice_id.verify_speaker(stranger_wav)
            self.assertFalse(is_stranger_ok)
            self.assertEqual(status_x, "stranger_detected")

    def test_t1_alarms_set_timer_alarm_and_stop_ringing(self):
        from riko import alarms

        with IsolatedMisoWorkspace() as ws:
            msg_timer = alarms.set_timer_seconds(45, label="Tea")
            msg_alarm = alarms.set_alarm_time("07:30 am", label="Morning")
            self.assertIn("45 seconds", msg_timer)
            self.assertIn("07:30 AM", msg_alarm)
            loaded = alarms.load_alarms()
            self.assertEqual(len(loaded), 2)
            self.assertTrue((ws.root / "alarms.json").exists())

            alarms._active_alarm_ringing = True
            self.assertTrue(alarms.is_ringing())
            stop_msg = alarms.stop_ringing()
            self.assertIn("silenced", stop_msg.lower())
            self.assertFalse(alarms.is_ringing())

    def test_t1_main_wake_word_gating_and_speaker_tagging(self):
        import main as riko_main

        with IsolatedMisoWorkspace(
            config_overrides={"hands_free": True, "require_wake_word": True, "barge_in": False}
        ):
            senpai_wav = _make_tone_wav(200.0, 600.0, duration_s=0.5)
            from riko import voice_id

            voice_id.enroll_voice(senpai_wav)

            record_calls = [senpai_wav, senpai_wav]

            def _fake_record(*a, **kw):
                if record_calls:
                    return record_calls.pop(0)
                raise KeyboardInterrupt()

            transcripts = iter(["just random background chatter", "Hey Miso check status"])
            llm_inputs: list[str] = []

            with mock.patch.object(sys, "argv", ["main.py"]):
                with mock.patch("riko.llm.check"), mock.patch("riko.asr.check"), mock.patch("riko.tts.check"):
                    with mock.patch("riko.viewer.start"), mock.patch("riko.heartbeat.start"):
                        with mock.patch("riko.telegram_bot.start_telegram_bridge"), mock.patch("riko.alarms.start"):
                            with mock.patch("riko.vision_observer.start"), mock.patch("riko.hotkeys.setup_global_hotkeys"):
                                with mock.patch("threading.Thread"):
                                    with mock.patch("riko.asr.record", side_effect=_fake_record):
                                        with mock.patch("riko.asr.transcribe", side_effect=lambda *a: next(transcripts)):
                                            with mock.patch(
                                                "riko.llm.reply",
                                                side_effect=lambda txt, cfg, **kw: llm_inputs.append(txt)
                                                or "[neutral] Everything is operational.",
                                            ):
                                                with mock.patch("riko.tts.speak", return_value=Path("x.wav")):
                                                    with mock.patch("riko.viewer.play"):
                                                        with mock.patch("time.sleep"):
                                                            riko_main.main()

            self.assertEqual(len(llm_inputs), 1, "Background chatter without wake word must be gated out")
            self.assertIn("[Speaker: Utkarsh Senpai]", llm_inputs[0])
            self.assertIn("Hey Miso check status", llm_inputs[0])

    def test_t1_git_head_branch_electron_js_and_no_browser_contract(self):
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True).strip()
        self.assertEqual(head, EXPECTED_HEAD_SHA)
        self.assertEqual(branch, "main")

        for js_name in ("electron_pet.js", "preload.js"):
            res = run_node_file_check(REPO_ROOT / js_name)
            self.assertEqual(res.returncode, 0, f"node --check failed on {js_name}:\n{res.stderr}")

        with IsolatedMisoWorkspace():
            import webbrowser

            with self.assertRaises(AssertionError):
                webbrowser.open("https://example.com")

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_asr_transcribe_filters_short_cjk_and_hallucinations(self):
        from riko import asr

        cfg = {"asr": "groq", "asr_language": "en"}
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk-fake-e2e"}):
            for bad_text in (".", "...", "a", "こんにちは", "Thanks for watching.", "Subtitles by"):
                fake_client = SimpleNamespace(
                    audio=SimpleNamespace(
                        transcriptions=SimpleNamespace(
                            create=lambda _t=bad_text, **kw: SimpleNamespace(text=_t)
                        )
                    )
                )
                with mock.patch.object(asr, "OpenAI", return_value=fake_client):
                    self.assertEqual(asr.transcribe(make_minimal_wav_bytes(), cfg), "", f"Failed to filter {bad_text!r}")

    def test_t2_asr_transcribe_ogg_filename_and_error_recovery(self):
        from riko import asr

        seen_files: list[str] = []

        def _create(**kw):
            seen_files.append(kw["file"][0])
            raise RuntimeError("transient network timeout")

        fake_client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create)))
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk-fake-e2e"}):
            with mock.patch.object(asr, "OpenAI", return_value=fake_client):
                res = asr.transcribe(b"OggS\x00\x02fake-ogg", {"asr": "groq", "asr_language": "en"})
                self.assertEqual(res, "")
                self.assertEqual(seen_files, ["voice.ogg"])

    def test_t2_voice_id_silent_short_and_unenrolled_boundaries(self):
        from riko import voice_id

        with IsolatedMisoWorkspace():
            # Unenrolled defaults to permissive not_enrolled
            ok, score, label = voice_id.verify_speaker(np.zeros(8000, dtype=np.float32))
            self.assertTrue(ok)
            self.assertEqual(label, "not_enrolled")

            # Silent / short audio returns None on extract and audio_too_short when enrolled
            self.assertIsNone(voice_id.extract_voiceprint(np.zeros(200, dtype=np.float32)))
            self.assertIsNone(voice_id.extract_voiceprint(np.zeros(8000, dtype=np.float32)))

            senpai_wav = _make_tone_wav(220.0, 660.0, duration_s=0.6)
            voice_id.enroll_voice(senpai_wav)
            ok2, score2, label2 = voice_id.verify_speaker(np.zeros(8000, dtype=np.float32))
            self.assertFalse(ok2)
            self.assertEqual(score2, 0.0)
            self.assertEqual(label2, "audio_too_short")

    def test_t2_alarms_invalid_time_and_corrupt_json_safe(self):
        from riko import alarms

        with IsolatedMisoWorkspace() as ws:
            (ws.root / "alarms.json").write_text("{invalid json", encoding="utf-8")
            self.assertEqual(alarms.load_alarms(), [])
            msg = alarms.set_alarm_time("not a valid time string")
            self.assertIn("Could not parse", msg)

    def test_t2_telegram_bridge_without_token_and_single_update_loop(self):
        from riko import config, telegram_bot

        class _ExitLoop(BaseException):
            pass

        with IsolatedMisoWorkspace() as ws:
            ws.set_env(TELEGRAM_BOT_TOKEN=None, OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            cfg = config.load_config()
            with mock.patch("threading.Thread") as mock_thread:
                telegram_bot.start_telegram_bridge(cfg)
                mock_thread.assert_not_called()

            posted_messages: list[dict] = []
            get_calls = 0

            def _fake_get(url, *a, **kw):
                nonlocal get_calls
                get_calls += 1
                resp = mock.MagicMock()
                if url.endswith("/getMe"):
                    resp.json.return_value = {"ok": True, "result": {"username": "miso_test_bot"}}
                elif url.endswith("/getUpdates"):
                    if get_calls == 2:
                        resp.json.return_value = {
                            "ok": True,
                            "result": [{"update_id": 101, "message": {"chat": {"id": 42}, "text": "Hi Miso"}}],
                        }
                    else:
                        raise _ExitLoop()
                return resp

            def _fake_post(url, *a, **kw):
                if url.endswith("/sendMessage"):
                    posted_messages.append(kw.get("json", {}))
                return mock.MagicMock()

            with MockFishServer():
                with FakeLLMStream(sync_replies=["[happy] Telegram works fine."]):
                    with mock.patch("requests.get", side_effect=_fake_get):
                        with mock.patch("requests.post", side_effect=_fake_post):
                            with self.assertRaises(_ExitLoop):
                                telegram_bot._telegram_loop("123:ABC", cfg)

            self.assertEqual(len(posted_messages), 1)
            self.assertEqual(posted_messages[0]["chat_id"], 42)
            self.assertIn("Telegram works fine.", posted_messages[0]["text"])


if __name__ == "__main__":
    unittest.main()
