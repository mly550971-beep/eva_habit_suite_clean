"""
media_router.py
---------------
Handles the everyday "do it in the browser" commands directly, WITHOUT
asking the local model to pick a tool first:

    شغل <أي فيديو/أغنية>         -> plays the top YouTube result
    شغل قرآن / سورة الكهف / ...  -> plays the recitation (plugins/quran_tool.py)
    ابحث عن X [على <موقع>]       -> opens a real search in the browser
    افتح <موقع>                  -> opens the site (facebook, amazon, ...)
    وقف / كمل الفيديو            -> media play/pause key

Why this exists: Eva runs a small local model (gemma4:e2b) with ~30 tools
declared. Small models often answer in text instead of calling a tool, or
pick the wrong one (tool_stats.json shows play_music was used once and
search_video / search_information never). For plain commands like these a
rule-based path is instant, works even when Ollama is slow, and can't
"forget" to act. Anything that doesn't clearly match returns None and goes
to the model exactly as before.

Called from offline_commands.try_handle(), which ui.py already runs on
every typed and spoken request.
"""

from __future__ import annotations

import re
import sys
import threading
import webbrowser

from web_helpers import (
    google_search_url,
    has_arabic,
    normalize_ar,
    play_on_youtube,
    resolve_site,
    site_search_url,
    youtube_search_url,
)

# ---------------------------------------------------------------- vocab ---

# Leading fillers (already normalised) that can precede the real command.
_FILLERS = [
    "يا ايفا", "ايفا", "ايفه", "ايفي", "hey eva", "eva", "لو سمحت", "من فضلك", "ممكن", "تقدر",
    "تقدري", "هتقدر", "please", "can you", "could you", "ياعم", "يا عم", "يا باشا", "بقي",
]

_PLAY_VERBS = sorted([
    "شغلي لي", "شغل لي", "شغللي", "شغلي", "شغل", "شغلولي", "شغلنا", "شغلي لنا",
    "play", "watch", "put on",
    "سمعني", "سمعيني", "سمعنا", "اسمع", "عايز اسمع", "عاوز اسمع", "عايزه اسمع", "عاوزه اسمع",
    "نفسي اسمع", "اتفرج علي", "اتفرج ع",
], key=len, reverse=True)

# "show me / I want to see X" is also used for the weather, files, the
# screen... so these only count as "play a video" when the thing asked for
# is clearly media.
_SOFT_PLAY_VERBS = sorted([
    "عايز اشوف", "عاوز اشوف", "عايزه اشوف", "عاوزه اشوف", "نفسي اشوف", "وريني", "فرجني علي",
    "فرجني", "show me",
], key=len, reverse=True)
_MEDIA_NOUNS = ("فيديو", "مقطع", "كليب", "فيلم", "مسلسل", "حلقه", "اغنيه", "اغاني", "مباراه",
                "ماتش", "فيديوهات", "video", "clip", "movie", "episode", "song")

_SEARCH_VERBS = sorted([
    "ابحث لي عن", "ابحثلي عن", "ابحث عن", "ابحث", "ابحثي عن", "ابحثي",
    "دور لي علي", "دورلي علي", "دور علي", "دور لي عن", "دور عن", "دوري علي", "دوري عن",
    "سيرش عن", "سيرش علي", "سيرش", "بحث عن", "search for", "search", "look up",
], key=len, reverse=True)

_OPEN_VERBS = sorted([
    "افتح لي", "افتحلي", "افتحي", "افتح", "روح علي", "روح ع", "خدني علي", "open", "go to",
    "launch",
], key=len, reverse=True)

_QURAN_WORDS = ("قران", "قرءان", "سوره", "quran", "koran", "surah", "ايه الكرسي", "اية الكرسي",
                "ayat al kursi", "ayatul kursi", "ayat al-kursi", "المعوذتين", "مصحف")

_QURAN_VERBS = ("شغل", "سمع", "اسمع", "اقرا", "افتح", "وريني", "بصوت", "play", "listen",
                "open", "تلاوه")

