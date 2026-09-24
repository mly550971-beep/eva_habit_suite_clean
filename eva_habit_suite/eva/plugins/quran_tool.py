"""
plugins/quran_tool.py
----------------------
Called from media_router.py's _handle_quran (not a normal declared tool -
Quran requests are matched by keyword before the model ever sees them,
same rule-based-first approach as the rest of media_router.py).

Deliberately does NOT depend on any specific Quran audio CDN's URL
scheme (those change, and guessing a wrong reciter/server id would
silently play the wrong thing with no error). Instead:
  - "play" mode searches YouTube for "<surah> <reciter>" and opens the
    first real result directly, via web_helpers.play_on_youtube - the
    exact same mechanism media_router already uses for every other
    "play X" request, so it's no more fragile than that.
  - "read" mode opens the matching chapter on quran.com (a stable,
    well-known URL: quran.com/<chapter number>, or quran.com/2/255 for
    Ayat al-Kursi specifically) - Arabic text plus translations, no
    audio CDN involved at all.
"""

from __future__ import annotations

from web_helpers import normalize_ar, play_on_youtube

# ---------------------------------------------------------------- data ---

SURAHS = {
    1: "الفاتحة", 2: "البقرة", 3: "آل عمران", 4: "النساء", 5: "المائدة",
    6: "الأنعام", 7: "الأعراف", 8: "الأنفال", 9: "التوبة", 10: "يونس",
    11: "هود", 12: "يوسف", 13: "الرعد", 14: "إبراهيم", 15: "الحجر",
    16: "النحل", 17: "الإسراء", 18: "الكهف", 19: "مريم", 20: "طه",
    21: "الأنبياء", 22: "الحج", 23: "المؤمنون", 24: "النور", 25: "الفرقان",
    26: "الشعراء", 27: "النمل", 28: "القصص", 29: "العنكبوت", 30: "الروم",
    31: "لقمان", 32: "السجدة", 33: "الأحزاب", 34: "سبأ", 35: "فاطر",
    36: "يس", 37: "الصافات", 38: "ص", 39: "الزمر", 40: "غافر",
    41: "فصلت", 42: "الشورى", 43: "الزخرف", 44: "الدخان", 45: "الجاثية",
    46: "الأحقاف", 47: "محمد", 48: "الفتح", 49: "الحجرات", 50: "ق",
    51: "الذاريات", 52: "الطور", 53: "النجم", 54: "القمر", 55: "الرحمن",
    56: "الواقعة", 57: "الحديد", 58: "المجادلة", 59: "الحشر", 60: "الممتحنة",
    61: "الصف", 62: "الجمعة", 63: "المنافقون", 64: "التغابن", 65: "الطلاق",
    66: "التحريم", 67: "الملك", 68: "القلم", 69: "الحاقة", 70: "المعارج",
    71: "نوح", 72: "الجن", 73: "المزمل", 74: "المدثر", 75: "القيامة",
    76: "الإنسان", 77: "المرسلات", 78: "النبأ", 79: "النازعات", 80: "عبس",
    81: "التكوير", 82: "الإنفطار", 83: "المطففين", 84: "الإنشقاق", 85: "البروج",
    86: "الطارق", 87: "الأعلى", 88: "الغاشية", 89: "الفجر", 90: "البلد",
    91: "الشمس", 92: "الليل", 93: "الضحى", 94: "الشرح", 95: "التين",
    96: "العلق", 97: "القدر", 98: "البينة", 99: "الزلزلة", 100: "العاديات",
    101: "القارعة", 102: "التكاثر", 103: "العصر", 104: "الهمزة", 105: "الفيل",
    106: "قريش", 107: "الماعون", 108: "الكوثر", 109: "الكافرون", 110: "النصر",
    111: "المسد", 112: "الإخلاص", 113: "الفلق", 114: "الناس",
}

