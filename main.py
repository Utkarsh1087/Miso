"""Talk to Riko: press Enter (or hands-free), speak, and she answers out loud on the avatar page.

    your voice -> asr.py -> text -> llm.py -> her reply -> tts.py -> her voice -> viewer.py -> avatar

Run:  uv run main.py                 (uses asr / tts from character_config.yaml)
      uv run main.py --hands-free    (auto-listens when you speak without pressing Enter)
      uv run main.py --tts fish      (override the voice)
      uv run main.py --asr groq      (override the ears)
"""
import argparse
import datetime
import os
import sys
import threading
import time

from riko import alarms, asr, heartbeat, hotkeys, llm, memory, tags, telegram_bot, tts, viewer, vision_observer, voice_id
from riko.config import load_config


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Talk to Riko.")
    parser.add_argument("--asr", choices=["local", "groq"], help="speech to text (overrides the config)")
    parser.add_argument("--tts", choices=["sovits", "fish"], help="her voice (overrides the config)")
    parser.add_argument("--hands-free", action="store_true", help="continuous listening without pressing Enter")
    args = parser.parse_args()

    cfg = load_config()
    cfg["asr"] = args.asr or cfg["asr"]
    cfg["tts"] = args.tts or cfg["tts"]
    if args.hands_free:
        cfg["hands_free"] = True

    mode = "hands-free" if cfg.get("hands_free") else "push-to-talk"
    print(f"\n=== Miso Desktop Companion Active ===")
    print(f"• Model: {cfg.get('groq_model', cfg.get('model', 'openai/gpt-oss-120b'))}  |  Ears: {cfg['asr']} ({mode})  |  Voice: {cfg['tts']}")
    print(f"• Hotkeys: Ctrl+Alt+R (Screen Vision), Ctrl+Alt+C (Camera Vision)")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print(f"• Telegram: Connected")
    llm.check(cfg)
    asr.check(cfg)
    tts.check(cfg)
    viewer.start(cfg)
    heartbeat.start(cfg)
    telegram_bot.start_telegram_bridge(cfg)
    alarms.start(cfg)
    vision_observer.start(cfg)
    print(f"• Status: Ready & listening...\n", flush=True)

    # Setup global hotkeys: Ctrl+Alt+R (Screen Vision) and Ctrl+Alt+C (Camera Vision)
    def handle_hotkey_inspect():
        print("\n[hotkey] Ctrl+Alt+R pressed! Inspecting active screen...")
        try:
            raw_answer = llm.reply("Look at my screen and give me your snarky reaction or advice in 1-2 sentences!", cfg, save_to_history=False)
            parsed = tags.parse_reply_tags(raw_answer)
            emotion = parsed.emotion
            clean_answer = parsed.clean_text
            print(f"[{emotion.upper()}:{parsed.intensity}] Miso: {clean_answer}")
            viewer.play(tts.speak(clean_answer, cfg), emotion=emotion, intensity=parsed.intensity, gesture=parsed.gesture, text=clean_answer)
        except Exception as e:
            print(f"[hotkey error] {e}")

    def handle_hotkey_camera():
        print("\n[hotkey] Ctrl+Alt+C pressed! Looking through webcam camera at senpai...")
        try:
            raw_answer = llm.reply("Look at me through the camera and give me your snarky reaction in 1-2 sentences!", cfg, save_to_history=False)
            parsed = tags.parse_reply_tags(raw_answer)
            emotion = parsed.emotion
            clean_answer = parsed.clean_text
            print(f"[{emotion.upper()}:{parsed.intensity}] Miso: {clean_answer}")
            viewer.play(tts.speak(clean_answer, cfg), emotion=emotion, intensity=parsed.intensity, gesture=parsed.gesture, text=clean_answer)
        except Exception as e:
            print(f"[hotkey error] {e}")

    hotkeys.setup_global_hotkeys(
        on_inspect_screen=handle_hotkey_inspect,
        on_inspect_camera=handle_hotkey_camera
    )

    # Proactive startup greeting with temporal awareness, mood & robust persona fallback
    def trigger_startup_greeting():
        try:
            temporal_ctx, mood = memory.get_temporal_context()
            prompt = (
                f"[{temporal_ctx} "
                f"Greet Utkarsh in 1 short, lively, authentic sentence matching your mood and time of day! "
                f"Do NOT repeat prior lines. Begin with [emotion:intensity] (1-3) and optional [gesture] e.g. [happy:2] or [relaxed:1].]"
            )
            raw_answer = llm.reply(prompt, cfg, save_to_history=False)
            parsed = tags.parse_reply_tags(raw_answer or "", default_emotion="happy")
            emotion = parsed.emotion
            intensity = parsed.intensity
            gesture = parsed.gesture
            clean_answer = parsed.clean_text

            # Robust fallback guard: if LLM returned empty, too short (<6 chars), or single token ("Done!")
            if not clean_answer or len(clean_answer) < 6 or clean_answer.lower() in ["done!", "done", "ok", "..."]:
                profile = memory.load_profile()
                now_ts = time.time()
                last_seen = profile.get("last_seen_timestamp", now_ts)
                mins_elapsed = max(0, int((now_ts - last_seen) / 60))
                hour = datetime.datetime.now().hour
                aff = memory.get_affection()
                fallback_text, fallback_emotion = memory.get_fallback_greeting(mins_elapsed, hour, aff)
                clean_answer = fallback_text
                emotion = fallback_emotion
                intensity = 2
                gesture = None

            memory.record_greeting(clean_answer)
            memory.update_session_active()

            print(f"\nMiso (startup): [{emotion.upper()}:{intensity}] {clean_answer}\n", flush=True)
            sentences = tts.split_into_sentences(clean_answer)
            if len(sentences) > 1 and (time.monotonic() - viewer._page_last_seen < 5):
                viewer.play_sentences(sentences, emotion=emotion, cfg=cfg, intensity=intensity, gesture=gesture)
            else:
                wav_path = tts.speak(clean_answer, cfg)
                viewer.play(wav_path, emotion=emotion, intensity=intensity, gesture=gesture, text=clean_answer)
        except Exception as e:
            pass

    threading.Thread(target=trigger_startup_greeting, daemon=True).start()

    while True:
        try:
            # Passes barge-in hook and flags busy so vision observer never interrupts speech
            barge_in_hook = viewer.stop_speech if cfg.get("barge_in", False) else None

            def on_speech_detected():
                heartbeat.set_busy(True)
                if barge_in_hook:
                    barge_in_hook()

            recording = asr.record(cfg, on_speech_start=on_speech_detected)
            if recording is None:
                heartbeat.set_busy(False)
                continue
            
            text = asr.transcribe(recording, cfg)
            if not text:
                heartbeat.set_busy(False)
                continue
            
            print(f"\nYou: {text}", flush=True)

            # Wake Word Filter (optional for hands-free mode)
            if cfg.get("hands_free") and cfg.get("require_wake_word"):
                lower_text = text.lower()
                wake_names = ["miso", "meeso", "hey miso", "hi miso", "ok miso", "riko", "riku"]
                if not any(w in lower_text for w in wake_names):
                    heartbeat.set_busy(False)
                    continue

            # Verify speaker voice identity if enrolled
            speaker_tag = ""
            if voice_id.has_enrolled_voice():
                is_senpai, confidence, status = voice_id.verify_speaker(recording)
                if is_senpai:
                    speaker_tag = "[Speaker: Utkarsh Senpai] "
                elif status == "stranger_detected":
                    speaker_tag = "[Speaker: Unfamiliar Stranger (Voice does NOT match Senpai)] "

            raw_answer = llm.reply(speaker_tag + text, cfg, audio_bytes=recording)

            # Extract emotion, intensity, optional gesture, and affection delta like [happy:2, +2][wave]
            parsed = tags.parse_reply_tags(raw_answer)
            emotion = parsed.emotion
            intensity = parsed.intensity
            gesture = parsed.gesture
            if parsed.affection_delta:
                memory.apply_affection_delta(parsed.raw_emotion_tag or f"{emotion}, {parsed.affection_delta:+d}")
            clean_answer = parsed.clean_text

            if not clean_answer or len(clean_answer) < 4:
                fb_text, fb_emo = memory.get_conversational_fallback(text)
                clean_answer = fb_text
                emotion = fb_emo
                intensity = 2
                gesture = None

            print(f"Miso: [{emotion.upper()}:{intensity}] {clean_answer}\n", flush=True)
            memory.update_session_active()

            sentences = tts.split_into_sentences(clean_answer)
            if len(sentences) > 1 and (time.monotonic() - viewer._page_last_seen < 5):
                viewer.play_sentences(sentences, emotion=emotion, cfg=cfg, intensity=intensity, gesture=gesture)
            else:
                wav_path = tts.speak(clean_answer, cfg)
                viewer.play(wav_path, emotion=emotion, intensity=intensity, gesture=gesture, text=clean_answer)
            time.sleep(0.35)  # Acoustic room decay
            heartbeat.mark_interaction()
            heartbeat.set_busy(False)
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            return
        except Exception as e:  # one bad turn should not end the chat
            print(f"[error] {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
