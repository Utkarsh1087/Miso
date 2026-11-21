"""Global hotkey support for Project Riko."""
import threading

try:
    import keyboard
except ImportError:
    keyboard = None


def setup_global_hotkeys(on_inspect_screen=None, on_inspect_camera=None, on_inspect=None):
    """Registers system-wide hotkeys:
    - Ctrl + Alt + R: Instant Screen Vision
    - Ctrl + Alt + C: Instant Camera Vision (look at senpai)
    """
    if not keyboard:
        return

    # Backward compatibility for single on_inspect parameter
    screen_cb = on_inspect_screen or on_inspect
    camera_cb = on_inspect_camera

    def trigger_screen():
        if screen_cb:
            threading.Thread(target=screen_cb, daemon=True).start()

    def trigger_camera():
        if camera_cb:
            threading.Thread(target=camera_cb, daemon=True).start()

    try:
        keyboard.add_hotkey("ctrl+alt+r", trigger_screen)
        print("[hotkeys] Registered global shortcut: Ctrl+Alt+R (Screen Vision)")
    except Exception:
        pass

    try:
        keyboard.add_hotkey("ctrl+alt+c", trigger_camera)
        print("[hotkeys] Registered global shortcut: Ctrl+Alt+C (Webcam Camera Vision)")
    except Exception:
        pass

