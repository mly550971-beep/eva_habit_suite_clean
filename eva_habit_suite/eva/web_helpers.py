"""
web_helpers.py
--------------
Small, dependency-free helpers shared by media_router.py and
plugins/quran_tool.py: search-URL builders, Arabic text normalization,
a known-site lookup, and a best-effort "find and open the first real
YouTube result directly" helper. Pure stdlib (urllib + re) - no API
keys, no extra packages, so nothing here can be the reason Eva fails to
start.

Note on play_on_youtube(): scraping a search results page is inherently
a little fragile (YouTube can change its page structure at any time).
On any failure - no internet, a changed page, a slow connection - this
NEVER raises; it just opens the search-results page instead of a
specific video (direct=False), which is exactly what happened here
before this helper existed.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request

# ------------------------------------------------------------- arabic ---

_AR_RANGE = re.compile(r"[\u0600-\u06FF]")
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
_TATWEEL = "\u0640"

# Folds common letter variants so the same word typed/spoken differently
# still matches: أ/إ/آ/ٱ -> ا, ى/ئ -> ي, ة -> ه, ؤ -> و.
_NORMALIZE_MAP = {
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ة": "ه",
    "ؤ": "و",
}


def has_arabic(text: str) -> bool:
    return bool(_AR_RANGE.search(text or ""))


def normalize_ar(text: str) -> str:
    """Lowercases Latin text; for Arabic, strips diacritics/tatweel and
    folds common letter variants. Collapses whitespace either way."""
    if not text:
        return ""
    t = text.strip().lower()
    t = _DIACRITICS.sub("", t)
    t = t.replace(_TATWEEL, "")
    for src, dst in _NORMALIZE_MAP.items():
        t = t.replace(src, dst)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# --------------------------------------------------------- search urls ---

def google_search_url(query: str) -> str:
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)


def youtube_search_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)


# ------------------------------------------------------------- sites ---

# name/nickname (Arabic or English) -> (display_name, base_url)
_SITES = {
    "facebook": ("Facebook", "https://www.facebook.com"),
    "فيسبوك": ("Facebook", "https://www.facebook.com"),
    "فيس": ("Facebook", "https://www.facebook.com"),
    "instagram": ("Instagram", "https://www.instagram.com"),
    "انستجرام": ("Instagram", "https://www.instagram.com"),
    "انستا": ("Instagram", "https://www.instagram.com"),
    "twitter": ("X", "https://x.com"),
    "x": ("X", "https://x.com"),
    "تويتر": ("X", "https://x.com"),
    "youtube": ("YouTube", "https://www.youtube.com"),
    "يوتيوب": ("YouTube", "https://www.youtube.com"),
    "amazon": ("Amazon", "https://www.amazon.com"),
    "امازون": ("Amazon", "https://www.amazon.com"),
    "gmail": ("Gmail", "https://mail.google.com"),
    "جيميل": ("Gmail", "https://mail.google.com"),
    "google": ("Google", "https://www.google.com"),
    "جوجل": ("Google", "https://www.google.com"),
    "whatsapp": ("WhatsApp", "https://web.whatsapp.com"),
    "واتساب": ("WhatsApp", "https://web.whatsapp.com"),
    "واتس": ("WhatsApp", "https://web.whatsapp.com"),
    "linkedin": ("LinkedIn", "https://www.linkedin.com"),
    "لينكدان": ("LinkedIn", "https://www.linkedin.com"),
    "wikipedia": ("Wikipedia", "https://www.wikipedia.org"),
    "ويكيبيديا": ("Wikipedia", "https://www.wikipedia.org"),
    "netflix": ("Netflix", "https://www.netflix.com"),
    "نتفلكس": ("Netflix", "https://www.netflix.com"),
    "tiktok": ("TikTok", "https://www.tiktok.com"),
    "تيك توك": ("TikTok", "https://www.tiktok.com"),
    "تيكتوك": ("TikTok", "https://www.tiktok.com"),
}

_SITE_SEARCH_PATTERNS = {
    "Amazon": "https://www.amazon.com/s?k={q}",
    "YouTube": "https://www.youtube.com/results?search_query={q}",
    "Wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "Facebook": "https://www.facebook.com/search/top?q={q}",
    "X": "https://x.com/search?q={q}",
    "Instagram": "https://www.instagram.com/explore/search/keyword/?q={q}",
    "TikTok": "https://www.tiktok.com/search?q={q}",
    "Netflix": "https://www.netflix.com/search?q={q}",
}


def resolve_site(name: str):
    """Returns (display_name, base_url) for a known site name/nickname
    (Arabic or English), or None if not recognised."""
    key = normalize_ar(name)
    if key in _SITES:
        return _SITES[key]
    # Word-boundary match for a site name mentioned as one word within a
    # longer phrase, not a raw substring: some nicknames are very short
    # (e.g. "x" for Twitter/X), and a plain "k in key" would then
    # false-positive on any word merely containing that letter/substring
    # (e.g. "box", "excel", "next" all contain "x"). Padding both sides
    # with spaces requires a whole word to match, not a fragment of one.
    padded_key = f" {key} "
    for k, v in _SITES.items():
        if f" {k} " in padded_key:
            return v
    return None


def site_search_url(site, query: str) -> str:
    """site is the (display_name, base_url) tuple resolve_site() returns."""
    display_name = site[0]
    pattern = _SITE_SEARCH_PATTERNS.get(display_name)
    q = urllib.parse.quote_plus(query)
    if pattern:
        return pattern.format(q=q)
    domain = site[1].split("//", 1)[-1]
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(f"site:{domain} {query}")


# ----------------------------------------------------------- youtube ---

_VIDEO_ID_RE = re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"')
_TITLE_RE = re.compile(r'"title":\{"runs":\[\{"text":"(.*?)"\}')


def play_on_youtube(query: str, open_fn=None) -> dict:
    """Best-effort: looks for the first real video on the YouTube search
    results page and opens/returns it directly (direct=True). On any
    failure at all, opens/returns the plain search results page instead
    (direct=False) - never raises."""
    search_url = youtube_search_url(query)
    video_id = None
    title = None
    try:
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        m = _VIDEO_ID_RE.search(html)
        if m:
            video_id = m.group(1)
            tm = _TITLE_RE.search(html[m.end():m.end() + 500])
            if tm:
                title = tm.group(1).encode().decode("unicode_escape", errors="ignore")
    except Exception:
        video_id = None

    if video_id:
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        if open_fn:
            open_fn(watch_url)
        return {"direct": True, "url": watch_url, "title": title}

    if open_fn:
        open_fn(search_url)
    return {"direct": False, "url": search_url, "title": None}