# "play <these>" is NOT a request to find a video: it's the offline
# capabilities (resume music, open apps, hardware) - leave those to
# offline_commands / the model.
_NOT_MEDIA_QUERY = {
    "الموسيقي", "موسيقي", "الاغنيه", "اغنيه", "الاغاني", "اغاني", "الفيديو", "فيديو", "الصوت",
    "الحاسبه", "المفكره", "الوورد", "الاكسل", "الرسام", "المتصفح", "البراوزر", "الكاميره", "الكاميرا",
    "الميكروفون", "البلوتوث", "الوايفاي", "الواي فاي", "الجهاز", "الكمبيوتر", "اللاب",
    "الشاشه", "التلفزيون", "التليفزيون", "الراديو", "music", "song", "the music", "the song",
    "video", "the video", "sound", "it", "that", "this", "الاغنيه دي", "الفيديو ده", "ده", "دي",
}
_NOT_MEDIA_QUERY = {normalize_ar(w) for w in _NOT_MEDIA_QUERY}
_NOT_MEDIA_PREFIX = ("برنامج", "تطبيق", "app ", "application ", "program ", "ملف", "اللعبه", "لعبه")

_TAIL_SITE = re.compile(
    r"\s+(?:علي|في|من|ع|on|in|from|at)\s+(?:ال)?(?:يوتيوب|يوتوب|youtube)\s*$"
)
_LEAD_LI = re.compile(r"^(?:لي|ليا|لينا|لنا|بقي|كده|ده)\s+")

_STOP_RE = re.compile(
    r"^(?:وقف|اوقف|وقفي|pause|stop)\s+(?:ال)?(?:فيديو|قران|سوره|تلاوه|اغنيه|موسيقي|تشغيل|video|quran|song|music)$"
)
_RESUME_RE = re.compile(
    r"^(?:كمل|كملي|resume|continue)\s+(?:ال)?(?:فيديو|قران|سوره|تلاوه|اغنيه|موسيقي|تشغيل|video|quran|song|music)$"
)

_DOMAIN_RE = re.compile(r"^(?:https?://)?([\w-]+(?:\.[\w-]+)*\.(?:com|net|org|eg|io|tv|me|gov|edu|co|info|app|dev))(?:/\S*)?$")


# -------------------------------------------------------------- helpers ---

def _perm(config, key: str, default: bool = True) -> bool:
    try:
        return bool(config.get("permissions", key, "enabled", default=default))
    except Exception:
        return default


def _blocked(config, text: str) -> bool:
    try:
        pats = config.get("permission_matrix", "blocked_patterns", default=[]) or []
    except Exception:
        pats = []
    low = text.lower()
    return any(str(p).lower() in low for p in pats)


def _strip_fillers(n: str) -> str:
    changed = True
    while changed:
        changed = False
        for f in _FILLERS:
            if n == f:
                return ""
            if n.startswith(f + " "):
                n = n[len(f) + 1:].strip()
                changed = True
    return n


def _after_verb(n: str, verbs) -> "str | None":
    """Text after the first matching leading verb phrase, or None."""
    for v in verbs:
        if n == v:
            return ""
        if n.startswith(v + " "):
            return n[len(v) + 1:].strip()
    return None


def _reply(ar: bool, arabic: str, english: str) -> str:
    return arabic if ar else english


_ctx = threading.local()


def _restore(q_norm: str) -> str:
    """Matching is done on normalised text (ة->ه, ى->ي, no tashkeel...), but
    the text we SEARCH for / speak back should keep the user's own spelling.
    Normalisation never adds or merges words, so the query's words sit at
    the same positions in the original text - slice them from there."""
    try:
        norm, orig = _ctx.norm, _ctx.orig
        q = q_norm.split()
        if q and len(norm) == len(orig):
            for i in range(len(norm) - len(q) + 1):
                if norm[i:i + len(q)] == q:
                    return " ".join(orig[i:i + len(q)])
    except Exception:
        pass
    return q_norm


def _media_key(action: str) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        vk = {"play_pause": 0xB3}[action]
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return True
    except Exception:
        return False


# --------------------------------------------------------------- intents ---

