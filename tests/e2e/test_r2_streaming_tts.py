"""E2E Tests for R2: Sentence-by-Sentence Streaming TTS & Fish Audio Config (Features F4, F5)."""
from __future__ import annotations

import inspect
import re
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import requests
import yaml

from tests.e2e.helpers import (
    REPO_ROOT,
    FakeLLMStream,
    IsolatedMisoWorkspace,
    MockFishServer,
    MockViewerServer,
    make_minimal_wav_bytes,
    require_attr,
    require_module,
)

EXPECTED_VOICE_ID = "5b05bc2a296046b3ac67577cb787dddc"
EXPECTED_MODEL = "s2.1-pro"
EXPECTED_SPEED = 1.0


def _feed_segmenter(seg, chunk: str) -> list[str]:
    if hasattr(seg, "feed"):
        out = seg.feed(chunk)
    elif hasattr(seg, "push"):
        out = seg.push(chunk)
    else:
        raise AssertionError("SentenceSegmenter must implement feed(chunk) or push(chunk)")
    if out is None:
        return []
    if isinstance(out, str):
        return [out] if out.strip() else []
    return [s.text if hasattr(s, "text") else str(s) for s in out if (s.text if hasattr(s, "text") else str(s)).strip()]


def _flush_segmenter(seg) -> list[str]:
    if hasattr(seg, "flush"):
        out = seg.flush()
    elif hasattr(seg, "finish"):
        out = seg.finish()
    else:
        raise AssertionError("SentenceSegmenter must implement flush() or finish()")
    if out is None:
        return []
    if isinstance(out, str):
        return [out] if out.strip() else []
    return [s.text if hasattr(s, "text") else str(s) for s in out if (s.text if hasattr(s, "text") else str(s)).strip()]


def require_streaming_contracts(test_case):
    """Synchronously verifies M2 streaming symbols exist before spawning worker threads."""
    from riko import llm, tts, viewer

    reply_stream = require_attr(test_case, llm, "reply_stream", "riko.llm")
    play_streaming = require_attr(test_case, viewer, "play_streaming_sentences", "riko.viewer")
    seg_cls = require_attr(test_case, tts, "SentenceSegmenter", "riko.tts")
    return reply_stream, play_streaming, seg_cls


def _drive_streaming_pipeline(test_case, prompt: str, cfg: dict):
    """Drives llm.reply_stream -> SentenceSegmenter (if needed) -> viewer.play_streaming_sentences."""
    reply_stream, play_streaming, seg_cls = require_streaming_contracts(test_case)
    tags = require_module(test_case, "riko.tags")
    parse_reply_tags = require_attr(test_case, tags, "parse_reply_tags", "riko.tags")

    sig = inspect.signature(play_streaming)
    param_names = list(sig.parameters.keys())

    # Collect stream from reply_stream and adapt cleanly to play_streaming_sentences contract
    raw_iter = reply_stream(prompt, cfg)

    # Peek first item to determine whether reply_stream yields structured events/sentences or raw deltas
    first = next(raw_iter, None)
    if first is None:
        return

    def _chained():
        yield first
        yield from raw_iter

    if isinstance(first, dict) or (hasattr(first, "text") and hasattr(first, "emotion")):
        # Structured events/sentences yielded directly by reply_stream
        if "cfg" in param_names:
            play_streaming(_chained(), cfg=cfg)
        else:
            play_streaming(_chained())
        return

    # Raw token deltas yielded by reply_stream -> parse leading tag header & segment incrementally
    def _sentence_gen():
        seg = seg_cls()
        header_buf = ""
        header_parsed = False
        emotion, intensity, gesture = "neutral", 2, None
        for chunk in _chained():
            tok = chunk if isinstance(chunk, str) else str(chunk)
            if not header_parsed:
                header_buf += tok
                if "]" in header_buf and not header_buf.rstrip().endswith("]"):
                    parsed = parse_reply_tags(header_buf)
                    emotion, intensity, gesture = parsed.emotion, parsed.intensity, parsed.gesture
                    header_parsed = True
                    for s in _feed_segmenter(seg, parsed.clean_text):
                        yield {"text": s, "emotion": emotion, "intensity": intensity, "gesture": gesture}
                elif len(header_buf) > 80 and not header_buf.lstrip().startswith("["):
                    header_parsed = True
                    for s in _feed_segmenter(seg, header_buf):
                        yield {"text": s, "emotion": emotion, "intensity": intensity, "gesture": gesture}
                continue
            for s in _feed_segmenter(seg, tok):
                yield {"text": s, "emotion": emotion, "intensity": intensity, "gesture": gesture}
        if not header_parsed and header_buf:
            parsed = parse_reply_tags(header_buf)
            emotion, intensity, gesture = parsed.emotion, parsed.intensity, parsed.gesture
            for s in _feed_segmenter(seg, parsed.clean_text):
                yield {"text": s, "emotion": emotion, "intensity": intensity, "gesture": gesture}
        for s in _flush_segmenter(seg):
            yield {"text": s, "emotion": emotion, "intensity": intensity, "gesture": gesture}

    # Check if play_streaming_sentences accepts sentence strings or dicts
    items = _sentence_gen()
    if "emotion" in param_names and "intensity" in param_names:
        # Extract emotion/intensity from first sentence item while staying streaming
        first_item = next(items, None)
        if first_item is None:
            return

        def _text_gen():
            yield first_item["text"]
            for it in items:
                yield it["text"]

        kwargs = {
            "emotion": first_item["emotion"],
            "intensity": first_item["intensity"],
            "cfg": cfg,
        }
        if "gesture" in param_names:
            kwargs["gesture"] = first_item["gesture"]
        play_streaming(_text_gen(), **kwargs)
    else:
        if "cfg" in param_names:
            play_streaming(items, cfg=cfg)
        else:
            play_streaming(items)


