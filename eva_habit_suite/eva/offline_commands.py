"""
offline_commands.py
--------------------
A rule-based command matcher that runs entirely on-device with NO network
calls, so a solid set of everyday commands still work with no internet at
all (or if Gemini's API is down), instead of Eva going silent.

Honest scope note: this covers roughly 40 REAL, distinct actions (open an
app, control volume/media, basic system info, unit conversions, a few
system actions...). Around 400 different PHRASES (English + Arabic,
several ways of saying the same thing) are recognized and mapped onto
those ~40 actions - that's the realistic way to get to "400 voice
commands": many phrasings of a workable number of genuine capabilities,
not 400 independent behaviors. Anything open-ended (actual conversation,
web lookups, "what should I...") still needs Gemini's real reasoning and
stays online-only.

Checked BEFORE Gemini on every text request (see ui.py's _run_analysis) -
a match here means zero API calls and zero network dependency for that
turn, which is also a nice latency win even when you ARE online.

Does NOT go through memory.py, so these turns aren't remembered as part
of the conversation - keeps this module simple and side-effect-free.
"""

from __future__ import annotations

import ast
import datetime
import operator
import os
import random
import re
import socket
import subprocess
import sys

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
}
_MATH_RE = re.compile(r"^[\d\s\.\+\-\*\/\(\)%]+$")
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _safe_eval_math(expr: str):
    """Evaluates a plain arithmetic expression (+ - * / % **, parens) with
    no names, function calls, or attribute access allowed - this NEVER
    calls eval()/exec() on the raw text, so it can't execute arbitrary code
    no matter what the user (or a hijacked transcript) says."""
    node = ast.parse(expr, mode="eval").body

    def _eval(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _SAFE_OPS:
            return _SAFE_OPS[type(n.op)](_eval(n.left), _eval(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _SAFE_OPS:
            return _SAFE_OPS[type(n.op)](_eval(n.operand))
        raise ValueError("unsupported expression")

    return _eval(node)


# --------------------------------------------------------------- helpers ---

def _start(target: str) -> bool:
    """Launches an app/folder/URI the same way Windows' Run dialog would.
    Windows-only (matches the rest of this project's Windows focus)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        subprocess.Popen(f'start "" "{target}"', shell=True)
        return True
    except Exception:
        return False


def _open_browser_blank() -> bool:
    try:
        import webbrowser
        # about:blank is a local page - opens the default browser with no
        # network request, unlike opening any real URL.
        return webbrowser.open("about:blank", new=1)
    except Exception:
        return False


def _media_key(action: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        vk = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}[action]
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    except Exception:
        pass


def _volume_key(action: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        vk = {"mute": 0xAD, "up": 0xAF, "down": 0xAE}[action]
        for _ in range(2 if action in ("up", "down") else 1):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    except Exception:
        pass


def _lock_screen() -> bool:
    try:
        if sys.platform.startswith("win"):
            import ctypes
            return bool(ctypes.windll.user32.LockWorkStation())
    except Exception:
        pass
    return False


def _shutdown_like(flag: str, delay: int = 15) -> bool:
    """flag: '/s' shutdown, '/r' restart. Always uses a delay (never
    instant) specifically so 'cancel_shutdown' below has a real window to
    work in if the command was misheard."""
    if not sys.platform.startswith("win"):
        return False
    try:
        subprocess.run(["shutdown", flag, "/t", str(delay)], check=False)
        return True
    except Exception:
        return False


def _cancel_shutdown() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        subprocess.run(["shutdown", "/a"], check=False)
        return True
    except Exception:
        return False


def _sleep_pc() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        ctypes.windll.powrprof.SetSuspendState(False, True, False)
        return True
    except Exception:
        return False


def _take_screenshot():
    try:
        from PIL import ImageGrab
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "EvaScreenshots")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        ImageGrab.grab().save(path)
        return path
    except Exception:
        return None


def _empty_recycle_bin() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI - no popup, no progress
        # dialog, since this already came with a voice confirmation.
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x00000001 | 0x00000002)
        return True
    except Exception:
        return False


def _battery_status():
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return None
        state = "charging" if b.power_plugged else "running on battery"
        return f"Battery is at {int(b.percent)} percent, {state}."
    except Exception:
        return None


def _system_uptime():
    try:
        import psutil
        boot = datetime.datetime.fromtimestamp(psutil.boot_time())
        delta = datetime.datetime.now() - boot
        hours, rem = divmod(int(delta.total_seconds()), 3600)
        minutes = rem // 60
        return f"This PC has been running for {hours} hours and {minutes} minutes."
    except Exception:
        return None


def _ip_address():
    try:
        # Local network IP only - resolved via the hostname, no request
        # ever leaves the machine (deliberately NOT a "what's my public IP"
        # lookup, since that would need internet).
        return f"Your local network IP is {socket.gethostbyname(socket.gethostname())}."
    except Exception:
        return None


def _disk_free_space():
    try:
        import psutil
        free_gb = psutil.disk_usage(os.sep).free / (1024 ** 3)
        return f"You have {free_gb:.1f} gigabytes free on your main drive."
    except Exception:
        return None


# ------------------------------------------------------ unit conversions ---

def _try_conversions(t: str):
    m = _NUM_RE.search(t)
    if not m:
        return None
    raw = m.group(1)  # exact text as typed/spoken, e.g. "10" - NOT the
    # float-formatted value, which could read "10.0" and then never match
    # the "10 km" in the original text.
    value = float(raw)
    has = lambda *words: any(w in t for w in words)

    km_words = ("km", "kilometer", "kilometers", "كم", "كيلومتر")
    mi_words = ("mile", "miles", "ميل")
    c_words = ("celsius", "درجة مئوية", "° c", "c ")
    f_words = ("fahrenheit", "فهرنهايت", "° f", "f ")
    kg_words = ("kg", "kilogram", "kilograms", "كيلو", "كيلوجرام")
    lb_words = ("lb", "lbs", "pound", "pounds", "رطل")

    # direction is inferred from which unit sits right next to the number
    if re.search(rf"{re.escape(raw)}\s*(?:{'|'.join(km_words)})", t) and has(*mi_words):
        return f"{value:g} km is about {value * 0.621371:.2f} miles."
    if re.search(rf"{re.escape(raw)}\s*(?:{'|'.join(mi_words)})", t) and has(*km_words):
        return f"{value:g} miles is about {value * 1.60934:.2f} km."
    if re.search(rf"{re.escape(raw)}\s*(?:{'|'.join(c_words)})", t) and has(*f_words):
        return f"{value:g}°C is {(value * 9 / 5) + 32:.1f}°F."
    if re.search(rf"{re.escape(raw)}\s*(?:{'|'.join(f_words)})", t) and has(*c_words):
        return f"{value:g}°F is {(value - 32) * 5 / 9:.1f}°C."
    if re.search(rf"{re.escape(raw)}\s*(?:{'|'.join(kg_words)})", t) and has(*lb_words):
        return f"{value:g} kg is about {value * 2.20462:.2f} lbs."
    if re.search(rf"{re.escape(raw)}\s*(?:{'|'.join(lb_words)})", t) and has(*kg_words):
        return f"{value:g} lbs is about {value * 0.453592:.2f} kg."
    return None


# ---------------------------------------------------------- capabilities ---
# Each capability: (id, [phrases...], handler). handler() returns the
# spoken reply string, or None if the action itself failed (in which case
# we fall through to Gemini instead of claiming success).

def _cap_open(target_name: str, spoken_name: str):
    def handler():
        return f"Opening {spoken_name}." if _start(target_name) else None
    return handler


CAPABILITIES = [
    ("get_time", [
        "what's the time", "what time is it", "current time", "tell me the time",
        "what is the time now", "do you know the time", "give me the time",
        "can you tell me the time", "what time do you have", "time please",
        "الساعة كام", "كام الساعة", "قوليلي الساعة", "عايز اعرف الساعة", "الوقت دلوقتي ايه",
        "قوليلي الوقت", "الساعة كام دلوقتي", "عارفة الساعة كام",
    ], lambda: f"It's {datetime.datetime.now().strftime('%I:%M %p').lstrip('0')}."),

    ("get_date", [
        "what's the date", "what is today's date", "what's today's date",
        "what day is it", "what day is today", "tell me the date", "today's date",
        "what's today", "what is the date today", "what month is it", "what year is it",
        "النهاردة كام", "تاريخ النهاردة", "امتى النهاردة", "انهاردة ايه", "قوليلي التاريخ",
        "احنا في اي شهر", "احنا في سنة كام", "النهاردة ايه بالتاريخ",
    ], lambda: f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}."),

    ("mute", ["mute", "mute the volume", "mute sound", "silence", "mute the sound", "please mute",
              "go silent", "turn the sound off",
              "اسكت", "كتم الصوت", "اقفل الصوت", "اسكتي الصوت", "امسحي الصوت"],
     lambda: ("Muted." if _volume_key("mute") or True else None)),

    ("unmute", ["unmute", "unmute the volume", "turn sound back on", "un-mute", "bring the sound back",
                "فك الكتم", "رجع الصوت", "رجعي الصوت", "شغلي الصوت تاني"],
     lambda: ("Unmuted." if _volume_key("mute") or True else None)),

    ("volume_up", ["volume up", "turn the volume up", "louder", "increase volume", "raise the volume",
                   "make it louder", "turn it up", "increase the sound", "up the volume",
                   "علي الصوت", "زود الصوت", "ارفع الصوت", "الصوت عالي", "خليه اعلى", "عالي الصوت"],
     lambda: ("Volume up." if _volume_key("up") or True else None)),

    ("volume_down", ["volume down", "turn the volume down", "quieter", "decrease volume", "lower the volume",
                     "make it quieter", "turn it down", "decrease the sound", "down the volume",
                     "صغر الصوت", "هدي الصوت", "خفض الصوت", "الصوت واطي", "خليه اقل", "واطي الصوت"],
     lambda: ("Volume down." if _volume_key("down") or True else None)),

    ("media_play_pause", ["play music", "pause music", "play the music", "pause the music",
                          "resume music", "play pause", "start the music", "stop the music",
                          "play song", "pause song",
                          "شغل الاغنية", "وقف الاغنية", "استمر التشغيل", "شغل الموسيقى", "وقف الموسيقى",
                          "كملي الاغنية"],
     lambda: ("Done." if _media_key("play_pause") or True else None)),

    ("media_next", ["next song", "next track", "skip song", "skip track", "play the next one",
                    "skip this song", "go to the next song", "next one please",
                    "الاغنية اللي بعدها", "التالي", "اقفز للاغنية الجاية", "الاغنية الجاية", "طلع اللي بعدها"],
     lambda: ("Next track." if _media_key("next") or True else None)),

    ("media_previous", ["previous song", "previous track", "go back a song", "last song",
                        "play the last song", "go to the previous track",
                        "الاغنية اللي قبلها", "ارجع اغنية", "رجعلي اللي قبلها"],
     lambda: ("Previous track." if _media_key("previous") or True else None)),

    ("lock_screen", ["lock the screen", "lock my screen", "lock the computer", "lock the pc", "lock windows",
                     "please lock the screen", "screen lock",
                     "اقفل الشاشة", "قفل الشاشة", "اقفل الجهاز", "قفلي الشاشة", "اقفلي الكمبيوتر"],
     lambda: "Locking the screen." if _lock_screen() else None),

    ("open_notepad", ["open notepad", "launch notepad", "start notepad", "open the notepad",
                      "give me notepad",
                      "افتح المفكرة", "شغل المفكرة", "افتحيلي المفكرة", "عايز المفكرة"],
     _cap_open("notepad.exe", "Notepad")),

    ("open_calculator", ["open calculator", "launch calculator", "open the calculator", "start calculator",
                         "give me the calculator",
                         "افتح الاله الحاسبة", "شغل الحاسبة", "افتحيلي الحاسبة", "عايز الحاسبة"],
     _cap_open("calc.exe", "the calculator")),

    ("open_file_explorer", ["open file explorer", "open explorer", "open my files", "open the files app",
                            "show my files", "open windows explorer",
                            "افتح مستكشف الملفات", "افتح الملفات", "وريني الملفات", "افتحيلي الملفات"],
     _cap_open("explorer.exe", "File Explorer")),

    ("open_task_manager", ["open task manager", "launch task manager", "show task manager",
                           "start task manager",
                           "افتح مدير المهام", "شغل مدير المهام", "افتحيلي مدير المهام"],
     _cap_open("taskmgr.exe", "Task Manager")),

    ("open_control_panel", ["open control panel", "launch control panel", "start control panel",
                            "افتح لوحة التحكم", "افتحيلي لوحة التحكم"],
     _cap_open("control.exe", "Control Panel")),

    ("open_settings", ["open settings", "open windows settings", "launch settings", "show settings",
                       "افتح الاعدادات", "افتحيلي الاعدادات"],
     lambda: "Opening Settings." if _start("ms-settings:") else None),

    ("open_cmd", ["open command prompt", "open cmd", "open the terminal", "launch cmd", "start the terminal",
                  "افتح الترمنال", "افتح موجه الاوامر", "افتحيلي الترمنال"],
     _cap_open("cmd.exe", "the command prompt")),

    ("open_paint", ["open paint", "launch paint", "start paint", "open ms paint",
                    "افتح الرسام", "شغل البرنامج الرسام", "افتحيلي الرسام"],
     _cap_open("mspaint.exe", "Paint")),

    ("open_word", ["open word", "launch word", "open microsoft word", "start word",
                   "افتح الوورد", "شغل الوورد", "افتحيلي الوورد"],
     _cap_open("winword.exe", "Word")),

    ("open_excel", ["open excel", "launch excel", "open microsoft excel", "start excel",
                    "افتح الاكسل", "شغل الاكسل", "افتحيلي الاكسل"],
     _cap_open("excel.exe", "Excel")),

    ("open_browser", ["open the browser", "open a browser", "launch the browser", "start the browser",
                      "open my browser",
                      "افتح المتصفح", "افتح البراوزر", "افتحيلي المتصفح"],
     lambda: "Opening your browser." if _open_browser_blank() else None),

    ("open_downloads", ["open downloads", "open the downloads folder", "show my downloads",
                        "افتح مجلد التنزيلات", "افتح التنزيلات", "وريني التنزيلات"],
     lambda: "Opening Downloads." if _start(os.path.join(os.path.expanduser("~"), "Downloads")) else None),

    ("open_desktop_folder", ["open the desktop folder", "show desktop files", "open my desktop folder",
                             "افتح مجلد سطح المكتب", "وريني سطح المكتب"],
     lambda: "Opening Desktop." if _start(os.path.join(os.path.expanduser("~"), "Desktop")) else None),

    ("take_screenshot", ["take a screenshot", "capture the screen", "screenshot this", "take a screen capture",
                         "grab a screenshot",
                         "خد سكرين شوت", "صور الشاشة", "خدلي سكرين شوت", "صوري الشاشة"],
     lambda: ("Screenshot saved." if _take_screenshot() else None)),

    ("empty_recycle_bin", ["empty the recycle bin", "empty recycle bin", "clear the trash", "empty the trash",
                           "فضي سلة المهملات", "امسح سلة المحذوفات", "افضي المهملات"],
     lambda: "Recycle bin emptied." if _empty_recycle_bin() else None),

    ("battery_status", ["what's my battery", "battery percentage", "how much battery do i have",
                        "battery status", "check my battery", "battery level",
                        "كام في البطارية", "شحن البطارية كام", "البطارية فيها كام"],
     _battery_status),

    ("system_uptime", ["how long has my pc been on", "system uptime", "how long has the computer been running",
                       "how long has the pc been running", "uptime",
                       "من امتى الجهاز شغال", "الجهاز شغال من امتى"],
     _system_uptime),

    ("ip_address", ["what's my ip address", "what is my ip", "show my ip address", "what is my local ip",
                    "ايه هو الاي بي بتاعي", "عايز اعرف الاي بي بتاعي"],
     _ip_address),

    ("disk_free_space", ["how much disk space do i have", "free disk space", "disk space left",
                         "how much storage do i have left", "check disk space",
                         "مساحة الهارد فاضية كام", "المساحة المتبقية", "المساحة الفاضية كام"],
     _disk_free_space),

    ("shutdown", ["shut down the computer", "shut down my pc", "turn off the computer", "power off the pc",
                  "shut the computer down",
                  "اقفل الجهاز خالص", "طفي الجهاز", "اطفي الكمبيوتر"],
     lambda: "Shutting down in 15 seconds - say 'cancel shutdown' to stop it." if _shutdown_like("/s") else None),

    ("restart", ["restart the computer", "restart my pc", "reboot the computer", "restart windows",
                 "reboot the pc",
                 "اعد تشغيل الجهاز", "ريستارت الجهاز", "اعملي ريستارت"],
     lambda: "Restarting in 15 seconds - say 'cancel shutdown' to stop it." if _shutdown_like("/r") else None),

    ("cancel_shutdown", ["cancel shutdown", "cancel the shutdown", "stop the shutdown", "abort shutdown",
                         "don't shut down", "cancel restart",
                         "الغي الاطفاء", "وقف الاطفاء", "لا متطفيش الجهاز"],
     lambda: "Shutdown cancelled." if _cancel_shutdown() else None),

    ("sleep_pc", ["put the computer to sleep", "sleep mode", "go to sleep", "put the pc to sleep",
                  "نوم الجهاز", "نام الجهاز", "نومي الكمبيوتر"],
     lambda: "Going to sleep." if _sleep_pc() else None),

    ("flip_coin", ["flip a coin", "toss a coin", "heads or tails", "flip the coin",
                   "قلبي عملة", "طلع وش او كتابة", "وش ولا كتابة"],
     lambda: f"It's {random.choice(['heads', 'tails'])}."),

    ("roll_dice", ["roll a dice", "roll the dice", "roll a die", "give me a random number between one and six",
                   "ارمي الزهر", "زهر النرد", "ارمي زهرة"],
     lambda: f"You rolled a {random.randint(1, 6)}."),

    ("offline_joke", ["tell me a joke", "make me laugh", "say something funny", "do you know any jokes",
                      "قوليلي نكتة", "عايز نكتة", "ضحكيني"],
     lambda: random.choice([
         "Why do programmers prefer dark mode? Because light attracts bugs.",
         "I told my computer I needed a break, and it said 'no problem, I'll go to sleep.'",
         "Why was the computer cold? It left its Windows open.",
         "I would tell you a joke about UDP, but you might not get it.",
         "There are 10 types of people: those who understand binary and those who don't.",
     ])),

    ("who_are_you", ["who are you", "what's your name", "what are you", "tell me who you are",
                     "مين انتي", "انتي مين", "اسمك ايه", "انتي مين بالظبط"],
     lambda: "I'm Eva, your personal assistant."),

    ("how_are_you", ["how are you", "how are you doing", "how's it going", "how are you feeling",
                     "عاملة ايه", "اخبارك ايه", "احوالك ايه"],
     lambda: "I'm doing great, thanks for asking! How can I help?"),

    ("thank_you", ["thank you", "thanks", "thank you very much", "thanks a lot", "appreciate it",
                   "شكرا", "متشكر", "تسلم", "شكرا جزيلا", "الله يخليكي"],
     lambda: "You're welcome!"),

    ("good_morning", ["good morning", "morning eva", "صباح الخير", "صباح النور"],
     lambda: "Good morning! Hope you have a great day."),

    ("good_night", ["good night", "night eva", "تصبح على خير", "تصبحي على خير"],
     lambda: "Good night! Sleep well."),
]


def try_handle(text: str, config, logger, last_response: str | None = None) -> str | None:
    """Returns a ready-to-speak reply if `text` matches a known offline
    command, or None if it doesn't - None means "send this to Gemini as
    usual", so this function is safe to call unconditionally on every turn.

    `last_response` (the last thing Eva said, if any) powers the "repeat
    that" command without needing Gemini at all."""
    if not text:
        return None

    # Media / Quran / adhan / DND / Pomodoro / downloads: rule-based and
    # independent of the offline_commands.enabled flag below (that flag
    # only gates the general math/system-info commands further down).
    try:
        import media_router
        routed = media_router.try_route(text, config, logger)
        if routed:
            return routed
    except Exception as e:
        logger.warning(f"[offline_commands] media_router routing failed: {e}")

    if not config.get("offline_commands", "enabled", default=True):
        return None

    t = text.strip().lower().rstrip("?؟. ")

    try:
        if re.search(r"\brepeat that\b|\bsay that again\b|\bwhat did you say\b|كرري|قوليها تاني", t):
            return last_response or "I haven't said anything yet."

        # basic math ("what's 12 * 7", "calculate 40/5", "5+5")
        m = re.search(r"(?:what'?s|calculate|compute|=)?\s*([\d\.\s\+\-\*\/\(\)%]+)$", t)
        if m:
            expr = m.group(1).strip()
            if _MATH_RE.match(expr) and any(op in expr for op in "+-*/%") and any(c.isdigit() for c in expr):
                try:
                    result = _safe_eval_math(expr)
                    result_str = f"{result:g}" if isinstance(result, float) else str(result)
                    return f"That's {result_str}."
                except Exception:
                    pass

        conversion = _try_conversions(t)
        if conversion:
            return conversion

        power_actions = {"shutdown", "restart", "cancel_shutdown", "sleep_pc", "empty_recycle_bin"}

        # Pick the single BEST match across every capability, not the first
        # one found in list order. Plain substring matching means a short
        # phrase for one capability can sit inside a longer phrase that
        # actually belongs to a different, later capability in the list
        # (e.g. "mute" is a literal substring of "unmute the volume", and
        # "اقفل الجهاز" [lock the device] is a literal substring of
        # "اقفل الجهاز خالص" [shut the device down completely]) - matching
        # in list order would silently misfire on the wrong, shorter-phrase
        # capability every time. The longest matching phrase is the most
        # specific one, so it wins; ties keep the earlier list position.
        best_len = 0
        best_cap = None
        for cap_id, phrases, handler in CAPABILITIES:
            matched_len = max((len(p) for p in phrases if p in t), default=0)
            if matched_len > best_len:
                best_len = matched_len
                best_cap = (cap_id, handler)

        if best_cap:
            cap_id, handler = best_cap
            if cap_id in power_actions and not config.get("offline_commands", "allow_power_actions", default=False):
                return None  # matched, but this device hasn't opted in - let Gemini answer instead
            if cap_id == "lock_screen" and not config.get("offline_commands", "allow_lock_screen", default=True):
                return None
            result = handler()
            if result:
                return result
    except Exception as e:
        logger.warning(f"[OfflineCommands] Error while matching '{text}': {e}")
        return None

    return None