def _handle_quran(n: str, ar: bool, config, logger):
    if not any(w in n for w in _QURAN_WORDS):
        return None
    if not any(v in n for v in _QURAN_VERBS):
        return None
    if not _perm(config, "quran", True):
        return None
    from plugins import quran_tool

    p = quran_tool.parse_request(n)
    result = quran_tool.play_quran(
        surah=p["surah"], reciter_idx=p["reciter"], read=p["read"],
        kursi=p["kursi"], muawwidhat=p["muawwidhat"], open_fn=webbrowser.open,
    )
    logger.info(f"[MediaRouter] quran -> {result['surah_name']} / {result['reciter_name']} via {result['via']}")
    if result["via"] == "read":
        return _reply(ar, f"فتحتلك {result['surah_name']} للقراءة.", f"Opened {result['surah_name']} to read.")
    return _reply(
        ar,
        f"شغلتلك {result['surah_name']} بصوت {result['reciter_name']}.",
        f"Playing {result['surah_name']} by {result['reciter_name']}.",
    )


def _clean_media_query(q: str) -> str:
    q = _LEAD_LI.sub("", q.strip())
    q = _TAIL_SITE.sub("", q).strip()
    return q


def _handle_play(n: str, ar: bool, config, logger):
    # "open youtube and play X" / "افتح يوتيوب وشغل X"
    m = re.match(r"^(?:افتح|افتحلي|open)\s+.{2,20}?\s+(?:و|and\s+)(?:شغل|شغلي|play)\s+(.+)$", n)
    query = m.group(1).strip() if m else _after_verb(n, _PLAY_VERBS)
    if query is None:
        soft = _after_verb(n, _SOFT_PLAY_VERBS)
        if soft and any(w in soft.split()[:2] for w in _MEDIA_NOUNS):
            query = soft
    if query is None:
        return None
    query = _clean_media_query(query)
    if not query or query in _NOT_MEDIA_QUERY or query.startswith(_NOT_MEDIA_PREFIX):
        return None
    if not _perm(config, "play_music", False):
        return None

    query = _restore(query)
    info = play_on_youtube(query, open_fn=webbrowser.open)
    logger.info(f"[MediaRouter] play '{query}' -> {info['url']} (direct={info['direct']})")
    if info["direct"]:
        title = (info["title"] or query)[:80]
        return _reply(ar, f"شغلتلك {title}.", f"Playing {title}.")
    return _reply(
        ar,
        f"فتحتلك نتايج {query} على يوتيوب، اختار اللي عايزه.",
        f"I opened the YouTube results for {query} - pick the one you want.",
    )


def _split_site_from_query(rest: str):
    """'ابحث عن سماعات على امازون' / 'ابحث في يوتيوب عن X' ->
    (site_tuple|None, spoken_site_phrase, query)."""
    rest = rest.strip()
    # leading: "في يوتيوب عن X" / "علي جوجل X"
    m = re.match(r"^(?:(?:في|علي|ع|on|in|at)\s+)?(\S+(?:\s\S+)?)\s+(?:عن|علي|for|about)\s+(.+)$", rest)
    if m:
        site = resolve_site(m.group(1))
        if site:
            return site, m.group(1), m.group(2).strip()
    # trailing: "X علي امازون" (try 2-word then 1-word site names)
    m = re.match(r"^(.+?)\s+(?:في|علي|ع|on|in|at)\s+(\S+\s\S+|\S+)$", rest)
    if m:
        site = resolve_site(m.group(2))
        if site:
            return site, m.group(2), m.group(1).strip()
    rest = re.sub(r"^(?:عن|for|about)\s+", "", rest).strip()
    return None, "", rest


def _handle_search(n: str, ar: bool, config, logger):
    rest = _after_verb(n, _SEARCH_VERBS)
    if rest is None:
        return None
    if not _perm(config, "web_search", False):
        return None
    site, site_phrase, query = _split_site_from_query(rest)
    if not query:
        return None
    query = _restore(query)
    if site:
        url = site_search_url(site, query)
        where = site[0]
        webbrowser.open(url)
        logger.info(f"[MediaRouter] site search '{query}' on {where} -> {url}")
        return _reply(ar, f"بحثتلك عن {query} على {_restore(site_phrase)}.", f"Searched {where} for {query}.")
    url = google_search_url(query)
    webbrowser.open(url)
    logger.info(f"[MediaRouter] google search '{query}'")
    return _reply(ar, f"فتحتلك جوجل وبحثت عن {query}.", f"I searched Google for {query}.")


