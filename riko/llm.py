"""Her brain: hybrid tool architecture combining instant pre-filtering (0ms) with LLM function calling."""
import json
import os
import re
import sys

from openai import OpenAI

from riko import memory, tools
from riko.config import ROOT

MAX_HISTORY_TURNS = 12  # keeps the last 12 messages in context to prevent token limit spikes

FUNCTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "play_youtube",
            "description": "Search and automatically play a video, music, stream, or topic on YouTube on senpai's PC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query, artist, song, or video title to play on YouTube."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Launch an application, program, folder, or website on senpai's computer (e.g. notepad, spotify, calculator, chrome, vs code, discord, steam, downloads, documents, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Name of the app, folder, or website to open."
                    }
                },
                "required": ["target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_internet",
            "description": "Search the live web for real-time information, today's news, current weather, scores, or facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The web search query."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_system_media",
            "description": "Control computer volume, playback, or system actions on senpai's PC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "volume_up", "volume_down", "mute",
                            "pause_resume", "next_song", "previous_song",
                            "lock_pc", "screenshot"
                        ],
                        "description": "The media or system control action to perform."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_diary_fact",
            "description": "Save an important personal fact about senpai to your persistent diary memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The personal fact to remember about senpai."
                    }
                },
                "required": ["fact"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "look_through_camera",
            "description": "Turn on the webcam camera to look at senpai in real life to see their face, expression, outfit, or what they are holding.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


def execute_tool(tool_name: str, args_dict: dict) -> str:
    """Executes a function call requested by the LLM and returns the text result."""
    print(f"[llm:tool] Executing {tool_name}({args_dict})...")
    if tool_name == "play_youtube":
        q = args_dict.get("query", "popular anime music")
        res = tools.detect_and_play_music(f"play {q} on youtube")
        return f"Successfully opened and started playing '{res or q}' on YouTube on senpai's PC."
    elif tool_name == "open_application":
        t = args_dict.get("target", "")
        res = tools.detect_and_open_app(f"open {t}")
        return f"Successfully opened '{res or t}' on senpai's PC."
    elif tool_name == "search_internet":
        q = args_dict.get("query", "")
        res = tools.search_web(q)
        return res or "No relevant search results found."
    elif tool_name == "control_system_media":
        act = args_dict.get("action", "")
        mapping = {
            "volume_up": "volume up",
            "volume_down": "volume down",
            "mute": "mute",
            "pause_resume": "pause",
            "pause": "pause",
            "stop": "stop the music",
            "stop_music": "stop the music",
            "close_video": "close video",
            "next_song": "next song",
            "previous_song": "previous song",
            "lock_pc": "lock my pc",
            "screenshot": "take a screenshot and save"
        }
        res = tools.control_media(mapping.get(act, act))
        return f"Successfully {res or act} on senpai's PC."
    elif tool_name == "save_diary_fact":
        fact = args_dict.get("fact", "")
        memory.add_fact(fact)
        return f"Saved '{fact}' to your permanent diary."
    elif tool_name == "look_through_camera":
        camera_b64 = tools.capture_camera_base64()
        if camera_b64:
            return "Successfully captured a photo of senpai through the webcam camera."
        return "Could not access the webcam camera."
    return "Action completed."


def check(cfg):
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_groq = bool(os.getenv("GROQ_API_KEY"))
    if not has_openai and not has_groq:
        sys.exit("[setup] Either OPENAI_API_KEY or GROQ_API_KEY is required in .env for the LLM.")
    if has_groq and not has_openai:
        model = os.getenv("GROQ_MODEL", cfg.get("groq_model", "openai/gpt-oss-120b"))
        print(f"[setup] Using Groq (free tier, model: {model}, vision: qwen3.8-27b) with Hybrid Tools")
    else:
        print(f"[setup] OPENAI_API_KEY found (the LLM, model {cfg['model']}) with Hybrid Tools")


def reply(user_text, cfg, image_b64=None, audio_bytes=None):
    history_path = ROOT / cfg["history_file"]
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    history.append({"role": "user", "content": user_text})

    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    # ── TIER 1: FAST PRE-MATCH (0ms delay for common direct commands) ──
    mem_action, mem_details = memory.detect_memory_action(user_text)
    mem_context = ""
    if mem_action == "saved":
        mem_context = f"\n[System Event: You just saved '{mem_details}' into your long-term personal diary about senpai. Confirm it affectionately in 1 short sentence!]"
    elif mem_action == "cleared":
        mem_context = f"\n[System Event: You just cleared your diary memory as senpai requested. Confirm in 1 short sentence!]"
    elif mem_action == "inquire":
        mem_context = f"\n[System Event: {mem_details}\nTell senpai what you remember about them in your snarky persona! Keep it short 1-3 sentences.]"

    media_action = None
    media_context = ""
    if not mem_action:
        media_action = tools.control_media(user_text)
        if media_action:
            print(f"[media] {media_action.capitalize()} for senpai!")
            media_context = f"\n[System Event: You just successfully {media_action} on senpai's computer. Playfully confirm it in 1 short sentence!]"

    music_vibe = None
    music_context = ""
    if not mem_action and not media_action:
        music_vibe = tools.detect_and_play_music(user_text)
        if music_vibe:
            print(f"[music] Playing {music_vibe} for senpai!")
            music_context = f"\n[System Event: You just searched and started playing {music_vibe} on senpai's computer. Playfully confirm that you put it on for them in 1 short sentence!]"

    app_opened = None
    app_context = ""
    if not mem_action and not media_action and not music_vibe:
        app_opened = tools.detect_and_open_app(user_text)
        if app_opened:
            print(f"[app] Opened {app_opened} for senpai!")
            app_context = f"\n[System Event: You just successfully opened '{app_opened}' on senpai's computer. Playfully confirm it in 1 short sentence!]"

    # Minigame check (Rock Paper Scissors, Coin Flip, Dice)
    game_result = None
    game_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened:
        game_result = tools.detect_minigame(user_text)
        if game_result:
            print(f"[minigame] {game_result}")
            game_context = f"\n[System Event: Minigame result: {game_result}. React to senpai with playful anime banter in 1 short sentence!]"

    # Wardrobe / Avatar switch check
    avatar_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result:
        switched_name = tools.detect_avatar_switch(user_text)
        if switched_name:
            from riko import viewer
            ok = viewer.switch_avatar(switched_name)
            if ok:
                avatar_context = f"\n[System Event: You just successfully changed into your '{switched_name}' avatar outfit! Show off your new look in 1 short sentence!]"
            else:
                avatar_context = f"\n[System Event: Senpai asked you to change into '{switched_name}', but that .vrm file was not found in character_files/avatars/. Playfully tell senpai to drop the file into character_files/avatars!]"

    # Voice model switch check
    voice_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context:
        voice_switched = tools.detect_voice_switch(user_text, cfg)
        if voice_switched:
            voice_context = f"\n[System Event: You just {voice_switched}! Greet senpai in your new voice tone in 1 short playful sentence!]"

    # Sentry Mode check
    sentry_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context:
        sentry_res = tools.detect_sentry_command(user_text, cfg)
        if sentry_res:
            sentry_context = f"\n[System Event: {sentry_res} Confirm in 1 short sassy sentence!]"

    # Workout Coach check
    workout_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context:
        workout_res = tools.detect_workout_command(user_text, cfg)
        if workout_res:
            workout_context = f"\n[System Event: {workout_res} Motivate or roast senpai in 1 short sentence!]"

    # Face Enrollment check
    face_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context:
        face_res = tools.detect_face_command(user_text)
        if face_res:
            face_context = f"\n[System Event: {face_res} Confirm in 1 short playful sentence!]"

    # Voice Enrollment check
    voice_enroll_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context and not face_context:
        voice_res = tools.detect_voice_command(user_text, audio_input=audio_bytes)
        if voice_res:
            voice_enroll_context = f"\n[System Event: {voice_res} Confirm in 1 short playful sentence!]"

    # Alarm & Timer check
    alarm_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context and not face_context and not voice_enroll_context:
        alarm_res = tools.detect_alarm_command(user_text, cfg)
        if alarm_res:
            alarm_context = f"\n[System Event: {alarm_res} Confirm in 1 short snarky sentence!]"

    # Co-Watching check
    cowatch_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context and not face_context and not voice_enroll_context and not alarm_context:
        cowatch_res = tools.detect_cowatch_command(user_text, cfg)
        if cowatch_res:
            cowatch_context = f"\n[System Event: {cowatch_res} Confirm in 1 short sentence!]"

    # Locomotion & Movement check (walk, sit, stand, dance, stretch, spin)
    locomotion_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context and not face_context and not voice_enroll_context and not alarm_context and not cowatch_context:
        locomotion_res = tools.detect_locomotion_command(user_text)
        if locomotion_res:
            locomotion_context = f"\n[System Event: You just {locomotion_res}! Playfully confirm in 1 short sassy sentence while performing this movement!]"

    # Camera Vision request (webcam or direct image attachment)
    camera_b64 = image_b64
    if not camera_b64 and not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context and not face_context and not voice_enroll_context and not alarm_context and not cowatch_context and not locomotion_context and tools.should_capture_camera(user_text):
        print("[vision] Looking through webcam camera at senpai...")
        camera_b64 = tools.capture_camera_base64()

    # Screen Vision request (desktop)
    screen_b64 = None
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context and not face_context and not voice_enroll_context and not alarm_context and not cowatch_context and not locomotion_context and not camera_b64 and tools.should_capture_screen(user_text):
        print("[vision] Checking your screen...")
        screen_b64 = tools.capture_screen_base64()

    search_context = ""
    if not mem_action and not media_action and not music_vibe and not app_opened and not game_result and not avatar_context and not voice_context and not sentry_context and not workout_context and not face_context and not voice_enroll_context and not alarm_context and not cowatch_context and not locomotion_context and not camera_b64 and not screen_b64 and tools.should_search_web(user_text):
        print(f"[search] Searching web for: {user_text}...")
        search_results = tools.search_web(user_text)
        if search_results:
            search_context = f"\n[Live Web Results:\n{search_results}\nUse the above live information if relevant to answer accurately.]\n"

    # Did any Tier 1 trigger take immediate action?
    fast_action_taken = bool(mem_action or media_action or music_vibe or app_opened or game_context or avatar_context or voice_context or sentry_context or workout_context or face_context or voice_enroll_context or alarm_context or cowatch_context or locomotion_context or camera_b64 or screen_b64 or search_context)

    # System prompt enriched with permanent diary memory facts
    effective_system_prompt = cfg["system_prompt"] + memory.get_memory_context()

    # Sliding window of recent messages
    context_window = history[-MAX_HISTORY_TURNS:] if len(history) > MAX_HISTORY_TURNS else history

    use_groq = bool(groq_key and (not openai_key or cfg.get("llm_provider") == "groq"))

    if not use_groq:
        try:
            client = OpenAI(api_key=openai_key)
            if fast_action_taken:
                extra_info = mem_context or media_context or music_context or app_context or game_context or avatar_context or voice_context or sentry_context or workout_context or face_context or voice_enroll_context or alarm_context or cowatch_context or locomotion_context or search_context
                formatted_window = [m.copy() for m in context_window]
                if extra_info:
                    formatted_window[-1]["content"] = formatted_window[-1]["content"] + extra_info
                res = client.chat.completions.create(
                    model=cfg["model"],
                    messages=[{"role": "system", "content": effective_system_prompt}] + formatted_window,
                )
                answer = res.choices[0].message.content
            else:
                words = user_text.lower().strip().split()
                is_potential_action = any(
                    w in user_text.lower() for w in [
                        "play", "open", "launch", "start", "search", "google", "look up",
                        "find", "volume", "mute", "pause", "resume", "skip", "next",
                        "lock", "screenshot", "remember", "forget", "screen",
                        "camera", "webcam", "look at me", "see me", "how do i look",
                        "weather", "who", "when", "how", "what is", "tell me about",
                        "watch", "listen", "put on", "stream", "tune", "song", "music", "video"
                    ]
                )
                should_provide_tools = is_potential_action or len(words) >= 4

                messages = [{"role": "system", "content": effective_system_prompt}] + context_window
                tool_kwargs = {"tools": FUNCTION_TOOLS, "tool_choice": "auto"} if should_provide_tools else {}
                res = client.chat.completions.create(
                    model=cfg["model"],
                    messages=messages,
                    **tool_kwargs
                )
                msg = res.choices[0].message
                if should_provide_tools and msg.tool_calls:
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                        tool_res = execute_tool(tc.function.name, args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_res
                        })
                    res2 = client.chat.completions.create(
                        model=cfg["model"],
                        messages=messages,
                        tools=FUNCTION_TOOLS
                    )
                    answer = res2.choices[0].message.content
                else:
                    answer = msg.content
        except Exception as e:
            if ("insufficient_quota" in str(e) or "429" in str(e)) and groq_key:
                print("[llm] OpenAI quota exhausted. Automatically falling back to Groq...")
                use_groq = True
            else:
                raise e

    if use_groq:
        groq_client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")

        if camera_b64 or screen_b64:
            img_b64 = camera_b64 or screen_b64
            context_instruction = (
                "[Here is a live photo captured from senpai's webcam camera. Senpai wants you to look at them! React to senpai (their face, hair, expressions, clothes, what they are holding, or room) in your snarky, cute anime persona! Keep it short 1-3 sentences.]"
                if camera_b64
                else "[Here is a screenshot of senpai's computer screen. React to what you see on the screen in your snarky persona! Keep it short 1-3 sentences.]"
            )
            vision_messages = [{"role": "system", "content": effective_system_prompt}]
            # Ground the visual observation in recent conversation history so Riko remembers context
            if context_window:
                prior_context = context_window[:-1] if context_window and context_window[-1].get("content") == user_text else context_window
                for m in prior_context[-6:]:
                    c = m.get("content", "")
                    if isinstance(c, str):
                        vision_messages.append({"role": m.get("role", "user"), "content": c})

            vision_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"{user_text}\n\n{context_instruction}"
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    }
                ]
            })
            chat_completion = groq_client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=vision_messages,
            )
            answer = chat_completion.choices[0].message.content
        elif fast_action_taken:
            # Fast-path: action already performed, 1 fast roundtrip
            messages = [{"role": "system", "content": effective_system_prompt}]
            extra_info = mem_context or media_context or music_context or app_context or game_context or avatar_context or voice_context or sentry_context or workout_context or face_context or voice_enroll_context or alarm_context or cowatch_context or locomotion_context or search_context
            formatted_window = [m.copy() for m in context_window]
            if extra_info:
                formatted_window[-1]["content"] = formatted_window[-1]["content"] + extra_info
            messages.extend(formatted_window)

            model_name = os.getenv("GROQ_MODEL", cfg.get("groq_model", "openai/gpt-oss-120b"))
            try:
                chat_completion = groq_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    tools=FUNCTION_TOOLS,
                    tool_choice="auto",
                    max_tokens=450,
                    presence_penalty=0.35,
                    frequency_penalty=0.25
                )
                msg = chat_completion.choices[0].message
                answer = msg.content or "Done!"
            except Exception as e:
                chat_completion = groq_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    max_tokens=450,
                    presence_penalty=0.35,
                    frequency_penalty=0.25
                )
                answer = chat_completion.choices[0].message.content
        else:
            # ── TIER 2: LLM FUNCTION CALLING FALLBACK ──
            # Noise & Vague Word Guard: Do not offer tools for short 1-3 word non-action inputs (e.g. "Hello", "You")
            words = user_text.lower().strip().split()
            is_potential_action = any(
                w in user_text.lower() for w in [
                    "play", "open", "launch", "start", "search", "google", "look up",
                    "find", "volume", "mute", "pause", "resume", "skip", "next",
                    "lock", "screenshot", "remember", "forget", "screen",
                    "weather", "who", "when", "how", "what is", "tell me about",
                    "watch", "listen", "put on", "stream", "tune", "song", "music", "video"
                ]
            )
            should_provide_tools = is_potential_action or len(words) >= 4

            messages = [{"role": "system", "content": effective_system_prompt}]
            messages.extend(context_window)

            model_name = os.getenv("GROQ_MODEL", cfg.get("groq_model", "openai/gpt-oss-120b"))
            
            tool_kwargs = {"tools": FUNCTION_TOOLS, "tool_choice": "auto"} if should_provide_tools else {}
            try:
                chat_completion = groq_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    max_tokens=450,
                    presence_penalty=0.35,
                    frequency_penalty=0.25,
                    **tool_kwargs
                )
                msg = chat_completion.choices[0].message
            except Exception as e:
                # Fallback if tool formatting error occurred
                print(f"[llm fallback note] {e}")
                chat_completion = groq_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    max_tokens=450,
                    presence_penalty=0.35,
                    frequency_penalty=0.25
                )
                msg = chat_completion.choices[0].message

            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    tool_output = execute_tool(tc.function.name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output
                    })
                # Second quick roundtrip to generate spoken answer from tool output
                chat_completion_2 = groq_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    tools=FUNCTION_TOOLS,
                    max_tokens=450,
                    presence_penalty=0.35,
                    frequency_penalty=0.25
                )
                answer = chat_completion_2.choices[0].message.content
            else:
                answer = msg.content

    # Collapse degenerate repeating symbol loops (e.g. musical notes or punctuation spam)
    if answer:
        answer = re.sub(r"([♪♫♬♩*#_~•\.\s]){3,}", r"\1\1", answer)
        answer = re.sub(r"(\b\w+\b)(?:\s+\1){3,}", r"\1 \1", answer, flags=re.IGNORECASE)

    # Dynamic fallback guard if answer returned empty or blank or just an unclosed bracket
    if not answer or not answer.strip() or len(re.sub(r"^\[[^\]]*\]?\s*", "", answer).strip()) < 4:
        fb_text, fb_emo = memory.get_conversational_fallback(user_text)
        answer = f"[{fb_emo}] {fb_text}"

    history.append({"role": "assistant", "content": answer})
    history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return answer


if __name__ == "__main__":
    from riko.config import load_config
    cfg = load_config()
    check(cfg)
    print("Testing hybrid reply:")
    print("Riko:", reply("Can you check what is the capital of Japan?", cfg))
