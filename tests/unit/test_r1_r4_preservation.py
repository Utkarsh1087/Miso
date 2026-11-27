"""Unit tests confirming all R4 capabilities remain intact alongside R1."""
from __future__ import annotations

from pathlib import Path
import queue
import unittest
from unittest.mock import patch

from riko import alarms, asr, cowatch, face_id, heartbeat, llm, sentry, telegram_bot, tools, viewer, vision_observer, voice_id

ROOT = Path(__file__).resolve().parents[2]


class TestR1R4Preservation(unittest.TestCase):
    def test_tools_function_definitions_and_detectors_intact(self):
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

        self.assertTrue(tools.should_capture_screen("look at my screen"))
        self.assertFalse(tools.should_capture_camera("look at my screen"))
        self.assertTrue(tools.should_capture_camera("how do i look"))
        self.assertTrue(tools.should_search_web("weather in Tokyo"))

        with patch("subprocess.Popen") as mock_popen:
            res = tools.detect_and_open_app("open notepad")
            self.assertEqual(res, "Notepad")
            mock_popen.assert_called_once()

        with patch.object(viewer, "_clips", queue.Queue()):
            self.assertIn("walking", tools.detect_locomotion_command("walk around"))
            item = viewer._clips.get_nowait()
            self.assertEqual(item, {"command": "action", "action": "walk"})

        rps = tools.detect_minigame("rock paper scissors rock")
        self.assertIsNotNone(rps)

    def test_r4_subsystems_import_and_contracts(self):
        self.assertTrue(callable(voice_id.verify_speaker))
        self.assertTrue(callable(voice_id.has_enrolled_voice))
        self.assertTrue(callable(asr.transcribe))
        self.assertTrue(callable(vision_observer.start))
        self.assertTrue(callable(heartbeat.start))
        self.assertTrue(callable(cowatch.start_cowatch))
        self.assertTrue(callable(sentry.start_sentry))
        self.assertTrue(callable(telegram_bot.start_telegram_bridge))
        self.assertTrue(callable(face_id.identify_person_in_frame))

        with patch.object(alarms, "load_alarms", return_value=[]), \
             patch.object(alarms, "save_alarms") as mock_save:
            msg = alarms.set_timer_seconds(15, label="Unit Test")
            self.assertIn("15 seconds", msg)
            mock_save.assert_called_once()

    def test_wake_word_and_frontend_r4_locomotion_preserved(self):
        main_src = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("require_wake_word", main_src)
        self.assertIn("wake_names", main_src)

        html = (ROOT / "client" / "index.html").read_text(encoding="utf-8")
        self.assertIn("@pixiv/three-vrm-animation@3.4.1", html)
        self.assertIn("VRMAnimationLoaderPlugin", html)
        self.assertIn("vrmaOwnsBones", html)
        self.assertIn("analyzePhonemes", html)
        self.assertIn("vrm.lookAt", html)
        for state in ("'walk'", "'sit'", "'dance'", "'stretch'", "'spin'", "'headpat'", "'poke'"):
            self.assertIn(state, html)


if __name__ == "__main__":
    unittest.main()