class TestF4FishAudioConfigPreservation(unittest.TestCase):
    """Feature F4: Fish Audio exact config preservation (voice_id, speed: 1.0, model: s2.1-pro)."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_character_config_fish_values_exact(self):
        cfg = yaml.safe_load((REPO_ROOT / "character_config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("tts"), "fish")
        fish = cfg.get("fish", {})
        self.assertEqual(fish.get("voice_id"), EXPECTED_VOICE_ID)
        self.assertEqual(float(fish.get("speed")), EXPECTED_SPEED)
        self.assertEqual(fish.get("model"), EXPECTED_MODEL)

    def test_t1_fish_http_request_uses_exact_voice_speed_and_model(self):
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY="fish-fake-key")
            from riko import config, tts

            cfg = config.load_config()
            with MockFishServer() as fish:
                out_path = tts.speak("Testing Fish Audio parameters.", cfg, filename="f4_test.wav")
                self.assertTrue(out_path.exists())
                self.assertEqual(len(fish.requests), 1)
                req = fish.requests[0]
                self.assertEqual(req.payload.get("reference_id"), EXPECTED_VOICE_ID)
                self.assertEqual(float(req.payload.get("prosody", {}).get("speed")), EXPECTED_SPEED)
                self.assertEqual(req.headers.get("model"), EXPECTED_MODEL)
                self.assertEqual(req.headers.get("authorization"), "Bearer fish-fake-key")

    def test_t1_fish_wav_written_only_inside_isolated_voice_dir(self):
        real_audio_dir = REPO_ROOT / "client" / "audio"
        before_files = sorted(p.name for p in real_audio_dir.glob("*")) if real_audio_dir.exists() else []
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY="fish-fake-key")
            from riko import config, tts

            cfg = config.load_config()
            with MockFishServer():
                out_path = tts.speak("Isolated wav file.", cfg, filename="unique_e2e_iso.wav")
                self.assertTrue(out_path.exists())
                self.assertTrue(str(out_path).startswith(str(ws.root)))
        after_files = sorted(p.name for p in real_audio_dir.glob("*")) if real_audio_dir.exists() else []
        self.assertEqual(before_files, after_files)
        self.assertFalse((real_audio_dir / "unique_e2e_iso.wav").exists())

    def test_t1_fish_check_passes_with_api_key(self):
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY="fish-fake-key")
            from riko import config, tts

            cfg = config.load_config()
            tts.check(cfg)  # Should not raise or exit

    def test_t1_voice_presets_tsundere_matches_canonical_voice_id(self):
        from riko import tools

        self.assertIn("tsundere", tools.VOICE_PRESETS)
        self.assertEqual(tools.VOICE_PRESETS["tsundere"][0], EXPECTED_VOICE_ID)

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_fish_check_exits_without_api_key(self):
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY=None)
            from riko import config, tts

            cfg = config.load_config()
            with self.assertRaises(SystemExit):
                tts.check(cfg)

    def test_t2_fish_http_500_raises_cleanly_without_corrupt_wav(self):
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY="fish-fake-key")
            from riko import config, tts

            cfg = config.load_config()
            with MockFishServer(status_code=500):
                with self.assertRaises(requests.HTTPError):
                    tts.speak("This should fail cleanly.", cfg, filename="err500.wav")
            self.assertFalse((ws.root / "client" / "audio" / "err500.wav").exists())

    def test_t2_fish_malformed_audio_bytes_rejected(self):
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY="fish-fake-key")
            from riko import config, tts

            cfg = config.load_config()
            with MockFishServer(status_code=200, response_bytes=b"not-a-valid-wav-stream"):
                with self.assertRaises(Exception):
                    tts.speak("Malformed bytes.", cfg, filename="badbytes.wav")
            self.assertFalse((ws.root / "client" / "audio" / "badbytes.wav").exists())

    def test_t2_clean_for_speech_truncates_overlong_input_before_fish(self):
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY="fish-fake-key")
            from riko import config, tts

            cfg = config.load_config()
            long_text = " ".join(["Stop writing broken loops right now."] * 20)
            with MockFishServer() as fish:
                tts.speak(long_text, cfg, filename="overlong.wav")
                sent_text = fish.requests[0].payload["text"]
                self.assertLessEqual(len(sent_text), 283)

    def test_t2_clean_for_speech_strips_tildes_and_emojis_for_fish(self):
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(FISH_API_KEY="fish-fake-key")
            from riko import config, tts

            cfg = config.load_config()
            with MockFishServer() as fish:
                tts.speak("[happy:2] Good morning~ ✨😊", cfg, filename="notilde.wav")
                sent_text = fish.requests[0].payload["text"]
                self.assertNotIn("~", sent_text)
                self.assertNotIn("✨", sent_text)
                self.assertNotIn("😊", sent_text)
                self.assertIn("Good morning", sent_text)


class TestF5SentenceSegmentationAndStreamingTTS(unittest.TestCase):
    """Feature F5: Sentence segmentation & streaming TTS dispatch ordering."""

    # ── Tier 1: Primary Feature Coverage ─────────────────────────────────────

    def test_t1_sentence_segmenter_splits_multi_sentence_stream(self):
        from riko import tts

        seg_cls = require_attr(self, tts, "SentenceSegmenter", "riko.tts")
        seg = seg_cls()
        tokens = ["First ", "sentence. ", "Second ", "sentence! ", "Third ", "question?"]
        emitted: list[str] = []
        for tok in tokens:
            emitted.extend(_feed_segmenter(seg, tok))
        emitted.extend(_flush_segmenter(seg))
        self.assertEqual(emitted, ["First sentence.", "Second sentence!", "Third question?"])

    def test_t1_sentence_1_dispatched_to_fish_and_viewer_before_llm_finishes(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config

            cfg = config.load_config()
            sentence2_gate = threading.Event()
            stream_seq = [
                "[angry:2][cross_arms] ",
                "Sentence one ",
                "is ready now. ",
                sentence2_gate,
                "Sentence two ",
                "arrives much later.",
            ]

            with FakeLLMStream(stream_sequences=[stream_seq]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        err_box: list[BaseException] = []

                        def _worker():
                            try:
                                _drive_streaming_pipeline(self, "Test streaming latency", cfg)
                            except BaseException as exc:
                                err_box.append(exc)

                        t = threading.Thread(target=_worker, daemon=True)
                        t.start()

                        # Sentence 1 MUST reach Fish Audio AND /next BEFORE sentence2_gate is set!
                        reqs = fish.wait_for_requests(1, timeout=5.0)
                        self.assertIn("Sentence one is ready now.", reqs[0].payload["text"])
                        self.assertFalse(
                            sentence2_gate.is_set(),
                            "Sentence 1 must reach Fish Audio before Sentence 2 tokens are released",
                        )

                        clip1 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertIsNotNone(clip1.get("audio"))
                        self.assertFalse(
                            sentence2_gate.is_set(),
                            "Sentence 1 must be queued on /next before LLM finishes Sentence 2",
                        )

                        # Now release Sentence 2
                        sentence2_gate.set()
                        reqs2 = fish.wait_for_requests(2, timeout=5.0)
                        self.assertIn("Sentence two arrives much later.", reqs2[1].payload["text"])

                        clip2 = srv.wait_for_next_audio(timeout=5.0)
                        self.assertIsNotNone(clip2.get("audio"))
                        srv.post_done()
                        t.join(timeout=5.0)
                        if err_box:
                            raise err_box[0]

    def test_t1_all_streamed_sentences_arrive_in_exact_order(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config

            cfg = config.load_config()
            stream_seq = [
                "[relaxed:2] ",
                "Alpha first. ",
                "Beta second! ",
                "Gamma third?",
            ]
            with FakeLLMStream(stream_sequences=[stream_seq]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "Three sentences", cfg),
                            daemon=True,
                        )
                        t.start()
                        reqs = fish.wait_for_requests(3, timeout=5.0)
                        self.assertEqual(
                            [r.payload["text"] for r in reqs],
                            ["Alpha first.", "Beta second!", "Gamma third?"],
                        )
                        clips = [srv.wait_for_next_audio(timeout=5.0) for _ in range(3)]
                        self.assertEqual(len(clips), 3)
                        self.assertEqual(len({c["audio"] for c in clips}), 3)
                        srv.post_done()
                        t.join(timeout=5.0)

    def test_t1_viewer_is_playing_stays_true_until_done_after_final_sentence(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, viewer

            cfg = config.load_config()
            stream_seq = ["[happy:2] First part. Second part."]
            with FakeLLMStream(stream_sequences=[stream_seq]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "Two parts", cfg),
                            daemon=True,
                        )
                        t.start()
                        fish.wait_for_requests(2, timeout=5.0)
                        srv.wait_for_next_audio(timeout=5.0)
                        self.assertTrue(viewer.is_playing(), "viewer.is_playing() must stay True until POST /done")
                        srv.wait_for_next_audio(timeout=5.0)
                        self.assertTrue(viewer.is_playing())
                        srv.post_done()
                        t.join(timeout=5.0)
                        self.assertFalse(viewer.is_playing())

    def test_t1_client_speech_queue_only_posts_done_when_drained(self):
        html = (REPO_ROOT / "client" / "index.html").read_text(encoding="utf-8")
        self.assertIn("speechQueue", html)
        self.assertIn("playNextSpeechChunk", html)
        # Ensure fetch('/done') appears inside the speechQueue.length === 0 guard
        m = re.search(
            r"if\s*\(\s*speechQueue\.length\s*===\s*0\s*\)\s*\{.*?fetch\(['\"]/done['\"]",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "client/index.html must post /done only when speechQueue.length === 0")

    # ── Tier 2: Boundary & Corner Cases ──────────────────────────────────────

    def test_t2_abbreviations_decimals_and_lists_not_over_split(self):
        from riko import tts

        seg_cls = require_attr(self, tts, "SentenceSegmenter", "riko.tts")
        seg = seg_cls()
        text = "Dr. Smith said v1.2 costs $3.50 today. Item 1. Next sentence!"
        emitted = _feed_segmenter(seg, text) + _flush_segmenter(seg)
        joined = " | ".join(emitted)
        self.assertFalse(
            any(s.strip() in {"Dr.", "v1.", "$3."} for s in emitted),
            f"Over-split on abbreviation/decimal: {joined}",
        )
        self.assertGreaterEqual(len(emitted), 2)

    def test_t2_trailing_fragment_without_punctuation_flushed_and_tag_guard(self):
        from riko import tts

        seg_cls = require_attr(self, tts, "SentenceSegmenter", "riko.tts")
        seg = seg_cls()
        # Unclosed bracket tag mid-stream should not fracture on internal punctuation
        emitted = _feed_segmenter(seg, "[sighs. pause] Wait for it")
        emitted.extend(_flush_segmenter(seg))
        self.assertTrue(any("Wait for it" in s for s in emitted), f"Expected trailing fragment flushed, got {emitted}")

    def test_t2_cjk_devanagari_and_ellipsis_segmentation(self):
        from riko import tts

        seg_cls = require_attr(self, tts, "SentenceSegmenter", "riko.tts")
        seg = seg_cls()
        emitted = _feed_segmenter(seg, "Wait... really? ठीक है। Done!") + _flush_segmenter(seg)
        self.assertGreaterEqual(len(emitted), 2)
        self.assertIn("Done!", emitted[-1])

    def test_t2_barge_in_stop_speech_clears_remaining_stream_and_resets_playing(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, viewer

            cfg = config.load_config()
            gate = threading.Event()
            stream_seq = ["[neutral:2] First sentence. ", gate, "Second sentence."]
            with FakeLLMStream(stream_sequences=[stream_seq]):
                with MockFishServer() as fish:
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        t = threading.Thread(
                            target=lambda: _drive_streaming_pipeline(self, "Interrupt test", cfg),
                            daemon=True,
                        )
                        t.start()
                        fish.wait_for_requests(1, timeout=5.0)
                        srv.wait_for_next_audio(timeout=5.0)
                        viewer.stop_speech()
                        srv.post_interrupted()
                        stop_msg = srv.wait_for_next_audio(timeout=5.0)
                        self.assertEqual(stop_msg.get("command"), "stop")
                        gate.set()
                        t.join(timeout=5.0)
                        self.assertFalse(viewer.is_playing())

    def test_t2_single_sentence_fish_500_does_not_hang_viewer(self):
        require_streaming_contracts(self)
        with IsolatedMisoWorkspace() as ws:
            ws.set_env(OPENAI_API_KEY="sk-fake-e2e", GROQ_API_KEY=None, FISH_API_KEY="fish-fake-key")
            from riko import config, viewer

            cfg = config.load_config()
            with FakeLLMStream(stream_sequences=[["[angry:2] Sentence fails cleanly."]]):
                with MockFishServer(status_code=500):
                    with MockViewerServer(ws) as srv:
                        srv.touch_page()
                        try:
                            _drive_streaming_pipeline(self, "Fail cleanly", cfg)
                        except Exception:
                            pass
                        self.assertFalse(viewer.is_playing(), "viewer.is_playing() must not remain stuck True on TTS error")


if __name__ == "__main__":
    unittest.main()
