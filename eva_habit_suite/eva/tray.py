"""
tray.py
-------
A small system tray icon (next to the clock on Windows) with a menu to
show either window or quit the app. Safe no-op if pystray isn't installed.
"""

import threading


def start_tray(assistant_name, logger, on_show_user, on_show_agent, on_quit):
    try:
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (64, 64), "black")
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=(0, 229, 255))

        menu = pystray.Menu(
            pystray.MenuItem(f"Show {assistant_name}", lambda: on_show_user()),
            pystray.MenuItem("Show Agent View", lambda: on_show_agent()),
            pystray.MenuItem("Quit", lambda: on_quit()),
        )
        icon = pystray.Icon(assistant_name, img, assistant_name, menu)
        threading.Thread(target=icon.run, daemon=True).start()
        logger.info("[Tray] System tray icon started.")
        return icon
    except ImportError:
        logger.warning("[Tray] pystray/Pillow unavailable - system tray icon disabled.")
        return None
    except Exception as e:
        logger.warning(f"[Tray] Could not start system tray icon: {e}")
        return None
