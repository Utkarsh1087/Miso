# Riku Technical Specification & Architectural Blueprint

> **Document Reference**: `docs/riku_technical_specification.md`  
> **System Name**: Project Riku (Embodied AI VTuber Companion System)  
> **Target Codebase**: `c:\web_devp_course\MERN_Projects\GENAI\Riku\riko_project`  
> **Version**: 2.0.0 (Production Specification aligned with 104-Video Riko Architecture)  
> **Status**: Verified Architectural Blueprint  

---

## Table of Contents
1. [System Architectural Overview](#1-system-architectural-overview)
2. [Subsystem 1: Low-Latency Voice Pipeline](#2-subsystem-1-low-latency-voice-pipeline)
   - [1.1 Audio Ingestion & Dual-Engine VAD](#11-audio-ingestion--dual-engine-vad)
   - [1.1b Push-to-Talk STT Mode](#11b-push-to-talk-stt-mode)
   - [1.2 Software AEC & Dynamic Barge-In Gating](#12-software-aec--dynamic-barge-in-gating)
   - [1.3 Multi-Backend ASR & Hallucination Scrubbing](#13-multi-backend-asr--hallucination-scrubbing)
   - [1.4 Streaming Sentence Chunking & Pipeline Concurrency](#14-streaming-sentence-chunking--pipeline-concurrency)
   - [1.5 Streaming TTS Engines & Prosody Inflection Markers](#15-streaming-tts-engines--prosody-inflection-markers)
   - [1.6 Latency Budget Allocation (<500ms Target)](#16-latency-budget-allocation-500ms-target)
3. [Subsystem 2: 3D Character Animation & VRM Engine](#3-subsystem-2-3d-character-animation--vrm-engine)
   - [2.1 Three.js & VRM 1.0/0.0 Client Architecture](#21-threejs--vrm-1000-client-architecture)
   - [2.2 Articulated Kinematic Multi-Joint Respiration](#22-articulated-kinematic-multi-joint-respiration)
   - [2.3 Pelvic Postural Weight Shift](#23-pelvic-postural-weight-shift)
   - [2.4 Gaze Tracking, Micro-Saccades & Attention Wandering](#24-gaze-tracking-micro-saccades--attention-wandering)
   - [2.5 Organic Double-Blinking](#25-organic-double-blinking)
   - [2.6 Conversational Gesticulation & VRM SpringBones Physics](#26-conversational-gesticulation--vrm-springbones-physics)
   - [2.7 Dynamic Wardrobe Model Hot-Reloading](#27-dynamic-wardrobe-model-hot-reloading)
4. [Subsystem 3: Facial Expressions & Viseme Synchronization](#4-subsystem-3-facial-expressions--viseme-synchronization)
   - [3.1 Web Audio FFT Formant Viseme Binning](#31-web-audio-fft-formant-viseme-binning)
   - [3.2 First-Order LERP Blendshape Smoothing](#32-first-order-lerp-blendshape-smoothing)
   - [3.3 Emotion Tag Extraction & Compound Micro-Expressions](#33-emotion-tag-extraction--compound-micro-expressions)
5. [Subsystem 4: Vision & Multimodal Perception](#5-subsystem-4-vision--multimodal-perception)
   - [4.1 DirectX Desktop Screen Capture (`mss`)](#41-directx-desktop-screen-capture-mss)
   - [4.2 DirectShow Camera Ingestion (`cv2.CAP_DSHOW`)](#42-directshow-camera-ingestion-cv2cap_dshow)
   - [4.3 Real-Time Facial Recognition Enrollment & Verification](#43-real-time-facial-recognition-enrollment--verification)
   - [4.4 Autonomous Security Sentry Mode](#44-autonomous-security-sentry-mode)
   - [4.5 Anime Video Co-Watching Scene Differencing](#45-anime-video-co-watching-scene-differencing)
   - [4.6 Workout Repetition Counter](#46-workout-repetition-counter)
6. [Subsystem 5: State, Memory, and Communication Protocols](#6-subsystem-5-state-memory-and-communication-protocols)
   - [5.1 Full-Duplex WebSocket Protocol (`/ws`) & Event Schemas](#51-full-duplex-websocket-protocol-ws--event-schemas)
   - [5.2 HTTP Polling Fallback Transport (`/next`)](#52-http-polling-fallback-transport-next)
   - [5.3 Hybrid Two-Tier Cognitive Reasoning (0ms Pre-Filter + Tools)](#53-hybrid-two-tier-cognitive-reasoning-0ms-pre-filter--tools)
   - [5.3b API Quota Auto-Fallback Protocol](#53b-api-quota-auto-fallback-protocol)
   - [5.4 Multi-Tier Memory Hierarchy & Dynamic Affection State Machine](#54-multi-tier-memory-hierarchy--dynamic-affection-state-machine)
   - [5.5 Desktop Pet Transparency & Spatial Audio](#55-desktop-pet-transparency--spatial-audio)
   - [5.6 Companion Daemons: Alarms, Heartbeat, Hotkeys, Telegram Bridge](#56-companion-daemons-alarms-heartbeat-hotkeys-telegram-bridge)
   - [5.7 Multi-Agent Coordination Architecture](#57-multi-agent-coordination-architecture)
7. [Component Interface Contracts & Data Flow](#7-component-interface-contracts--data-flow)
8. [Complete Project Code Layout](#8-complete-project-code-layout)

---

## 1. System Architectural Overview

Project Riku is architected as a real-time, low-latency, multimodal AI VTuber companion system. The architecture decouples into four independent operational planes communicating through clean interface contracts and event queues:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                  PLANE 1: SENSORY INGESTION                            │
│  • Microphone (16kHz PCM) ──> [Dual VAD: Silero / Dynamic RMS] ──> [Groq Whisper ASR]  │
│  • Webcam (DirectShow) ──> [Haar Face ID / Center-of-Motion Workout / Sentry Diff]     │
│  • Monitor (DirectX MSS) ──> [Co-Watching Differencing / Lanczos Downscaling]          │
│  • Mobile Remote ──> [Telegram Bot Bridge (Voice Notes & Photos)]                      │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Transcribed Text / Image Payloads
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                             PLANE 2: COGNITIVE REASONING (BRAIN)                       │
│  • Tier 1 Fast Match (0ms): Regex Pre-Filter (Volume, Media, Apps, Diary, Minigames)   │
│  • Tier 2 Streaming LLM: OpenAI gpt-4.1-mini (Primary) / Groq Llama 3.3 (Fallback)     │
│  • Context Buffer: Sliding 12-Turn Window (`chat_history.json`)                        │
│  • Relationship State: Persistent Diary Facts & Dynamic Affection Score (`profile.json`)│
│  • Sentence Clause Splitter: Punctuation Token Chunking (`re.split`)                   │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Clause Text Streams ('Hehe~ What are you looking at?')
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                             PLANE 3: VOICE SYNTHESIS (STREAMING TTS)                   │
│  • Cloud TTS: Fish Audio API (`s2.1-pro`, balanced latency mode, <150ms chunk turnaround)│
│  • Local TTS: GPT-SoVITS v2 Server (`http://127.0.0.1:9880/tts`, RTX GPU acceleration) │
│  • Prosody Modulation: Pitch glide `~`, breath pause `...`, tsundere pitch peak `!`     │
│  • Binary Audio Frame Encoding: 24kHz Mono 16-bit PCM / WAV Buffer Generation          │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Audio Chunks & Emotion Event Packets
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                            PLANE 4: EMBODIED 3D CLIENT (THREE.JS + VRM)                │
│  • Transport: Full-Duplex WebSocket (`/ws`) with HTTP Polling Fallback (`/next`)       │
│  • Web Audio API: 256-point FFT Formant Viseme Binning (`aa`, `oh`, `ou`, `ih`, `ee`)  │
│  • Procedural Kinematics: Multi-joint breathing, pelvic sway, gesticulation, SpringBone│
│  • Natural Gaze: Micro-saccades (1.2-3.7s), attention wander (6-12s), prolonged stare  │
│  • Physical Touch: 3D Raycaster Hitboxes (Headpat `💖` vs Body Poke `💢`)              │
│  • Desktop Shell: Win32 Chroma Key Layered Window (`desktop_pet.py`) & Electron Shell  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Subsystem 1: Low-Latency Voice Pipeline

The low-latency voice pipeline is engineered to achieve a target **Time-to-First-Audio (TTFA) under 500ms**, transforming user speech into avatar vocal response with zero perceived conversational lag.

### 1.1 Audio Ingestion & Dual-Engine VAD
Audio ingestion operates on continuous microphone input captured via `sounddevice.InputStream` configured at standardized speech specifications:
- **Sampling Rate**: $f_s = 16,000$ Hz
- **Channel Configuration**: Mono (1 channel)
- **Sample Format**: 32-bit floating point (`dtype='float32'`)
- **Frame Chunk Size**: 1,600 samples (100ms duration per processing frame)

#### Dynamic Ambient Noise Tracking & Energy VAD
Energy estimation per 100ms frame is calculated using root-mean-square (RMS) amplitude:
$$\text{RMS} = \sqrt{\frac{1}{N} \sum_{i=1}^N x_i^2} \quad (N = 1600)$$

To adapt to varying acoustic environments (e.g., air conditioning noise, computer fans, street traffic), the idle noise floor dynamically updates using an exponential moving average:
$$\text{RMS}_{amb}(t) = (1 - \beta) \cdot \text{RMS}_{amb}(t-1) + \beta \cdot \text{RMS}(t) \quad (\beta = 0.05)$$

Speech activation thresholds are defined dynamically:
$$T_{start} = \max(0.014, 2.2 \cdot \text{RMS}_{amb})$$
$$T_{sustain} = 0.75 \cdot T_{start}$$

To avoid clipping unvoiced fricatives and plosives (e.g., /s/, /t/, /p/) occurring before the RMS energy crosses $T_{start}$, the pipeline maintains a circular FIFO pre-roll ring buffer holding the 4 most recent 100ms frames (400ms total). Upon speech trigger, these 4 frames are prepended to the recording buffer.

#### Silero VAD Neural DNN Integration
For noisy environments, the pipeline supports neural voice activity detection via **Silero VAD v4/v5** running on ONNX Runtime:
- Chunk duration: 512 samples (32ms at 16kHz).
- Output: Speech probability score $P_{speech} \in [0.0, 1.0]$.
- Activation rule: $P_{speech} > 0.50$ triggers speech onset; $P_{speech} < 0.35$ sustained over 24 consecutive frames (768ms) triggers speech offset.

### 1.1b Push-to-Talk STT Mode (Feature 1)
In addition to hands-free continuous VAD, Riku provides an explicit Push-to-Talk (PTT) manual recording pipeline (`riko/asr.py:45-59`):
- **Trigger Interface**: User initiates recording via keyboard `Enter` keypress (or configured gamepad/PTT hotkey).
- **Audio Acquisition & Validation**: Audio is sampled at 16kHz mono 32-bit floating point PCM. To prevent false activations from accidental key taps or rapid double-taps, the pipeline enforces a minimum recording duration threshold:
  $$\Delta t_{rec} \ge 0.40 	ext{ s} \quad (N \ge 6,400 	ext{ samples})$$
  Any recording shorter than 0.40s or exhibiting silent energy ($	ext{RMS} < 0.010$) is immediately discarded without dispatching an API request to Groq Whisper, preventing wasted API quota.
- **Immediate Playback Cancellation**: If avatar voice playback is active (`viewer.is_playing() == True`) when the user initiates Push-to-Talk, `viewer.stop_speech()` is immediately executed, canceling current TTS synthesis, draining audio output queues, and emitting a stop command to the client.

### 1.2 Software AEC & Dynamic Barge-In Gating
Desktop companions face the classic speaker-to-microphone acoustic echo feedback loop: when Riko speaks through desktop speakers, her own voice enters the microphone, triggering false voice detections. Riku deploys **Software Acoustic Echo Cancellation via Dynamic Energy Gating** (`riko/asr.py:88-101`):

```
                        ┌─────────────────────────────────┐
                        │   Avatar Audio Playback State   │
                        └────────────────┬────────────────┘
                                         │
                     viewer.is_playing() == False (IDLE)
                                         ├─────────────────────────┐
                                         ▼                         ▼ viewer.is_playing() == True (SPEAKING)
                      ┌───────────────────────────┐   ┌───────────────────────────┐
                      │ Normal Ambient Threshold  │   │  Elevated AEC Threshold   │
                      │ T_idle = max(0.014, 2.2*R)│   │ T_active = max(0.038,     │
                      │                           │   │             3.8 * T_idle) │
                      └─────────────┬─────────────┘   └─────────────┬─────────────┘
                                    │                               │
                                    ▼                               ▼
                             RMS > T_idle ?                  RMS > T_active ?
                                    │                               │
                           YES: Trigger Speech             YES (2 frames): BARGE-IN!
                                                          • Calls viewer.stop_speech()
                                                          • Emits client 'stop' command
                                                          • Clears audio output queues
```

When avatar speech is active, the detection threshold is dynamically elevated by $3.8\times$, bounded by a critical upper safety clamp:
$$T_{active} = \min(0.120, \max(0.038, 3.8 \cdot T_{start}))$$

#### Acoustic Gating Safety Clamps & Justification:
- **Floor Clamp ($0.038$)**: Guarantees that in whisper-quiet rooms where ambient noise floor is exceptionally low ($T_{start} \approx 0.014$), the active threshold does not collapse to a level where minor speaker acoustic reflections trigger false barge-in loops.
- **Upper Safety Clamp ($0.120$)**: In high-noise environments or systems with loud speaker-to-microphone coupling, unconstrained scaling ($3.8 \cdot T_{start}$) can elevate $T_{active}$ to $0.160\text{--}0.250+$. Because normal conversational human speech at 40cm distance typically registers between $0.030$ and $0.065$ RMS, an unconstrained threshold would cause **complete user lockout**, making barge-in physically impossible unless the user shouts. Clamping $T_{active} \le 0.120$ ensures that loud intentional human voice can always trigger barge-in while suppressing speaker feedback up to 75% system volume.
- **Startup Refractory Window**: A 200ms refractory period immediately following avatar speech initiation disarms barge-in to prevent transient amplifier clicks and mechanical speaker pop transients from tripping cancellation.

#### Concurrent Threading Requirement for Software AEC
A critical architectural requirement for software AEC is **asynchronous pipeline concurrency**. In a sequential single-threaded execution model (such as early prototypes where `viewer.play()` blocks until audio playback terminates), `record_vad` is never executing while `viewer.is_playing() == True`. In that flawed architecture, barge-in is physically inoperative because the microphone is deaf while the avatar speaks.

To ensure functional AEC barge-in:
1. `record_vad` runs in a dedicated background audio ingestion thread (`AudioCaptureThread`), continuously monitoring 100ms microphone frames.
2. `viewer.play()` streams audio chunks asynchronously through WebSockets (`/ws`) or HTTP polling (`/next`).
3. While `viewer.is_playing()` evaluates to `True`, the audio capture thread dynamically evaluates $T_{active} = \min(0.120, \max(0.038, 3.8 \cdot T_{start}))$.
4. Upon detecting 2 consecutive frames exceeding $T_{active}$, the thread fires `on_speech_start()`, instantly invoking `viewer.stop_speech()`, aborting active TTS generation workers, and emitting a client cancellation event.

Because acoustic speaker reflections arriving at the microphone have lower localized energy than direct near-field human speech, speaker bleed stays strictly below $T_{active}$. When senpai speaks intentionally over Riko, his near-field voice crosses $T_{active}$ for 2 consecutive frames (200ms), immediately triggering `on_speech_start()`, which calls `viewer.stop_speech()`, halts WebGL audio playback, and cancels ongoing TTS queues.

### 1.3 Multi-Backend ASR & Hallucination Scrubbing
Riku integrates a dual-tier speech-to-text architecture prioritizing cloud speed with offline resilience:
1. **Primary Cloud STT (Groq Whisper Large v3 Turbo)**:
   - Endpoint: `https://api.groq.com/openai/v1/audio/transcriptions`
   - Model: `whisper-large-v3-turbo`
   - Prompt conditioning: `"Senpai talking with Riko."`
   - Parameter: `temperature=0.0`, `language="en"`
   - Turnaround Latency: **$90\text{--}130$ ms**.
2. **Local Fallback STT (Faster-Whisper)**:
   - Model: `base.en` (or `small.en`) quantized to `compute_type="int8"` running on CTranslate2.
   - Parameter: `beam_size=1`, `condition_on_previous_text=False`.
   - Turnaround Latency: **$280\text{--}420$ ms** on modern CPUs.

#### Hallucination Blacklist Scrubbing
Whisper models are prone to hallucinating phrases during low-level noise or trailing silence. `riko/asr.py:26-32` implements an exact-match blacklist filter:
```python
COMMON_HALLUCINATIONS = {
    "you", "thank you", "thank you.", "thank you very much.",
    "thanks for watching!", "thanks for watching.", "subtitles by",
    "music", "[music]", "(music)", "bye", "bye!", ".", "...",
    "please subscribe", "subscribe", "like and subscribe!"
}
```
Any transcript matching `COMMON_HALLUCINATIONS` (case-insensitive) or possessing fewer than 2 alphabetic characters is dropped without triggering the LLM brain.

### 1.4 Streaming Sentence Chunking & Pipeline Concurrency
To avoid waiting for the full LLM completion before commencing voice synthesis, Riku implements a streaming sentence chunker. Incoming tokens from the LLM generator are buffered until hitting a speakable punctuation boundary:
$$R_{split} = \text{`(?<=[.!?,;।\n])\s+'}$$

Once the token buffer matches $R_{split}$ and contains at least 3 words, **Chunk 0** is immediately dispatched to the TTS synthesis worker. While Chunk 0 synthesizes and begins playing on the client, Chunk 1 and Chunk 2 generate concurrently:

```
Time (ms)  0         100        200        300        400        500        600        700
STT        [=== Whisper ===]
LLM                   [Chunk 0][Chunk 1][Chunk 2]
TTS                            [=== Synth Chunk 0 ===][=== Synth Chunk 1 ===]
Audio Playback                                        [▶ Play 0 ◀──────][▶ Play 1 ◀─
                                                       ▲
                                             Time to First Audio (<500ms)
```

### 1.5 Streaming TTS Engines & Prosody Inflection Markers
Riku supports two production synthesis backends:
1. **Cloud Fish Audio API (`s2.1-pro`)**:
   - Endpoint: `https://api.fish.audio/v1/tts`
   - Format: WAV 24,000 Hz, 16-bit Mono, `latency="balanced"`
   - Default Voice: Riko Official (`5b05bc2a296046b3ac67577cb787dddc`)
   - Chunk Latency: **$110\text{--}140$ ms**.
2. **Local GPT-SoVITS v2 Server**:
   - Endpoint: `http://127.0.0.1:9880/tts`
   - Reference Audio: `character_files/main_sample.wav` (5.2s clean anime sample)
   - Reference Text: Prompt transcript conditioning vocal style
   - Chunk Latency: **$240\text{--}380$ ms** on NVIDIA RTX 3060+.

#### Prosody Inflection Formatting
To prevent the monotonous cadence of generic TTS, the LLM system prompt enforces acoustic inflection markers supported by Fish Audio and modern neural vocoders:
- **Tilde (`~`)**: Imparts an acoustic pitch glide (rising-falling frequency modulation), essential for teasing, playful, or flirtatious remarks (*'Hehe~ Senpai, are you staring again?'*).
- **Ellipsis (`...`)**: Generates an acoustic glottal closure and audible breath sigh, simulating tsundere hesitation or embarrassment (*'I mean... it's not like I care!'*).
- **Exclamation (`!`)**: Triggers fundamental frequency ($F_0$) peak elevation, expressing energetic tsundere outrage (*'Baka!'*).

### 1.6 Latency Budget Allocation & Architectural Reconciliation (<500ms Target)

A rigorous latency analysis requires distinguishing between the **legacy store-and-forward prototype** and the **optimized pipelined streaming architecture**:

#### Legacy Store-and-Forward Baseline (~3.2s – 4.5s Latency)
In the legacy un-pipelined architecture (`main.py:86-110`), operations execute strictly sequentially with full intermediate materialization:
1. **Microphone VAD Silence Hangover (800ms)**: The energy VAD requires 8 consecutive silent 100ms frames (`silence_chunks >= max_silence`) before breaking the recording loop. The physical wait time after speech cessation is strictly $\ge 800$ ms.
2. **Serial Network Cloud RTT (860ms)**: Three sequential transcontinental HTTP connections (Upload to Groq ~330ms RTT + OpenAI LLM ~320ms RTT + Fish Audio TTS ~210ms RTT) incur a baseline network propagation delay of $\ge 860$ ms.
3. **Full Completion Inference (1,800ms)**: Waiting for full LLM token generation (150 tokens $\approx 800$ ms) and full response TTS synthesis WAV write ($pprox 800$ ms).
4. **Client Polling Jitter (75ms)**: 150ms HTTP `setInterval` polling introduces 0–150ms (average 75ms) transport delay.
$$	ext{Total Legacy TTFA} = 800	ext{ms} + 440	ext{ms} + 1120	ext{ms} + 810	ext{ms} + 75	ext{ms} pprox \mathbf{3,245	ext{ ms}}$$

#### Optimized Pipelined Streaming Architecture (<500ms TTFA Target)
To shatter the multi-second barrier and achieve conversational fluidity under 500ms, Riku fundamentally re-engineers each stage:
1. **Silero Neural VAD with 200ms Hangover**: Replaces the 800ms energy hangover with a tight 200ms neural speech-offset window, detecting utterance completion in $\le 180$ ms.
2. **Groq LPU Whisper Cloud Ingestion**: Cloud Whisper Large v3 Turbo on Groq LPUs processes the 16kHz audio buffer in 110ms with persistent HTTP/2 keep-alive.
3. **Streaming Clause Pipelining (Token 6)**: The regex sentence splitter enforces a dual-delimiter rule (split on punctuation `[.!?,;]` OR on whitespace once token count exceeds 8 tokens), emitting **Chunk 0** within 45ms.
4. **Fish Audio Balanced Streaming Synthesis**: Chunk 0 is synthesized via Fish Audio `latency="balanced"` streaming API, returning the initial 24kHz audio chunk in 125ms.
5. **Full-Duplex WebSocket Delivery (`/ws`)**: Bypasses the 150ms HTTP polling cycle by streaming binary PCM chunks directly over WebSockets to Web Audio `AudioBufferSourceNode` in $< 15$ ms.

| Pipeline Stage | Component | Typical Latency | Cumulative Time | Architectural Optimization Mechanism |
|---|---|---|---|---|
| **1. VAD Detection** | Neural Silero VAD | 180 ms | 180 ms | 200ms neural hangover window (replaces 800ms energy hangover) |
| **2. Speech-to-Text**| Groq Whisper Turbo| 110 ms | 290 ms | LPU inference via cloud API with persistent HTTP/2 keep-alive |
| **3. Cognitive Chunk**| Streaming LLM | 45 ms | 335 ms | Dual-delimiter clause splitter emitting Chunk 0 at Token 5–7 |
| **4. Voice Synthesis**| Fish Audio API | 125 ms | 460 ms | Balanced latency streaming mode with direct binary chunk delivery |
| **5. Web Audio Play**| Full-Duplex `/ws` | 15 ms | **475 ms** | Binary WebSocket stream direct to Web Audio `AudioBufferSourceNode` |

---

## 3. Subsystem 2: 3D Character Animation & VRM Engine

### 2.1 Three.js & VRM 1.0/0.0 Client Architecture
The 3D presentation layer is built on **Three.js r179** and the official **`@pixiv/three-vrm` 3.4.1** runtime:
- **Scene Setup**: Perspective camera ($FOV = 30^\circ$), looking down the -Z axis at humanoid head height ($y \approx 1.35$m).
- **Coordinate Normalization**: VRM 0.0 models have an inverted forward coordinate frame. The client executes `VRMUtils.rotateVRM0(vrm)` immediately upon loading, ensuring avatar models face the camera consistently regardless of asset version.
- **Deep Resource Cleanup**: When swapping avatars at runtime (`character_files/avatars/`), the client invokes `VRMUtils.deepDispose(currentVrm.scene)` to purge textures, geometries, and shader programs from WebGL GPU memory before instantiating the new avatar.

### 2.2 Articulated Kinematic Multi-Joint Respiration
Single-bone breathing looks stiff and artificial. Riku models respiration as a kinematic chain across five humanoid skeletal nodes governed by coupled harmonic oscillators:

```
                         [ Respiration Oscillator (w = 1.6 rad/s, ~15.3 bpm) ]
                                                  │
            ┌─────────────────────┬───────────────┴───────────────┬─────────────────────┐
            ▼                     ▼                               ▼                     ▼
     [ Spine Bone ]        [ Chest Bone ]                  [ Neck Bone ]        [ Shoulder Bones ]
     Pitch Forward         Thoracic Expansion              Counter-Tilt         Vertical Shrug
     sin(1.6t) * 0.018     sin(1.6t + 0.3) * 0.014        -sin(1.6t) * 0.008    ±sin(1.6t) * 0.012
```

$$\theta_{spine.x}(t) = 0.018 \sin(1.6 t)$$
$$\theta_{spine.y}(t) = 0.012 \sin(0.4 t) \quad \text{(subtle lateral torso breathing twist)}$$
$$\theta_{chest.x}(t) = 0.014 \sin(1.6 t + 0.3) \quad \text{(phase-delayed expansion)}$$
$$\theta_{neck.x}(t) = -0.008 \sin(1.6 t) \quad \text{(cervical counter-balance)}$$
$$\theta_{shoulderLeft.z}(t) = 0.012 \sin(1.6 t), \quad \theta_{shoulderRight.z}(t) = -0.012 \sin(1.6 t)$$

### 2.3 Pelvic Postural Weight Shift
To simulate natural biological weight transfer between feet during standing idle poses, the `hips` bone undergoes continuous low-frequency lateral sway:
$$\theta_{hips.z}(t) = 0.018 \sin(0.35 t)$$
$$\theta_{hips.y}(t) = 0.015 \cos(0.28 t)$$
$$x_{hips}(t) = 0.008 \sin(0.35 t)$$

### 2.4 Gaze Tracking, Micro-Saccades & Attention Wandering
To eliminate the uncanny 'psychopathic stare' where an avatar locks eyes relentlessly with the mouse cursor, Riku decouples eye tracking into three distinct physiological behaviors:

1. **Primary Gaze Tracking**:
   - Normalizes mouse cursor coordinates $(X_{mouse}, Y_{mouse}) \in [-1, +1]^2$.
   - Maps cursor to 3D world target on plane $Z = 2.0$:
     $$X_{target} = 1.3 \cdot X_{mouse}, \quad Y_{target} = Y_{head} + 0.7 \cdot Y_{mouse}, \quad Z_{target} = 2.0$$
   - Injected into `currentVrm.lookAt.target`.

2. **Stochastic Micro-Saccades** (`client/index.html:647-656`):
   - Human eyes perform continuous rapid micro-darts to maintain visual acuity.
   - Every $t_{saccade} \sim U(1.2, 3.7)$ seconds, a ballistic perturbation vector is injected:
     $$\vec{S} = (\text{rand}(-0.06, 0.06), \text{rand}(-0.04, 0.04), 0)$$
   - Smoothly lerped into the eye LookAt coordinate.

3. **Cognitive Attention Wandering** (`client/index.html:659-674`):
   - When humans think or listen, they break direct eye contact. Every 6 to 12 seconds, Riku's gaze target drifts away to a peripheral coordinate $( \pm 0.6, Y_{head} \pm 0.2, 1.8 )$ for $1.0\text{--}2.4$ seconds before returning.

### 2.5 Organic Double-Blinking
Eyelid blinking is governed by a Poisson arrival process with a mean interval of 3.8 seconds ($t_{blink} \in [2.5, 6.3]$ s):
- Primary blink closure: 130ms duration (`blink = 1.0`).
- Double-blink probability: Exactly **28%** of blinks trigger an immediate secondary flutter (100ms closure occurring 90ms after reopening), creating unmistakable biological presence.

### 2.6 Conversational Gesticulation & VRM SpringBones Physics
- **Conversational Arm & Head Bobbing**: While voice playback is active, audio RMS amplitude drives synchronized physical gestures:
  - Right forearm raises in natural conversational cadence (`rightUpperArm.rotation.x = -0.3 + 0.2 * RMS`).
  - Subtle head nodding bobbing synchronized to syllable rhythm.
- **VRM SpringBones Physics**: Evaluated each frame via `vrm.springBoneManager.update(delta)`. Verlet particle physics simulate hair strands, ribbons, and skirt dynamics under gravity, air resistance, and spherical collision hulls placed on head, chest, and arms.

### 2.7 Dynamic Wardrobe Model Hot-Reloading
The client supports runtime avatar hot-swapping without interrupting the backend:
- User presses hotkey `W` or speaks 'change your outfit'.
- Server queries `GET /avatars`, selecting the next `.vrm` file in `character_files/avatars/`.
- Client invokes `VRMUtils.deepDispose()`, streams the new `.vrm` array buffer, executes `rotateVRM0`, and rebinds the expression manager seamlessly.

---

## 4. Subsystem 3: Facial Expressions & Viseme Synchronization

### 3.1 Web Audio FFT Formant Viseme Binning & Phonetic Architecture

#### 3-Band FFT Formant Binning (Active WebGL Implementation)
To achieve zero-overhead real-time lip-synchronization without CPU-heavy neural decoders, the Three.js client connects a Web Audio `AnalyserNode` (`fftSize = 256`, 128 frequency bins, $\Delta f = 172.26$ Hz) directly to the avatar's voice stream (`client/index.html:265-294`):

| Bin Index | Frequency Band (Hz) | Primary Formant | VRM Viseme Morph Target | Weight Formulation |
|---|---|---|---|---|
| **Bins 2–6** | 344 – 1033 Hz | $F_1$ Low Back Formant | `oh`, `ou` | $W_{oh} = \min(1.0, 1.5 \cdot \frac{1}{5}\sum_{k=2}^6 \frac{B_k}{255})$ |
| **Bins 7–16** | 1206 – 2756 Hz | $F_1/F_2$ Central Open | `aa` | $W_{aa} = \min(1.0, 1.8 \cdot \frac{1}{10}\sum_{k=7}^{16} \frac{B_k}{255})$ |
| **Bins 17–36** | 2928 – 6200 Hz | $F_2/F_3$ High Front | `ee`, `ih` | $W_{ee} = \min(1.0, 0.4 \cdot \text{Mid} + 0.9 \cdot \text{High})$ |

When silence is detected (overall audio level $< 0.015$), all mouth blendshapes (`aa`, `ih`, `ou`, `ee`, `oh`) decay rapidly to 0.0 within 40ms, preventing the avatar from keeping her mouth open during vocal pauses.

#### Acoustic Limitations of 3-Band FFT Formant Binning
While 3-band FFT formant binning is computationally lightweight (<1% CPU in browser), empirical acoustic analysis reveals notable visual fidelity limitations:
1. **Bilabial Plosives (/m/, /p/, /b/) Distortion**: Bilabial consonants require complete lip closure. However, their low nasal resonance and voice bar (~300 Hz) concentrate acoustic energy into Low Band (Bins 2–6), calculating $W_{oh} = 0.35$ and $W_{ou} = 0.16$. Consequently, the avatar's mouth pops open into an `oh` shape during sounds that physically require closed lips (e.g. *'senpai'*, *'baka'*, *'maybe'*).
2. **Sibilant Fricatives (/s/, /z/) Mouth Widening**: High-frequency dental fricatives (4,000–6,000 Hz) trigger High Band energy, calculating $W_{ee} = 0.30$ and $W_{ih} = 0.22$, pulling the lips wide when the teeth should be closed with neutral lips.
3. **High-Pitch Fundamental Harmonic Bleed**: High-pitched anime feminine vocal timbres produce prominent harmonic overtones between 1,200 and 2,500 Hz, causing false `aa` jaw opening on unvoiced or nasal transitions.

#### Upgrade Path: Rhubarb Lip Sync & Vosk Phoneme Alignment
To eliminate formant distortion and achieve professional VTuber animation fidelity, Riku defines a standardized upgrade specification to **Rhubarb Lip Sync** and **Vosk Offline Acoustic Alignment**:

1. **Rhubarb Preston Blair Phoneme Mapping**:
   - Integrates Rhubarb Lip Sync CLI / WebAssembly into the audio ingestion pipe, converting synthesized WAV audio into Preston Blair viseme targets:
     * **Shape A (Closed Lips)**: /m, b, p/ $\to$ strictly clamps all mouth blendshapes to $0.0$ (or dedicated closed-lip morph target).
     * **Shape B (Slightly Open Teeth)**: /k, s, t, d, n/ $\to$ subtle jaw drop ($0.15$), mouth width neutral.
     * **Shape C (Open Vowel)**: /e, eh, ey/ $\to$ mid opening (`ee: 0.60`, `aa: 0.30`).
     * **Shape D (Wide Open Jaw)**: /aa, ae, ay/ $\to$ maximum vertical jaw opening (`aa: 1.0`).
     * **Shape E (Rounded Lips)**: /oh, ao, ow/ $\to$ circular mouth rounding (`oh: 1.0`).
     * **Shape F (Pursed Lips)**: /ou, uw, w/ $\to$ forward lip protrusion (`ou: 1.0`).
     * **Shape G (Labiodental)**: /f, v/ $\to$ upper teeth resting on lower lip.
     * **Shape H (Alveolar Tongue)**: /l, th/ $\to$ open mouth with tongue tip elevation.
     * **Shape X (Silence Rest)**: Idle resting pose with closed lips.
2. **Vosk Offline Time-Aligned Phoneme Alignment**:
   - Deploys `vosk-model-small-en-us` (40MB offline ONNX model) in an asynchronous audio worker.
   - Outputs millisecond-accurate phoneme cue timestamps:
     ```json
     {"event": "viseme_cue", "start": 0.12, "end": 0.18, "shape": "A", "target_blendshape": "mouth_closed"}
     ```
   - Viseme cue packets are streamed over the `/ws` WebSocket alongside audio binary frames, allowing Three.js to execute frame-accurate morph target interpolation without relying on heuristic audio FFT binning.

### 3.2 First-Order LERP Blendshape Smoothing
Directly applying raw FFT weights causes high-frequency facial jitter. Riku filters all blendshape weights through a first-order exponential smoothing function:
$$W_e(t) = W_e(t-1) + \alpha \cdot (W_{target} - W_e(t-1)) \quad (\alpha = 0.12)$$
This guarantees smooth, organic transitions between facial expressions.

### 3.3 Emotion Tag Extraction & Compound Micro-Expressions
Emotion tags (`[happy]`, `[angry]`, `[sad]`, `[surprised]`, `[relaxed]`, `[neutral]`) emitted by the LLM are stripped from spoken dialogue and mapped to compound multi-blendshape poses:

| Emotion State | Primary Blendshape | Secondary Blendshapes | Humanoid Skeletal Pose |
|---|---|---|---|
| **Neutral** | none (all 0.0) | `blink` (periodic) | Natural upright, idle respiration active |
| **Happy** | `happy: 0.85` | `relaxed: 0.30` | Energetic vertical bounce, head tilted, right hand wave |
| **Angry (Tsundere)** | `angry: 0.90` | `surprised: 0.20` | Crossed arms (`leftArm: -0.4, 0.45, -0.9`), huffing head tilt |
| **Surprised** | `surprised: 0.85` | `aa: 0.15` | Leaning backward (`spine.x = -0.07`), both hands raised |
| **Sad** | `sad: 0.85` | none | Drooped shoulders (`shoulder: ±0.03`), bowed head (`head.x = 0.18`) |
| **Flustered / Blush**| `surprised: 0.65` | `happy: 0.85`, `blink: 0.45`| Averted head (`head.y = -0.32`), fidgeting arm posture |
| **Headpat Bliss** | `happy: 0.95` | `relaxed: 0.85`, `blink: 0.55`| Head tilted upward (`head.x = -0.12`), rhythmic leaning |

---

## 5. Subsystem 4: Vision & Multimodal Perception

### 4.1 DirectX Desktop Screen Capture (`mss`)
- **DirectX Duplication**: Screen capture uses `mss.mss()`, binding directly to the Windows DirectX Desktop Duplication API ($<15$ms frame acquisition).
- **Downscaling Pipeline**: Frame buffer is resized via Pillow to a maximum width of 800px maintaining aspect ratio using high-quality Lanczos resampling.
- **Compression & Encoding**: Encoded in-memory to JPEG at quality 80 and converted to base64 Data URI for multimodal LLM ingestion (`qwen/qwen3.8-27b` on Groq or `gpt-4o`).

### 4.2 DirectShow Camera Ingestion (`cv2.CAP_DSHOW`)
- **DirectShow Backend**: Specifying `cv2.CAP_DSHOW` in `cv2.VideoCapture(0, cv2.CAP_DSHOW)` avoids Windows Media Foundation's 2.5-second initialization delay.
- **Auto-Exposure Warmup**: Reads and discards 2 initial frames to allow hardware camera sensor auto-exposure and auto-white-balance to stabilize.
- **Output**: $640 \times 480$ RGB JPEG base64 payload.

### 4.3 Real-Time Facial Recognition Enrollment & Verification
Implemented in `riko/face_id.py`:
1. **Face Enrollment**: User triggers 'enroll my face'. System captures webcam frame, applies OpenCV Haar Cascade (`haarcascade_frontalface_default.xml`), extracts bounding box with 15% padding, normalizes to $256 \times 256$ 8-bit grayscale, and stores to `character_files/senpai_face.jpg`.
2. **Verification Matching**: Live webcam frames are compared against the enrolled template using normalized cross-correlation:
   $$R(x, y) = \frac{\sum_{x', y'} (T(x', y') - \bar{T})(I(x+x', y+y') - \bar{I}_{x, y})}{\sqrt{\sum_{x', y'} (T(x', y') - \bar{T})^2 \sum_{x', y'} (I(x+x', y+y') - \bar{I}_{x, y})^2}}$$
   - If peak correlation $R_{max} \ge 0.40$, identity is verified as Utkarsh Senpai.
   - If $R_{max} < 0.40$, system flags an unfamiliar stranger, prompting Riko to enter defensive tsundere interrogation mode.

### 4.4 Autonomous Security Sentry Mode
Implemented in `riko/sentry.py`:
- Continuous background webcam thread capturing at 3 FPS ($320 \times 240$ resolution).
- Applies 2D Gaussian blur kernel ($K = 21 \times 21, \sigma = 0$) and computes absolute frame difference $D(x, y) = |G_t(x, y) - G_{t-1}(x, y)|$.
- Thresholds at $\tau = 25$ to generate binary motion mask. Motion ratio:
  $$M = \frac{1}{W \cdot H} \sum_{x,y} [D(x,y) > 25]$$
- If $M > 0.035$ across 2 consecutive evaluation cycles, an intruder alert triggers: Riko vocalizes a warning and sends a captured snapshot to the vision LLM for witty commentary.

### 4.5 Anime Video Co-Watching Scene Differencing
Implemented in `riko/cowatch.py`:
- Samples desktop screen every 12 seconds downscaled to $160 \times 90$ thumbnails.
- Computes mean absolute luminance pixel delta:
  $$\Delta_{scene} = \frac{1}{160 \times 90} \sum_{x,y} |I_t(x,y) - I_{t-1}(x,y)|$$
- If $\Delta_{scene} > 12.0$ (indicating an anime scene cut or high-action sequence) and avatar is not currently speaking, triggers spontaneous sassy reaction via vision LLM with a 20-second cooldown.

### 4.6 Workout Repetition Counter
Implemented in `riko/workout.py`:
- Tracks vertical center-of-gravity displacement of user in webcam frames.
- Detects downward phase ($dy > 6$ px) and upward completion ($dy < -6$ px) with vertical stroke requirement $> 15$ px.
- Counts exercise repetitions out loud (pushups, squats, curls) with comedic tsundere motivation (*'Come on senpai, my twin-tails have more muscle than that!'*).

---

## 6. Subsystem 5: State, Memory, and Communication Protocols

### 5.1 Full-Duplex WebSocket Protocol (`/ws`) & Event Schemas
Riku's primary real-time transport connects the Python backend server (`riko/viewer.py`) and the WebGL client (`client/index.html`) over `ws://127.0.0.1:8080/ws`.

#### Client $\to$ Server Event Schemas
```json
// 1. User Barge-In Signal (Microphone Speech Onset)
{
  "event": "barge_in",
  "timestamp_ms": 1731401234567,
  "reason": "speech_detected"
}

// 2. Playback Acknowledgment / Completion
{
  "event": "playback_ended",
  "clip_id": "chunk_1731401234_0",
  "duration_sec": 1.42
}

// 3. Avatar Physical Touch Interaction
{
  "event": "avatar_touch",
  "zone": "head",
  "coordinates": {"x": 0.05, "y": 1.38, "z": 0.12},
  "timestamp_ms": 1731401235100
}

// 4. Prolonged Stare Hover
{
  "event": "stare_detected",
  "duration_sec": 3.95
}
```

#### Server $\to$ Client Event Schemas
```json
// 1. Speech Generation Header
{
  "event": "speech_start",
  "stream_id": "stream_9918",
  "emotion": "happy",
  "text": "Hehe~ What are you looking at, senpai?"
}

// 2. Streaming Audio Chunk Metadata (Followed immediately by Binary Frame)
{
  "event": "audio_chunk",
  "stream_id": "stream_9918",
  "chunk_index": 0,
  "is_final": false,
  "sample_rate": 24000,
  "channels": 1
}

// 3. System Action Command
{
  "event": "command",
  "action": "stop"
}
```

### 5.2 HTTP Polling Fallback Transport (`/next`)
To maintain 100% backward compatibility with the upstream 50K snapshot, Riku preserves the HTTP polling interface:
- `GET /next` (polled every 150ms by client): Returns `{"audio": "audio/riko.wav?v=...", "emotion": "happy", "command": null}` or `{"command": "stop"}`.
- `POST /done`: Signals playback completion.
- `POST /interrupted`: Signals barge-in interruption.
- `GET /avatars`: Lists installed `.vrm` files.
- `GET /avatar.vrm`: Serves active avatar binary stream.

### 5.3 Hybrid Two-Tier Cognitive Reasoning (0ms Pre-Filter + Tools)
Riku solves LLM tool latency by deploying a hybrid two-tier reasoning architecture:

```
                           [ User Spoken Utterance ]
                                       │
                                       ▼
                    ┌─────────────────────────────────────┐
                    │     Tier 1: 0ms Regex Pre-Filter    │
                    └──────────────────┬──────────────────┘
                                       │
                      Matches regex pattern for system action?
                                       ├─────────────────────────────┐
                                       ▼ YES                         ▼ NO
                     ┌──────────────────────────────────┐   ┌──────────────────────────────────┐
                     │      Instant Action Execution    │   │      Tier 2: Streaming LLM       │
                     │ • Volume Mute / Up / Down        │   │ • gpt-4.1-mini / Groq Llama 3.3  │
                     │ • Open App / Play YouTube        │   │ • Structured FUNCTION_TOOLS      │
                     │ • Sentry / Workout / Co-watch    │   │ • Vague-Word Tool Guard          │
                     │ • Save Diary Fact to profile.json│   │ • Emotion Bracket Extraction     │
                     └──────────────────────────────────┘   └──────────────────────────────────┘
```

#### Vague-Word Tool Guard
LLM function calling frequently hallucinates system actions on casual utterances (e.g., user saying 'Play' in casual banter triggering YouTube playback). `riko/llm.py:336-363` enforces a vague-word guard:
- If user input is fewer than 4 words and contains no explicit imperative action keywords, tool schemas are withheld from the LLM completion call, ensuring pure conversational responses.

### 5.3b API Quota Auto-Fallback Protocol (Feature 38)
To prevent conversational crashes when cloud LLM rate limits or billing quotas are exhausted, Riku implements an automated multi-provider failover interceptor (`riko/llm.py:440-475`):

```
                       [ Incoming Conversational Turn ]
                                       │
                                       ▼
                   ┌───────────────────────────────────────┐
                   │    Primary: OpenAI gpt-4.1-mini       │
                   └───────────────────┬───────────────────┘
                                       │
                         Completion Request Status
                                       ├───────────────────────────────┐
                                       ▼ HTTP 200 OK                   ▼ HTTP 429 / Quota Error
                     ┌───────────────────────────────────┐   ┌───────────────────────────────────┐
                     │ Stream Tokens to Sentence Chunker │   │   API Quota Fallback Interceptor  │
                     └───────────────────────────────────┘   │ • Catch openai.RateLimitError     │
                                                             │ • Catch 'insufficient_quota' error│
                                                             └─────────────────┬─────────────────┘
                                                                               │
                                                                               ▼
                                                             ┌───────────────────────────────────┐
                                                             │    Secondary: Groq Llama 3.3 70B  │
                                                             │ • Re-inject 12-turn chat history  │
                                                             │ • Retain persona & diary facts    │
                                                             │ • Stream tokens via Groq API      │
                                                             │ • Activate 5-min cooldown circuit │
                                                             └───────────────────────────────────┘
```

#### Failover Execution Specification:
1. **Exception Interception**: The completion caller wraps OpenAI API requests in a dedicated handler intercepting `openai.RateLimitError` (HTTP 429), `openai.APIConnectionError`, and JSON error responses containing `"insufficient_quota"`.
2. **Context State Migration**:
   - The active 12-turn conversation window from `chat_history.json` and persistent memory context from `profile.json` are packaged without data loss.
   - Function schemas (`FUNCTION_TOOLS`) are translated to Groq-compatible OpenAI SDK format.
3. **Secondary Provider Execution**: The completion request is instantaneously rerouted to Groq Cloud running `llama-3.3-70b-versatile` (or `qwen-2.5-32b`), which delivers high-throughput inference (>250 tokens/sec) on Groq LPUs.
4. **Circuit Breaker Cooldown**: Once triggered, a 300-second (5-minute) circuit breaker engages. Subsequent dialogue turns bypass OpenAI entirely during the cooldown period, eliminating repeated 429 connection timeouts. After 300s, a background canary probe tests OpenAI availability to restore primary routing.

### 5.4 Multi-Tier Memory Hierarchy & Dynamic Affection State Machine
1. **Short-Term Conversational Buffer (`chat_history.json`)**:
   - Maintains a sliding window FIFO array bounded by `MAX_HISTORY_TURNS = 12`.
2. **Persistent Long-Term Diary (`profile.json`)**:
   - Automatically stores personal facts extracted via regex (`\bremember\s+(that\s+)?(.+)`, `\bmy name is\s+([a-zA-Z0-9\s]+)`).
   - Injected into every LLM completion prompt under `Personal Facts about Senpai:`.
3. **Dynamic Affection Meter State Machine**:
   - Affection score bounded within $[-50, +100]$.
   - Dynamic persona conditioning injected into prompt:
     - $<0$: **Hostile Tsundere** (*'You're annoying, senpai. Why are you even talking to me?'*)
     - $0\dots 39$: **Classic Tsundere** (*'B-Baka! It's not like I made this for you!'*)
     - $40\dots 74$: **Warm Partner** (*'Hehe~ You actually remembered, senpai? Good job!'*)
     - $\ge 75$: **Full Dere** (*'I'm really glad you're here with me, senpai...'* )

### 5.5 Desktop Pet Transparency & Spatial Audio
- **Win32 Layered Chroma Key Window (`desktop_pet.py`)**: Edge WebView2 runtime styled with chroma key `RGB(13, 14, 15)`. Windows Win32 API hooks `WS_EX_LAYERED` and `SetLayeredWindowAttributes(hwnd, 0x000F0E0D, 0, LWA_COLORKEY)` to achieve borderless hardware transparency.
- **Spatial Audio Panning**: Web Audio `StereoPannerNode` calculating stereo pan based on desktop screen coordinates:
  $$\text{pan} = 2.0 \cdot \left(\frac{\text{window.screenX}}{\text{screenWidth}}\right) - 1.0 \quad (\text{clamped to } [-0.85, +0.85])$$

### 5.6 Companion Daemons: Alarms, Heartbeat, Hotkeys, Telegram Bridge
- **Relentless Alarm Clock (`riko/alarms.py`)**: Thread checking `alarms.json` every second. Emits continuous escalating spoken roasts until user responds.
- **Proactive Heartbeat (`riko/heartbeat.py`)**: Prompts LLM to initiate autonomous check-in when user is idle for $>15$ minutes between 7 AM and 2 AM.
- **Global Windows Hotkeys (`riko/hotkeys.py`, Feature 44)**: System-wide low-level keyboard hooks running in a background daemon thread (`RegisterHotKey` / `keyboard` listener):
  * `Ctrl+Alt+R`: Instantly captures the primary display screen via DirectX `mss`, Lanczos downscales to 800px, and triggers Riko's vision commentary.
  * `Ctrl+Alt+C`: Captures a live webcam frame via DirectShow (`cv2.CAP_DSHOW`) with 2-frame warmup and prompts Riko to describe what senpai is doing.
  * Daemon execution ensures hotkeys respond instantaneously regardless of which game, IDE, or desktop window currently possesses OS focus.
- **Mobile Telegram Bridge (`riko/telegram_bot.py`, Feature 45)**: Long-polling Telegram bot enabling remote voice note conversation and photo chat from mobile phones.

### 5.7 Multi-Agent Coordination Architecture (Feature 48)
Videos 96 and 97 demonstrate Riko interacting in a multi-companion environment (e.g. Riko and a rival Tsundere sister or Furina). Riku formalizes this capability into the **Multi-Agent Coordination Architecture**:

```
                                  [ User Utterance / Trigger ]
                                                │
                                                ▼
                              ┌───────────────────────────────────┐
                              │     Turn-Taking Orchestrator      │
                              │ • Loop Counter: turns <= 3        │
                              │ • Priority User Barge-In Monitor  │
                              └─────────────────┬─────────────────┘
                                                │
                                                ▼
                              ┌───────────────────────────────────┐
                              │             Agent A               │
                              │ (System: Riko, Sweet & Teasing)   │
                              └─────────────────┬─────────────────┘
                                                │ Agent A Voice & Dialogue
                                                ├───────────────────────────────┐
                                                ▼                               ▼
                              ┌───────────────────────────────────┐   ┌───────────────────────────────────┐
                              │       Three.js Scene Graph        │   │    Agent B Context Ingestion      │
                              │ • VRM 1: Riko (X = -0.45m)        │   │ Prompt: "[Agent A said: ...]      │
                              │ • VRM 2: Furina (X = +0.45m)      │   │  Respond naturally to Agent A"    │
                              │ • Mutual Yaw Orientation (±15°)   │   └─────────────────┬─────────────────┘
                              └───────────────────────────────────┘                     │
                                                                                        ▼
                                                                      ┌───────────────────────────────────┐
                                                                      │             Agent B               │
                                                                      │ (System: Furina, Drama Tsundere)  │
                                                                      └─────────────────┬─────────────────┘
                                                                                        │
                                                                        [ Agent B Voice & Dialogue ]
                                                                                        │
                                                                                        ▼
                                                                      Orchestrator increments loop count;
                                                                      Yields after 3 autonomous turns.
```

#### Multi-Agent Engineering Protocols:
1. **Dual VRM WebGL Scene Graph**:
   - The Three.js client instantiates multiple `VRM` instances in the same WebGL scene canvas.
   - Spatial layout: Agent 1 (Riko) positioned at $x = -0.45	ext{m}$, Agent 2 (Furina / Tsundere) positioned at $x = +0.45	ext{m}$.
   - Skeletal orientation: Both models rotate inward with a slight mutual yaw angle ($\pm 15^\circ$), directing gaze between senpai and each other.
   - Separate animation managers: Each avatar possesses independent instances of `VRMExpressionManager`, `VRMLookAtHead`, and `VRMSpringBoneManager`.
2. **Autonomous Turn-Taking & Prompt Formatting**:
   - When multi-agent mode is active, the completion orchestrator alternates dialogue turns.
   - After Agent A finishes speaking, her transcript is injected into Agent B's prompt:
     `[Senpai is watching. Agent A just said to you: "{agent_a_speech}". Respond directly to Agent A in your distinctive personality, maintaining the banter.]`
   - Agent B generates her reply, which triggers Agent B's unique voice preset and viseme stream.
3. **Turn Arbitration & Infinite Loop Breaker**:
   - Autonomous conversational agents naturally tend toward infinite recursive conversation loops, consuming API tokens indefinitely.
   - Riku enforces a hard turn arbitrator: `MAX_AUTONOMOUS_TURNS = 3`.
   - After 3 consecutive inter-agent exchanges without human participation, the orchestrator automatically suspends autonomous generation, transitioning both avatars to idle respiration state until senpai speaks again.
   - **Barge-In Priority Preemption**: Any detected user speech immediately terminates the autonomous turn loop and yields control back to senpai.
4. **Acoustic Cross-Talk & Echo Prevention**:
   - In physical speaker environments, Agent A's voice playing through desktop speakers could easily be picked up by the microphone and mistakenly interpreted as user speech directed at Agent B.
   - Software AEC elevation ($T_{active} = \min(0.120, \dots)$) is asserted globally whenever *any* agent is speaking (`any(a.is_speaking() for a in agents)`).
   - Agent-to-agent dialogue transmission occurs strictly via internal memory buffers rather than acoustic loopback, guaranteeing zero acoustic distortion or false speech triggers.

---

## 7. Component Interface Contracts & Data Flow

### Contract 1: Audio Ingestion ↔ LLM Brain (`riko/asr.py` $\to$ `riko/llm.py`)
```python
def record_vad(on_speech_start: Optional[Callable[[], None]] = None) -> Optional[np.ndarray]:
    """Continuously samples microphone; triggers on_speech_start() upon voice onset.
    Returns float32 mono 16kHz audio buffer or None on silence."""

def transcribe(audio: np.ndarray) -> str:
    """Transcribes speech buffer using Groq Whisper (fallback to Faster-Whisper).
    Returns cleaned transcript string with hallucinations scrubbed."""
```

### Contract 2: LLM Brain ↔ TTS Pipeline (`riko/llm.py` $\to$ `riko/tts.py`)
```python
def stream_tts_clauses(text_stream: Iterator[str]) -> Iterator[Tuple[str, bytes]]:
    """Consumes streaming token generator, yields (emotion_tag, wav_bytes) per sentence clause."""
```

### Contract 3: Backend Server ↔ Three.js Client (`riko/viewer.py` $\leftrightarrow$ `client/index.html`)
- Server exposes `/ws` endpoint for bi-directional JSON/binary frames.
- Server exposes `/next`, `/done`, `/interrupted`, `/avatar.vrm`, `/avatars` for HTTP polling.

---

## 8. Complete Project Code Layout

```
c:\web_devp_course\MERN_Projects\GENAI\Riku\riko_project\
├── .env                         # API keys (OPENAI, GROQ, FISH, TELEGRAM)
├── character_config.yaml        # Persona prompt, voice presets, ears thresholds
├── chat_history.json            # Sliding 12-turn conversational memory
├── profile.json                 # Persistent diary facts and affection score
├── desktop_pet.py               # PyWebView Win32 chroma-key desktop pet
├── electron_pet.js              # Electron frameless transparent desktop shell
├── main.py                      # Unified conversational orchestrator
├── pyproject.toml               # Python dependencies and packaging specs
├── character_files/
│   ├── avatars/                 # User-provided .vrm wardrobe models
│   ├── main_sample.wav          # GPT-SoVITS local voice cloning reference sample
│   └── sample_avatar.vrm        # Bundled VRM 1.0 sample 3D avatar
├── client/
│   ├── index.html               # Three.js r179 + @pixiv/three-vrm client with FFT visemes
│   └── audio/                   # Audio output cache directory
├── docs/
│   ├── rayen_104_video_analysis.md    # Requirement R1
│   ├── riku_technical_specification.md # Requirement R2
│   └── riku_implementation_roadmap.md  # Requirement R3
└── riko/
    ├── alarms.py                # Persistent wake-up alarm clock daemon
    ├── asr.py                   # Hands-free VAD, AEC barge-in & Groq Whisper
    ├── config.py                # Configuration and environment loader
    ├── cowatch.py               # Screen diff anime co-watching tracker
    ├── face_id.py               # Webcam face enrollment & template matching
    ├── heartbeat.py             # Proactive background check-in daemon
    ├── hotkeys.py               # Global hotkey hooks (Ctrl+Alt+R, Ctrl+Alt+C)
    ├── llm.py                   # Hybrid 2-tier brain: regex pre-filter + tools
    ├── memory.py                # Diary facts & Affection Meter state machine
    ├── sentry.py                # Autonomous webcam room security sentry
    ├── telegram_bot.py          # Mobile Telegram bot bridge
    ├── tools.py                 # Media keys, YouTube search, vision tools
    ├── tts.py                   # Fish Audio cloud & GPT-SoVITS local synthesis
    ├── viewer.py                # Dual WebSocket & HTTP polling viewer server
    └── workout.py               # Webcam vertical motion exercise rep counter
```