# A handful of well-known reciters, most requested first (index 0 = default).
# Each entry: (canonical Arabic name, [alias words to match in speech]).
RECITERS = [
    ("مشاري راشد العفاسي", ["العفاسي", "مشاري", "الفعاسي"]),
    ("عبدالباسط عبدالصمد", ["عبدالباسط", "عبد الباسط", "عبدالصمد"]),
    ("عبدالرحمن السديس", ["السديس", "سديس"]),
    ("سعد الغامدي", ["الغامدي"]),
    ("ماهر المعيقلي", ["المعيقلي", "ماهر المعيقلي"]),
    ("ياسر الدوسري", ["الدوسري"]),
    ("محمود خليل الحصري", ["الحصري"]),
    ("محمد صديق المنشاوي", ["المنشاوي"]),
    ("أبو بكر الشاطري", ["الشاطري"]),
]

_READ_WORDS = ("اقرا", "اقرأ", "قراءه", "قراءة", "read", "نص", "المصحف")
_KURSI_WORDS = ("كرسي",)
_MUAWWIDHAT_WORDS = ("معوذتين", "معوذات", "المعوذتين", "المعوذات")

_SURAH_LOOKUP = {}
for _num, _name in SURAHS.items():
    key = normalize_ar(_name)
    _SURAH_LOOKUP[key] = _num
    if key.startswith("ال"):
        _SURAH_LOOKUP[key[2:]] = _num  # also match without the "ال" prefix


def parse_request(n: str) -> dict:
    """n is already normalize_ar()'d text (see media_router.try_route)."""
    read = any(w in n for w in _READ_WORDS)
    kursi = any(w in n for w in _KURSI_WORDS)
    muawwidhat = any(w in n for w in _MUAWWIDHAT_WORDS)

    reciter_idx = 0
    for idx, (_name, aliases) in enumerate(RECITERS):
        if any(normalize_ar(a) in n for a in aliases):
            reciter_idx = idx
            break

    surah = None
    if not kursi and not muawwidhat:
        # Word-boundary match, not a raw substring: a couple of surahs
        # are named with a single letter (ص = 38, ق = 50), and a plain
        # "key in n" would then false-positive on any unrelated word that
        # happens to contain that letter (e.g. "رقم" contains ق). Padding
        # both sides with spaces requires the key to appear as a whole
        # word/phrase, not buried inside a longer one.
        padded_n = f" {n} "
        for key in sorted(_SURAH_LOOKUP, key=len, reverse=True):
            if key and f" {key} " in padded_n:
                surah = _SURAH_LOOKUP[key]
                break

    return {"surah": surah, "reciter": reciter_idx, "read": read,
            "kursi": kursi, "muawwidhat": muawwidhat}


def play_quran(surah, reciter_idx, read, kursi, muawwidhat, open_fn) -> dict:
    reciter_idx = reciter_idx if 0 <= reciter_idx < len(RECITERS) else 0
    reciter_name = RECITERS[reciter_idx][0]

    if kursi:
        surah_name = "آية الكرسي"
        read_url = "https://quran.com/2/255"
        audio_query = f"آية الكرسي {reciter_name}"
    elif muawwidhat:
        surah_name = "المعوذات الثلاث"
        read_url = "https://quran.com/112"  # first of the three; the rest follow on quran.com
        audio_query = f"المعوذات الثلاث كاملة {reciter_name}"
    else:
        surah_num = surah or 1  # default: Al-Fatiha
        surah_name = SURAHS.get(surah_num, SURAHS[1])
        read_url = f"https://quran.com/{surah_num}"
        audio_query = f"سورة {surah_name} {reciter_name}"

    if read:
        open_fn(read_url)
        return {"surah_name": surah_name, "reciter_name": reciter_name, "via": "read"}

    play_on_youtube(audio_query, open_fn=open_fn)
    return {"surah_name": surah_name, "reciter_name": reciter_name, "via": "play"}
