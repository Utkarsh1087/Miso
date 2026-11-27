"""Shared E2E test harness: hermetic workspace isolation, mock HTTP/LLM/Fish servers,
GLB/VRMA binary validator, headless JS syntax checker, and lazy M1-M3 contract helpers.
"""
from __future__ import annotations

import hashlib
import importlib
import io
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest import mock

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Canonical files in the real repository that E2E tests must NEVER mutate
GUARDED_REPO_FILES = (
    "profile.json",
    "chat_history.json",
    "character_config.yaml",
    "alarms.json",
)


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_minimal_wav_bytes(duration_s: float = 0.16, sample_rate: int = 16000, freq_hz: float = 440.0) -> bytes:
    """Generates a valid mono 16-bit PCM WAV buffer in memory."""
    n_samples = max(1, int(duration_s * sample_rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            val = int(12000 * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate)))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def make_minimal_glb_bytes() -> bytes:
    """Generates a minimal valid GLB v2 placeholder for dummy sample_avatar.vrm."""
    doc = {
        "asset": {"version": "2.0", "generator": "miso-e2e-fixture"},
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Root"}],
    }
    json_bytes = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4 != 0:
        json_bytes += b" "
    total_len = 12 + 8 + len(json_bytes)
    header = struct.pack("<4sII", b"glTF", 2, total_len)
    c0 = struct.pack("<II", len(json_bytes), 0x4E4F534A)
    return header + c0 + json_bytes


