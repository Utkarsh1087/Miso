"""Transparent floating desktop pet window for Project Riko."""
import os

# Ensure WebView2 initializes with alpha=0 transparent background
os.environ["WEBVIEW2_DEFAULT_BACKGROUND_COLOR"] = "0"

import ctypes
import threading
import time
import webview

# A dedicated chroma key color (RGB: 13, 14, 15) that does not clash with avatar colors
CHROMA_R = 13
CHROMA_G = 14
CHROMA_B = 15
CHROMA_COLORREF = CHROMA_R | (CHROMA_G << 8) | (CHROMA_B << 16)


def _apply_windows_transparency(window):
    """Enforces true hardware desktop transparency on Windows 10/11."""
    try:
        import clr
        clr.AddReference('System.Drawing')
        clr.AddReference('System.Windows.Forms')
        from System.Drawing import Color

        for _ in range(60):
            if window.native and hasattr(window.native, 'browser'):
                break
            time.sleep(0.05)

        form = window.native
        if not form:
            return

        key_color = Color.FromArgb(CHROMA_R, CHROMA_G, CHROMA_B)

        # 1. Configure the WinForms container Form
        form.AllowTransparency = True
        form.BackColor = key_color
        form.TransparencyKey = key_color

        # 2. Configure the underlying WebView2 control explicitly
        if hasattr(form, 'browser') and form.browser and hasattr(form.browser, 'webview'):
            wv = form.browser.webview
            wv.DefaultBackgroundColor = Color.Transparent
            if hasattr(wv, 'CoreWebView2') and wv.CoreWebView2:
                try:
                    wv.CoreWebView2.Controller.DefaultBackgroundColor = Color.Transparent
                except Exception:
                    pass

        # 3. Apply Win32 WS_EX_LAYERED and SetLayeredWindowAttributes
        hwnd = int(form.Handle.ToInt64())
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        LWA_COLORKEY = 1

        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        user32.SetLayeredWindowAttributes(hwnd, CHROMA_COLORREF, 0, LWA_COLORKEY)

        # 4. Position window near bottom right above the taskbar
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        win_w = 380
        win_h = 620
        pos_x = max(40, screen_w - win_w - 60)
        pos_y = max(40, screen_h - win_h - 70)
        user32.SetWindowPos(hwnd, -1, pos_x, pos_y, win_w, win_h, 0x0040)
        print("[Desktop Pet] True transparency & positioning successfully applied.")
    except Exception as e:
        print(f"[Desktop Pet] Transparency hook notice: {e}")


def main():
    print("Starting Riko as a Transparent Desktop Pet...")
    window = webview.create_window(
        title='Project Riko',
        url='http://127.0.0.1:8080/?transparent=true',
        width=380,
        height=620,
        frameless=True,
        on_top=True,
        transparent=True,
        background_color='#0d0e0f',
    )

    def on_started():
        threading.Thread(target=_apply_windows_transparency, args=(window,), daemon=True).start()

    webview.start(on_started)


if __name__ == '__main__':
    main()