def _handle_open_site(n: str, ar: bool, config, logger):
    target = _after_verb(n, _OPEN_VERBS)
    if not target:
        return None
    if not (_perm(config, "open_any_url", False) or _perm(config, "open_websites", False)):
        return None
    m = _DOMAIN_RE.match(target.replace(" ", ""))
    if m:
        url = target.replace(" ", "")
        url = url if url.startswith("http") else "https://" + url
        webbrowser.open(url)
        return _reply(ar, f"فتحتلك {m.group(1)}.", f"Opened {m.group(1)}.")
    if any(h in target for h in ("كروم", "chrome", "edge", "ايدج", "فايرفوكس", "firefox", "برنامج", "تطبيق", "app")):
        return None
    site = resolve_site(target)
    # Only handle it when the WHOLE phrase is basically the site name,
    # so "open notepad" / "open my files" never get hijacked.
    if not site:
        return None
    words = target.split()
    if len(words) > 3:
        return None
    webbrowser.open(site[1])
    logger.info(f"[MediaRouter] open site {site[0]} -> {site[1]}")
    return _reply(ar, f"فتحتلك {_restore(target)}.", f"Opened {site[0]}.")


def _handle_pause_resume(n: str, ar: bool, config, logger):
    if _STOP_RE.match(n):
        return _reply(ar, "تمام.", "Done.") if _media_key("play_pause") else None
    if _RESUME_RE.match(n):
        return _reply(ar, "تمام.", "Done.") if _media_key("play_pause") else None
    return None


# ------------------------------------------------- adhan / prayer times ---

_PRAYER_WORDS = {"فجر": "fajr", "ظهر": "dhuhr", "عصر": "asr", "مغرب": "maghrib", "عشاء": "isha"}
_PRAYER_RE = r"(?:ال)?(فجر|ظهر|عصر|مغرب|عشاء)"
_ADHAN_STOP_RE = re.compile(
    r"^(?:وقف|اوقف|وقفي|اقفل|اسكت|اسكتي|كفايه|كفايه كده|بس|خلاص|stop)(?:\s+(?:ال)?(?:اذان|ادان))?$"
)
_ADHAN_STOP_EXPLICIT_RE = re.compile(r"^(?:وقف|اوقف|وقفي|اقفل|اسكت|stop)\s+(?:ال)?(?:اذان|ادان)$")
_ADHAN_PLAY_RE = re.compile(r"^(?:شغل|شغلي|شغللي|play)\s+(?:ال)?(?:اذان|ادان|adhan)(?:\s+" + _PRAYER_RE + r")?$")
_ALL_TIMES_RE = re.compile(r"(?:مواعيد|مواقيت|اوقات|جدول)\s+(?:ال)?(?:صلاه|صلوات|اذان)|prayer times")
_NEXT_RE = re.compile(
    r"(?:(?:ال)?صلاه\s+(?:ال)?(?:جايه|جاي|قادمه|جاييه)|(?:ال)?اذان\s+(?:ال)?(?:جاي|جايه|قادم)|"
    r"(?:امتي|كام)\s+(?:ال)?(?:اذان|صلاه)(?:\s+(?:ال)?(?:جاي|جايه))?$|next prayer)"
)
_ONE_RE = re.compile(
    r"(?:^|\s)" + _PRAYER_RE + r"\s+(?:كام|امتي|الساعه كام)$|"
    r"^(?:امتي|كام)\s+(?:(?:ال)?اذان\s+)?" + _PRAYER_RE + r"$|"
    r"^(?:ال)?اذان\s+" + _PRAYER_RE + r"\s+(?:كام|امتي)$"
)