def require_module(test_case: Any, module_name: str):
    """Lazily imports a module so unittest discovery never crashes before M1-M3 land."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        test_case.fail(f"Contract module '{module_name}' not implemented yet: {exc}")


def require_attr(test_case: Any, obj: Any, attr_name: str, context: str = ""):
    """Lazily resolves a contract symbol, failing cleanly if missing."""
    if not hasattr(obj, attr_name):
        label = f"{context}." if context else f"{getattr(obj, '__name__', obj)}."
        test_case.fail(f"Contract symbol '{label}{attr_name}' not implemented yet")
    return getattr(obj, attr_name)


class IsolatedMisoWorkspace:
    """Hermetic temporary workspace patching ROOT and all module-level Path constants.

    Guarantees real repository files (profile.json, chat_history.json, character_config.yaml,
    alarms.json, client/audio/, character_files/senpai_*) are never touched.
    """

    def __init__(
        self,
        *,
        copy_profile: bool = True,
        copy_chat_history: bool = True,
        copy_markdown: bool = False,
        custom_profile: Optional[dict] = None,
        custom_chat_history: Optional[list] = None,
        config_overrides: Optional[dict] = None,
        block_browser: bool = True,
    ):
        self.copy_profile = copy_profile
        self.copy_chat_history = copy_chat_history
        self.copy_markdown = copy_markdown
        self.custom_profile = custom_profile
        self.custom_chat_history = custom_chat_history
        self.config_overrides = config_overrides or {}
        self.block_browser = block_browser

        self._tmp: Optional[tempfile.TemporaryDirectory] = None
        self.root: Optional[Path] = None
        self._baseline_hashes: dict[str, Optional[str]] = {}
        self._patches: list[tuple[Any, str, Any]] = []
        self._browser_patch = None
        self._env_backup: dict[str, Optional[str]] = {}

    def __enter__(self) -> "IsolatedMisoWorkspace":
        for rel in GUARDED_REPO_FILES:
            self._baseline_hashes[rel] = sha256_file(REPO_ROOT / rel)

        self._tmp = tempfile.TemporaryDirectory(prefix="miso_e2e_")
        self.root = Path(self._tmp.name)

        # Seed directory structure
        (self.root / "client" / "audio").mkdir(parents=True, exist_ok=True)
        (self.root / "character_files" / "avatars").mkdir(parents=True, exist_ok=True)
        (self.root / "screenshots").mkdir(parents=True, exist_ok=True)

        # Seed character_config.yaml
        real_cfg_path = REPO_ROOT / "character_config.yaml"
        cfg_data = yaml.safe_load(real_cfg_path.read_text(encoding="utf-8"))
        if self.config_overrides:
            for k, v in self.config_overrides.items():
                if isinstance(v, dict) and isinstance(cfg_data.get(k), dict):
                    cfg_data[k].update(v)
                else:
                    cfg_data[k] = v
        (self.root / "character_config.yaml").write_text(
            yaml.safe_dump(cfg_data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        # Seed profile.json
        if self.custom_profile is not None:
            (self.root / "profile.json").write_text(
                json.dumps(self.custom_profile, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        elif self.copy_profile and (REPO_ROOT / "profile.json").exists():
            shutil.copy2(REPO_ROOT / "profile.json", self.root / "profile.json")

        # Seed chat_history.json
        if self.custom_chat_history is not None:
            (self.root / "chat_history.json").write_text(
                json.dumps(self.custom_chat_history, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        elif self.copy_chat_history and (REPO_ROOT / "chat_history.json").exists():
            shutil.copy2(REPO_ROOT / "chat_history.json", self.root / "chat_history.json")

        # Optional Markdown files copy
        if self.copy_markdown:
            for md in ("IDENTITY.md", "MEMORIES.md", "PROFILE.md"):
                src = REPO_ROOT / md
                if src.exists():
                    shutil.copy2(src, self.root / md)

        # Seed client/index.html & minimal sample_avatar.vrm
        real_html = REPO_ROOT / "client" / "index.html"
        if real_html.exists():
            shutil.copy2(real_html, self.root / "client" / "index.html")
        else:
            (self.root / "client" / "index.html").write_text("<html></html>", encoding="utf-8")

        (self.root / "character_files" / "sample_avatar.vrm").write_bytes(make_minimal_glb_bytes())

        # Copy .vrma / vfx assets if present in real repo so MockViewerServer serves them
        for sub in ("animations", "vfx", "js"):
            src_sub = REPO_ROOT / "client" / sub
            if src_sub.exists() and src_sub.is_dir():
                shutil.copytree(src_sub, self.root / "client" / sub, dirs_exist_ok=True)

        # Patch all riko.* module ROOT and Path bindings
        self._patch_modules()

        # Block webbrowser.open by default
        if self.block_browser:
            def _blocked_browser(*args, **kwargs):
                raise AssertionError(f"webbrowser.open forbidden during automated tests: {args}")

            self._browser_patch = mock.patch("webbrowser.open", side_effect=_blocked_browser)
            self._browser_patch.start()

        return self

    def _save_and_set(self, target: Any, attr: str, value: Any):
        old_val = getattr(target, attr)
        self._patches.append((target, attr, old_val))
        setattr(target, attr, value)

    def _patch_modules(self):
        assert self.root is not None
        module_names = [
            "riko.config",
            "riko.memory",
            "riko.llm",
            "riko.tts",
            "riko.viewer",
            "riko.alarms",
            "riko.face_id",
            "riko.voice_id",
            "riko.tools",
            "riko.asr",
            "riko.vision_observer",
            "riko.cowatch",
            "riko.sentry",
            "riko.workout",
            "riko.heartbeat",
            "riko.telegram_bot",
            "riko.tags",
            "riko.memory_md",
        ]
        for mname in module_names:
            try:
                mod = importlib.import_module(mname)
            except ImportError:
                continue

            if hasattr(mod, "ROOT"):
                self._save_and_set(mod, "ROOT", self.root)

            # Remap any module-level Path constants pointing inside REPO_ROOT
            for attr_name, val in list(vars(mod).items()):
                if attr_name.startswith("__"):
                    continue
                if isinstance(val, Path):
                    try:
                        rel = val.resolve().relative_to(REPO_ROOT.resolve())
                    except ValueError:
                        continue
                    self._save_and_set(mod, attr_name, self.root / rel)

        # Explicit deterministic bindings for known critical paths
        import riko.memory as mem_mod
        import riko.tts as tts_mod
        import riko.alarms as alarms_mod
        import riko.face_id as face_mod
        import riko.voice_id as voice_mod

        explicit = [
            (mem_mod, "PROFILE_PATH", self.root / "profile.json"),
            (tts_mod, "VOICE_DIR", self.root / "client" / "audio"),
            (tts_mod, "VOICE_FILE", self.root / "client" / "audio" / "riko.wav"),
            (alarms_mod, "ALARMS_FILE", self.root / "alarms.json"),
            (face_mod, "ENROLLED_FACE_PATH", self.root / "character_files" / "senpai_face.jpg"),
            (voice_mod, "VOICEPRINT_DIR", self.root / "character_files"),
            (voice_mod, "ENROLLED_VOICEPRINT_PATH", self.root / "character_files" / "senpai_voiceprint.npy"),
            (voice_mod, "ENROLLED_VOICE_SAMPLE_PATH", self.root / "character_files" / "senpai_voice.wav"),
        ]
        for mod, attr, new_val in explicit:
            if hasattr(mod, attr):
                # Avoid double-saving if already saved above
                if not any(t is mod and a == attr for t, a, _ in self._patches):
                    self._save_and_set(mod, attr, new_val)
                else:
                    setattr(mod, attr, new_val)

        # Reset transient visual memory buffer cleanly
        if hasattr(mem_mod, "_visual_events"):
            self._save_and_set(mem_mod, "_visual_events", [])

    def set_env(self, **kwargs: Optional[str]):
        for k, v in kwargs.items():
            if k not in self._env_backup:
                self._env_backup[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._browser_patch is not None:
                self._browser_patch.stop()
                self._browser_patch = None

            for target, attr, old_val in reversed(self._patches):
                setattr(target, attr, old_val)
            self._patches.clear()

            for k, old_v in self._env_backup.items():
                if old_v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = old_v
            self._env_backup.clear()

            if self._tmp is not None:
                self._tmp.cleanup()
                self._tmp = None

            # Assert real repo guarded files are untouched
            for rel, before_hash in self._baseline_hashes.items():
                after_hash = sha256_file(REPO_ROOT / rel)
                if before_hash != after_hash:
                    raise AssertionError(
                        f"Hermetic isolation violated: real repo file '{rel}' changed "
                        f"(before={before_hash}, after={after_hash})"
                    )
        except Exception:
            if exc_type is None:
                raise


class MockViewerServer:
    """Ephemeral ThreadingHTTPServer wrapping riko.viewer._Handler without port 8080 conflicts."""

    def __init__(self, workspace: IsolatedMisoWorkspace):
        self.workspace = workspace
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.base_url: str = ""
        self.speaker_calls: list[tuple[Any, Any]] = []
        self._sd_play_patch = None
        self._sd_wait_patch = None
        self._saved_state: dict[str, Any] = {}

    def __enter__(self) -> "MockViewerServer":
        from riko import viewer

        assert self.workspace.root is not None
        self._saved_state = {
            "_avatar": viewer._avatar,
            "_active_avatar_name": viewer._active_avatar_name,
            "_page_last_seen": viewer._page_last_seen,
            "_is_speaking": viewer._is_speaking,
        }
        self._drain_clips(viewer)
        viewer._finished.clear()
        viewer._is_speaking = False
        viewer._page_last_seen = float("-inf")
        viewer._avatar = self.workspace.root / "character_files" / "sample_avatar.vrm"
        viewer._active_avatar_name = "sample_avatar.vrm"

        self._sd_play_patch = mock.patch(
            "riko.viewer.sd.play",
            side_effect=lambda data, sr, *a, **kw: self.speaker_calls.append((len(data), sr)),
        )
        self._sd_wait_patch = mock.patch("riko.viewer.sd.wait", side_effect=lambda *a, **kw: None)
        self._sd_play_patch.start()
        self._sd_wait_patch.start()

        handler_cls = partial(viewer._Handler, directory=str(self.workspace.root / "client"))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    @staticmethod
    def _drain_clips(viewer):
        while not viewer._clips.empty():
            try:
                viewer._clips.get_nowait()
            except queue.Empty:
                break

    def touch_page(self) -> dict:
        return self.get_next()

    def get_next(self) -> dict:
        r = requests.get(f"{self.base_url}/next", timeout=5)
        r.raise_for_status()
        return r.json()

    def wait_for_next_audio(self, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = self.get_next()
            if item.get("audio") or item.get("command"):
                return item
            time.sleep(0.02)
        raise TimeoutError(f"Timed out after {timeout}s waiting for /next clip")

    def post_done(self) -> requests.Response:
        r = requests.post(f"{self.base_url}/done", timeout=5)
        r.raise_for_status()
        return r

    def post_interrupted(self) -> requests.Response:
        r = requests.post(f"{self.base_url}/interrupted", timeout=5)
        r.raise_for_status()
        return r

    def post_chat(self, text: str) -> dict:
        r = requests.post(f"{self.base_url}/api/chat", json={"text": text}, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_bytes(self, rel_path: str) -> requests.Response:
        path = rel_path if rel_path.startswith("/") else f"/{rel_path}"
        return requests.get(f"{self.base_url}{path}", timeout=5)

    def __exit__(self, exc_type, exc_val, exc_tb):
        from riko import viewer

        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None

        if self._sd_play_patch is not None:
            self._sd_play_patch.stop()
        if self._sd_wait_patch is not None:
            self._sd_wait_patch.stop()

        self._drain_clips(viewer)
        viewer._finished.set()
        for k, v in self._saved_state.items():
            setattr(viewer, k, v)


@dataclass
class FishRequestEvent:
    timestamp: float
    payload: dict
    headers: dict


class MockFishServer:
    """Local HTTP /v1/tts server capturing ordered payloads/headers and returning valid WAV."""

    def __init__(self, status_code: int = 200, response_bytes: Optional[bytes] = None):
        self.status_code = status_code
        self.response_bytes = response_bytes if response_bytes is not None else make_minimal_wav_bytes()
        self.requests: list[FishRequestEvent] = []
        self._cond = threading.Condition()
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.base_url: str = ""
        self._orig_post = None
        self._post_patch = None

    def __enter__(self) -> "MockFishServer":
        parent = self

        class _FishHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {"_raw": raw.decode("utf-8", errors="replace")}

                headers_dict = {k.lower(): v for k, v in self.headers.items()}
                with parent._cond:
                    parent.requests.append(
                        FishRequestEvent(
                            timestamp=time.monotonic(),
                            payload=payload,
                            headers=headers_dict,
                        )
                    )
                    parent._cond.notify_all()

                if parent.status_code != 200:
                    body = b'{"error": "mock fish error"}'
                    self.send_response(parent.status_code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                body = parent.response_bytes
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FishHandler)
        port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self._orig_post = requests.post

        def _routed_post(url, *args, **kwargs):
            if isinstance(url, str) and url.startswith("https://api.fish.audio/v1/tts"):
                url = f"{parent.base_url}/v1/tts"
            return parent._orig_post(url, *args, **kwargs)

        self._post_patch = mock.patch("requests.post", side_effect=_routed_post)
        self._post_patch.start()
        return self

    def wait_for_requests(self, count: int, timeout: float = 5.0) -> list[FishRequestEvent]:
        deadline = time.monotonic() + timeout
        with self._cond:
            while len(self.requests) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting for {count} Fish TTS requests (got {len(self.requests)})"
                    )
                self._cond.wait(timeout=remaining)
            return list(self.requests)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._post_patch is not None:
            self._post_patch.stop()
            self._post_patch = None
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None


class FakeLLMStream:
    """Deterministic OpenAI/Groq client fake supporting sync and Event-gated streaming."""

    def __init__(
        self,
        sync_replies: Optional[list[str]] = None,
        stream_sequences: Optional[list[list[Any]]] = None,
        tool_calls_first_turn: Optional[list[dict]] = None,
    ):
        self.sync_replies = list(sync_replies or ["[neutral] Default fake reply."])
        self.stream_sequences = list(stream_sequences or [])
        self.tool_calls_first_turn = tool_calls_first_turn
        self.calls: list[dict] = []
        self._patches: list[Any] = []
        self._sync_idx = 0
        self._stream_idx = 0

    def __enter__(self) -> "FakeLLMStream":
        fake = self

        class _Completions:
            def create(self_comp, **kwargs):
                fake.calls.append(kwargs)
                if kwargs.get("stream"):
                    seq = (
                        fake.stream_sequences[fake._stream_idx]
                        if fake._stream_idx < len(fake.stream_sequences)
                        else ["[neutral] Default stream reply."]
                    )
                    fake._stream_idx += 1

                    def _gen():
                        for item in seq:
                            if isinstance(item, threading.Event):
                                if not item.wait(timeout=8.0):
                                    raise TimeoutError("FakeLLMStream barrier event timed out")
                                continue
                            if callable(item):
                                item()
                                continue
                            yield SimpleNamespace(
                                choices=[
                                    SimpleNamespace(
                                        delta=SimpleNamespace(content=str(item)),
                                        finish_reason=None,
                                    )
                                ]
                            )

                    return _gen()

                # Non-streaming response
                if fake.tool_calls_first_turn and fake._sync_idx == 0:
                    fake._sync_idx += 1
                    tcs = [
                        SimpleNamespace(
                            id=f"call_{i}",
                            function=SimpleNamespace(
                                name=tc["name"],
                                arguments=json.dumps(tc.get("arguments", {})),
                            ),
                        )
                        for i, tc in enumerate(fake.tool_calls_first_turn)
                    ]
                    msg = SimpleNamespace(content="", tool_calls=tcs)
                    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

                text = (
                    fake.sync_replies[fake._sync_idx]
                    if fake._sync_idx < len(fake.sync_replies)
                    else fake.sync_replies[-1]
                )
                fake._sync_idx += 1
                msg = SimpleNamespace(content=text, tool_calls=None)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        class _FakeClient:
            def __init__(self_c, *args, **kwargs):
                self_c.chat = SimpleNamespace(completions=_Completions())

        self._patches.append(mock.patch("openai.OpenAI", side_effect=_FakeClient))
        try:
            import riko.llm  # noqa: F401
            self._patches.append(mock.patch("riko.llm.OpenAI", side_effect=_FakeClient))
        except Exception:
            pass

        for p in self._patches:
            p.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in reversed(self._patches):
            p.stop()
        self._patches.clear()


def _reject_nonfinite_json(val: str):
    raise ValueError(f"Non-finite JSON constant in GLB/VRMA: {val}")


def _decode_accessor(doc: dict, bin_bytes: bytes, accessor_idx: int) -> list[tuple[float, ...]]:
    accessors = doc.get("accessors", [])
    if not (0 <= accessor_idx < len(accessors)):
        raise ValueError(f"Invalid accessor index: {accessor_idx}")
    acc = accessors[accessor_idx]
    if "sparse" in acc:
        raise ValueError("Sparse accessors are forbidden in VRMA")
    if acc.get("componentType") != 5126:
        raise ValueError(f"Expected FLOAT (5126) accessor, got {acc.get('componentType')}")

    type_counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
    acc_type = acc.get("type")
    if acc_type not in type_counts:
        raise ValueError(f"Unsupported accessor type: {acc_type}")
    n_comp = type_counts[acc_type]
    count = int(acc.get("count", 0))
    bv_idx = acc.get("bufferView")
    if bv_idx is None:
        return [(0.0,) * n_comp for _ in range(count)]

    bvs = doc.get("bufferViews", [])
    if not (0 <= bv_idx < len(bvs)):
        raise ValueError(f"Invalid bufferView index: {bv_idx}")
    bv = bvs[bv_idx]
    offset = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(bv.get("byteStride") or (n_comp * 4))
    fmt = f"<{n_comp}f"
    out = []
    for i in range(count):
        pos = offset + i * stride
        if pos + n_comp * 4 > len(bin_bytes):
            raise ValueError(f"Accessor {accessor_idx} out of BIN chunk bounds")
        vals = struct.unpack_from(fmt, bin_bytes, pos)
        if not all(math.isfinite(v) for v in vals):
            raise ValueError(f"Non-finite float value in accessor {accessor_idx}: {vals}")
        out.append(vals)
    return out


def validate_vrma_glb(path: Path) -> dict:
    """Validates a binary glTF 2.0 .vrma file and its VRMC_vrm_animation extension."""
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError(f"{path.name}: file too small ({len(data)} bytes) for GLB2 header")

    magic, version, total_len = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path.name}: invalid GLB magic {magic!r}")
    if version != 2:
        raise ValueError(f"{path.name}: expected GLB version 2, got {version}")
    if total_len != len(data):
        raise ValueError(f"{path.name}: declared GLB length {total_len} != actual {len(data)}")

    c0_len, c0_type = struct.unpack_from("<II", data, 12)
    if c0_type != 0x4E4F534A:
        raise ValueError(f"{path.name}: chunk 0 is not JSON (0x{c0_type:08X})")
    if 20 + c0_len > len(data):
        raise ValueError(f"{path.name}: chunk 0 exceeds file length")

    json_raw = data[20 : 20 + c0_len].decode("utf-8")
    doc = json.loads(json_raw, parse_constant=_reject_nonfinite_json)

    bin_bytes = b""
    offset = 20 + c0_len
    if offset < len(data):
        if offset + 8 > len(data):
            raise ValueError(f"{path.name}: truncated chunk 1 header")
        c1_len, c1_type = struct.unpack_from("<II", data, offset)
        if c1_type != 0x004E4942:
            raise ValueError(f"{path.name}: chunk 1 is not BIN (0x{c1_type:08X})")
        if offset + 8 + c1_len > len(data):
            raise ValueError(f"{path.name}: BIN chunk exceeds file length")
        bin_bytes = data[offset + 8 : offset + 8 + c1_len]

    if doc.get("asset", {}).get("version") != "2.0":
        raise ValueError(f"{path.name}: asset.version must be '2.0'")

    # Reject external URIs
    for buf in doc.get("buffers", []):
        uri = buf.get("uri")
        if uri and not str(uri).startswith("data:"):
            raise ValueError(f"{path.name}: external buffer URI forbidden: {uri}")

    ext_used = doc.get("extensionsUsed", [])
    if "VRMC_vrm_animation" not in ext_used:
        raise ValueError(f"{path.name}: missing 'VRMC_vrm_animation' in extensionsUsed")

    ext_root = doc.get("extensions", {})
    if "VRMC_vrm_animation" not in ext_root:
        raise ValueError(f"{path.name}: missing 'VRMC_vrm_animation' in extensions")

    vrma = ext_root["VRMC_vrm_animation"]
    human_bones = vrma.get("humanoid", {}).get("humanBones", {})
    if not isinstance(human_bones, dict) or not human_bones:
        raise ValueError(f"{path.name}: VRMC_vrm_animation.humanoid.humanBones is empty")

    nodes = doc.get("nodes", [])
    seen_nodes: set[int] = set()
    for bone_name, bone_info in human_bones.items():
        node_idx = bone_info.get("node") if isinstance(bone_info, dict) else None
        if not isinstance(node_idx, int) or not (0 <= node_idx < len(nodes)):
            raise ValueError(f"{path.name}: bone '{bone_name}' references invalid node {node_idx}")
        if node_idx in seen_nodes:
            raise ValueError(f"{path.name}: duplicate node index {node_idx} in humanBones")
        seen_nodes.add(node_idx)

    animations = doc.get("animations", [])
    if not animations:
        raise ValueError(f"{path.name}: animations list is empty")

    for anim in animations:
        samplers = anim.get("samplers", [])
        channels = anim.get("channels", [])
        if not samplers or not channels:
            raise ValueError(f"{path.name}: animation missing samplers or channels")

        for s_idx, sampler in enumerate(samplers):
            times = [t[0] for t in _decode_accessor(doc, bin_bytes, sampler["input"])]
            if not times:
                raise ValueError(f"{path.name}: sampler {s_idx} has empty input keyframes")
            if times[0] < 0.0:
                raise ValueError(f"{path.name}: sampler {s_idx} has negative start time {times[0]}")
            for i in range(1, len(times)):
                if times[i] <= times[i - 1]:
                    raise ValueError(
                        f"{path.name}: sampler {s_idx} timestamps not strictly increasing: {times[i-1]} -> {times[i]}"
                    )
            _decode_accessor(doc, bin_bytes, sampler["output"])

        for c_idx, ch in enumerate(channels):
            s_idx = ch.get("sampler")
            target = ch.get("target", {})
            node_idx = target.get("node")
            path_name = target.get("path")
            if not isinstance(s_idx, int) or not (0 <= s_idx < len(samplers)):
                raise ValueError(f"{path.name}: channel {c_idx} invalid sampler {s_idx}")
            if node_idx is not None and not (0 <= node_idx < len(nodes)):
                raise ValueError(f"{path.name}: channel {c_idx} invalid node {node_idx}")
            if path_name not in {"translation", "rotation", "scale", "weights"}:
                raise ValueError(f"{path.name}: channel {c_idx} invalid path {path_name}")

    return doc


def extract_client_module_js(html_path: Path) -> list[str]:
    """Extracts all <script type="module">...</script> blocks from client/index.html."""
    html = html_path.read_text(encoding="utf-8")
    pattern = re.compile(r'<script\s+type=["\']module["\']\s*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
    return pattern.findall(html)


def run_node_check(js_code: str, suffix: str = ".mjs") -> subprocess.CompletedProcess:
    """Runs `node --check` on a JS snippet via a self-cleaning temp file."""
    with tempfile.TemporaryDirectory(prefix="miso_node_check_") as td:
        tmp_js = Path(td) / f"check{suffix}"
        tmp_js.write_text(js_code, encoding="utf-8")
        return subprocess.run(
            ["node", "--check", str(tmp_js)],
            capture_output=True,
            text=True,
            timeout=15,
        )


def run_node_file_check(file_path: Path) -> subprocess.CompletedProcess:
    """Runs `node --check` directly on an existing JS file."""
    return subprocess.run(
        ["node", "--check", str(file_path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
