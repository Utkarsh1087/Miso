"""Mobile Phone Bridge for Riko:
Connects Riko to Telegram via standard HTTP polling (0 extra dependencies).
Allows senpai to talk to Riko from anywhere in the world via Telegram voice notes or photos!
"""
import os
import re
import threading
import time

import requests

from riko import asr, llm, tts


def start_telegram_bridge(cfg: dict):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[telegram] No TELEGRAM_BOT_TOKEN in .env. Mobile phone bridge disabled.")
        return

    print("[telegram] Starting Mobile Phone Telegram Bridge...")
    threading.Thread(target=_telegram_loop, args=(token, cfg), daemon=True).start()


def _telegram_loop(token: str, cfg: dict):
    base_url = f"https://api.telegram.org/bot{token}"
    last_update_id = 0

    try:
        # Verify token
        me = requests.get(f"{base_url}/getMe", timeout=10).json()
        if not me.get("ok"):
            print(f"[telegram error] Invalid token: {me}")
            return
        bot_name = me.get("result", {}).get("username")
        print(f"[telegram] Connected! Chat with Miso on Telegram: @{bot_name}")
    except Exception as e:
        print(f"[telegram connection error] {e}")
        return

    while True:
        try:
            params = {"offset": last_update_id + 1, "timeout": 20}
            resp = requests.get(f"{base_url}/getUpdates", params=params, timeout=25).json()
            if not resp.get("ok"):
                time.sleep(2)
                continue

            for update in resp.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                user_text = ""
                photo_b64 = None

                # 1. Voice Note from phone
                if "voice" in msg:
                    file_id = msg["voice"]["file_id"]
                    file_info = requests.get(f"{base_url}/getFile?file_id={file_id}").json()
                    file_path = file_info.get("result", {}).get("file_path")
                    if file_path:
                        audio_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                        audio_bytes = requests.get(audio_url).content
                        user_text = asr.transcribe(audio_bytes, cfg)
                        print(f"[telegram:voice] Senpai: {user_text}")

                # 2. Text message from phone
                elif "text" in msg:
                    user_text = msg["text"]
                    print(f"[telegram:text] Senpai: {user_text}")

                # 3. Photo from phone camera
                elif "photo" in msg:
                    photo_id = msg["photo"][-1]["file_id"]
                    file_info = requests.get(f"{base_url}/getFile?file_id={photo_id}").json()
                    file_path = file_info.get("result", {}).get("file_path")
                    if file_path:
                        photo_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                        photo_bytes = requests.get(photo_url).content
                        import base64
                        photo_b64 = base64.b64encode(photo_bytes).decode('utf-8')
                        user_text = msg.get("caption") or "Look at this photo I just took on my phone! Give me your reaction, Miso!"
                        print(f"[telegram:photo] Senpai sent a photo: {user_text}")

                if not user_text:
                    continue

                # Generate Riko's reply using shared memory brain & vision
                raw_reply = llm.reply(user_text, cfg, image_b64=photo_b64)
                m = re.match(r"^\[([a-zA-Z]+)\]\s*", raw_reply)
                clean_reply = raw_reply[m.end():] if m else raw_reply

                # Send text reply
                requests.post(f"{base_url}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": clean_reply
                })

                # Synthesize and send voice note back to phone
                try:
                    wav_path = tts.speak(clean_reply, cfg, filename="telegram_voice.wav")
                    with open(wav_path, "rb") as audio_file:
                        requests.post(f"{base_url}/sendVoice", data={"chat_id": chat_id}, files={"voice": audio_file})
                except Exception as e:
                    print(f"[telegram voice reply note] {e}")

        except Exception as e:
            time.sleep(3)