def _handle_adhan(n: str, ar: bool, config, logger):
    import adhan as adhan_mod
    from datetime import datetime
    from prayer_times import (ARABIC_NAMES, PRAYERS, format_remaining_ar, format_time_ar,
                              get_service)

    player = adhan_mod.get_player()
    # 1) Stop - bare "اسكت/وقف/كفاية" only counts while the adhan is playing,
    #    so it never steals those words from other features.
    if player is not None and player.is_playing and _ADHAN_STOP_RE.match(n):
        player.stop()
        return _reply(ar, "تمام، وقفت الأذان.", "Adhan stopped.")
    if _ADHAN_STOP_EXPLICIT_RE.match(n):
        return _reply(ar, "الأذان مش شغال دلوقتي.", "The adhan isn't playing.")

    # 2) Play now (also a handy way to test your audio setup)
    m = _ADHAN_PLAY_RE.match(n)
    if m:
        key = _PRAYER_WORDS.get(m.group(1) or "", "dhuhr")
        player = adhan_mod.get_player(config, logger)
        import threading
        threading.Thread(target=player.play, args=(key, True), daemon=True).start()
        return _reply(ar, "حاضر، شغلت الأذان.", "Playing the adhan.")

    # 3) Questions about times
    all_times = _ALL_TIMES_RE.search(n)
    nxt = _NEXT_RE.search(n)
    one = _ONE_RE.search(n)
    if not (all_times or nxt or one):
        return None

    svc = get_service(config, logger)
    svc.ensure_today()
    now = datetime.now()
    times, source = svc.get(now.date())
    approx = "" if source == "cache" else _reply(ar, " (تقريبية، من غير نت)", " (approximate, offline)")

    if one and not all_times:
        name = next(g for g in one.groups() if g)
        key = _PRAYER_WORDS[name]
        return _reply(ar, f"أذان {ARABIC_NAMES[key]} الساعة {format_time_ar(times[key])}.{approx}",
                      f"{key.capitalize()} is at {times[key]}.{approx}")
    if nxt and not all_times:
        key, when = svc.next_prayer(now)
        if key:
            return _reply(
                ar,
                f"الصلاة الجاية {ARABIC_NAMES[key]} الساعة {format_time_ar(when.strftime('%H:%M'))}، "
                f"فاضل {format_remaining_ar(when - now)}.{approx}",
                f"Next prayer: {key.capitalize()} at {when.strftime('%H:%M')}.{approx}",
            )
    parts = [f"{ARABIC_NAMES[k]} {format_time_ar(times[k])}" for k in PRAYERS]
    return _reply(ar, "مواعيد الصلاة النهاردة: " + "، ".join(parts) + "." + approx,
                  "Prayer times today: " + ", ".join(f"{k} {times[k]}" for k in PRAYERS) + "." + approx)


# --------------------------------------------- do-not-disturb / focus ---

_DND_ON_RE = re.compile(r"^(?:متزعجنيش|ماتزعجنيش|وضع مش مزعج|وضع عدم الازعاج|do not disturb|dnd)(?:\s+\d+\s*(?:ساعه|ساعات))?$")
_DND_ON_HOURS_RE = re.compile(r"^(?:متزعجنيش|ماتزعجنيش|وضع مش مزعج)\s+(\d+)\s*(?:ساعه|ساعات)$")
_DND_OFF_RE = re.compile(r"^(?:زعجني تاني|الغي وضع مش مزعج|رجع التنبيهات|شغل التنبيهات)$")

_POMO_START_RE = re.compile(
    r"^(?:ابدا|ابدأ|شغل)\s+(?:جلسه\s+)?(?:بومودورو|تركيز|pomodoro)(?:\s+(\d+))?$"
)
_POMO_STOP_RE = re.compile(r"^(?:وقف|الغي|اقفل)\s+(?:جلسه\s+)?(?:بومودورو|التركيز|pomodoro)$")
_POMO_STATUS_RE = re.compile(r"^(?:الجلسه فين|فاضل قد ايه|الجلسه هتخلص امتي|pomodoro status)$")

_ORGANIZE_RE = re.compile(r"^(?:رتب|نظم)\s+(?:ال)?(?:تنزيلات|داونلودز|downloads)$")


def _handle_dnd(n: str, ar: bool, config, logger):
    from dnd import get_dnd

    dnd = get_dnd(config)
    m = _DND_ON_HOURS_RE.match(n)
    if m:
        hours = int(m.group(1))
        dnd.enable(hours=hours)
        return _reply(ar, f"تمام، مش هزعجك لمدة {hours} ساعة.", f"Do-Not-Disturb on for {hours}h.")
    if _DND_ON_RE.match(n):
        dnd.enable()
        return _reply(ar, "تمام، وضع مش مزعج شغال - قول 'زعجني تاني' لما تحب ترجّعه.",
                      "Do-Not-Disturb is on.")
    if _DND_OFF_RE.match(n):
        dnd.disable()
        return _reply(ar, "تمام، رجعت التنبيهات.", "Do-Not-Disturb is off.")
    return None


def _handle_pomodoro(n: str, ar: bool, config, logger):
    import pomodoro

    m = _POMO_START_RE.match(n)
    if m:
        rounds = int(m.group(1)) if m.group(1) else int(config.get("pomodoro", "rounds", default=4))
        focus = int(config.get("pomodoro", "focus_minutes", default=25))
        brk = int(config.get("pomodoro", "break_minutes", default=5))

        def on_phase(phase, round_no, total):
            from notifier import notify
            if phase == "focus":
                notify("Eva", f"جولة تركيز {round_no}/{total} بدأت ({focus} دقيقة).", logger)
            elif phase == "break":
                notify("Eva", f"وقت راحة {brk} دقايق.", logger)
            elif phase == "done":
                notify("Eva", "خلصت كل الجولات - عمل رائع!", logger)

        pomodoro.start_session(focus, brk, rounds, on_phase_change=on_phase)
        return _reply(
            ar,
            f"تمام، بدأت {rounds} جولات تركيز، كل جولة {focus} دقيقة وراحة {brk} دقايق.",
            f"Started {rounds} pomodoro rounds ({focus}m focus / {brk}m break).",
        )
    if _POMO_STOP_RE.match(n):
        stopped = pomodoro.cancel_session()
        return _reply(ar, "تمام، وقفت الجلسة." if stopped else "مفيش جلسة شغالة.",
                      "Session stopped." if stopped else "No session running.")
    if _POMO_STATUS_RE.match(n):
        session = pomodoro.get_session()
        if session is None:
            return _reply(ar, "مفيش جلسة تركيز شغالة دلوقتي.", "No pomodoro session running.")
        return session.status_text()
    return None


def _handle_organize(n: str, ar: bool, config, logger):
    if not _ORGANIZE_RE.match(n):
        return None
    import os
    import threading

    from daily_extras import organize_folder

    folder = config.get("downloads_organizer", "folder", default="") or \
        os.path.join(os.path.expanduser("~"), "Downloads")

    def run():
        counts = organize_folder(folder)
        total = sum(v for k, v in counts.items() if k != "_errors")
        logger.info(f"[MediaRouter] organize_folder({folder}) -> {counts}")

    threading.Thread(target=run, daemon=True).start()
    return _reply(ar, "تمام، بدأت أرتب مجلد التنزيلات.", "Organizing your downloads folder now.")


# ------------------------------------------------------------------ main ---

def try_route(text: str, config, logger):
    """Returns the reply to speak if `text` was a media/search/open-site
    command that was carried out, else None (=> normal flow continues)."""
    if not text:
        return None
    # Speech-to-text / typing often glues punctuation to words ("ايفا،") -
    # turn it into spaces first so the leading verb is still recognised.
    cleaned = re.sub(r"[،,؛;!؟?]+", " ", text).strip(" .")
    n = normalize_ar(cleaned)
    if not n or _blocked(config, n):
        return None
    ar = has_arabic(text)
    _ctx.norm = n.split()
    _ctx.orig = cleaned.split()
    n = _strip_fillers(n)
    if not n:
        return None

    for handler in (_handle_dnd, _handle_pomodoro, _handle_organize, _handle_adhan, _handle_pause_resume, _handle_quran, _handle_play, _handle_search, _handle_open_site):
        try:
            reply = handler(n, ar, config, logger)
        except Exception as exc:  # never let routing break the normal flow
            logger.warning(f"[MediaRouter] {handler.__name__} failed on '{text}': {exc}")
            reply = None
        if reply:
            return reply
    return None
