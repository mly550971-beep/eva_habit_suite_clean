#!/usr/bin/env python3
"""
HABIT TRACKER - Offline Desktop Application
--------------------------------------------
Built with PyQt6 + matplotlib + sqlite3 (100% local, no internet required).

Run with:  python3 main.py
Requires:  pip install PyQt6 matplotlib
"""

import sys
import os
import sqlite3
import calendar
import math
import tempfile
import wave
from functools import partial
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QComboBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea,
    QInputDialog, QMessageBox, QSizePolicy, QLineEdit, QDialog, QStackedLayout,
    QFormLayout, QDialogButtonBox, QCheckBox, QColorDialog,
    QMenu, QProgressBar, QSystemTrayIcon, QTimeEdit,
    QGraphicsOpacityEffect, QDateEdit, QDateTimeEdit, QListWidget, QListWidgetItem, QTextEdit,
    QSpinBox, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QTime, QDate, QSize, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QIcon, QPixmap, QAction, QLinearGradient, QRadialGradient

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.patches as mpatches
import numpy as np


# =====================================================================
# GEOGRAPHY / TIMEZONE DATA (for the profile window + live local clock)
# =====================================================================

CONTINENTS = {
    "Africa": {
        "Egypt": "Africa/Cairo", "Morocco": "Africa/Casablanca", "Algeria": "Africa/Algiers",
        "Tunisia": "Africa/Tunis", "Libya": "Africa/Tripoli", "Sudan": "Africa/Khartoum",
        "Nigeria": "Africa/Lagos", "Kenya": "Africa/Nairobi", "South Africa": "Africa/Johannesburg",
        "Ethiopia": "Africa/Addis_Ababa",
    },
    "Asia": {
        "Saudi Arabia": "Asia/Riyadh", "United Arab Emirates": "Asia/Dubai", "Qatar": "Asia/Qatar",
        "Kuwait": "Asia/Kuwait", "Bahrain": "Asia/Bahrain", "Oman": "Asia/Muscat",
        "Jordan": "Asia/Amman", "Lebanon": "Asia/Beirut", "Iraq": "Asia/Baghdad",
        "Syria": "Asia/Damascus", "Palestine": "Asia/Gaza", "Yemen": "Asia/Aden",
        "India": "Asia/Kolkata", "Pakistan": "Asia/Karachi", "China": "Asia/Shanghai",
        "Japan": "Asia/Tokyo", "South Korea": "Asia/Seoul", "Indonesia": "Asia/Jakarta",
        "Malaysia": "Asia/Kuala_Lumpur",
    },
    "Europe": {
        "United Kingdom": "Europe/London", "Germany": "Europe/Berlin", "France": "Europe/Paris",
        "Italy": "Europe/Rome", "Spain": "Europe/Madrid", "Netherlands": "Europe/Amsterdam",
        "Russia": "Europe/Moscow", "Greece": "Europe/Athens", "Sweden": "Europe/Stockholm",
        "Turkey": "Europe/Istanbul",
    },
    "North America": {
        "United States": "America/New_York", "Canada": "America/Toronto", "Mexico": "America/Mexico_City",
    },
    "South America": {
        "Brazil": "America/Sao_Paulo", "Argentina": "America/Argentina/Buenos_Aires",
        "Chile": "America/Santiago", "Colombia": "America/Bogota",
    },
    "Oceania": {
        "Australia": "Australia/Sydney", "New Zealand": "Pacific/Auckland",
    },
    "Other": {"UTC": "UTC"},
}


# =====================================================================
# CONFIG / CONSTANTS
# =====================================================================

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "habit_tracker.db")

DEFAULT_HABITS = [
    # icon, name, target_enabled, target_value, category
    ("📖", "Read 10 Pages", True, 20, "Study"),
    ("👟", "Walk 5,000 steps", True, 25, "Health"),
    ("💧", "Water (2l)", True, 22, "Health"),
    ("🚫", "No Alcohol", False, 15, "Health"),
    ("📚", "Study 2 hours", True, 18, "Study"),
    ("🌙", "Sleep 7+ hours", True, 18, "Health"),
    ("🏋️", "Exercise", True, 15, "Health"),
    ("📋", "Daily Plan", True, 20, "Work"),
    ("🧘", "Meditate", False, 10, "Mindfulness"),
    ("🧹", "Clean 15 mins", False, 10, "Other"),
    ("📝", "Journal", True, 15, "Mindfulness"),
    ("💰", "Spend 0$", True, 10, "Finance"),
]

DEFAULT_CATEGORIES = ["Work", "Study", "Personal", "Health", "Delivery", "Finance", "Meeting", "Shopping", "Goal", "Note", "Chores", "Creative", "Travel", "Calls", "Mindfulness", "Other"]

# Auto-suggested icon per category. When the user picks/types a category in
# the Add/Edit Habit dialog and hasn't manually customized the icon, the
# icon field updates to match automatically (e.g. "Study" -> book emoji).
CATEGORY_ICONS = {
    "Work": "💼",
    "Study": "📚",
    "Personal": "🧍",
    "Health": "❤️",
    "Delivery": "📦",
    "Finance": "💰",
    "Meeting": "🗓️",
    "Shopping": "🛒",
    "Goal": "🎯",
    "Note": "📝",
    "Chores": "🧹",
    "Creative": "🎨",
    "Travel": "✈️",
    "Calls": "📞",
    "Mindfulness": "🧘",
    "Other": "⭐",
}

# Streak milestones (in days) that unlock an achievement badge. Based on the
# best all-time streak (every habit done, same day) across the app's history.
ACHIEVEMENTS = [
    (3, "🌱", "3-Day Spark"),
    (7, "🔥", "1-Week Streak"),
    (14, "💪", "2-Week Streak"),
    (30, "🏅", "1-Month Streak"),
    (60, "🥈", "2-Month Streak"),
    (100, "🥇", "100-Day Streak"),
    (180, "💎", "6-Month Streak"),
    (365, "👑", "1-Year Streak"),
]

# XP: every completed check-off (all-time, across all habits) is 1 XP.
# Level = simple bracket so it grows a little slower at higher levels.
XP_PER_LEVEL = 25


def level_from_xp(xp):
    """Returns (level, xp_into_level, xp_needed_for_level)."""
    level = 1
    remaining = xp
    needed = XP_PER_LEVEL
    while remaining >= needed:
        remaining -= needed
        level += 1
        needed = XP_PER_LEVEL + (level - 1) * 5
    return level, remaining, needed


# =====================================================================
# TRANSLATIONS (English / Arabic)
# =====================================================================
# Small, dependency-free i18n layer: every user-facing string used more
# than once (or that's worth translating) has a key here. tr(key, lang)
# looks it up; anything not found just falls back to the key itself, so
# a missing translation never crashes the app — it just shows in English.

STRINGS = {
    "app_title": {"en": "HABIT TRACKER", "ar": "متابع العادات"},
    "app_subtitle": {"en": "Track Your Progress and Set New Habits", "ar": "تابع تقدمك وحدد عادات جديدة"},
    "finish_month": {"en": "✅ FINISH MONTH", "ar": "✅ إنهاء الشهر"},
    "reset_month": {"en": "🔄 RESET MONTH", "ar": "🔄 إعادة تعيين الشهر"},
    "review_missed": {"en": "🔍 Review Missed Days", "ar": "🔍 مراجعة الأيام الفائتة"},
    "finish_this_month_btn": {"en": "✅ FINISH THIS MONTH", "ar": "✅ إنهاء هذا الشهر"},
    "all_categories": {"en": "All Categories", "ar": "كل الفئات"},
    "category_filter_tt": {"en": "Filter habits by category", "ar": "فلترة العادات حسب الفئة"},
    "view_month": {"en": "🗓️ Month View", "ar": "🗓️ عرض شهري"},
    "view_week": {"en": "📆 Week View", "ar": "📆 عرض أسبوعي"},
    "week_label": {"en": "Week {n}: {start} – {end}", "ar": "الأسبوع {n}: {start} – {end}"},
    "prev_week": {"en": "◀ Prev Week", "ar": "◀ الأسبوع السابق"},
    "next_week": {"en": "Next Week ▶", "ar": "الأسبوع التالي ▶"},
    "lang_toggle_tt": {"en": "Switch to Arabic", "ar": "التبديل إلى الإنجليزية"},
    "reminders_tt": {"en": "Reminder settings", "ar": "إعدادات التذكير"},
    "card_daily_goal": {"en": "DAILY GOAL COMPLETION", "ar": "نسبة إنجاز اليوم"},
    "card_breakdown": {"en": "MONTHLY HABIT BREAKDOWN", "ar": "تفاصيل عادات الشهر"},
    "card_mood": {"en": "MONTHLY MOOD", "ar": "المزاج الشهري"},
    "card_weekly_pct": {"en": "WEEKLY PERCENTAGE COMPLETE", "ar": "نسبة الإنجاز الأسبوعية"},
    "card_best_worst": {"en": "BEST & WORST HABITS (ALL, RANKED)", "ar": "أفضل وأسوأ العادات (كل العادات)"},
    "card_progress_log": {"en": "PROGRESS LOG (DAY BY DAY, THIS MONTH)", "ar": "سجل التقدم (يوم بيوم، هذا الشهر)"},
    "card_yearly": {"en": "YEARLY PROGRESS", "ar": "التقدم السنوي"},
    "card_level": {"en": "LEVEL & ACHIEVEMENTS", "ar": "المستوى والإنجازات"},
    "xp_label": {"en": "Level {level} — {xp}/{needed} XP", "ar": "المستوى {level} — {xp}/{needed} نقطة"},
    "col_day": {"en": "Day", "ar": "اليوم"},
    "col_done": {"en": "Done", "ar": "المُنجز"},
    "col_cumulative": {"en": "Cumulative", "ar": "التراكمي"},
    "col_delta": {"en": "Δ vs prev day", "ar": "Δ عن اليوم السابق"},
    "col_num": {"en": "#", "ar": "#"},
    "col_habits": {"en": "DAILY HABITS", "ar": "العادات اليومية"},
    "col_target": {"en": "TARGET", "ar": "الهدف"},
    "col_total": {"en": "TOTAL", "ar": "الإجمالي"},
    "col_status": {"en": "STATUS", "ar": "الحالة"},
    "add_new_habit": {"en": "➕  ADD NEW HABIT", "ar": "➕  إضافة عادة جديدة"},
    "mood_tracker_row": {"en": "😊  DAILY MOOD TRACKER", "ar": "😊  متابعة المزاج اليومي"},
    "notes_row": {"en": "📝  DAILY NOTE", "ar": "📝  ملاحظة اليوم"},
    "edit": {"en": "Edit", "ar": "تعديل"},
    "delete": {"en": "Delete", "ar": "حذف"},
    "save": {"en": "Save", "ar": "حفظ"},
    "cancel": {"en": "Cancel", "ar": "إلغاء"},
    "name": {"en": "Name:", "ar": "الاسم:"},
    "icon": {"en": "Icon:", "ar": "الأيقونة:"},
    "category": {"en": "Category:", "ar": "الفئة:"},
    "delete_habit_title": {"en": "Delete Habit?", "ar": "حذف العادة؟"},
    "delete_habit_body": {
        "en": "This will permanently delete \"{name}\" and every logged day for it. This cannot be undone.\n\nContinue?",
        "ar": "هيتم حذف \"{name}\" نهائيًا مع كل الأيام المسجّلة ليها. مينفعش ترجع بعد كده.\n\nتكمل؟",
    },
    "note_dialog_title": {"en": "Note for {date}", "ar": "ملاحظة يوم {date}"},
    "note_dialog_label": {"en": "Short note (optional):", "ar": "ملاحظة قصيرة (اختياري):"},
    "all_caught_up_title": {"en": "All caught up", "ar": "كله تمام"},
    "all_caught_up_body": {"en": "No missed days need review 🎉", "ar": "مفيش أيام محتاجة مراجعة 🎉"},
    "reminder_dialog_title": {"en": "Daily Reminder", "ar": "التذكير اليومي"},
    "reminder_enable": {"en": "Enable a daily reminder", "ar": "تفعيل تذكير يومي"},
    "reminder_time_label": {"en": "Remind me at:", "ar": "ذكّرني الساعة:"},
    "reminder_notif_title": {"en": "Habit Tracker", "ar": "متابع العادات"},
    "reminder_notif_body": {"en": "Don't forget to log today's habits! 🌟", "ar": "متنساش تسجّل عادات النهارده! 🌟"},
    "celebrate_toast": {"en": "🎉 All habits done for {date}! Great job!", "ar": "🎉 خلّصت كل عادات يوم {date}! تسلم!"},
    "external_update_toast": {"en": "🔄 Updated by Eva", "ar": "🔄 اتحدّث من إيفا"},
    "tray_show_hide": {"en": "Show / Hide", "ar": "إظهار / إخفاء"},
    "tray_today_habits": {"en": "Today's Habits", "ar": "عادات النهاردة"},
    "tray_quit": {"en": "Quit", "ar": "خروج"},
    "profile_setup_prompt": {"en": "👤 Set up your profile", "ar": "👤 جهّز بروفايلك"},
}


def tr(key, lang, **kwargs):
    entry = STRINGS.get(key)
    text = entry.get(lang, entry.get("en", key)) if entry else key
    return text.format(**kwargs) if kwargs else text

MOODS = [
    ("😄", "Happy"),
    ("😌", "Relieved"),
    ("😐", "Neutral"),
    ("😟", "Sad"),
    ("😫", "Stressed"),
]
MOOD_COMBO_ITEMS = ["—"] + [f"{icon} {name}" for icon, name in MOODS]

HABIT_TYPES = [("check", "✅ Check (Yes/No)"), ("numeric", "🔢 Numeric value")]
DIRECTIONS = [("min", "≥ At least (reach the goal)"), ("max", "≤ At most (stay under the limit)")]
PERIODS = [("month", "Per month"), ("week", "Per week")]


def numeric_meets_goal(value, daily_goal, direction):
    """Whether a single day's numeric entry counts as a success."""
    if daily_goal is None or value is None:
        return value is not None and value > 0
    if direction == "max":
        return value <= daily_goal
    return value >= daily_goal


def required_for_month(habit, days_in_month):
    """Converts a habit's target into 'successful days needed this month'.
    For period='month' this is just target_value (unchanged, original
    behavior). For period='week' the person set a weekly quota (e.g. '3
    times a week'), so it's scaled to the number of days in the month."""
    if habit.get("period") == "week":
        return max(1, round(habit["target_value"] * days_in_month / 7))
    return habit["target_value"]


def target_label(habit):
    """Short '🎯 …' label shown under the habit name in the grid."""
    t = habit.get("habit_type", "check")
    unit = habit.get("unit") or ""
    if t == "numeric":
        goal = habit.get("daily_goal")
        arrow = "≤" if habit.get("direction") == "max" else "≥"
        goal_txt = f"{arrow}{goal:g}" if goal is not None else "any"
        suffix = f" {unit}/day" if unit else "/day"
        return f"🎯 {goal_txt}{suffix}"
    if habit.get("period") == "week":
        return f"🎯 {habit['target_value']}×/week"
    return f"🎯 {habit['target_value']}"

THEMES = {
    "light": {
        "bg": "#F3F4F6",
        "card": "#FFFFFF",
        "text": "#1E293B",
        "subtext": "#64748B",
        "border": "#E2E8F0",
        "accent_teal": "#0F766E",
        "accent_green": "#22C55E",
        "accent_orange": "#F97316",
        "accent_blue": "#3B82F6",
        "accent_yellow": "#EAB308",
        "danger": "#EF4444",
        "off_switch": "#CBD5E1",
        "row_alt": "#F8FAFC",
        "pending_bg": "#FFF7ED",
        "missed_bg": "#FEF2F2",
    },
    "dark": {
        "bg": "#0F172A",
        "card": "#1E293B",
        "text": "#F8FAFC",
        "subtext": "#94A3B8",
        "border": "#334155",
        "accent_teal": "#2DD4BF",
        "accent_green": "#4ADE80",
        "accent_orange": "#FB923C",
        "accent_blue": "#38BDF8",
        "accent_yellow": "#FACC15",
        "danger": "#F87171",
        "off_switch": "#475569",
        "row_alt": "#243147",
        "pending_bg": "#3A2B12",
        "missed_bg": "#3A1414",
    },
    "paper": {
        "bg": "#F4EDE0",
        "card": "#FBF6EC",
        "text": "#3B2F2A",
        "subtext": "#8A7A6A",
        "border": "#E4D6BE",
        "accent_teal": "#7A5C3E",
        "accent_green": "#6B8E4E",
        "accent_orange": "#C97B3D",
        "accent_blue": "#5B7A99",
        "accent_yellow": "#C9A227",
        "danger": "#B14A3C",
        "off_switch": "#D8C9AE",
        "row_alt": "#EFE5D2",
        "pending_bg": "#F1E0C4",
        "missed_bg": "#EAD3CB",
    },
    "ocean": {
        "bg": "#EAF6F8",
        "card": "#FFFFFF",
        "text": "#0B3142",
        "subtext": "#4E7C8C",
        "border": "#CDE7EC",
        "accent_teal": "#0891B2",
        "accent_green": "#10B981",
        "accent_orange": "#F59E0B",
        "accent_blue": "#2563EB",
        "accent_yellow": "#D4A017",
        "danger": "#DC2626",
        "off_switch": "#BFE3EA",
        "row_alt": "#DEF2F5",
        "pending_bg": "#FEF3C7",
        "missed_bg": "#FEE2E2",
    },
}

THEME_ORDER = ["light", "dark", "paper", "ocean"]
THEME_ICONS = {"light": "☀️", "dark": "🌙", "paper": "📜", "ocean": "🌊"}
THEME_LABELS = {"light": "Light", "dark": "Dark", "paper": "Paper", "ocean": "Ocean"}


# =====================================================================
# PROFILE DIALOG (name / birthdate / location / gender)
# =====================================================================

class ProfileDialog(QDialog):
    """Optional one-time (editable later) window asking for the person's
    name, birthdate, continent/country (used only to pick a timezone for
    the live clock in the header), and gender. Everything is optional —
    closing/cancelling just skips it and the app works exactly as before."""

    def __init__(self, existing=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tell us about you (optional)")
        self.setMinimumWidth(380)
        existing = existing or {}

        form = QFormLayout(self)

        self.name_edit = QLineEdit(existing.get("name", ""))
        form.addRow("Name:", self.name_edit)

        dob_row = QHBoxLayout()
        self.day_combo = QComboBox()
        self.day_combo.addItems([str(d) for d in range(1, 32)])
        self.month_combo = QComboBox()
        self.month_combo.addItems([calendar.month_name[m] for m in range(1, 13)])
        self.year_combo = QComboBox()
        this_year = date.today().year
        self.year_combo.addItems([str(y) for y in range(this_year - 100, this_year + 1)])
        if existing.get("bday"):
            self.day_combo.setCurrentText(str(existing["bday"]))
        if existing.get("bmonth"):
            self.month_combo.setCurrentIndex(int(existing["bmonth"]) - 1)
        if existing.get("byear"):
            self.year_combo.setCurrentText(str(existing["byear"]))
        else:
            self.year_combo.setCurrentText(str(this_year - 25))
        dob_row.addWidget(self.day_combo)
        dob_row.addWidget(self.month_combo)
        dob_row.addWidget(self.year_combo)
        form.addRow("Birthdate:", dob_row)

        self.continent_combo = QComboBox()
        self.continent_combo.addItems(list(CONTINENTS.keys()))
        self.continent_combo.currentTextChanged.connect(self._refill_countries)
        form.addRow("Continent:", self.continent_combo)

        self.country_combo = QComboBox()
        form.addRow("Country:", self.country_combo)

        if existing.get("continent") in CONTINENTS:
            self.continent_combo.setCurrentText(existing["continent"])
        self._refill_countries(self.continent_combo.currentText())
        if existing.get("country"):
            idx = self.country_combo.findText(existing["country"])
            if idx >= 0:
                self.country_combo.setCurrentIndex(idx)

        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["Prefer not to say", "Male", "Female"])
        if existing.get("gender"):
            idx = self.gender_combo.findText(existing["gender"])
            if idx >= 0:
                self.gender_combo.setCurrentIndex(idx)
        form.addRow("Gender:", self.gender_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _refill_countries(self, continent):
        self.country_combo.clear()
        self.country_combo.addItems(list(CONTINENTS.get(continent, {}).keys()))

    def _test_sound(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "_play_alarm_sound"):
            parent._play_alarm_sound(strong=True)

    def get_values(self):
        return {
            "name": self.name_edit.text().strip(),
            "bday": self.day_combo.currentText(),
            "bmonth": str(self.month_combo.currentIndex() + 1),
            "byear": self.year_combo.currentText(),
            "continent": self.continent_combo.currentText(),
            "country": self.country_combo.currentText(),
            "gender": self.gender_combo.currentText(),
        }


# =====================================================================
# REVIEW MISSED DAYS DIALOG
# =====================================================================

class ReviewDialog(QDialog):
    """Shown when there are past days with incomplete habits that haven't
    been reviewed yet. Lets the person tick anything they actually did but
    forgot to log, before those days get marked as officially 'missed'
    (red). Nothing turns red until the person has had this chance."""

    def __init__(self, missed_data, parent=None):
        # missed_data: list of (date_str, date_obj, [habit_dict, ...missing])
        super().__init__(parent)
        self.setWindowTitle("Review Missed Days")
        self.resize(420, 480)
        self.checkboxes = {}

        outer = QVBoxLayout(self)
        info = QLabel(
            "These past days have habits that weren't checked off. If you actually "
            "did any of them but forgot to log it, tick them now. Anything left "
            "unticked will be marked as missed."
        )
        info.setWordWrap(True)
        outer.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        v = QVBoxLayout(inner)
        for date_str, d, missing in missed_data:
            header = QLabel(f"📅 {d.strftime('%a, %d %b %Y')}")
            f = QFont()
            f.setBold(True)
            header.setFont(f)
            v.addWidget(header)
            for h in missing:
                cb = QCheckBox(f"{h['icon']} {h['name']}")
                self.checkboxes[(date_str, h["id"])] = cb
                v.addWidget(cb)
        v.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        self.later_btn = QPushButton("Remind Me Later")
        self.confirm_btn = QPushButton("✅ Confirm & Mark Reviewed")
        self.later_btn.clicked.connect(self.reject)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.later_btn)
        btn_row.addWidget(self.confirm_btn)
        outer.addLayout(btn_row)

    def get_checked(self):
        return [key for key, cb in self.checkboxes.items() if cb.isChecked()]


# =====================================================================
# ADD / EDIT HABIT DIALOG (supports check, numeric-min and numeric-max
# habits, plus per-month or per-week targets)
# =====================================================================

class HabitEditDialog(QDialog):
    """Used both for 'Add New Habit' (existing=None) and for editing an
    existing habit's full configuration (existing=habit dict)."""

    def __init__(self, existing=None, parent=None, categories=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Habit" if existing else "Add New Habit")
        self.setMinimumWidth(360)
        existing = existing or {}

        form = QFormLayout(self)

        self.icon_edit = QLineEdit(existing.get("icon", "⭐"))
        self.icon_edit.setMaximumWidth(50)
        form.addRow("Icon:", self.icon_edit)

        self.name_edit = QLineEdit(existing.get("name", ""))
        form.addRow("Name:", self.name_edit)

        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        all_cats = list(dict.fromkeys(DEFAULT_CATEGORIES + list(categories or [])))
        self.category_combo.addItems([""] + all_cats)
        current_cat = existing.get("category", "")
        idx = self.category_combo.findText(current_cat)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        else:
            self.category_combo.setCurrentText(current_cat)
        self.category_combo.setToolTip("Pick or type a category, e.g. Health, Work, Study — the icon fills in automatically unless you set your own")
        form.addRow("Category:", self.category_combo)

        # Track whether the icon was deliberately typed by the user (vs. an
        # auto-suggested one from the category), so we only auto-fill it
        # while the user hasn't overridden it themselves.
        current_icon = existing.get("icon", "⭐")
        mapped_icon = CATEGORY_ICONS.get(current_cat)
        self._user_set_icon = bool(mapped_icon and current_icon != mapped_icon) or \
            bool(not mapped_icon and existing and current_icon != "⭐")
        self.icon_edit.textEdited.connect(self._on_icon_manually_edited)
        self.category_combo.currentTextChanged.connect(self._on_category_changed)

        self.type_combo = QComboBox()
        for key, label in HABIT_TYPES:
            self.type_combo.addItem(label, key)
        idx = self.type_combo.findData(existing.get("habit_type", "check"))
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.type_combo.currentIndexChanged.connect(self._sync_visibility)
        form.addRow("Type:", self.type_combo)

        self.direction_combo = QComboBox()
        for key, label in DIRECTIONS:
            self.direction_combo.addItem(label, key)
        idx = self.direction_combo.findData(existing.get("direction", "min"))
        if idx >= 0:
            self.direction_combo.setCurrentIndex(idx)
        self.direction_label = QLabel("Goal type:")
        form.addRow(self.direction_label, self.direction_combo)

        self.unit_edit = QLineEdit(existing.get("unit", ""))
        self.unit_edit.setPlaceholderText("e.g. pages, minutes, liters")
        self.unit_label = QLabel("Unit:")
        form.addRow(self.unit_label, self.unit_edit)

        self.daily_goal_edit = QLineEdit(
            "" if existing.get("daily_goal") is None else f"{existing['daily_goal']:g}"
        )
        self.daily_goal_edit.setPlaceholderText("e.g. 10")
        self.goal_label = QLabel("Daily goal:")
        form.addRow(self.goal_label, self.daily_goal_edit)

        self.period_combo = QComboBox()
        for key, label in PERIODS:
            self.period_combo.addItem(label, key)
        idx = self.period_combo.findData(existing.get("period", "month"))
        if idx >= 0:
            self.period_combo.setCurrentIndex(idx)
        form.addRow("Target period:", self.period_combo)

        self.target_enabled_check = QCheckBox("Track a target for this habit")
        self.target_enabled_check.setChecked(existing.get("target_enabled", True))
        form.addRow(self.target_enabled_check)

        self.target_value_edit = QLineEdit(str(existing.get("target_value", 20)))
        self.target_label = QLabel("Target (days this month):")
        form.addRow(self.target_label, self.target_value_edit)

        self.selected_color = existing.get("color")
        self.color_btn = QPushButton("Choose color…")
        self.color_btn.clicked.connect(self._pick_color)
        self.clear_color_btn = QPushButton("Use default")
        self.clear_color_btn.clicked.connect(self._clear_color)
        self._update_color_btn()
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.clear_color_btn)
        form.addRow("Cell color:", color_row)

        self.period_combo.currentIndexChanged.connect(self._sync_target_label)
        self._sync_visibility()
        self._sync_target_label()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_icon_manually_edited(self, _text):
        self._user_set_icon = True

    def _on_category_changed(self, text):
        if self._user_set_icon:
            return
        icon = CATEGORY_ICONS.get(text.strip())
        if icon:
            self.icon_edit.setText(icon)

    def _sync_visibility(self):
        is_numeric = self.type_combo.currentData() == "numeric"
        for widget in (self.direction_combo, self.unit_edit, self.daily_goal_edit,
                       self.direction_label, self.unit_label, self.goal_label):
            widget.setVisible(is_numeric)

    def _sync_target_label(self):
        if self.period_combo.currentData() == "week":
            self.target_label.setText("Target (times per week):")
        else:
            self.target_label.setText("Target (days this month):")

    def _pick_color(self):
        initial = QColor(self.selected_color) if self.selected_color else QColor("#0F766E")
        color = QColorDialog.getColor(initial, self, "Choose a color for this habit")
        if color.isValid():
            self.selected_color = color.name()
            self._update_color_btn()

    def _clear_color(self):
        self.selected_color = None
        self._update_color_btn()

    def _update_color_btn(self):
        if self.selected_color:
            self.color_btn.setStyleSheet(
                f"background:{self.selected_color}; color:white; font-weight:700;"
            )
            self.color_btn.setText(self.selected_color)
        else:
            self.color_btn.setStyleSheet("")
            self.color_btn.setText("Choose color…")

    def _on_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing name", "Please enter a habit name.")
            return
        try:
            target_value = int(self.target_value_edit.text().strip())
            if target_value < 1:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Invalid target", "Target must be a whole number ≥ 1.")
            return
        if self.type_combo.currentData() == "numeric":
            goal_text = self.daily_goal_edit.text().strip()
            if goal_text:
                try:
                    float(goal_text.replace(",", "."))
                except ValueError:
                    QMessageBox.warning(self, "Invalid goal", "Daily goal must be a number.")
                    return
        self.accept()

    def get_values(self):
        is_numeric = self.type_combo.currentData() == "numeric"
        goal_text = self.daily_goal_edit.text().strip().replace(",", ".")
        daily_goal = float(goal_text) if (is_numeric and goal_text) else None
        return {
            "icon": self.icon_edit.text().strip() or "⭐",
            "name": self.name_edit.text().strip(),
            "habit_type": self.type_combo.currentData(),
            "direction": self.direction_combo.currentData(),
            "unit": self.unit_edit.text().strip() if is_numeric else "",
            "daily_goal": daily_goal,
            "period": self.period_combo.currentData(),
            "target_enabled": self.target_enabled_check.isChecked(),
            "target_value": int(self.target_value_edit.text().strip()),
            "color": self.selected_color,
            "category": self.category_combo.currentText().strip(),
        }


class ReminderDialog(QDialog):
    """Small settings dialog: turn a daily reminder on/off and pick the
    time it should fire at (checked by the main window's reminder_timer
    against the system clock, and delivered via the tray icon)."""
    def __init__(self, enabled=False, time_str="20:00", lang="en", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("reminder_dialog_title", lang))
        self.setMinimumWidth(320)
        v = QVBoxLayout(self)

        self.enable_check = QCheckBox(tr("reminder_enable", lang))
        self.enable_check.setChecked(enabled)
        v.addWidget(self.enable_check)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel(tr("reminder_time_label", lang)))
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("h:mm AP")
        h, m = (int(x) for x in time_str.split(":"))
        self.time_edit.setTime(QTime(h, m))
        time_row.addWidget(self.time_edit)
        self.sound_check = QCheckBox("🔔 Play alarm sound")
        self.sound_check.setChecked(True)
        time_row.addWidget(self.sound_check)
        test_sound = QPushButton("▶ Test alarm")
        test_sound.setToolTip("Play a real alarm sound now")
        test_sound.clicked.connect(self._test_sound)
        time_row.addWidget(test_sound)
        time_row.addStretch()
        v.addLayout(time_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("save", lang))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel", lang))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def get_values(self):
        return {
            "enabled": self.enable_check.isChecked(),
            "time": self.time_edit.time().toString("HH:mm"),
            "sound": self.sound_check.isChecked(),
        }


# =====================================================================
# DATABASE LAYER
# =====================================================================

class Database:
    def __init__(self, path=DB_FILE):
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        # WAL mode lets a reader and a writer (this app + Eva, writing to
        # the same file from a separate process) work at the same time
        # without one blocking/locking out the other, which is what the
        # auto-refresh polling now routinely triggers.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._migrate_flexible_habits()
        self._seed_defaults()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT '⭐',
                target_enabled BOOLEAN NOT NULL DEFAULT 1,
                target_value INTEGER NOT NULL DEFAULT 20,
                display_order INTEGER NOT NULL,
                habit_type TEXT NOT NULL DEFAULT 'check',
                direction TEXT NOT NULL DEFAULT 'min',
                period TEXT NOT NULL DEFAULT 'month',
                unit TEXT NOT NULL DEFAULT '',
                daily_goal REAL,
                color TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS habit_logs (
                habit_id INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                completed BOOLEAN NOT NULL DEFAULT 1,
                value REAL,
                PRIMARY KEY (habit_id, log_date),
                FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mood_logs (
                log_date TEXT PRIMARY KEY,
                mood_type TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS day_reviews (
                log_date TEXT PRIMARY KEY,
                reviewed_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS month_summaries (
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                completion REAL NOT NULL,
                total_checks INTEGER NOT NULL,
                best_habit_name TEXT,
                best_habit_total INTEGER,
                worst_habit_name TEXT,
                worst_habit_total INTEGER,
                current_streak INTEGER,
                best_streak INTEGER,
                finished_at TEXT,
                PRIMARY KEY (year, month)
            )
        """)
        self.conn.commit()

    def _migrate_flexible_habits(self):
        """Adds the new flexible-habit columns to a pre-existing database
        (created before habit types / weekly targets / numeric habits
        existed) without touching any data already in it."""
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(habits)")
        existing = {row[1] for row in cur.fetchall()}
        additions = [
            ("habit_type", "TEXT NOT NULL DEFAULT 'check'"),
            ("direction", "TEXT NOT NULL DEFAULT 'min'"),
            ("period", "TEXT NOT NULL DEFAULT 'month'"),
            ("unit", "TEXT NOT NULL DEFAULT ''"),
            ("daily_goal", "REAL"),
            ("color", "TEXT"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("created_at", "TEXT"),
        ]
        for col, decl in additions:
            if col not in existing:
                cur.execute(f"ALTER TABLE habits ADD COLUMN {col} {decl}")

        # Legacy databases did not store a creation date. Infer missing
        # values from each habit's real history instead of using a fake fixed
        # date such as 2000-01-01. If a habit has no history, use today so it
        # cannot create phantom missed days. This also repairs databases that
        # already have the column but contain NULLs.
        cur.execute("SELECT id FROM habits WHERE created_at IS NULL OR TRIM(created_at) = ''")
        legacy_ids = [r[0] for r in cur.fetchall()]
        for habit_id in legacy_ids:
            cur.execute("SELECT MIN(log_date) FROM habit_logs WHERE habit_id=?", (habit_id,))
            first_log = cur.fetchone()[0]
            cur.execute(
                "UPDATE habits SET created_at=? WHERE id=?",
                (first_log or date.today().isoformat(), habit_id)
            )

        cur.execute("PRAGMA table_info(habit_logs)")
        existing_logs = {row[1] for row in cur.fetchall()}
        if "value" not in existing_logs:
            cur.execute("ALTER TABLE habit_logs ADD COLUMN value REAL")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_notes (
                log_date TEXT PRIMARY KEY,
                note TEXT NOT NULL DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS planner_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Personal',
                pinned BOOLEAN NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS planner_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                start_time TEXT NOT NULL DEFAULT '09:00',
                end_time TEXT NOT NULL DEFAULT '10:00',
                category TEXT NOT NULL DEFAULT 'Personal',
                location TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                reminder_minutes INTEGER NOT NULL DEFAULT 15,
                repeat_rule TEXT NOT NULL DEFAULT 'None',
                completed BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        # Personal Life OS tables. All are local/offline and safe to add to legacy DBs.
        cur.execute("""CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, emoji TEXT NOT NULL, color TEXT DEFAULT '')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT DEFAULT '', category TEXT DEFAULT 'Personal', emoji TEXT DEFAULT '🏠', priority TEXT DEFAULT 'Medium', due_date TEXT, due_time TEXT, status TEXT DEFAULT 'Pending', reminder_minutes INTEGER DEFAULT 0, repeat_rule TEXT DEFAULT 'None', project_id INTEGER, goal_id INTEGER, parent_id INTEGER, created_at TEXT NOT NULL, completed_at TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS inbox (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, created_at TEXT NOT NULL, converted_type TEXT DEFAULT '')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT DEFAULT '', emoji TEXT DEFAULT '🎯', priority TEXT DEFAULT 'Medium', start_date TEXT, target_date TEXT, status TEXT DEFAULT 'Active', created_at TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, emoji TEXT DEFAULT '💼', category TEXT DEFAULT 'Work', priority TEXT DEFAULT 'Medium', start_date TEXT, deadline TEXT, status TEXT DEFAULT 'Active', created_at TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, client TEXT DEFAULT '', phone TEXT DEFAULT '', address TEXT DEFAULT '', amount REAL DEFAULT 0, priority TEXT DEFAULT 'Medium', scheduled_date TEXT, scheduled_time TEXT, status TEXT DEFAULT 'New', notes TEXT DEFAULT '', created_at TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS focus_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT, seconds INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, item_id INTEGER, action TEXT, created_at TEXT NOT NULL, payload TEXT DEFAULT '')""")
        defaults=[('Work','💼'),('Study','📚'),('Personal','🏠'),('Health','🏃'),('Delivery','📦'),('Finance','💰'),('Meeting','👥'),('Shopping','🛒'),('Goal','🎯'),('Note','📝'),('Chores','🧹'),('Creative','🎨'),('Travel','🚗'),('Calls','📞'),('Other','⚙️')]
        for name,emoji in defaults:
            cur.execute('INSERT OR IGNORE INTO categories(name,emoji) VALUES(?,?)',(name,emoji))
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date,due_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at)")
        self.conn.commit()

    def _seed_defaults(self):
        cur = self.conn.cursor()
        # New workspaces start completely empty. Users build their own habits/tasks.
        cur.execute("SELECT COUNT(*) FROM settings WHERE key='theme'")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO settings (key, value) VALUES ('theme', 'light')")
            self.conn.commit()

    # ---------------- Personal Life OS ----------------
    def categories(self):
        return self.conn.execute("SELECT name,emoji FROM categories ORDER BY name").fetchall()
    def add_task(self,title,description,category,emoji,priority,due_date,due_time,reminder=0,repeat_rule='None',project_id=None,goal_id=None):
        now=datetime.now().isoformat(timespec='seconds')
        cur=self.conn.execute("INSERT INTO tasks(title,description,category,emoji,priority,due_date,due_time,reminder_minutes,repeat_rule,project_id,goal_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(title,description,category,emoji,priority,due_date,due_time,reminder,repeat_rule,project_id,goal_id,now))
        self.conn.commit(); return cur.lastrowid
    def update_task_title(self, task_id, title):
        title = (title or "").strip()
        if not title:
            return False
        self.conn.execute("UPDATE tasks SET title=? WHERE id=?", (title, task_id))
        self.conn.commit()
        return True

    def update_task_field(self, task_id, field, value):
        allowed = {"title", "category", "emoji", "priority", "due_date", "due_time", "status"}
        if field not in allowed:
            raise ValueError("Unsupported task field")
        self.conn.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, task_id))
        self.conn.commit()

    def list_tasks(self,day=None,query='',status=None):
        sql="SELECT id,title,description,category,emoji,priority,due_date,due_time,status,reminder_minutes,repeat_rule FROM tasks WHERE 1=1"; args=[]
        if day: sql += " AND due_date=?"; args.append(day)
        if query: sql += " AND (title LIKE ? OR description LIKE ? OR category LIKE ?)"; q='%'+query+'%'; args += [q,q,q]
        if status: sql += " AND status=?"; args.append(status)
        return self.conn.execute(sql+" ORDER BY CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, COALESCE(due_time,'99:99'),id",args).fetchall()
    def set_task_status(self,task_id,status):
        now=datetime.now().isoformat(timespec='seconds') if status=='Done' else None
        self.conn.execute("UPDATE tasks SET status=?,completed_at=? WHERE id=?",(status,now,task_id)); self.conn.execute("INSERT INTO history(item_type,item_id,action,created_at) VALUES('task',?,?,?)",(task_id,status,datetime.now().isoformat(timespec='seconds'))); self.conn.commit()
    def delete_task(self,task_id): self.conn.execute("DELETE FROM tasks WHERE id=?",(task_id,)); self.conn.commit()
    def add_inbox(self,content): self.conn.execute("INSERT INTO inbox(content,created_at) VALUES(?,?)",(content,datetime.now().isoformat(timespec='seconds'))); self.conn.commit()
    def list_inbox(self): return self.conn.execute("SELECT id,content,created_at FROM inbox ORDER BY id DESC").fetchall()
    def delete_inbox(self,i): self.conn.execute("DELETE FROM inbox WHERE id=?",(i,)); self.conn.commit()
    def add_goal(self,title,description,emoji,priority,target_date):
        self.conn.execute("INSERT INTO goals(title,description,emoji,priority,start_date,target_date,created_at) VALUES(?,?,?,?,?,?,?)",(title,description,emoji,priority,date.today().isoformat(),target_date,datetime.now().isoformat(timespec='seconds'))); self.conn.commit()
    def list_goals(self): return self.conn.execute("SELECT id,title,description,emoji,priority,start_date,target_date,status FROM goals ORDER BY status,target_date").fetchall()
    def add_project(self,title,emoji,category,priority,deadline):
        self.conn.execute("INSERT INTO projects(title,emoji,category,priority,start_date,deadline,created_at) VALUES(?,?,?,?,?,?,?)",(title,emoji,category,priority,date.today().isoformat(),deadline,datetime.now().isoformat(timespec='seconds'))); self.conn.commit()
    def list_projects(self): return self.conn.execute("SELECT id,title,emoji,category,priority,deadline,status FROM projects ORDER BY status,deadline").fetchall()
    def add_delivery(self,title,client,phone,address,amount,priority,scheduled_date,scheduled_time,status,notes):
        self.conn.execute("INSERT INTO deliveries(title,client,phone,address,amount,priority,scheduled_date,scheduled_time,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(title,client,phone,address,amount,priority,scheduled_date,scheduled_time,status,notes,datetime.now().isoformat(timespec='seconds'))); self.conn.commit()
    def list_deliveries(self,day=None):
        if day: return self.conn.execute("SELECT id,title,client,phone,address,amount,priority,scheduled_date,scheduled_time,status,notes FROM deliveries WHERE scheduled_date=? ORDER BY scheduled_time",(day,)).fetchall()
        return self.conn.execute("SELECT id,title,client,phone,address,amount,priority,scheduled_date,scheduled_time,status,notes FROM deliveries ORDER BY scheduled_date,scheduled_time").fetchall()

    # ---------------- planner / notebook ----------------
    def list_notes(self, query=''):
        cur = self.conn.cursor()
        q = f"%{query.strip()}%"
        cur.execute("SELECT id,title,body,category,pinned,created_at,updated_at FROM planner_notes "
                    "WHERE title LIKE ? OR body LIKE ? OR category LIKE ? ORDER BY pinned DESC, updated_at DESC", (q,q,q))
        return cur.fetchall()

    def save_planner_note(self, note_id, title, body, category, pinned=False):
        now = datetime.now().isoformat(timespec='seconds')
        cur = self.conn.cursor()
        if note_id:
            cur.execute("UPDATE planner_notes SET title=?,body=?,category=?,pinned=?,updated_at=? WHERE id=?",
                        (title,body,category,int(pinned),now,note_id))
        else:
            cur.execute("INSERT INTO planner_notes(title,body,category,pinned,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (title,body,category,int(pinned),now,now))
        self.conn.commit()

    def delete_planner_note(self, note_id):
        self.conn.execute("DELETE FROM planner_notes WHERE id=?", (note_id,))
        self.conn.commit()

    def list_events(self, start_date=None, end_date=None):
        cur = self.conn.cursor()
        if start_date and end_date:
            cur.execute("SELECT id,title,event_date,start_time,end_time,category,location,description,reminder_minutes,repeat_rule,completed "
                        "FROM planner_events WHERE event_date BETWEEN ? AND ? ORDER BY event_date,start_time", (start_date,end_date))
        else:
            cur.execute("SELECT id,title,event_date,start_time,end_time,category,location,description,reminder_minutes,repeat_rule,completed "
                        "FROM planner_events ORDER BY event_date,start_time")
        return cur.fetchall()

    def add_event(self, title, event_date, start_time, end_time, category, location, description, reminder_minutes, repeat_rule):
        self.conn.execute("INSERT INTO planner_events(title,event_date,start_time,end_time,category,location,description,reminder_minutes,repeat_rule) VALUES(?,?,?,?,?,?,?,?,?)",
                          (title,event_date,start_time,end_time,category,location,description,int(reminder_minutes),repeat_rule))
        self.conn.commit()

    def delete_event(self, event_id):
        self.conn.execute("DELETE FROM planner_events WHERE id=?", (event_id,))
        self.conn.commit()

    def toggle_event(self, event_id, completed):
        self.conn.execute("UPDATE planner_events SET completed=? WHERE id=?", (int(completed),event_id))
        self.conn.commit()

    def due_reminders(self, now_dt):
        """Return event reminders that are due, including a small catch-up window.
        This prevents a 20-second timer tick from missing an exact minute boundary.
        """
        today = now_dt.date().isoformat()
        cur = self.conn.cursor()
        cur.execute("SELECT id,title,event_date,start_time,reminder_minutes FROM planner_events WHERE event_date=? AND completed=0", (today,))
        result=[]
        for row in cur.fetchall():
            try:
                event_dt=datetime.combine(date.fromisoformat(row[2]), datetime.strptime(row[3], '%H:%M').time())
                reminder_at=event_dt-timedelta(minutes=max(0,int(row[4])))
                seconds=(now_dt-reminder_at).total_seconds()
                if -5 <= seconds <= 90:
                    result.append(row+(max(0,int((event_dt-now_dt).total_seconds()/60)),))
            except (ValueError, TypeError):
                pass
        return result

    # ---------------- settings ----------------
    def get_setting(self, key, default=None):
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    # ---------------- habits ----------------
    def get_habits(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, name, icon, target_enabled, target_value, display_order, "
                    "habit_type, direction, period, unit, daily_goal, color, "
                    "COALESCE(category, ''), COALESCE(created_at, ?) "
                    "FROM habits ORDER BY display_order ASC, id ASC", (date.today().isoformat(),))
        rows = cur.fetchall()
        return [
            {"id": r[0], "name": r[1], "icon": r[2], "target_enabled": bool(r[3]),
             "target_value": r[4], "display_order": r[5],
             "habit_type": r[6] or "check", "direction": r[7] or "min",
             "period": r[8] or "month", "unit": r[9] or "", "daily_goal": r[10],
             "color": r[11], "category": r[12] or "", "created_at": r[13]}
            for r in rows
        ]

    def get_all_categories(self):
        """Distinct, non-empty categories currently in use, alphabetically."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT DISTINCT category FROM habits WHERE category IS NOT NULL AND category != '' "
            "ORDER BY category ASC"
        )
        return [r[0] for r in cur.fetchall()]

    def add_habit(self, name, icon="⭐", target_enabled=True, target_value=20,
                  habit_type="check", direction="min", period="month",
                  unit="", daily_goal=None, color=None, category=""):
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(MAX(display_order), -1) + 1 FROM habits")
        order = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO habits (name, icon, target_enabled, target_value, display_order, "
            "habit_type, direction, period, unit, daily_goal, color, category, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, icon, int(target_enabled), target_value, order,
             habit_type, direction, period, unit, daily_goal, color, category,
             date.today().isoformat())
        )
        self.conn.commit()
        return cur.lastrowid

    def reorder_habits(self, ordered_ids):
        """Given the full list of habit ids in their new display order,
        rewrites display_order for all of them in one go (used by
        drag-and-drop reordering in the habits table)."""
        cur = self.conn.cursor()
        cur.executemany(
            "UPDATE habits SET display_order=? WHERE id=?",
            [(i, hid) for i, hid in enumerate(ordered_ids)]
        )
        self.conn.commit()

    def rename_habit(self, habit_id, new_name):
        cur = self.conn.cursor()
        cur.execute("UPDATE habits SET name=? WHERE id=?", (new_name, habit_id))
        self.conn.commit()

    def set_target_enabled(self, habit_id, enabled):
        cur = self.conn.cursor()
        cur.execute("UPDATE habits SET target_enabled=? WHERE id=?", (int(enabled), habit_id))
        self.conn.commit()

    def set_target_value(self, habit_id, value):
        cur = self.conn.cursor()
        cur.execute("UPDATE habits SET target_value=? WHERE id=?", (value, habit_id))
        self.conn.commit()

    def update_habit_config(self, habit_id, name, icon, target_enabled, target_value,
                             habit_type, direction, period, unit, daily_goal, color,
                             category=""):
        """Full editor used by HabitEditDialog — writes every configurable
        field for the habit in one go (daily_goal/color may legitimately
        be None for check-type / no-custom-color habits)."""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE habits SET name=?, icon=?, target_enabled=?, target_value=?, "
            "habit_type=?, direction=?, period=?, unit=?, daily_goal=?, color=?, "
            "category=? WHERE id=?",
            (name, icon, int(target_enabled), target_value, habit_type, direction,
             period, unit, daily_goal, color, category, habit_id)
        )
        self.conn.commit()

    def delete_habit(self, habit_id):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM habits WHERE id=?", (habit_id,))
        cur.execute("DELETE FROM habit_logs WHERE habit_id=?", (habit_id,))
        self.conn.commit()

    # ---------------- habit logs ----------------
    def get_month_logs(self, year, month):
        """Returns {(habit_id, day_int): True} for completed logs in the given month."""
        prefix = f"{year:04d}-{month:02d}-"
        cur = self.conn.cursor()
        cur.execute(
            "SELECT habit_id, log_date FROM habit_logs "
            "WHERE completed=1 AND log_date LIKE ?", (prefix + "%",)
        )
        result = {}
        for habit_id, log_date in cur.fetchall():
            day = int(log_date.split("-")[2])
            result[(habit_id, day)] = True
        return result

    def get_month_values(self, year, month):
        """Returns {(habit_id, day): value} for numeric-type habits in the
        given month (used to display the actual number typed in, not just
        a checkmark)."""
        prefix = f"{year:04d}-{month:02d}-"
        cur = self.conn.cursor()
        cur.execute(
            "SELECT habit_id, log_date, value FROM habit_logs "
            "WHERE value IS NOT NULL AND log_date LIKE ?", (prefix + "%",)
        )
        result = {}
        for habit_id, log_date, value in cur.fetchall():
            day = int(log_date.split("-")[2])
            result[(habit_id, day)] = value
        return result

    def set_numeric_value(self, habit_id, date_str, value, completed):
        """Stores the raw number the person entered for a numeric/negative
        habit, plus whether that number satisfies the habit's daily goal
        (so all the existing streak/total/completion logic — which only
        looks at `completed` — keeps working unchanged)."""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO habit_logs (habit_id, log_date, completed, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(habit_id, log_date) DO UPDATE SET completed=excluded.completed, "
            "value=excluded.value",
            (habit_id, date_str, int(completed), value)
        )
        self.conn.commit()

    def clear_numeric_value(self, habit_id, date_str):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM habit_logs WHERE habit_id=? AND log_date=?", (habit_id, date_str))
        self.conn.commit()

    def toggle_log(self, habit_id, date_str, completed):
        cur = self.conn.cursor()
        if completed:
            cur.execute(
                "INSERT INTO habit_logs (habit_id, log_date, completed) VALUES (?, ?, 1) "
                "ON CONFLICT(habit_id, log_date) DO UPDATE SET completed=1",
                (habit_id, date_str)
            )
        else:
            cur.execute(
                "DELETE FROM habit_logs WHERE habit_id=? AND log_date=?",
                (habit_id, date_str)
            )
        self.conn.commit()

    def count_completed_for_date(self, date_str):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM habit_logs WHERE log_date=? AND completed=1", (date_str,))
        return cur.fetchone()[0]

    def get_all_log_dates(self):
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT log_date FROM habit_logs ORDER BY log_date ASC")
        return [r[0] for r in cur.fetchall()]

    def get_log_date_bounds(self):
        """Return the earliest/latest real log date, or (None, None)."""
        cur = self.conn.cursor()
        cur.execute("SELECT MIN(log_date), MAX(log_date) FROM habit_logs")
        return cur.fetchone()

    def get_all_time_totals(self):
        cur = self.conn.cursor()
        cur.execute("SELECT habit_id, COUNT(*) FROM habit_logs WHERE completed=1 GROUP BY habit_id")
        return dict(cur.fetchall())

    def get_day_logs(self, date_str):
        """Set of habit_ids completed on a specific date."""
        cur = self.conn.cursor()
        cur.execute("SELECT habit_id FROM habit_logs WHERE log_date=? AND completed=1", (date_str,))
        return {r[0] for r in cur.fetchall()}

    def delete_month_logs(self, year, month):
        """Used by 'Reset This Month' — wipes raw logs/moods/review-flags for
        one month only. Does NOT touch month_summaries (already-finished
        months stay saved)."""
        prefix = f"{year:04d}-{month:02d}-"
        cur = self.conn.cursor()
        cur.execute("DELETE FROM habit_logs WHERE log_date LIKE ?", (prefix + "%",))
        cur.execute("DELETE FROM mood_logs WHERE log_date LIKE ?", (prefix + "%",))
        cur.execute("DELETE FROM day_reviews WHERE log_date LIKE ?", (prefix + "%",))
        self.conn.commit()

    # ---------------- missed-day review ----------------
    def mark_day_reviewed(self, date_str):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO day_reviews (log_date, reviewed_at) VALUES (?, datetime('now')) "
            "ON CONFLICT(log_date) DO UPDATE SET reviewed_at=excluded.reviewed_at",
            (date_str,)
        )
        self.conn.commit()

    def get_all_reviewed_dates(self):
        cur = self.conn.cursor()
        cur.execute("SELECT log_date FROM day_reviews")
        return {r[0] for r in cur.fetchall()}

    def get_daily_counts_map(self):
        """Returns {date_str: count_completed} for EVERY logged date, in one query.
        Used so streak calculations don't hit the DB once per day (that repeated
        per-day querying was the main cause of the app feeling slow / 'draggy'
        when moving between months and years)."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT log_date, COUNT(*) FROM habit_logs WHERE completed=1 GROUP BY log_date"
        )
        return dict(cur.fetchall())

    # ---------------- month summaries (yearly progress) ----------------
    def save_month_summary(self, year, month, completion, total_checks,
                            best_habit_name, best_habit_total,
                            worst_habit_name, worst_habit_total,
                            current_streak, best_streak):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO month_summaries
                (year, month, completion, total_checks, best_habit_name, best_habit_total,
                 worst_habit_name, worst_habit_total, current_streak, best_streak, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(year, month) DO UPDATE SET
                completion=excluded.completion,
                total_checks=excluded.total_checks,
                best_habit_name=excluded.best_habit_name,
                best_habit_total=excluded.best_habit_total,
                worst_habit_name=excluded.worst_habit_name,
                worst_habit_total=excluded.worst_habit_total,
                current_streak=excluded.current_streak,
                best_streak=excluded.best_streak,
                finished_at=excluded.finished_at
        """, (year, month, completion, total_checks, best_habit_name, best_habit_total,
              worst_habit_name, worst_habit_total, current_streak, best_streak))
        self.conn.commit()

    def get_month_summary(self, year, month):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT completion, total_checks, best_habit_name, best_habit_total,
                   worst_habit_name, worst_habit_total, current_streak, best_streak, finished_at
            FROM month_summaries WHERE year=? AND month=?
        """, (year, month))
        row = cur.fetchone()
        if not row:
            return None
        keys = ["completion", "total_checks", "best_habit_name", "best_habit_total",
                "worst_habit_name", "worst_habit_total", "current_streak", "best_streak", "finished_at"]
        return dict(zip(keys, row))

    def get_year_summaries(self, year):
        """Returns {month_int: summary_dict} for every month of `year` that has been finished."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT month, completion, total_checks, best_habit_name, best_habit_total,
                   worst_habit_name, worst_habit_total, current_streak, best_streak, finished_at
            FROM month_summaries WHERE year=?
        """, (year,))
        keys = ["completion", "total_checks", "best_habit_name", "best_habit_total",
                "worst_habit_name", "worst_habit_total", "current_streak", "best_streak", "finished_at"]
        result = {}
        for row in cur.fetchall():
            result[row[0]] = dict(zip(keys, row[1:]))
        return result

    # ---------------- moods ----------------
    def get_month_moods(self, year, month):
        """Returns {day_int: mood_type} for the given month."""
        prefix = f"{year:04d}-{month:02d}-"
        cur = self.conn.cursor()
        cur.execute("SELECT log_date, mood_type FROM mood_logs WHERE log_date LIKE ?", (prefix + "%",))
        result = {}
        for log_date, mood_type in cur.fetchall():
            day = int(log_date.split("-")[2])
            result[day] = mood_type
        return result

    def set_mood(self, date_str, mood_type):
        cur = self.conn.cursor()
        if mood_type is None:
            cur.execute("DELETE FROM mood_logs WHERE log_date=?", (date_str,))
        else:
            cur.execute(
                "INSERT INTO mood_logs (log_date, mood_type) VALUES (?, ?) "
                "ON CONFLICT(log_date) DO UPDATE SET mood_type=excluded.mood_type",
                (date_str, mood_type)
            )
        self.conn.commit()

    # ---------------- daily notes ----------------
    def get_month_notes(self, year, month):
        """Returns {day_int: note_text} for the given month (empty notes omitted)."""
        prefix = f"{year:04d}-{month:02d}-"
        cur = self.conn.cursor()
        cur.execute(
            "SELECT log_date, note FROM daily_notes WHERE log_date LIKE ? AND note != ''",
            (prefix + "%",)
        )
        result = {}
        for log_date, note in cur.fetchall():
            day = int(log_date.split("-")[2])
            result[day] = note
        return result

    def set_note(self, date_str, text):
        cur = self.conn.cursor()
        text = (text or "").strip()
        if text:
            cur.execute(
                "INSERT INTO daily_notes (log_date, note) VALUES (?, ?) "
                "ON CONFLICT(log_date) DO UPDATE SET note=excluded.note",
                (date_str, text)
            )
        else:
            cur.execute("DELETE FROM daily_notes WHERE log_date=?", (date_str,))
        self.conn.commit()

    def get_note(self, date_str):
        cur = self.conn.cursor()
        cur.execute("SELECT note FROM daily_notes WHERE log_date=?", (date_str,))
        row = cur.fetchone()
        return row[0] if row else ""

    # ---------------- lifetime stats (gamification) ----------------
    def get_lifetime_xp(self):
        """Total completed check-offs across every habit, ever — used as XP."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM habit_logs WHERE completed=1")
        return cur.fetchone()[0]

    def get_alltime_best_streak(self):
        """Best-ever run of days where EVERY currently-active habit was
        completed on the same day, across the app's entire history."""
        total_habits = self.conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
        if total_habits == 0:
            return 0
        cur = self.conn.cursor()
        cur.execute(
            "SELECT log_date, COUNT(*) FROM habit_logs WHERE completed=1 GROUP BY log_date"
        )
        daily_counts = dict(cur.fetchall())
        if not daily_counts:
            return 0
        all_dates = sorted(daily_counts.keys())
        start = date.fromisoformat(all_dates[0])
        end = date.fromisoformat(all_dates[-1])
        best = current = 0
        d = start
        while d <= end:
            if daily_counts.get(d.strftime("%Y-%m-%d"), 0) >= total_habits:
                current += 1
                best = max(best, current)
            else:
                current = 0
            d += timedelta(days=1)
        return best


# =====================================================================
# CUSTOM WIDGETS
# =====================================================================

class ToggleSwitch(QWidget):
    """A pill-shaped ON/OFF switch, styled like the reference design."""
    toggled = pyqtSignal(bool)

    def __init__(self, checked=False, theme=None, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._theme = theme or THEMES["light"]
        self.setFixedSize(42, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, val):
        self._checked = bool(val)
        self.update()

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        radius = rect.height() / 2
        on_color = QColor(self._theme["accent_green"])
        off_color = QColor(self._theme["off_switch"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(on_color if self._checked else off_color)
        painter.drawRoundedRect(rect, radius, radius)
        circle_d = rect.height() - 4
        x = rect.width() - circle_d - 2 if self._checked else 2
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(x), 2, int(circle_d), int(circle_d))


class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DayCell(QPushButton):
    """A single checkable day cell in the habit grid.
    cell_state: 'normal' | 'pending' (past day, not yet reviewed) |
    'missed' (past day, reviewed, still incomplete)."""
    def __init__(self, checked=False, enabled=True, cell_state="normal"):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setEnabled(enabled)
        self.setFixedSize(28, 28)
        self.setText("✓" if checked else "")
        self.setObjectName("dayCell")
        self.setProperty("cellState", cell_state)
        self.toggled.connect(self._on_toggle)

    def _on_toggle(self, checked):
        self.setText("✓" if checked else "")


class HabitTableWidget(QTableWidget):
    """QTableWidget subclass that supports dragging a habit row to a new
    position. Deliberately does NOT let Qt perform its own internal
    row-move: QTableWidget is known to not move cell widgets along with
    a row during InternalMove drag-and-drop, which would desync the
    on-screen buttons/combos from their underlying habit. Instead we
    detect the drop, ignore Qt's handling entirely, and let the parent
    window recompute the full order and rebuild the table from the
    database — so nothing ever gets out of sync."""
    rowsReordered = pyqtSignal(int, int)  # from_row, to_row

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.habit_row_count = 0
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        drop_row = self.indexAt(pos).row()
        selected = self.selectionModel().selectedRows()
        event.ignore()  # never let Qt move things itself — see class docstring
        if not selected or drop_row < 0:
            return
        source_row = selected[0].row()
        if not (0 <= source_row < self.habit_row_count):
            return
        if drop_row >= self.habit_row_count:
            drop_row = self.habit_row_count - 1
        if drop_row == source_row:
            return
        self.rowsReordered.emit(source_row, drop_row)


class ValueDayCell(QPushButton):
    """A day cell for numeric/negative habits — shows the number typed in
    (instead of a checkmark) and reacts to a click by asking for a value
    rather than toggling. cell_state matches DayCell's ('normal' / 'pending'
    / 'missed') and 'success' additionally colors the cell green even
    before the day is in the past, so hitting today's goal is visible
    immediately."""
    def __init__(self, value=None, success=False, enabled=True, cell_state="normal"):
        super().__init__()
        self.setCheckable(False)
        self.setEnabled(enabled)
        self.setFixedSize(28, 28)
        self.setText("" if value is None else f"{value:g}")
        self.setObjectName("dayCell")
        self.setProperty("cellState", "normal" if success else cell_state)
        self.setProperty("numericSuccess", success)


# =====================================================================
# CHART CANVASES (matplotlib embedded in Qt)
# =====================================================================

class MplCanvas(FigureCanvas):
    def __init__(self, width=4, height=1.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        # More bottom/top breathing room than before — the old margins made
        # the gauge % label and the weekly bar labels get clipped/overlapped.
        self.fig.subplots_adjust(left=0.10, right=0.97, top=0.86, bottom=0.24)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _strip(self, theme):
        self.fig.patch.set_alpha(0)
        self.ax.set_facecolor("none")
        for spine in self.ax.spines.values():
            spine.set_visible(False)
        self.ax.tick_params(colors=theme["subtext"], labelsize=7)


class GaugeCanvas(MplCanvas):
    def plot(self, value, theme):
        self.ax.clear()
        self._strip(theme)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        colors = [theme["accent_blue"], theme["accent_teal"], theme["accent_yellow"], theme["accent_orange"]]
        n = len(colors)
        for i, c in enumerate(colors):
            theta1 = 180 - (i + 1) * 180 / n
            theta2 = 180 - i * 180 / n
            wedge = mpatches.Wedge((0, 0), 1.0, theta1, theta2, width=0.32, facecolor=c, edgecolor="none")
            self.ax.add_patch(wedge)
        angle = np.radians(180 - (max(0, min(value, 100)) / 100) * 180)
        nx, ny = 0.8 * np.cos(angle), 0.8 * np.sin(angle)
        self.ax.plot([0, nx], [0, ny], color=theme["text"], linewidth=2.2, solid_capstyle="round")
        self.ax.add_patch(mpatches.Circle((0, 0), 0.045, color=theme["text"], zorder=5))
        self.ax.text(0, -0.32, f"{value:.0f}%", ha="center", va="center",
                     fontsize=19, fontweight="bold", color=theme["text"])
        self.ax.text(0, -0.55, "Overall Average", ha="center", va="center",
                     fontsize=8, color=theme["subtext"])
        self.ax.set_xlim(-1.15, 1.15)
        self.ax.set_ylim(-0.75, 1.15)
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        self.draw()


class LineCanvas(MplCanvas):
    def plot(self, x, y, theme, ymax=100, step=5):
        self.ax.clear()
        self._strip(theme)
        color = theme["accent_teal"]
        self.ax.plot(x, y, color=color, linewidth=2)
        self.ax.fill_between(x, y, color=color, alpha=0.15)
        self.ax.set_ylim(0, max(ymax, 1))
        if len(x) > 1:
            ticks = list(range(x[0], x[-1] + 1, step)) or x
            self.ax.set_xticks(ticks)
        self.ax.grid(axis="y", color=theme["border"], linewidth=0.6)
        self.ax.set_axisbelow(True)
        self.draw()


class BarCanvas(MplCanvas):
    def plot(self, labels, values, theme, colors=None, unit="%"):
        self.ax.clear()
        self._strip(theme)
        bar_colors = colors if colors else [theme["accent_teal"]] * len(values)
        bars = self.ax.bar(labels, values, color=bar_colors, width=0.6)
        top = max(values + [1]) * 1.45
        for bar, v in zip(bars, values):
            self.ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + top * 0.03,
                         f"{v:.0f}{unit}", ha="center", fontsize=7.5, color=theme["text"])
        self.ax.set_ylim(0, top)
        self.ax.set_yticks([])
        self.ax.tick_params(axis="x", labelsize=7, rotation=0)
        self.draw()


# =====================================================================
# ANIMATED BACKGROUND
# =====================================================================

class AnimatedBackground(QWidget):
    """Reliable, clearly visible animated background rendered behind the UI.

    Uses only Qt + math so it keeps running consistently on Windows/PyQt6.
    The animation is intentionally visible in the open areas of the window,
    while the translucent cards keep the content readable.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.phase = 0.0
        self.theme_name = "light"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)  # ~60 FPS

    def showEvent(self, event):
        super().showEvent(event)
        if not self.timer.isActive():
            self.timer.start(16)

    def set_theme(self, theme_name):
        self.theme_name = theme_name
        self.update()

    def _tick(self):
        # Continuous movement; deliberately fast enough to be noticeable.
        self.phase = (self.phase + 0.025) % (math.tau)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = max(1, self.width())
        h = max(1, self.height())

        if self.theme_name == "dark":
            bg1, bg2 = QColor("#07111F"), QColor("#10243A")
            glow_colors = [QColor("#00D8C8"), QColor("#5B8CFF"), QColor("#A66CFF")]
        elif self.theme_name == "paper":
            bg1, bg2 = QColor("#F1E8D8"), QColor("#FAF5EA")
            glow_colors = [QColor("#D79A4A"), QColor("#7BA7A2"), QColor("#B783C6")]
        elif self.theme_name == "ocean":
            bg1, bg2 = QColor("#E4F5F7"), QColor("#F5FBFC")
            glow_colors = [QColor("#18BFD0"), QColor("#5C8DFF"), QColor("#6AC7A5")]
        else:
            bg1, bg2 = QColor("#EAF3F5"), QColor("#F8FAFC")
            glow_colors = [QColor("#16C7B7"), QColor("#4AA9F5"), QColor("#9B7CFF")]

        # IMPORTANT: this widget is an overlay, so it must NOT paint an opaque
        # background. The static theme color belongs to the central widget; this
        # layer only paints translucent moving light. That makes the animation
        # visible on Windows even when the content widgets occupy the whole window.
        blobs = [
            (0.035, 0.16, 300, 0.34, 0.0, 0.10, 0.12),
            (0.965, 0.15, 330, 0.30, 2.1, 0.10, 0.10),
            (0.035, 0.84, 340, 0.28, 3.5, 0.09, 0.10),
            (0.965, 0.78, 300, 0.32, 4.8, 0.10, 0.11),
        ]
        for i, (x, y, radius, alpha, offset, tx, ty) in enumerate(blobs):
            cx = x * w + math.sin(self.phase * (0.70 + i * 0.06) + offset) * w * tx
            cy = y * h + math.cos(self.phase * (0.54 + i * 0.05) + offset) * h * ty
            pulse = 0.72 + 0.28 * math.sin(self.phase * 1.15 + offset)
            color = QColor(glow_colors[i % len(glow_colors)])
            rg = QRadialGradient(cx, cy, radius)
            center = QColor(color)
            center.setAlphaF(alpha * pulse)
            rg.setColorAt(0.0, center)
            mid = QColor(color)
            mid.setAlphaF(alpha * 0.28)
            rg.setColorAt(0.42, mid)
            edge = QColor(color)
            edge.setAlpha(0)
            rg.setColorAt(1.0, edge)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rg)
            painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))

        # Floating particles with obvious drift.
        for i in range(64):
            base_x = (i * 149 + 37) % w
            base_y = (i * 83 + 61) % h
            speed = 0.45 + (i % 7) * 0.07
            px = (base_x + math.sin(self.phase * speed + i * 0.8) * 38) % w
            py = (base_y + math.cos(self.phase * speed * 0.63 + i) * 20) % h
            radius = 1.0 + (i % 3) * 0.7
            particle = QColor(glow_colors[i % len(glow_colors)])
            particle.setAlpha(90 if self.theme_name == "dark" else 65)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(particle)
            painter.drawEllipse(int(px), int(py), int(radius * 2), int(radius * 2))

        # Moving orbital arcs add an unmistakable animation cue around the edges.
        arc_color = QColor(glow_colors[0])
        arc_color.setAlpha(80 if self.theme_name == "dark" else 55)
        pen = QPen(arc_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for j, scale in enumerate((1.0, 0.72)):
            cx = int(w * (0.72 + 0.05 * math.sin(self.phase * 0.38 + j)))
            cy = int(h * (0.42 + 0.04 * math.cos(self.phase * 0.31 + j)))
            size = int(620 * scale)
            start = int((self.phase * (95 + j * 28) + j * 130) * 16)
            span = int((82 + 22 * math.sin(self.phase + j)) * 16)
            painter.drawArc(cx - size // 2, cy - size // 2, size, size, start, span)

        painter.end()


# =====================================================================
# MAIN WINDOW
# =====================================================================

class HabitTrackerWindow(QMainWindow):
    DAY_COL_OFFSET = 3   # columns before day-1: #, HABITS, TARGET
    TOTAL_COL_EXTRA = 2  # TOTAL, STATUS after day 31

    def __init__(self):
        super().__init__()
        self.db = Database()
        self.theme_name = self.db.get_setting("theme", "light")
        self.lang = self.db.get_setting("lang", "en")

        today = date.today()
        self.current_year = today.year
        self.current_month = today.month

        # --- new-feature state ---
        self.category_filter = "All"
        self.habit_search = ""
        self.view_mode = "month"      # "month" | "week"
        self.week_offset = 0          # which 7-day chunk of the month, in week view
        self._last_rendered_habits = []
        self._celebrated_dates = set()      # dates we've already shown the toast for, this session
        self._notified_today = None         # date the daily reminder already fired for, this session
        self._notified_event_ids = set()

        self.setWindowTitle("Habit Tracker")
        self.resize(1480, 900)
        self.setMinimumSize(1100, 680)

        self._build_ui()
        # Always open on the real current month/year, regardless of any legacy selector state.
        self.month_combo.blockSignals(True)
        self.year_combo.blockSignals(True)
        self.month_combo.setCurrentIndex(today.month - 1)
        self.year_combo.setCurrentText(str(today.year))
        self.month_combo.blockSignals(False)
        self.year_combo.blockSignals(False)
        self._build_tray_icon()
        self.apply_theme()
        self.retranslate_ui()
        self._maybe_show_profile_dialog(first_run=True)
        self._update_profile_display()
        self.refresh_all()
        self._maybe_review_missed_days(manual=False)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        self._tick_clock()

        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self._check_reminder)
        self.reminder_timer.start(1_000)  # check every second so alarms fire reliably at the scheduled time

        # Picks up changes written to the database file by another process
        # (e.g. Eva, a voice assistant that can add/check off habits by
        # talking to this same habit_tracker.db directly - see its
        # habit_tracker_tool.py). This app only ever refreshes its table
        # from the database in response to the user's own actions here, so
        # without this an external write would be saved correctly but
        # invisible in an already-open window until something else
        # happened to trigger a refresh. A cheap mtime check every couple
        # of seconds is enough to catch that and re-pull automatically.
        try:
            self._db_mtime = os.path.getmtime(self.db.path)
        except OSError:
            self._db_mtime = None
        self.external_change_timer = QTimer(self)
        self.external_change_timer.timeout.connect(self._check_external_db_change)
        self.external_change_timer.start(2_000)

    def _check_external_db_change(self):
        try:
            mtime = os.path.getmtime(self.db.path)
        except OSError:
            return
        if self._db_mtime is not None and mtime == self._db_mtime:
            return
        self._db_mtime = mtime

        # Skip a refresh while the user is in the middle of an inline edit
        # or has a modal dialog open - rebuilding the table underneath a
        # cell that's mid-edit would just throw that edit away. The next
        # poll (2s later) will still be watching, so nothing is lost, it
        # just waits its turn.
        if self.table.state() == self.table.State.EditingState or QApplication.activeModalWidget():
            return

        # Preserve where the user actually is (selection + scroll) - a full
        # rebuild otherwise silently resets both, which is jarring if
        # they're mid-review when Eva's write comes in.
        selected_row = self.table.currentRow()
        selected_habit_id = None
        if 0 <= selected_row < len(getattr(self, "_last_rendered_habits", []) or []):
            selected_habit_id = self._last_rendered_habits[selected_row]["id"]
        scroll_value = self.table.verticalScrollBar().value()

        # setUpdatesEnabled(False) batches every widget change below into a
        # single repaint when re-enabled, instead of one paint per chart/
        # table/badge as each is rebuilt - this is what actually removes
        # the visible "flash", not skipping any of the recompute (skipping
        # the charts would just leave them showing stale numbers).
        self.setUpdatesEnabled(False)
        try:
            self.refresh_all()

            if selected_habit_id is not None:
                for row, habit in enumerate(self._last_rendered_habits or []):
                    if habit["id"] == selected_habit_id:
                        self.table.setCurrentCell(row, max(0, self.table.currentColumn()))
                        break
            self.table.verticalScrollBar().setValue(scroll_value)
        except sqlite3.OperationalError:
            # Rare read/write clash with the other process writing to the
            # same file - skip this cycle silently, the next poll (2s
            # later) will pick up the change once the clash has cleared.
            pass
        finally:
            self.setUpdatesEnabled(True)

        self._show_toast(self.tr_("external_update_toast"), self.theme()["accent_blue"])

    # -----------------------------------------------------------------
    # TRANSLATION
    # -----------------------------------------------------------------
    def tr_(self, key, **kwargs):
        return tr(key, self.lang, **kwargs)

    def toggle_language(self):
        self.lang = "ar" if self.lang == "en" else "en"
        self.db.set_setting("lang", self.lang)
        self.retranslate_ui()
        self.refresh_all()

    def retranslate_ui(self):
        L = self.tr_
        self.title_label.setText(L("app_title"))
        self.subtitle_label.setText(L("app_subtitle"))
        self.finish_month_header_btn.setText(L("finish_month"))
        self.finish_month_header_btn.setToolTip(
            "Review a summary, then save this month and move to the next" if self.lang == "en"
            else "راجع ملخص الشهر، وبعدين احفظه وانتقل للي بعده"
        )
        self.reset_month_btn.setText(L("reset_month"))
        self.reset_month_btn.setToolTip(
            "Start this month over — clears its logs without touching saved months" if self.lang == "en"
            else "ابدأ الشهر ده من جديد — بيمسح تسجيلاته من غير ما يأثر على الشهور المحفوظة"
        )
        self.review_btn.setText(L("review_missed"))
        self.finish_month_btn.setText(L("finish_this_month_btn"))
        self.category_combo.setToolTip(L("category_filter_tt"))
        self.today_btn.setToolTip("Jump back to the current month" if self.lang == "en" else "الرجوع لشهر اليوم الحالي")
        self.habit_search_edit.setPlaceholderText("Search habits…" if self.lang == "en" else "ابحث عن عادة…")
        self.lang_btn.setToolTip(L("lang_toggle_tt"))
        self.reminder_btn.setToolTip(L("reminders_tt"))
        self.profile_btn.setToolTip("Edit your profile" if self.lang == "en" else "تعديل بروفايلك")
        self.table.setToolTip(
            "Drag a habit's name to reorder it. Right-click a habit for more options." if self.lang == "en"
            else "اسحب اسم العادة عشان ترتبها. دوس زرار يمين على أي عادة لخيارات أكتر."
        )

        self.card1_title.setText(L("card_daily_goal"))
        self.card2_title.setText(L("card_breakdown"))
        self.card3_title.setText(L("card_mood"))
        self.card4_title.setText(L("card_weekly_pct"))
        self.card5_title.setText(L("card_best_worst"))
        self.card6_title.setText(L("card_progress_log"))
        self.card7_title.setText(L("card_yearly"))
        self.card8_title.setText(L("card_level"))

        self.progress_table.setHorizontalHeaderLabels(
            [L("col_day"), L("col_done"), L("col_cumulative"), L("col_delta")]
        )
        self.table.setHorizontalHeaderLabels(self._table_headers())
        self._update_view_mode_controls()
        self._update_category_filter_options()
        self._update_tray_menu_texts()

    def _update_category_filter_options(self):
        """Rebuilds the category dropdown from categories currently in
        use, keeping the current selection if it still exists."""
        cats = self.db.get_all_categories()
        current = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem(self.tr_("all_categories"), "All")
        for c in cats:
            self.category_combo.addItem(c, c)
        idx = self.category_combo.findData(current if current else "All")
        self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_filter = self.category_combo.currentData() or "All"
        self.category_combo.blockSignals(False)

    def on_category_filter_changed(self):
        new_val = self.category_combo.currentData() or "All"
        if new_val == self.category_filter:
            return
        self.category_filter = new_val
        self.refresh_all()

    def on_habit_search_changed(self, text):
        self.habit_search = text.strip().lower()
        self.refresh_all()

    def go_today(self):
        today = date.today()
        self.week_offset = 0
        self._set_month_year(today.year, today.month)

    # -----------------------------------------------------------------
    # MONTH / WEEK VIEW
    # -----------------------------------------------------------------
    def _week_chunks(self):
        """Splits the current month into (start_day, end_day) 7-day
        chunks, e.g. [(1,7), (8,14), (15,21), (22,28), (29,31)]."""
        days_in_month = calendar.monthrange(self.current_year, self.current_month)[1]
        chunks = []
        start = 1
        while start <= days_in_month:
            end = min(start + 6, days_in_month)
            chunks.append((start, end))
            start = end + 1
        return chunks

    def toggle_view_mode(self):
        self.view_mode = "week" if self.view_mode == "month" else "month"
        if self.view_mode == "week":
            # Land on the week containing today if we're looking at the
            # current month, otherwise the first week of the month.
            today = date.today()
            self.week_offset = 0
            if today.year == self.current_year and today.month == self.current_month:
                for i, (s, e) in enumerate(self._week_chunks()):
                    if s <= today.day <= e:
                        self.week_offset = i
                        break
        self._update_view_mode_controls()
        self._render_table(self.compute_stats(), self.theme())

    def go_prev_week(self):
        if self.week_offset > 0:
            self.week_offset -= 1
        else:
            # Cross into the previous month's last week.
            self.go_prev_month()
            self.week_offset = max(0, len(self._week_chunks()) - 1)
        self._update_view_mode_controls()
        self._render_table(self.compute_stats(), self.theme())

    def go_next_week(self):
        chunks = self._week_chunks()
        if self.week_offset < len(chunks) - 1:
            self.week_offset += 1
        else:
            self.go_next_month()
            self.week_offset = 0
        self._update_view_mode_controls()
        self._render_table(self.compute_stats(), self.theme())

    def _update_view_mode_controls(self):
        is_week = self.view_mode == "week"
        self.view_toggle_btn.setText(self.tr_("view_week") if is_week else self.tr_("view_month"))
        self.prev_week_btn.setVisible(is_week)
        self.next_week_btn.setVisible(is_week)
        self.week_label.setVisible(is_week)
        self.prev_week_btn.setText("◀")
        self.next_week_btn.setText("▶")
        if is_week:
            chunks = self._week_chunks()
            idx = min(self.week_offset, len(chunks) - 1) if chunks else 0
            if chunks:
                s, e = chunks[idx]
                self.week_label.setText(self.tr_("week_label", n=idx + 1, start=s, end=e))

    # -----------------------------------------------------------------
    # SYSTEM TRAY + QUICK CHECK-IN
    # -----------------------------------------------------------------
    def _build_tray_icon(self):
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#14b8a6"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        painter.setPen(QColor("white"))
        font = QFont()
        font.setPointSize(28)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "✓")
        painter.end()

        self.tray_icon = QSystemTrayIcon(QIcon(pix), self)
        self.tray_icon.setToolTip("Habit Tracker")

        self.tray_menu = QMenu()
        self.tray_show_action = QAction(self.tr_("tray_show_hide"), self)
        self.tray_show_action.triggered.connect(self._toggle_window_visibility)
        self.tray_today_menu = QMenu(self.tr_("tray_today_habits"))
        self.tray_quit_action = QAction(self.tr_("tray_quit"), self)
        self.tray_quit_action.triggered.connect(QApplication.instance().quit)

        self.tray_menu.addAction(self.tray_show_action)
        self.tray_menu.addMenu(self.tray_today_menu)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.tray_quit_action)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _toggle_window_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_window_visibility()

    def _update_tray_menu_texts(self):
        if not hasattr(self, "tray_show_action"):
            return
        self.tray_show_action.setText(self.tr_("tray_show_hide"))
        self.tray_today_menu.setTitle(self.tr_("tray_today_habits"))
        self.tray_quit_action.setText(self.tr_("tray_quit"))
        self._rebuild_tray_today_menu()

    def _rebuild_tray_today_menu(self):
        """Lets the person check off TODAY's habits straight from the
        tray, without opening the full window. Scoped to the real
        calendar 'today' regardless of which month is currently open."""
        if not hasattr(self, "tray_today_menu"):
            return
        self.tray_today_menu.clear()
        today = date.today()
        date_str = today.isoformat()
        done_ids = self.db.get_day_logs(date_str)
        for h in self.db.get_habits():
            if h.get("habit_type") == "numeric":
                continue  # needs an actual value — not a quick toggle
            action = QAction(f"{h['icon']} {h['name']}", self.tray_today_menu)
            action.setCheckable(True)
            action.setChecked(h["id"] in done_ids)
            action.toggled.connect(partial(self._on_tray_habit_toggled, h["id"], date_str))
            self.tray_today_menu.addAction(action)

    def _on_tray_habit_toggled(self, habit_id, date_str, checked):
        self.db.toggle_log(habit_id, date_str, checked)
        today = date.today()
        if today.year == self.current_year and today.month == self.current_month:
            self.refresh_all()
        else:
            self._rebuild_tray_today_menu()
        if checked:
            self._maybe_celebrate_day(date_str)

    # -----------------------------------------------------------------
    # REMINDERS
    # -----------------------------------------------------------------
    def _play_alarm_sound(self, strong=True):
        """Play a noticeable alarm on Windows, asynchronously so the UI stays responsive."""
        try:
            if sys.platform.startswith("win"):
                import winsound

                # Build a tiny WAV at runtime: this avoids relying on Windows'
                # optional notification sounds or on Beep hardware support.
                sample_rate = 44100
                pattern = [
                    (880, 0.22), (0, 0.08), (1047, 0.22), (0, 0.08),
                    (1319, 0.32), (0, 0.10),
                ]
                if not strong:
                    pattern = [(988, 0.20), (0, 0.08), (1175, 0.28)]
                # Repeat the pattern so it sounds like an alarm, not a single beep.
                pattern = pattern * (3 if strong else 2)
                path = os.path.join(tempfile.gettempdir(), "habit_tracker_alarm.wav")
                with wave.open(path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    frames = bytearray()
                    for freq, duration in pattern:
                        count = int(sample_rate * duration)
                        for i in range(count):
                            if freq:
                                # Slightly softened square wave for a more alarm-like tone.
                                value = 12000 if math.sin(2 * math.pi * freq * i / sample_rate) >= 0 else -12000
                            else:
                                value = 0
                            frames += int(value).to_bytes(2, byteorder="little", signed=True)
                    wf.writeframes(frames)
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                QApplication.beep()
                QTimer.singleShot(250, QApplication.beep)
                QTimer.singleShot(500, QApplication.beep)
        except Exception as exc:
            print(f"Alarm sound error: {exc}")
            try:
                QApplication.beep()
                QTimer.singleShot(250, QApplication.beep)
                QTimer.singleShot(500, QApplication.beep)
            except Exception:
                pass

    def _notify_alarm(self, title, body, event_id=None, sound=True):
        if event_id is not None and event_id in self._notified_event_ids:
            return
        if event_id is not None:
            self._notified_event_ids.add(event_id)
        if sound:
            self._play_alarm_sound()
        if hasattr(self, "tray_icon"):
            self.tray_icon.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 10000)
        else:
            QMessageBox.information(self, title, body)

    def open_reminder_settings(self):
        enabled = self.db.get_setting("reminder_enabled", "0") == "1"
        time_str = self.db.get_setting("reminder_time", "20:00")
        dlg = ReminderDialog(enabled=enabled, time_str=time_str, lang=self.lang, parent=self)
        if dlg.exec():
            v = dlg.get_values()
            self.db.set_setting("reminder_enabled", "1" if v["enabled"] else "0")
            self.db.set_setting("reminder_time", v["time"])
            self.db.set_setting("reminder_sound", "1" if v.get("sound", True) else "0")
            self._play_alarm_sound() if v.get("sound", True) else None
            self._notified_today = None  # allow it to fire today if the new time hasn't passed

    def _check_reminder(self):
        now = datetime.now()
        # Planner event reminders
        for row in self.db.due_reminders(now):
            event_id,title,event_date,start_time,minutes,delta=row
            if event_id in self._notified_event_ids: continue
            self._notified_event_ids.add(event_id)
            when = "now" if delta == 0 else (f"in {delta} min" if delta > 0 else "now")
            self._notify_alarm("📅 Planner Reminder", f"{title} — {when}", event_id=event_id, sound=True)
        # Existing daily habit reminder remains supported.
        if self.db.get_setting("reminder_enabled", "0") != "1": return
        reminder_time=self.db.get_setting("reminder_time", "20:00")
        if now.strftime("%H:%M") != reminder_time: return
        today_str=date.today().isoformat()
        if self._notified_today == today_str: return
        self._notified_today=today_str
        self._notify_alarm(self.tr_("reminder_notif_title"), self.tr_("reminder_notif_body"), sound=self.db.get_setting("reminder_sound", "1") == "1")

    # -----------------------------------------------------------------
    # PROFILE (name / birthdate / country / gender) + live local clock
    # -----------------------------------------------------------------
    def _load_profile(self):
        keys = ["name", "bday", "bmonth", "byear", "continent", "country", "gender"]
        profile = {k: self.db.get_setting(f"profile_{k}") for k in keys}
        return profile if profile.get("name") is not None or profile.get("country") else {}

    def _save_profile(self, values):
        for k, v in values.items():
            self.db.set_setting(f"profile_{k}", v)
        self.db.set_setting("profile_set", "1")

    def _maybe_show_profile_dialog(self, first_run=False):
        if first_run and self.db.get_setting("profile_set") == "1":
            return
        existing = self._load_profile()
        dlg = ProfileDialog(existing=existing, parent=self)
        if dlg.exec():
            self._save_profile(dlg.get_values())
        elif first_run:
            # Mark as "asked" even on cancel so we don't nag every launch.
            self.db.set_setting("profile_set", "1")
        self._update_profile_display()

    def edit_profile(self):
        self._maybe_show_profile_dialog(first_run=False)

    def _update_profile_display(self):
        p = self._load_profile()
        name = p.get("name") or ""
        country = p.get("country") or ""
        tz_name = None
        for continent, countries in CONTINENTS.items():
            if country in countries:
                tz_name = countries[country]
                break
        self._profile_tz = tz_name

        if p.get("bday") and p.get("bmonth") and p.get("byear"):
            try:
                bdate = date(int(p["byear"]), int(p["bmonth"]), int(p["bday"]))
                today = date.today()
                age = today.year - bdate.year - ((today.month, today.day) < (bdate.month, bdate.day))
            except ValueError:
                age = None
        else:
            age = None

        pieces = []
        if name:
            pieces.append(f"👋 {name}")
        if age is not None:
            pieces.append(f"{age} yrs")
        if p.get("gender") and p["gender"] != "Prefer not to say":
            pieces.append(p["gender"])
        if country:
            pieces.append(f"🌍 {country}")
        self.profile_label.setText("  •  ".join(pieces) if pieces else "👤 Set up your profile")

    def _tick_clock(self):
        try:
            tz = ZoneInfo(self._profile_tz) if getattr(self, "_profile_tz", None) else None
        except Exception:
            tz = None
        now = datetime.now(tz) if tz else datetime.now()
        self.clock_label.setText(now.strftime("%I:%M:%S %p"))

    # -----------------------------------------------------------------
    # THEME
    # -----------------------------------------------------------------
    def theme(self):
        return THEMES[self.theme_name]

    def toggle_theme(self):
        menu = QMenu(self)
        for name in THEME_ORDER:
            action = menu.addAction(f"{THEME_ICONS[name]}  {THEME_LABELS[name]}")
            action.setCheckable(True)
            action.setChecked(name == self.theme_name)
            action.triggered.connect(partial(self.set_theme, name))
        menu.exec(self.theme_btn.mapToGlobal(self.theme_btn.rect().bottomLeft()))

    def set_theme(self, name):
        if name not in THEMES:
            return
        self.theme_name = name
        self.db.set_setting("theme", self.theme_name)
        self.apply_theme()
        self.refresh_all()

    def apply_theme(self):
        t = self.theme()
        self.theme_btn.setText(THEME_ICONS.get(self.theme_name, "🎨"))
        self.theme_btn.setToolTip(f"Theme: {THEME_LABELS.get(self.theme_name, self.theme_name)} — click to change")
        self.setStyleSheet(self._build_qss(t))
        if hasattr(self, "animated_bg"):
            self.animated_bg.set_theme(self.theme_name)
        if hasattr(self, "profile_label"):
            self.profile_label.setStyleSheet(f"color:{t['subtext']}; font-size:12px; font-weight:600;")
        if hasattr(self, "clock_label"):
            self.clock_label.setStyleSheet(f"color:{t['accent_teal']}; font-size:13px; font-weight:800;")

    def _build_qss(self, t):
        card = QColor(t['card'])
        card_rgba = f"rgba({card.red()}, {card.green()}, {card.blue()}, 232)"
        card_soft = f"rgba({card.red()}, {card.green()}, {card.blue()}, 185)"
        bg = QColor(t['bg'])
        bg_soft = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, 170)"
        return f"""
            QMainWindow, QWidget#centralWidget {{ background: {t["bg"]}; }}
            QWidget#contentLayer {{ background: transparent; }}
            QLabel {{ color: {t['text']}; }}
            QLabel#titleLabel {{
                font-size: 28px; font-weight: 850; color: {t['text']}; letter-spacing: 1px;
            }}
            QLabel#subtitleLabel {{ font-size: 12px; color: {t['subtext']}; }}
            QLabel#cardTitle {{ font-size: 12px; font-weight: 700; color: {t['subtext']}; letter-spacing: 1px; }}
            QFrame#card {{
                background: {card_rgba}; border: 1px solid {t['border']}; border-radius: 16px;
            }}
            QFrame#badge {{
                background: {card_soft}; border: 1px solid {t['border']}; border-radius: 10px;
            }}
            QPushButton#navBtn {{
                background: {t['card']}; border: 1px solid {t['border']}; border-radius: 10px;
                font-size: 13px; font-weight: 700; color: {t['text']}; padding: 0 9px;
            }}
            QPushButton#navBtn:hover {{ background: {t['row_alt']}; border-color: {t['accent_teal']}; }}
            QPushButton#navBtn:pressed {{ background: {t['row_alt']}; }}
            QPushButton#themeBtn {{
                background: {t['card']}; border: 1px solid {t['border']}; border-radius: 18px; font-size: 15px;
            }}
            QComboBox {{
                background: {card_soft}; border: 1px solid {t['border']}; border-radius: 8px;
                padding: 4px 10px; color: {t['text']}; font-weight: 600;
            }}
            QComboBox QAbstractItemView {{
                background: {t['card']}; color: {t['text']}; selection-background-color: {t['accent_teal']};
            }}
            QTableWidget {{
                background: {card_rgba}; color: {t['text']}; border: 1px solid {t['border']};
                gridline-color: {t['border']}; border-radius: 14px;
                selection-background-color: {t['row_alt']};
                alternate-background-color: {t['row_alt']};
            }}
            QHeaderView::section {{
                background: {bg_soft}; color: {t['subtext']}; font-weight: 700; font-size: 10px;
                border: none; border-bottom: 2px solid {t['border']}; padding: 6px 2px;
            }}
            QTableWidget::item {{ border-bottom: 1px solid {t['border']}; }}
            QTableWidget QLineEdit {{ background: {card_soft}; color: {t['text']}; border: 1px solid {t['accent_teal']}; padding: 3px 8px; }}
            QPushButton#dayCell {{
                background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 6px; color: {t['text']};
            }}
            QPushButton#dayCell[cellState="pending"] {{
                background: {t['pending_bg']}; border: 1px solid {t['accent_orange']};
            }}
            QPushButton#dayCell[cellState="missed"] {{
                background: {t['missed_bg']}; border: 1px solid {t['danger']}; color: {t['danger']};
            }}
            QPushButton#dayCell:checked {{
                background: {t['accent_teal']}; color: white; border: 1px solid {t['accent_teal']};
                font-weight: 700;
            }}
            QPushButton#dayCell[numericSuccess="true"] {{
                background: {t['accent_teal']}; color: white; border: 1px solid {t['accent_teal']};
                font-weight: 700;
            }}
            QPushButton#dayCell:disabled {{ background: transparent; border: 1px solid transparent; }}
            QPushButton#addHabitBtn {{
                background: transparent; color: {t['accent_teal']}; font-weight: 700;
                border: 1px dashed {t['border']}; border-radius: 8px; padding: 6px;
            }}
            QPushButton#addHabitBtn:hover {{ background: {t['row_alt']}; }}
            QLineEdit {{
                background: {card_soft}; color: {t['text']}; border: 1px solid {t['border']};
                border-radius: 10px; padding: 5px 10px; selection-background-color: {t['accent_teal']};
            }}
            QLineEdit:focus {{ border: 1px solid {t['accent_teal']}; }}
            QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 16px; background: {card_rgba}; }}
            QTabBar::tab {{ background: {card_soft}; color: {t['subtext']}; padding: 9px 18px; margin-right: 3px; border-radius: 9px; font-weight: 700; }}
            QTabBar::tab:selected {{ background: {t['accent_teal']}; color: white; }}
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{ background: {card_soft}; border: 1px solid {t['border']}; border-radius: 12px; padding: 9px; margin: 4px 0; }}
            QListWidget::item:selected {{ background: {t['row_alt']}; border: 1px solid {t['accent_teal']}; }}
            QTextEdit {{ background: {card_rgba}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 14px; padding: 12px; font-size: 13px; }}
            QTextEdit:focus {{ border: 1px solid {t['accent_teal']}; }}
            QDateEdit, QTimeEdit {{ background: {card_soft}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 9px; padding: 6px 10px; }}
            QCheckBox {{ color: {t['text']}; spacing: 7px; }}
            QTabWidget::pane {{ margin-top: 4px; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; }}
            QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 5px; }}
        """

    # -----------------------------------------------------------------
    # UI BUILD
    # -----------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        central.setAutoFillBackground(False)
        self.setCentralWidget(central)

        # Use a simple overlapping grid instead of QStackedLayout(StackAll).
        # StackAll can behave differently across Qt/Windows builds and may leave
        # the dashboard layer invisible while the background still paints.
        # The grid keeps the animated background behind the actual UI reliably.
        stack = QGridLayout(central)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)

        content = QWidget(central)
        content.setObjectName("contentLayer")
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        content.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        content.setAutoFillBackground(False)
        root = QVBoxLayout(content)
        root.setContentsMargins(22, 14, 22, 14)
        root.setSpacing(11)

        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(13)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(370)
        left_content = self._build_left_panel()
        left_scroll.setWidget(left_content)
        body.addWidget(left_scroll)

        body.addWidget(self._build_right_panel(), stretch=1)

        root.addLayout(body, stretch=1)
        stack.addWidget(content, 0, 0)
        self.dashboard_layer = content
        self.planner_layer = self._build_planner_layer()
        self.planner_layer.hide()
        stack.addWidget(self.planner_layer, 0, 0)
        self.life_layer = self._build_life_os_layer()
        self.life_layer.hide()
        stack.addWidget(self.life_layer, 0, 0)

        # Put the animation LAST in the same grid. It is transparent for mouse
        # events and paints only translucent glows/particles, so it can visibly
        # animate above the UI without blocking clicks or hiding widgets.
        self.animated_bg = AnimatedBackground(central)
        self.animated_bg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.animated_bg.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        stack.addWidget(self.animated_bg, 0, 0)
        self.animated_bg.raise_()
        self._main_stack = stack

    def _raise_animation_overlay(self):
        # The animation is a transparent overlay. Re-raise it whenever a page
        # is switched so the moving glow remains visible above the active page.
        if hasattr(self, "animated_bg"):
            self.animated_bg.raise_()
            self.animated_bg.update()

    def show_planner(self):
        self.dashboard_layer.hide(); self.life_layer.hide(); self.planner_layer.show(); self.planner_layer.raise_(); self._raise_animation_overlay(); self._refresh_planner()
    def show_dashboard(self):
        self.planner_layer.hide(); self.life_layer.hide(); self.dashboard_layer.show(); self.dashboard_layer.raise_(); self._raise_animation_overlay()
    def show_life_os(self):
        self.dashboard_layer.hide(); self.planner_layer.hide(); self.life_layer.show(); self.life_layer.raise_(); self._raise_animation_overlay(); self._refresh_life_os()

    def _build_planner_layer(self):
        page=QWidget(); page.setObjectName("contentLayer")
        root=QVBoxLayout(page); root.setContentsMargins(22,14,22,14); root.setSpacing(12)
        top=QHBoxLayout()
        title=QLabel("📓 Planner"); title.setObjectName("titleLabel")
        self.planner_subtitle=QLabel("Notes, appointments, deliveries and smart reminders")
        self.planner_subtitle.setObjectName("subtitleLabel")
        back=QPushButton("← Dashboard"); back.setObjectName("navBtn"); back.clicked.connect(self.show_dashboard)
        top.addWidget(title); top.addWidget(self.planner_subtitle); top.addStretch(); top.addWidget(back)
        root.addLayout(top)
        tabs=QTabWidget(); root.addWidget(tabs,1)

        # Notebook
        notes=QWidget(); nv=QHBoxLayout(notes); nv.setSpacing(14)
        left=QVBoxLayout(); self.note_search=QLineEdit(); self.note_search.setPlaceholderText("🔎 Search your notes..."); self.note_search.textChanged.connect(self._refresh_notes)
        self.note_list=QListWidget(); self.note_list.setSpacing(2); self.note_list.currentRowChanged.connect(self._load_selected_note)
        left.addWidget(self.note_search); left.addWidget(self.note_list,1)
        nb=QHBoxLayout(); self.new_note_btn=QPushButton("＋ New Note"); self.new_note_btn.clicked.connect(self._new_note); self.delete_note_btn=QPushButton("🗑 Delete"); self.delete_note_btn.clicked.connect(self._delete_selected_note); nb.addWidget(self.new_note_btn); nb.addWidget(self.delete_note_btn); left.addLayout(nb)
        editor=QVBoxLayout(); self.note_title=QLineEdit(); self.note_title.setPlaceholderText("Give this note a clear title..."); self.note_title.setMinimumHeight(42)
        self.note_category=QComboBox(); self.note_category.addItems(["Personal","Work","Study","Ideas","Projects","Delivery","Other"])
        self.note_pinned=QCheckBox("📌 Pin this note")
        self.note_body=QTextEdit(); self.note_body.setPlaceholderText("Write anything here...\n\nMeeting notes • delivery details • ideas • phone numbers • plans • follow-ups")
        self.note_body.setMinimumHeight(280)
        meta=QHBoxLayout(); meta.addWidget(self.note_category); meta.addWidget(self.note_pinned); meta.addStretch()
        save=QPushButton("💾 Save Note"); save.setMinimumHeight(40); save.clicked.connect(self._save_current_note)
        editor.addWidget(QLabel("NOTE TITLE")); editor.addWidget(self.note_title); editor.addLayout(meta); editor.addWidget(self.note_body,1); editor.addWidget(save)
        nv.addLayout(left,1); nv.addLayout(editor,2); tabs.addTab(notes,"📓 Notebook")

        # Calendar / reminders
        events=QWidget(); ev=QVBoxLayout(events); ev.setSpacing(10)
        row=QHBoxLayout(); self.event_date_filter=QDateEdit(); self.event_date_filter.setCalendarPopup(True); self.event_date_filter.setDisplayFormat("ddd, d MMM yyyy"); self.event_date_filter.setDate(QDate.currentDate()); self.event_date_filter.dateChanged.connect(self._refresh_events)
        add=QPushButton("＋ Add Appointment / Delivery"); add.clicked.connect(self._add_event_dialog)
        allb=QPushButton("Show All"); allb.clicked.connect(lambda: self._refresh_events(all_dates=True))
        todayb=QPushButton("Today"); todayb.clicked.connect(lambda: (self.event_date_filter.setDate(QDate.currentDate()), self._refresh_events()))
        row.addWidget(QLabel("📅")); row.addWidget(self.event_date_filter); row.addWidget(add); row.addWidget(todayb); row.addWidget(allb); row.addStretch(); ev.addLayout(row)
        self.event_list=QListWidget(); self.event_list.setSpacing(5); ev.addWidget(self.event_list,1)
        hint=QLabel("💡 Add a delivery, appointment or deadline. Set an alarm, then press Done when finished."); hint.setObjectName("subtitleLabel"); ev.addWidget(hint)
        tabs.addTab(events,"📅 Calendar & Reminders")
        return page

    def _refresh_planner(self):
        self._refresh_notes(); self._refresh_events()

    def _refresh_notes(self):
        if not hasattr(self,'note_list'): return
        current=self.note_list.currentItem(); current_id=current.data(Qt.ItemDataRole.UserRole) if current else None
        self.note_list.blockSignals(True); self.note_list.clear()
        for row in self.db.list_notes(self.note_search.text()):
            title=("📌  " if row[4] else "📝  ")+row[1]
            item=QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole,row[0])
            item.setToolTip(f"{row[3]} • Updated {row[6]}")
            self.note_list.addItem(item)
            if row[0]==current_id: self.note_list.setCurrentItem(item)
        self.note_list.blockSignals(False)
        if self.note_list.currentRow() < 0 and self.note_list.count(): self.note_list.setCurrentRow(0)

    def _load_selected_note(self,row):
        if row<0: return
        item=self.note_list.item(row); nid=item.data(Qt.ItemDataRole.UserRole)
        data=next((r for r in self.db.list_notes('') if r[0]==nid),None)
        if data:
            self._editing_note_id=nid; self.note_title.setText(data[1]); self.note_body.setPlainText(data[2]); self.note_category.setCurrentText(data[3]); self.note_pinned.setChecked(bool(data[4]))

    def _new_note(self):
        self._editing_note_id=None; self.note_title.clear(); self.note_body.clear(); self.note_category.setCurrentIndex(0); self.note_pinned.setChecked(False); self.note_title.setFocus()

    def _save_current_note(self):
        title=self.note_title.text().strip()
        if not title: QMessageBox.warning(self,"Notebook","Please enter a note title."); return
        self.db.save_planner_note(getattr(self,'_editing_note_id',None),title,self.note_body.toPlainText(),self.note_category.currentText(),self.note_pinned.isChecked()); self._refresh_notes()

    def _delete_selected_note(self):
        item=self.note_list.currentItem()
        if not item: return
        self.db.delete_planner_note(item.data(Qt.ItemDataRole.UserRole)); self._new_note(); self._refresh_notes()

    def _refresh_events(self, *args, all_dates=False):
        if not hasattr(self,'event_list'): return
        self.event_list.clear()
        rows=self.db.list_events() if all_dates else self.db.list_events(self.event_date_filter.date().toPyDate().isoformat(),self.event_date_filter.date().toPyDate().isoformat())
        for r in rows:
            item=QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole,r[0]); item.setSizeHint(QSize(0, 76))
            card=QWidget(); lay=QHBoxLayout(card); lay.setContentsMargins(10,7,8,7); lay.setSpacing(10)
            done=QCheckBox(); done.setChecked(bool(r[10])); done.setToolTip("Mark as done")
            done.toggled.connect(partial(self._toggle_event_done, r[0]))
            try:
                pretty_time = datetime.strptime(r[3], "%H:%M").strftime("%I:%M %p").lstrip("0")
            except Exception:
                pretty_time = r[3]
            time_lbl=QLabel(f"{pretty_time}\n{r[2]}"); time_lbl.setMinimumWidth(110); time_lbl.setStyleSheet(f"color:{self.theme()['accent_teal']}; font-weight:800;")
            text=QVBoxLayout(); title=QLabel(r[1]); title.setStyleSheet("font-size:13px; font-weight:800;")
            meta=" • ".join(x for x in [r[5], r[6]] if x)
            if r[8]: meta += ("  ·  🔔 " + ("at time" if r[8]==0 else f"{r[8]} min before"))
            if r[9] != "None": meta += f"  ·  🔁 {r[9]}"
            meta_lbl=QLabel(meta); meta_lbl.setObjectName("subtitleLabel")
            text.addWidget(title); text.addWidget(meta_lbl)
            if r[7]:
                desc=QLabel(r[7]); desc.setObjectName("subtitleLabel"); desc.setWordWrap(True); text.addWidget(desc)
            delete=QPushButton("🗑"); delete.setFixedSize(34,34); delete.setToolTip("Delete")
            delete.clicked.connect(partial(self._delete_event_by_id, r[0]))
            lay.addWidget(done); lay.addWidget(time_lbl); lay.addLayout(text,1); lay.addWidget(delete)
            self.event_list.addItem(item); self.event_list.setItemWidget(item,card)

    def _toggle_event_done(self, event_id, checked):
        self.db.toggle_event(event_id, checked)
        self._refresh_events()

    def _delete_event_by_id(self, event_id):
        if QMessageBox.question(self,"Delete event","Delete this appointment / reminder?") == QMessageBox.StandardButton.Yes:
            self.db.delete_event(event_id); self._refresh_events()

    def _add_event_dialog(self):
        dlg=QDialog(self); dlg.setWindowTitle("Add Appointment / Delivery / Deadline"); dlg.setMinimumWidth(560); form=QFormLayout(dlg); form.setSpacing(10)
        title=QLineEdit(); title.setPlaceholderText("e.g. Deliver package to Ahmed")
        dt=QDateEdit(); dt.setCalendarPopup(True); dt.setDisplayFormat("ddd, d MMM yyyy"); dt.setDate(QDate.currentDate())
        start=QTimeEdit(QTime.currentTime()); start.setDisplayFormat("h:mm AP")
        end=QTimeEdit(QTime.currentTime().addSecs(3600)); end.setDisplayFormat("h:mm AP")
        cat=QComboBox(); cat.addItems(["Personal","Work","Study","Meeting","Delivery","Deadline","Other"]); cat.setCurrentText("Delivery")
        loc=QLineEdit(); loc.setPlaceholderText("Optional location / address")
        desc=QTextEdit(); desc.setPlaceholderText("Details, phone number, what needs to be delivered, etc."); desc.setMinimumHeight(100)
        rem=QComboBox(); rem.addItem("🔔 At time",0); rem.addItem("5 minutes before",5); rem.addItem("15 minutes before",15); rem.addItem("30 minutes before",30); rem.addItem("1 hour before",60); rem.addItem("1 day before",1440)
        repeat=QComboBox(); repeat.addItems(["None","Daily","Weekly","Monthly","Weekdays"])
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject)
        for label,w in [("Title",title),("Date",dt),("Start",start),("End",end),("Type",cat),("Location",loc),("Details / Note",desc),("Alarm",rem),("Repeat",repeat)]: form.addRow(label,w)
        form.addRow(buttons)
        if dlg.exec():
            if not title.text().strip():
                QMessageBox.warning(self,"Missing title","Please enter a title."); return
            self.db.add_event(title.text().strip(),dt.date().toPyDate().isoformat(),start.time().toString('HH:mm'),end.time().toString('HH:mm'),cat.currentText(),loc.text().strip(),desc.toPlainText().strip(),rem.currentData() or 0,repeat.currentText())
            self.event_date_filter.setDate(dt.date()); self._refresh_events()


    def _delete_event_prompt(self,item):
        eid=item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self,"Delete event","Delete this appointment/reminder?") == QMessageBox.StandardButton.Yes:
            self.db.delete_event(eid); self._refresh_events()

    def _build_life_os_layer(self):
        page=QWidget(); page.setObjectName("contentLayer")
        root=QVBoxLayout(page); root.setContentsMargins(22,14,22,14); root.setSpacing(12)
        top=QHBoxLayout(); title=QLabel("🏠 Personal Life OS"); title.setObjectName("titleLabel")
        sub=QLabel("One calm place for your tasks, goals, habits and day."); sub.setObjectName("subtitleLabel")
        back=QPushButton("← Habits"); back.setObjectName("navBtn"); back.clicked.connect(self.show_dashboard)
        top.addWidget(title); top.addWidget(sub); top.addStretch(); top.addWidget(back); root.addLayout(top)
        tabs=QTabWidget(); root.addWidget(tabs,1); self.life_tabs=tabs
        # Today dashboard
        dash=QWidget(); dv=QVBoxLayout(dash)
        self.life_summary=QLabel(); self.life_summary.setObjectName("cardTitle"); dv.addWidget(self.life_summary)
        self.quick=QLineEdit(); self.quick.setPlaceholderText("⚡ Quick add: Study Python tomorrow 7pm"); self.quick.returnPressed.connect(self._quick_add); dv.addWidget(self.quick)
        self.today_table=QTableWidget(0,7); self._configure_task_table(self.today_table); dv.addWidget(self.today_table,1)
        tabs.addTab(dash,"🏠 Today")
        # Tasks
        tasks=QWidget(); tv=QVBoxLayout(tasks); tr=QHBoxLayout(); self.task_search=QLineEdit(); self.task_search.setPlaceholderText("🔎 Search tasks..."); self.task_search.textChanged.connect(self._refresh_tasks)
        add=QPushButton("＋ Add Task"); add.clicked.connect(self._add_task_dialog); tr.addWidget(self.task_search,1); tr.addWidget(add); tv.addLayout(tr)
        self.task_table=QTableWidget(0,7); self._configure_task_table(self.task_table); tv.addWidget(self.task_table,1); tabs.addTab(tasks,"📋 Tasks")
        # Inbox
        inbox=QWidget(); iv=QVBoxLayout(inbox); self.inbox_edit=QLineEdit(); self.inbox_edit.setPlaceholderText("📥 Capture anything… press Enter"); self.inbox_edit.returnPressed.connect(self._capture_inbox); iv.addWidget(self.inbox_edit); self.inbox_list=QListWidget(); iv.addWidget(self.inbox_list,1); tabs.addTab(inbox,"📥 Inbox")
        # Goals / projects / deliveries
        goals=QWidget(); gv=QVBoxLayout(goals); self.goal_list=QListWidget(); gb=QPushButton("＋ Create Goal"); gb.clicked.connect(self._add_goal_dialog); gv.addWidget(gb); gv.addWidget(self.goal_list,1); tabs.addTab(goals,"🎯 Goals")
        projects=QWidget(); pv=QVBoxLayout(projects); self.project_list=QListWidget(); pb=QPushButton("＋ Create Project"); pb.clicked.connect(self._add_project_dialog); pv.addWidget(pb); pv.addWidget(self.project_list,1); tabs.addTab(projects,"💼 Projects")
        dels=QWidget(); lv=QVBoxLayout(dels); self.delivery_list=QListWidget(); lb=QPushButton("＋ Add Delivery"); lb.clicked.connect(self._add_delivery_dialog); lv.addWidget(lb); lv.addWidget(self.delivery_list,1); tabs.addTab(dels,"📦 Deliveries")
        focus=QWidget(); fv=QVBoxLayout(focus); self.focus_label=QLabel("25:00"); self.focus_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.focus_label.setStyleSheet("font-size:42px;font-weight:900;"); fb=QPushButton("▶ Start Focus"); fb.clicked.connect(self._toggle_focus); fv.addStretch(); fv.addWidget(self.focus_label); fv.addWidget(fb); fv.addStretch(); tabs.addTab(focus,"⏱ Focus")
        return page

    def _category_picker(self):
        c=QComboBox(); data=self.db.categories()
        for name,emoji in data: c.addItem(f"{emoji} {name}", (name,emoji))
        return c

    def _quick_add(self):
        text=self.quick.text().strip()
        if not text: return
        import re
        low=text.lower(); category="Personal"; emoji="🏠"
        for n,e in self.db.categories():
            if n.lower() in low: category,emoji=n,e; break
        priority="High" if any(x in low for x in ["urgent","critical","عاجل"]) else "Medium"
        due=date.today().isoformat(); due_time=None
        if "tomorrow" in low or "غد" in low: due=(date.today()+timedelta(days=1)).isoformat()
        m=re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b',low)
        if m:
            hh=int(m.group(1)); mm=int(m.group(2) or 0); ap=m.group(3)
            if ap=='pm' and hh<12: hh+=12
            if ap=='am' and hh==12: hh=0
            due_time=f"{hh:02d}:{mm:02d}"
        self.db.add_task(text,category=category,emoji=emoji,priority=priority,description="",due_date=due,due_time=due_time)
        self.quick.clear(); self._refresh_life_os()

    def _add_task_dialog(self):
        dlg=QDialog(self); dlg.setWindowTitle("Add Task"); form=QFormLayout(dlg)
        title=QLineEdit(); desc=QTextEdit(); desc.setMaximumHeight(90); cat=self._category_picker(); pri=QComboBox(); pri.addItems(["Critical","High","Medium","Low"]); dt=QDateEdit(QDate.currentDate()); dt.setCalendarPopup(True); tm=QTimeEdit(QTime.currentTime()); tm.setDisplayFormat("h:mm AP"); rep=QComboBox(); rep.addItems(["None","Daily","Weekdays","Weekly","Monthly"])
        for lab,w in [("Task",title),("Details",desc),("Category",cat),("Priority",pri),("Date",dt),("Time",tm),("Repeat",rep)]: form.addRow(lab,w)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); form.addRow(bb)
        if dlg.exec() and title.text().strip():
            n,e=cat.currentData(); self.db.add_task(title.text().strip(),desc.toPlainText().strip(),n,e,pri.currentText(),dt.date().toPyDate().isoformat(),tm.time().toString("HH:mm"),repeat_rule=rep.currentText()); self._refresh_life_os()

    def _refresh_tasks(self):
        if not hasattr(self,'task_table'): return
        rows=self.db.list_tasks(query=self.task_search.text().strip()); self._fill_task_table(self.task_table,rows)

    def _configure_task_table(self, table):
        """Configure the task table for both existing-task editing and a
        persistent inline "new task" row.  The draft row is always first and
        lets the user type immediately; category is chosen from the same
        central emoji/category registry used everywhere else."""
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(["Logo", "Task", "Category", "Due", "Priority", "Status", "Actions"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        table.setColumnWidth(0, 72)
        table.setColumnWidth(1, 280)
        table.setColumnWidth(2, 150)
        table.itemChanged.connect(partial(self._task_table_item_changed, table))

    def _make_task_draft_row(self, table, rows=None):
        """Create a real editable inline task row.

        The previous implementation used an empty QTableWidgetItem. On some
        Windows/Qt builds that item would look selected but fail to enter an
        editor reliably. Using a real QLineEdit as a cell widget makes typing
        deterministic and lets Enter create the task immediately.
        """
        row = 0
        table.insertRow(row)

        # Logo cell: follows the same category registry used everywhere else.
        logo = QLabel("＋")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setToolTip("New task")
        logo.setStyleSheet("font-size:20px;")
        table.setCellWidget(row, 0, logo)

        # Real text editor, always visible and always focusable.
        title = QLineEdit()
        title.setPlaceholderText("Type a task here…  e.g. Finish report")
        title.setClearButtonEnabled(True)
        title.setObjectName("inlineTaskEditor")
        title.setMinimumHeight(34)
        title.returnPressed.connect(lambda t=table: self._save_inline_task_editor(t))
        table.setCellWidget(row, 1, title)

        combo = QComboBox()
        combo.setObjectName("inlineTaskCategory")
        for name, emoji in self.db.categories():
            combo.addItem(f"{emoji}  {name}", (name, emoji))
        combo.currentIndexChanged.connect(lambda _=0, c=combo, l=logo: self._sync_task_logo(c, l))
        table.setCellWidget(row, 2, combo)

        due = QTableWidgetItem("Today")
        due.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        due.setFlags(due.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, 3, due)

        pri = QTableWidgetItem("🟡 Medium")
        pri.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        pri.setFlags(pri.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, 4, pri)

        st = QTableWidgetItem("⏳ Pending")
        st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        st.setFlags(st.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, 5, st)

        action = QTableWidgetItem("↵ Enter")
        action.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        action.setFlags(action.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, 6, action)
        self._sync_task_logo(combo, logo)

        # Give the editor the initial keyboard focus only for the Tasks tab.
        if table is getattr(self, "task_table", None):
            title.setFocus()

    def _sync_task_logo(self, combo, logo):
        data = combo.currentData()
        emoji = data[1] if data else "🏠"
        logo.setText(emoji)
        logo.setFont(QFont("Segoe UI Emoji", 18))

    def _save_inline_task_editor(self, table):
        if table.rowCount() == 0:
            return
        editor = table.cellWidget(0, 1)
        if not isinstance(editor, QLineEdit):
            return
        title = editor.text().strip()
        if not title:
            editor.setFocus()
            return
        combo = table.cellWidget(0, 2)
        category, emoji = combo.currentData() if combo else ("Personal", "🏠")
        try:
            self.db.add_task(
                title,
                category=category,
                emoji=emoji,
                priority="Medium",
                description="",
                due_date=date.today().isoformat(),
                due_time=None,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not save task", str(exc))
            return
        self._refresh_life_os()
        # After refresh, focus the new empty inline editor again.
        QTimer.singleShot(0, self._focus_inline_task_editor)

    def _focus_inline_task_editor(self):
        table = getattr(self, "task_table", None)
        if table is None or table.rowCount() == 0:
            return
        editor = table.cellWidget(0, 1)
        if isinstance(editor, QLineEdit):
            editor.setFocus()
            editor.selectAll()

    def _fill_task_table(self, table, rows):
        table.blockSignals(True)
        table.setRowCount(0)
        table.blockSignals(False)
        for r in rows:
            i = table.rowCount()
            table.insertRow(i)
            vals = [r[4], r[1], r[3], f"{r[6] or ''} {r[7] or ''}".strip(), r[5], r[8], ""]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, r[0])
                if j == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setToolTip(f"{r[4]}  {r[3]}")
                    item.setFont(QFont("Segoe UI Emoji", 18))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                elif j == 1:
                    item.setToolTip("Double-click or press F2 to edit the task name")
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(i, j, item)
            done = QPushButton("✓")
            done.setToolTip("Mark as done")
            done.clicked.connect(partial(self._task_status, r[0], "Done"))
            fail = QPushButton("✕")
            fail.setToolTip("Mark as failed")
            fail.clicked.connect(partial(self._task_status, r[0], "Failed"))
            table.setCellWidget(i, 6, self._button_row(done, fail))

        # The inline entry row is ALWAYS the first row.
        self._make_task_draft_row(table, rows)

    def _task_table_item_changed(self, table, item):
        # Kept for backwards compatibility with existing connections. All new
        # task entry uses the real QLineEdit above.
        if item.column() != 1:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        title = item.text().strip()
        if task_id and title:
            self.db.update_task_title(task_id, title)

    def _button_row(self,*buttons):
        w=QWidget(); l=QHBoxLayout(w); l.setContentsMargins(2,2,2,2)
        for b in buttons: l.addWidget(b)
        return w
    def _task_status(self,tid,status): self.db.set_task_status(tid,status); self._refresh_life_os()

    def _capture_inbox(self):
        x=self.inbox_edit.text().strip()
        if x: self.db.add_inbox(x); self.inbox_edit.clear(); self._refresh_inbox()
    def _refresh_inbox(self):
        self.inbox_list.clear()
        for i,text,created in self.db.list_inbox():
            item=QListWidgetItem(f"📥 {text}\n{created[:16]}"); item.setData(Qt.ItemDataRole.UserRole,i); self.inbox_list.addItem(item)

    def _add_goal_dialog(self):
        text,ok=QInputDialog.getText(self,"New Goal","Goal title:")
        if ok and text.strip(): self.db.add_goal(text.strip(),"","🎯","Medium",(date.today()+timedelta(days=30)).isoformat()); self._refresh_life_os()
    def _add_project_dialog(self):
        text,ok=QInputDialog.getText(self,"New Project","Project title:")
        if ok and text.strip(): self.db.add_project(text.strip(),"💼","Work","Medium",(date.today()+timedelta(days=30)).isoformat()); self._refresh_life_os()
    def _add_delivery_dialog(self):
        dlg=QDialog(self); dlg.setWindowTitle("Add Delivery"); f=QFormLayout(dlg); title=QLineEdit(); client=QLineEdit(); phone=QLineEdit(); address=QLineEdit(); amount=QLineEdit(); dt=QDateEdit(QDate.currentDate()); dt.setCalendarPopup(True); tm=QTimeEdit(QTime.currentTime()); tm.setDisplayFormat("h:mm AP"); notes=QTextEdit(); notes.setMaximumHeight(80)
        for lab,w in [("Order",title),("Client",client),("Phone",phone),("Address",address),("Amount",amount),("Date",dt),("Time",tm),("Notes",notes)]: f.addRow(lab,w)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); f.addRow(bb)
        if dlg.exec() and title.text().strip():
            try: val=float(amount.text() or 0)
            except ValueError: val=0
            self.db.add_delivery(title.text().strip(),client.text().strip(),phone.text().strip(),address.text().strip(),val,"Medium",dt.date().toPyDate().isoformat(),tm.time().toString("HH:mm"),"New",notes.toPlainText().strip()); self._refresh_life_os()
    def _toggle_focus(self):
        if not hasattr(self,'_focus_running') or not self._focus_running:
            self._focus_running=True; self._focus_seconds=25*60; self._focus_tick(); self.focus_timer=QTimer(self); self.focus_timer.timeout.connect(self._focus_tick); self.focus_timer.start(1000)
        else: self._focus_running=False; self.focus_timer.stop()
    def _focus_tick(self):
        if self._focus_seconds<=0: self._focus_running=False; self.focus_timer.stop(); self._notify_alarm("⏱ Focus complete","Great work!",sound=True); return
        self.focus_label.setText(f"{self._focus_seconds//60:02d}:{self._focus_seconds%60:02d}"); self._focus_seconds-=1
    def _refresh_life_os(self):
        if not hasattr(self,'today_table'): return
        today=date.today().isoformat(); rows=self.db.list_tasks(day=today); done=sum(r[8]=='Done' for r in rows); total=len(rows); self.life_summary.setText(f"TODAY  •  {done}/{total} tasks complete  •  {round(done/total*100) if total else 0}%")
        self._fill_task_table(self.today_table,rows); self._refresh_tasks(); self._refresh_inbox()
        self.goal_list.clear()
        for r in self.db.list_goals(): self.goal_list.addItem(f"{r[3]} {r[1]}  •  {r[4]}  •  due {r[6] or '—'}")
        self.project_list.clear()
        for r in self.db.list_projects(): self.project_list.addItem(f"{r[2]} {r[1]}  •  {r[3]}  •  {r[4]}")
        self.delivery_list.clear()
        for r in self.db.list_deliveries(day=today): self.delivery_list.addItem(f"📦 {r[1]}  •  {r[2] or '—'}  •  {r[8] or '—'}  •  {r[9]}")

    def _build_header(self):
        header = QWidget()
        layout = QVBoxLayout(header)
        layout.setSpacing(2)

        self.title_label = QLabel("HABIT TRACKER")
        self.title_label.setObjectName("titleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.subtitle_label = QLabel("Your daily habits, progress, and streaks — all in one place")
        self.subtitle_label.setObjectName("subtitleLabel")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

        # Profile summary (name / age / gender / country) + live local clock
        profile_row = QHBoxLayout()
        profile_row.addStretch()
        self.profile_label = QLabel("")
        self.profile_label.setStyleSheet(f"color:{self.theme()['subtext']}; font-size:12px; font-weight:600;")
        self.profile_btn = QPushButton("👤")
        self.profile_btn.setObjectName("themeBtn")
        self.profile_btn.setFixedSize(30, 30)
        self.profile_btn.setToolTip("Edit your profile")
        self.profile_btn.clicked.connect(self.edit_profile)
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setStyleSheet(f"color:{self.theme()['accent_teal']}; font-size:13px; font-weight:800;")
        profile_row.addWidget(self.profile_btn)
        profile_row.addWidget(self.profile_label)
        profile_row.addSpacing(12)
        profile_row.addWidget(QLabel("🕒"))
        profile_row.addWidget(self.clock_label)
        profile_row.addStretch()
        layout.addLayout(profile_row)

        controls = QHBoxLayout()
        controls.addStretch()

        self.prev_btn = QPushButton("<")
        self.prev_btn.setObjectName("navBtn")
        self.prev_btn.setFixedSize(38, 38)
        self.prev_btn.clicked.connect(self.go_prev_month)

        self.month_combo = QComboBox()
        self.month_combo.addItems([calendar.month_name[i].upper() for i in range(1, 13)])
        self.month_combo.setFixedWidth(160)
        self.month_combo.currentIndexChanged.connect(self.on_month_year_changed)

        self.year_combo = QComboBox()
        current_year = date.today().year
        first_log, last_log = self.db.get_log_date_bounds()
        years = {current_year + i for i in range(-5, 6)}
        for value in (first_log, last_log):
            if value:
                try:
                    years.add(date.fromisoformat(value).year)
                except ValueError:
                    pass
        self.year_combo.addItems([str(y) for y in sorted(years)])
        self.year_combo.setFixedWidth(90)
        self.year_combo.currentIndexChanged.connect(self.on_month_year_changed)

        self.next_btn = QPushButton(">")
        self.next_btn.setObjectName("navBtn")
        self.next_btn.setFixedSize(38, 38)
        self.next_btn.clicked.connect(self.go_next_month)

        # Category filter
        self.today_btn = QPushButton("Today")
        self.today_btn.setObjectName("navBtn")
        self.today_btn.setFixedHeight(38)
        self.today_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.today_btn.clicked.connect(self.go_today)

        self.category_combo = QComboBox()
        self.category_combo.setFixedWidth(145)
        self.category_combo.currentIndexChanged.connect(self.on_category_filter_changed)

        self.habit_search_edit = QLineEdit()
        self.habit_search_edit.setPlaceholderText("Search habits…")
        self.habit_search_edit.setClearButtonEnabled(True)
        self.habit_search_edit.setFixedWidth(190)
        self.habit_search_edit.setFixedHeight(38)
        self.habit_search_edit.textChanged.connect(self.on_habit_search_changed)

        # Month / Week view toggle + week nav (week widgets hidden in month mode)
        self.view_toggle_btn = QPushButton()
        self.view_toggle_btn.setObjectName("navBtn")
        self.view_toggle_btn.setFixedHeight(38)
        self.view_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_toggle_btn.clicked.connect(self.toggle_view_mode)

        self.prev_week_btn = QPushButton()
        self.prev_week_btn.setObjectName("navBtn")
        self.prev_week_btn.setFixedHeight(38)
        self.prev_week_btn.clicked.connect(self.go_prev_week)

        self.week_label = QLabel("")
        self.week_label.setStyleSheet(f"color:{self.theme()['subtext']}; font-size:11px; font-weight:700;")

        self.next_week_btn = QPushButton()
        self.next_week_btn.setObjectName("navBtn")
        self.next_week_btn.setFixedHeight(38)
        self.next_week_btn.clicked.connect(self.go_next_week)

        self.theme_btn = QPushButton("🌙")
        self.theme_btn.setObjectName("themeBtn")
        self.theme_btn.setFixedSize(38, 38)
        self.theme_btn.clicked.connect(self.toggle_theme)

        self.lang_btn = QPushButton("🌐")
        self.lang_btn.setObjectName("themeBtn")
        self.lang_btn.setFixedSize(38, 38)
        self.lang_btn.clicked.connect(self.toggle_language)

        self.reminder_btn = QPushButton("🔔")
        self.reminder_btn.setObjectName("themeBtn")
        self.reminder_btn.setFixedSize(38, 38)
        self.reminder_btn.clicked.connect(self.open_reminder_settings)

        self.finish_month_header_btn = QPushButton("✅ FINISH MONTH")
        self.finish_month_header_btn.setObjectName("navBtn")
        self.finish_month_header_btn.setFixedHeight(38)
        self.finish_month_header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.finish_month_header_btn.clicked.connect(self.finish_month)

        self.reset_month_btn = QPushButton("🔄 RESET MONTH")
        self.reset_month_btn.setObjectName("navBtn")
        self.reset_month_btn.setFixedHeight(38)
        self.reset_month_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_month_btn.clicked.connect(self.reset_month)

        self.review_btn = QPushButton("🔍 Review Missed Days")
        self.review_btn.setObjectName("navBtn")
        self.review_btn.setFixedHeight(38)
        self.review_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_btn.clicked.connect(lambda: self._maybe_review_missed_days(manual=True))

        controls.addWidget(self.prev_btn)
        controls.addWidget(self.month_combo)
        controls.addWidget(QLabel("📅"))
        controls.addWidget(self.year_combo)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.today_btn)
        self.life_btn = QPushButton("🏠 Life OS")
        self.life_btn.setObjectName("navBtn")
        self.life_btn.setFixedHeight(38)
        self.life_btn.clicked.connect(self.show_life_os)
        self.life_btn.setToolTip("Open the Tasks / Life OS workspace")
        controls.addWidget(self.life_btn)
        self.planner_btn = QPushButton("📓 Planner")
        self.planner_btn.setObjectName("navBtn")
        self.planner_btn.setFixedHeight(38)
        self.planner_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.planner_btn.clicked.connect(self.show_planner)
        controls.addWidget(self.planner_btn)
        controls.addSpacing(5)
        controls.addWidget(self.view_toggle_btn)
        controls.addWidget(self.prev_week_btn)
        controls.addWidget(self.week_label)
        controls.addWidget(self.next_week_btn)
        controls.addWidget(self.category_combo)
        controls.addWidget(self.habit_search_edit)
        controls.addStretch()
        controls.addWidget(self.reminder_btn)
        controls.addWidget(self.lang_btn)
        controls.addWidget(self.theme_btn)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        actions.addWidget(self.finish_month_header_btn)
        actions.addWidget(self.reset_month_btn)
        actions.addWidget(self.review_btn)
        layout.addLayout(controls)
        layout.addLayout(actions)
        return header

    def _card(self, title_text):
        frame = QFrame()
        frame.setObjectName("card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        title = QLabel(title_text)
        title.setObjectName("cardTitle")
        v.addWidget(title)
        return frame, v, title

    def _badge(self, icon, title_text, value_text, color):
        frame = QFrame()
        frame.setObjectName("badge")
        h = QHBoxLayout(frame)
        h.setContentsMargins(10, 8, 10, 8)
        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 16))
        text_v = QVBoxLayout()
        text_v.setSpacing(0)
        title_lbl = QLabel(title_text)
        title_lbl.setStyleSheet(f"color:{self.theme()['subtext']}; font-size: 10px; font-weight:600;")
        value_lbl = QLabel(value_text)
        value_lbl.setStyleSheet(f"color:{color}; font-size: 15px; font-weight:800;")
        text_v.addWidget(title_lbl)
        text_v.addWidget(value_lbl)
        h.addWidget(icon_lbl)
        h.addLayout(text_v)
        h.addStretch()
        return frame

    def _build_left_panel(self):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setSpacing(14)
        v.setContentsMargins(0, 0, 6, 0)

        # Card 1: Daily Goal Completion
        card1, l1, self.card1_title = self._card("DAILY GOAL COMPLETION")
        self.gauge_canvas = GaugeCanvas(width=3.2, height=2.3)
        self.gauge_canvas.setMinimumHeight(190)
        self.daily_line_canvas = LineCanvas(width=3.2, height=1.9)
        self.daily_line_canvas.setMinimumHeight(140)
        l1.addWidget(self.gauge_canvas)
        l1.addWidget(self.daily_line_canvas)
        v.addWidget(card1)

        # Card 2: Monthly Habit Breakdown
        card2, l2, self.card2_title = self._card("MONTHLY HABIT BREAKDOWN")
        self.badge_grid = QGridLayout()
        self.badge_grid.setSpacing(8)
        l2.addLayout(self.badge_grid)
        self.trend_canvas = LineCanvas(width=3.2, height=1.6)
        self.trend_canvas.setMinimumHeight(130)
        l2.addWidget(self.trend_canvas)
        v.addWidget(card2)

        # Card 3: Monthly Mood
        card3, l3, self.card3_title = self._card("MONTHLY MOOD")
        mood_row = QHBoxLayout()
        self.mood_pct_labels = {}
        for icon, name in MOODS:
            col = QVBoxLayout()
            icon_lbl = QLabel(icon)
            icon_lbl.setFont(QFont("Segoe UI Emoji", 18))
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl = QLabel(name)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet(f"color:{self.theme()['subtext']}; font-size:10px;")
            col.addWidget(icon_lbl)
            col.addWidget(name_lbl)
            mood_row.addLayout(col)
        l3.addLayout(mood_row)
        self.mood_bar_canvas = BarCanvas(width=3.2, height=1.8)
        self.mood_bar_canvas.setMinimumHeight(150)
        l3.addWidget(self.mood_bar_canvas)
        v.addWidget(card3)

        # Card 4: Weekly Percentage Complete
        card4, l4, self.card4_title = self._card("WEEKLY PERCENTAGE COMPLETE")
        self.weekly_bar_canvas = BarCanvas(width=3.2, height=2.0)
        self.weekly_bar_canvas.setMinimumHeight(160)
        l4.addWidget(self.weekly_bar_canvas)
        v.addWidget(card4)

        # Card 5: All habits ranked (best -> worst), not just the top/bottom one
        card5, l5, self.card5_title = self._card("BEST & WORST HABITS (ALL, RANKED)")
        self.best_badge_holder = QVBoxLayout()
        self.best_badge_holder.setSpacing(4)
        l5.addLayout(self.best_badge_holder)
        v.addWidget(card5)

        # Card 6: Day-by-day progress log for the open month — a running
        # total that grows/shrinks exactly with what you check on each day.
        card6, l6, self.card6_title = self._card("PROGRESS LOG (DAY BY DAY, THIS MONTH)")
        self.progress_table = QTableWidget()
        self.progress_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.progress_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.progress_table.verticalHeader().setVisible(False)
        self.progress_table.setColumnCount(4)
        self.progress_table.setHorizontalHeaderLabels(["Day", "Done", "Cumulative", "Δ vs prev day"])
        self.progress_table.horizontalHeader().setStretchLastSection(True)
        self.progress_table.setFixedHeight(220)
        l6.addWidget(self.progress_table)
        v.addWidget(card6)

        # Card 7: Yearly progress — filled in once months are "finished"
        card7, l7, self.card7_title = self._card("YEARLY PROGRESS")
        self.year_summary_label = QLabel("")
        self.year_summary_label.setWordWrap(True)
        self.year_summary_label.setStyleSheet(f"color:{self.theme()['subtext']}; font-size:11px;")
        l7.addWidget(self.year_summary_label)
        self.year_bar_canvas = BarCanvas(width=3.2, height=1.9)
        self.year_bar_canvas.setMinimumHeight(150)
        l7.addWidget(self.year_bar_canvas)
        self.finish_month_btn = QPushButton("✅ FINISH THIS MONTH")
        self.finish_month_btn.setObjectName("addHabitBtn")
        self.finish_month_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.finish_month_btn.clicked.connect(self.finish_month)
        l7.addWidget(self.finish_month_btn)
        v.addWidget(card7)

        # Card 8: Level & Achievements (gamification) — XP is every
        # completed check-off, ever; badges unlock at all-time best-streak
        # milestones (3, 7, 14, 30... days where every habit was done).
        card8, l8, self.card8_title = self._card("LEVEL & ACHIEVEMENTS")
        self.level_label = QLabel("")
        self.level_label.setStyleSheet(f"color:{self.theme()['accent_teal']}; font-size:13px; font-weight:800;")
        l8.addWidget(self.level_label)
        self.xp_bar = QProgressBar()
        self.xp_bar.setTextVisible(False)
        self.xp_bar.setFixedHeight(10)
        l8.addWidget(self.xp_bar)
        self.badges_row = QHBoxLayout()
        self.badges_row.setSpacing(6)
        badges_wrap = QWidget()
        badges_wrap.setLayout(self.badges_row)
        badges_scroll = QScrollArea()
        badges_scroll.setWidget(badges_wrap)
        badges_scroll.setWidgetResizable(True)
        badges_scroll.setFixedHeight(56)
        badges_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        badges_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        l8.addWidget(badges_scroll)
        v.addWidget(card8)

        v.addStretch()
        return panel

    def _table_headers(self):
        return ([self.tr_("col_num"), self.tr_("col_habits"), self.tr_("col_target")]
                + [str(d) for d in range(1, 32)]
                + [self.tr_("col_total"), self.tr_("col_status")])

    def _build_right_panel(self):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.table = HabitTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.rowsReordered.connect(self.on_rows_reordered)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table.setToolTip("Drag a habit's name to reorder it. Right-click a habit for more options.")

        headers = self._table_headers()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setToolTip("Click a day number to mark all check-type habits done/undone. Right-click a cell to mark it ✕ not done.")
        header.sectionClicked.connect(self._on_day_header_clicked)
        self.table.setColumnWidth(0, 32)
        self.table.setColumnWidth(1, 245)
        self.table.setColumnWidth(2, 105)
        for d in range(31):
            self.table.setColumnWidth(3 + d, 30)
        self.table.setColumnWidth(3 + 31, 55)
        self.table.setColumnWidth(3 + 32, 60)

        v.addWidget(self.table, stretch=1)
        return panel

    # -----------------------------------------------------------------
    # MONTH NAVIGATION
    # -----------------------------------------------------------------
    def go_prev_month(self):
        m, y = self.current_month - 1, self.current_year
        if m < 1:
            m, y = 12, y - 1
        self._set_month_year(y, m)

    def go_next_month(self):
        m, y = self.current_month + 1, self.current_year
        if m > 12:
            m, y = 1, y + 1
        self._set_month_year(y, m)

    def _set_month_year(self, year, month):
        self.current_year, self.current_month = year, month
        self.month_combo.blockSignals(True)
        self.year_combo.blockSignals(True)
        self.month_combo.setCurrentIndex(month - 1)
        self.year_combo.setCurrentText(str(year))
        self.month_combo.blockSignals(False)
        self.year_combo.blockSignals(False)
        self.refresh_all()

    def on_month_year_changed(self):
        month = self.month_combo.currentIndex() + 1
        try:
            year = int(self.year_combo.currentText())
        except ValueError:
            year = self.current_year
        self.current_month, self.current_year = month, year
        self.refresh_all()

    # -----------------------------------------------------------------
    # STATS
    # -----------------------------------------------------------------
    def _active_habits_on(self, habits, day):
        """Habits that existed on a given calendar day."""
        day_str = day.isoformat()
        return [h for h in habits if (h.get("created_at") or day_str) <= day_str]

    def compute_current_streak(self, habits, daily_counts=None):
        if not habits:
            return 0
        if daily_counts is None:
            daily_counts = self.db.get_daily_counts_map()
        today = date.today()
        streak = 0
        d = today
        while True:
            active = self._active_habits_on(habits, d)
            if active and daily_counts.get(d.isoformat(), 0) >= len(active):
                streak += 1
                d -= timedelta(days=1)
            else:
                break
            if streak > 3650:
                break
        return streak

    def compute_best_streak(self, habits, daily_counts=None):
        if not habits:
            return 0
        if daily_counts is None:
            daily_counts = self.db.get_daily_counts_map()
        created_dates = [h.get("created_at") for h in habits if h.get("created_at")]
        if not created_dates:
            return 0
        start = min(date.fromisoformat(x) for x in created_dates)
        end = date.today()
        best = current = 0
        d = start
        while d <= end:
            active = self._active_habits_on(habits, d)
            if active and daily_counts.get(d.isoformat(), 0) >= len(active):
                current += 1
                best = max(best, current)
            else:
                current = 0
            d += timedelta(days=1)
        return best

    def compute_stats(self):
        year, month = self.current_year, self.current_month
        days_in_month = calendar.monthrange(year, month)[1]
        habits = self.db.get_habits()
        if self.category_filter and self.category_filter != "All":
            habits = [h for h in habits if h.get("category") == self.category_filter]
        if self.habit_search:
            q = self.habit_search
            habits = [h for h in habits if q in h.get("name", "").lower() or q in h.get("category", "").lower()]
        logs = self.db.get_month_logs(year, month)
        moods = self.db.get_month_moods(year, month)
        notes = self.db.get_month_notes(year, month)
        total_habits = len(habits)
        today = date.today()
        is_current_month = year == today.year and month == today.month
        is_future_month = (year, month) > (today.year, today.month)
        last_counted_day = 0 if is_future_month else (today.day if is_current_month else days_in_month)

        # A habit only contributes to the denominator after it exists, and
        # future days never count as missed/possible. This fixes inflated
        # monthly percentages for habits created mid-month.
        eligible_by_day = {}
        for day in range(1, days_in_month + 1):
            d = date(year, month, day)
            eligible_by_day[day] = self._active_habits_on(habits, d) if day <= last_counted_day else []

        daily_completion = []
        for day in range(1, days_in_month + 1):
            eligible = eligible_by_day[day]
            done = sum(1 for h in eligible if logs.get((h["id"], day)))
            daily_completion.append(done / len(eligible) * 100 if eligible else 0.0)

        counted_days = last_counted_day
        overall_avg = (sum(daily_completion[:counted_days]) / counted_days) if counted_days else 0

        total_checks = sum(1 for (hid, day), v in logs.items()
                           if v and day <= last_counted_day and any(h["id"] == hid for h in eligible_by_day.get(day, [])))
        possible_checks = sum(len(eligible_by_day[d]) for d in range(1, last_counted_day + 1))
        monthly_completion = (total_checks / possible_checks * 100) if possible_checks else 0

        habit_totals = {}
        for h in habits:
            habit_totals[h["id"]] = sum(1 for day in range(1, last_counted_day + 1)
                                         if h in eligible_by_day.get(day, []) and logs.get((h["id"], day)))

        best_habit = worst_habit = None
        habits_ranked = sorted(habits, key=lambda h: habit_totals.get(h["id"], 0), reverse=True)
        if habits_ranked:
            best_habit = habits_ranked[0]
            worst_habit = habits_ranked[-1]

        cumulative, running = [], 0
        for day in range(1, days_in_month + 1):
            if day <= last_counted_day:
                running += sum(1 for h in eligible_by_day[day] if logs.get((h["id"], day)))
            cumulative.append(running)

        mood_counts = {name: 0 for _, name in MOODS}
        for mtype in moods.values():
            if mtype in mood_counts:
                mood_counts[mtype] += 1
        total_mood_logs = sum(mood_counts.values())
        mood_pct = {k: (v / total_mood_logs * 100 if total_mood_logs else 0) for k, v in mood_counts.items()}

        weeks = []
        start = 1
        while start <= days_in_month:
            end = min(start + 6, days_in_month)
            completed = 0
            possible = 0
            for d in range(start, min(end, last_counted_day) + 1):
                eligible = eligible_by_day[d]
                completed += sum(1 for h in eligible if logs.get((h["id"], d)))
                possible += len(eligible)
            weeks.append(completed / possible * 100 if possible else 0)
            start = end + 1

        daily_counts = self.db.get_daily_counts_map()
        current_streak = self.compute_current_streak(habits, daily_counts)
        best_streak = self.compute_best_streak(habits, daily_counts)

        progress_log = []
        prev_total = 0
        running = 0
        for day in range(1, last_counted_day + 1):
            done_today = sum(1 for h in eligible_by_day[day] if logs.get((h["id"], day)))
            running += done_today
            progress_log.append({
                "day": day, "done": done_today, "total_habits": len(eligible_by_day[day]),
                "cumulative": running, "delta": done_today - prev_total,
            })
            prev_total = done_today

        return {
            "days_in_month": days_in_month, "habits": habits, "logs": logs, "moods": moods,
            "notes": notes, "daily_completion": daily_completion, "overall_avg": overall_avg,
            "monthly_completion": monthly_completion, "habit_totals": habit_totals,
            "best_habit": best_habit, "worst_habit": worst_habit, "habits_ranked": habits_ranked,
            "cumulative": cumulative, "mood_pct": mood_pct, "weeks": weeks,
            "current_streak": current_streak, "best_streak": best_streak,
            "total_checks": total_checks, "progress_log": progress_log,
            "possible_checks": possible_checks, "last_counted_day": last_counted_day,
        }

    # -----------------------------------------------------------------
    # REFRESH / RENDER
    # -----------------------------------------------------------------
    def refresh_all(self):
        stats = self.compute_stats()
        t = self.theme()

        days = list(range(1, stats["days_in_month"] + 1))
        self.gauge_canvas.plot(stats["overall_avg"], t)
        self.daily_line_canvas.plot(days, stats["daily_completion"], t, ymax=100)
        self.trend_canvas.plot(days, stats["cumulative"], t, ymax=150, step=5)

        self._render_badges(stats, t)

        mood_labels = [name for _, name in MOODS]
        mood_values = [stats["mood_pct"][name] for name in mood_labels]
        mood_colors = [t["accent_green"], t["accent_teal"], t["accent_blue"], t["accent_yellow"], t["accent_orange"]]
        self.mood_bar_canvas.plot(mood_labels, mood_values, t, colors=mood_colors)

        week_labels = [f"Week {i+1}" for i in range(len(stats["weeks"]))]
        self.weekly_bar_canvas.plot(week_labels, stats["weeks"], t, colors=[t["accent_teal"]] * len(stats["weeks"]))

        self._render_best_worst(stats, t)
        self._render_table(stats, t)
        self._render_progress_log(stats, t)
        self._render_year_progress(t)
        self._render_level_card(t)
        self._update_category_filter_options()
        self._update_view_mode_controls()
        self._rebuild_tray_today_menu()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
            elif item.layout():
                self._clear_layout(item.layout())

    def _render_badges(self, stats, t):
        # NOTE: this used to show "Current Streak" twice by mistake (a
        # copy-paste bug) instead of a 4th distinct metric. Fixed to show
        # 4 genuinely different numbers.
        self._clear_layout(self.badge_grid)
        b1 = self._badge("✅", "Monthly Completion", f"{stats['monthly_completion']:.0f}%", t["accent_green"])
        b2 = self._badge("🔥", "Current Streak", f"{stats['current_streak']} days", t["accent_orange"])
        b3 = self._badge("📌", "Checks This Month", f"{stats['total_checks']}", t["accent_blue"])
        b4 = self._badge("🏆", "Total Best Streak", f"{stats['best_streak']} days", t["accent_teal"])
        self.badge_grid.addWidget(b1, 0, 0)
        self.badge_grid.addWidget(b2, 0, 1)
        self.badge_grid.addWidget(b3, 1, 0)
        self.badge_grid.addWidget(b4, 1, 1)

    def _render_best_worst(self, stats, t):
        # Now shows EVERY habit ranked by days-completed this month (not
        # just the single best/worst), so nothing is hidden.
        self._clear_layout(self.best_badge_holder)
        ranked = stats["habits_ranked"]
        days_in_month = stats["days_in_month"]
        if not ranked:
            self.best_badge_holder.addWidget(QLabel("No habits yet."))
            return
        n = len(ranked)
        for i, h in enumerate(ranked):
            total = stats["habit_totals"].get(h["id"], 0)
            pct = (total / days_in_month * 100) if days_in_month else 0
            if i == 0 and total > 0:
                icon, tag, color = "✅", "BEST", t["accent_green"]
            elif i == n - 1 and n > 1:
                icon, tag, color = "⚠️", "WORST", t["danger"]
            else:
                icon, tag, color = h["icon"], f"#{i+1}", t["accent_teal"]
            label = f"{h['icon']} {h['name']} — {total}/{days_in_month} days ({pct:.0f}%)"
            self.best_badge_holder.addWidget(self._badge(icon, tag, label, color))

    def _render_progress_log(self, stats, t):
        """Day-by-day table: how many habits were done that day, the running
        cumulative total for the month, and the change vs the previous day
        (positive = you did more than the day before, negative = less)."""
        log = stats["progress_log"]
        self.progress_table.setRowCount(len(log))
        for row, entry in enumerate(log):
            day_item = QTableWidgetItem(f"Day {entry['day']}")
            day_item.setFlags(day_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            done_item = QTableWidgetItem(f"{entry['done']}/{entry['total_habits']}")
            done_item.setFlags(done_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            done_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            cum_item = QTableWidgetItem(str(entry["cumulative"]))
            cum_item.setFlags(cum_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cum_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            delta = entry["delta"]
            sign = "+" if delta > 0 else ("" if delta == 0 else "")
            delta_item = QTableWidgetItem(f"{sign}{delta}")
            delta_item.setFlags(delta_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            delta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if delta > 0:
                delta_item.setForeground(QColor(t["accent_green"]))
            elif delta < 0:
                delta_item.setForeground(QColor(t["danger"]))

            self.progress_table.setItem(row, 0, day_item)
            self.progress_table.setItem(row, 1, done_item)
            self.progress_table.setItem(row, 2, cum_item)
            self.progress_table.setItem(row, 3, delta_item)
        # Jump to today's row (bottom) so the most recent day is visible.
        if log:
            self.progress_table.scrollToBottom()

    def _render_year_progress(self, t):
        """Shows the months of the current year that have been 'finished'
        with the FINISH THIS MONTH button, so you can watch the year fill
        up month by month instead of only ever seeing one month at a time."""
        year = self.current_year
        summaries = self.db.get_year_summaries(year)
        finished_months = sorted(summaries.keys())
        if finished_months:
            avg = sum(summaries[m]["completion"] for m in finished_months) / len(finished_months)
            self.year_summary_label.setText(
                f"{year}: {len(finished_months)}/12 months finished — "
                f"average completion so far: {avg:.0f}%"
            )
        else:
            self.year_summary_label.setText(
                f"{year}: no months finished yet. Press the button below at the "
                f"end of a month to lock in its results here."
            )
        labels = [calendar.month_abbr[m] for m in range(1, 13)]
        values = [summaries[m]["completion"] if m in summaries else 0 for m in range(1, 13)]
        colors = [t["accent_teal"] if m in summaries else t["off_switch"] for m in range(1, 13)]
        self.year_bar_canvas.plot(labels, values, t, colors=colors)

    def _render_level_card(self, t):
        """Gamification: XP = every completed check-off, ever. Badges
        unlock at all-time best-streak milestones (every habit done on
        the same day, for N days running)."""
        xp = self.db.get_lifetime_xp()
        level, into_level, needed = level_from_xp(xp)
        self.level_label.setText(f"⭐ {self.tr_('xp_label', level=level, xp=into_level, needed=needed)}")
        self.xp_bar.setMaximum(needed)
        self.xp_bar.setValue(into_level)

        best_ever = self.db.get_alltime_best_streak()
        self._clear_layout(self.badges_row)
        for days_needed, icon, label in ACHIEVEMENTS:
            earned = best_ever >= days_needed
            lbl = QLabel(icon)
            lbl.setFont(QFont("Segoe UI Emoji", 20))
            lbl.setToolTip(f"{label} ({days_needed}d)" if earned else f"{label} ({days_needed}d) — locked, best streak so far: {best_ever}d")
            if not earned:
                lbl.setStyleSheet(f"color:{t['off_switch']};")
                effect = QGraphicsOpacityEffect(lbl)
                effect.setOpacity(0.25)
                lbl.setGraphicsEffect(effect)
            self.badges_row.addWidget(lbl)
        self.badges_row.addStretch()

    def finish_month(self):
        """Shows a summary of the currently-open month and asks for
        confirmation BEFORE saving anything or moving forward. Only on
        'Yes' does it get written to the yearly history and does the view
        advance to next month — so nothing is saved by accident."""
        stats = self.compute_stats()
        best = stats["best_habit"]
        worst = stats["worst_habit"]
        month_name = calendar.month_name[self.current_month]

        msg = (
            f"Here's what you did in {month_name} {self.current_year}:\n\n"
            f"Monthly completion: {stats['monthly_completion']:.0f}%\n"
            f"Total habit checks: {stats['total_checks']}\n"
            f"Current streak: {stats['current_streak']} days\n"
            f"Best streak: {stats['best_streak']} days\n"
        )
        if best:
            msg += f"Best habit: {best['icon']} {best['name']} ({stats['habit_totals'][best['id']]} days)\n"
        if worst:
            msg += f"Worst habit: {worst['icon']} {worst['name']} ({stats['habit_totals'][worst['id']]} days)\n"
        msg += "\nSave this and move on to next month?"

        resp = QMessageBox.question(
            self, "Finish This Month?", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return  # nothing saved, nothing changed, still on the same month

        self.db.save_month_summary(
            self.current_year, self.current_month,
            completion=stats["monthly_completion"],
            total_checks=stats["total_checks"],
            best_habit_name=(f"{best['icon']} {best['name']}" if best else None),
            best_habit_total=(stats["habit_totals"].get(best["id"]) if best else None),
            worst_habit_name=(f"{worst['icon']} {worst['name']}" if worst else None),
            worst_habit_total=(stats["habit_totals"].get(worst["id"]) if worst else None),
            current_streak=stats["current_streak"],
            best_streak=stats["best_streak"],
        )
        self.go_next_month()

    def reset_month(self):
        """'Start fresh' — wipes the currently-open month's raw logs/moods
        so you can begin it again from zero. Does NOT touch any month
        that was already saved with FINISH MONTH, and does not affect any
        other month."""
        month_name = calendar.month_name[self.current_month]
        resp = QMessageBox.question(
            self, "Reset This Month?",
            f"This will permanently delete every logged habit and mood entry for "
            f"{month_name} {self.current_year}. Other months (and anything already "
            f"finished) are not affected. This cannot be undone.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self.db.delete_month_logs(self.current_year, self.current_month)
            self.refresh_all()

    # -----------------------------------------------------------------
    # MISSED-DAY REVIEW
    # -----------------------------------------------------------------
    def _find_unreviewed_missed_dates(self):
        """Past days (up to 30 days back) with at least one incomplete
        habit that haven't been reviewed yet.

        BUGFIX: a habit only counts as "missing" on days on/after its own
        created_at. Previously every currently-existing habit was checked
        against every one of the last 30 days regardless of when it was
        added, so a brand-new install (or a freshly added habit) would
        immediately be flagged as having ~30 days of missed habits it
        never had the chance to do."""
        today = date.today()
        window_start = today - timedelta(days=30)
        reviewed = self.db.get_all_reviewed_dates()
        habits = self.db.get_habits()
        result = []
        d = window_start
        while d < today:
            date_str = d.isoformat()
            if date_str not in reviewed:
                done_ids = self.db.get_day_logs(date_str)
                missing = [
                    h for h in habits
                    if h["id"] not in done_ids and h.get("created_at", "2000-01-01") <= date_str
                ]
                if missing:
                    result.append((date_str, d, missing))
            d += timedelta(days=1)
        return result

    def _maybe_review_missed_days(self, manual=False):
        missed = self._find_unreviewed_missed_dates()
        if not missed:
            if manual:
                QMessageBox.information(self, "All caught up", "No missed days need review 🎉")
            return
        dlg = ReviewDialog(missed, parent=self)
        if dlg.exec():
            for date_str, habit_id in dlg.get_checked():
                self.db.toggle_log(habit_id, date_str, True)
            for date_str, _, _ in missed:
                self.db.mark_day_reviewed(date_str)
            self.refresh_all()
        # If "Remind Me Later" was pressed, nothing is marked reviewed —
        # those days stay orange ("pending") until reviewed.

    def _render_table(self, stats, t):
        habits = stats["habits"]
        logs = stats["logs"]
        moods = stats["moods"]
        notes = stats["notes"]
        days_in_month = stats["days_in_month"]
        today = date.today()
        reviewed_dates = self.db.get_all_reviewed_dates()
        year, month = self.current_year, self.current_month
        values = self.db.get_month_values(year, month)
        self._last_rendered_habits = habits

        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.clearSpans()

        self.add_row_index = len(habits)
        self.mood_row_index = len(habits) + 1
        self.notes_row_index = len(habits) + 2
        self.table.setRowCount(len(habits) + 3)
        self.table.habit_row_count = len(habits)

        for row, h in enumerate(habits):
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setFlags(num_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, num_item)

            display_name = (h.get("name") or "").strip()
            name_item = QTableWidgetItem(f"{h['icon']}  {display_name or 'Unnamed habit'}")
            name_item.setData(Qt.ItemDataRole.UserRole, h["id"])
            name_item.setForeground(QColor(t["text"]))
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            name_item.setFlags(name_item.flags() | Qt.ItemFlag.ItemIsEditable)
            name_item.setToolTip((h.get("category") or "") + (" • Double-click to rename" if display_name else "Double-click to enter a name"))
            self.table.setItem(row, 1, name_item)

            target_widget = self._build_target_cell(h, t)
            self.table.setCellWidget(row, 2, target_widget)

            total = stats["habit_totals"][h["id"]]
            is_numeric = h.get("habit_type") == "numeric"
            for day in range(1, 32):
                col = self.DAY_COL_OFFSET - 1 + day
                if day <= days_in_month:
                    checked = bool(logs.get((h["id"], day)))
                    this_date = date(year, month, day)
                    if checked or this_date >= today:
                        cell_state = "normal"
                    else:
                        date_str = this_date.isoformat()
                        cell_state = "missed" if date_str in reviewed_dates else "pending"
                    if is_numeric:
                        val = values.get((h["id"], day))
                        cell = ValueDayCell(value=val, success=checked, cell_state=cell_state)
                        cell.clicked.connect(partial(self.on_value_cell_clicked, h["id"], day))
                    else:
                        cell = DayCell(checked=checked, cell_state=cell_state)
                        cell.clicked.connect(partial(self.on_day_toggled, h["id"], day))
                        if cell_state == "missed":
                            cell.setText("✕")
                            cell.setToolTip("Not done — right-click to change status")
                        else:
                            cell.setToolTip("Click = done/undone • Right-click = mark not done")
                        cell.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                        cell.customContextMenuRequested.connect(
                            partial(self._on_day_cell_context_menu, h["id"], day, cell)
                        )
                    if checked and h.get("color"):
                        cell.setStyleSheet(
                            f"QPushButton#dayCell {{ background:{h['color']}; color:white; "
                            f"border:1px solid {h['color']}; font-weight:700; }}"
                        )
                    self.table.setCellWidget(row, col, cell)
                else:
                    self.table.setCellWidget(row, col, QWidget())

            total_item = QTableWidgetItem(str(total))
            total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3 + 31, total_item)

            required = required_for_month(h, days_in_month)
            ok = (not h["target_enabled"]) or (total >= required)
            status_item = QTableWidgetItem("✓" if ok else "✗")
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor(t["accent_green"] if ok else t["danger"]))
            self.table.setItem(row, 3 + 32, status_item)

        # "+ ADD NEW HABIT" row (not draggable / not a drop target)
        add_row = self.add_row_index
        self.table.setSpan(add_row, 0, 1, 3)
        add_item = QTableWidgetItem(self.tr_("add_new_habit"))
        add_item.setFlags((add_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                           & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled)
        add_item.setForeground(QColor(t["accent_teal"]))
        font = QFont()
        font.setBold(True)
        add_item.setFont(font)
        self.table.setItem(add_row, 0, add_item)

        # "DAILY MOOD TRACKER" footer row (not draggable / not a drop target)
        mood_row = self.mood_row_index
        self.table.setSpan(mood_row, 0, 1, 3)
        mood_label_item = QTableWidgetItem(self.tr_("mood_tracker_row"))
        mood_label_item.setFlags((mood_label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                                  & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled)
        font2 = QFont()
        font2.setBold(True)
        mood_label_item.setFont(font2)
        self.table.setItem(mood_row, 0, mood_label_item)

        for day in range(1, 32):
            col = self.DAY_COL_OFFSET - 1 + day
            if day <= days_in_month:
                combo = QComboBox()
                combo.addItems(MOOD_COMBO_ITEMS)
                current_mood = moods.get(day)
                if current_mood:
                    for i, (_, name) in enumerate(MOODS):
                        if name == current_mood:
                            combo.setCurrentIndex(i + 1)
                            break
                combo.currentIndexChanged.connect(partial(self.on_mood_changed, day))
                self.table.setCellWidget(mood_row, col, combo)
            else:
                self.table.setCellWidget(mood_row, col, QWidget())

        # "DAILY NOTE" footer row (not draggable / not a drop target)
        notes_row = self.notes_row_index
        self.table.setSpan(notes_row, 0, 1, 3)
        notes_label_item = QTableWidgetItem(self.tr_("notes_row"))
        notes_label_item.setFlags((notes_label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                                   & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled)
        font3 = QFont()
        font3.setBold(True)
        notes_label_item.setFont(font3)
        self.table.setItem(notes_row, 0, notes_label_item)

        for day in range(1, 32):
            col = self.DAY_COL_OFFSET - 1 + day
            if day <= days_in_month:
                note_text = notes.get(day, "")
                btn = QPushButton("📝" if note_text else "＋")
                btn.setObjectName("dayCell")
                btn.setFixedSize(28, 28)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                if note_text:
                    btn.setToolTip(note_text)
                btn.clicked.connect(partial(self.on_note_cell_clicked, day))
                self.table.setCellWidget(notes_row, col, btn)
            else:
                self.table.setCellWidget(notes_row, col, QWidget())

        self._apply_week_view_visibility(days_in_month)
        self.table.blockSignals(False)

    def _apply_week_view_visibility(self, days_in_month):
        """In week mode, hides every day column outside the currently
        selected 7-day chunk so the grid narrows down to just that week.
        In month mode, every day column is shown."""
        if self.view_mode == "week":
            chunks = self._week_chunks()
            idx = min(self.week_offset, len(chunks) - 1) if chunks else 0
            start, end = chunks[idx] if chunks else (1, days_in_month)
        else:
            start, end = 1, days_in_month
        for day in range(1, 32):
            col = self.DAY_COL_OFFSET - 1 + day
            visible = day <= days_in_month and start <= day <= end
            self.table.setColumnHidden(col, not visible)

    def _build_target_cell(self, habit, t):
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(2)
        toggle = ToggleSwitch(checked=habit["target_enabled"], theme=t)
        toggle.toggled.connect(partial(self.on_target_toggled, habit["id"]))
        toggle_row = QHBoxLayout()
        toggle_row.addStretch()
        toggle_row.addWidget(toggle)
        toggle_row.addStretch()

        value_lbl = ClickableLabel(target_label(habit))
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_lbl.setStyleSheet(f"color:{t['subtext']}; font-size:10px;")
        value_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        value_lbl.setToolTip("Click to edit this habit's type, unit, and target")
        value_lbl.clicked.connect(partial(self.on_target_value_clicked, habit["id"]))

        v.addLayout(toggle_row)
        v.addWidget(value_lbl)
        return container

    # -----------------------------------------------------------------
    # EVENT HANDLERS
    # -----------------------------------------------------------------
    def on_day_toggled(self, habit_id, day, checked):
        date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
        self.db.toggle_log(habit_id, date_str, checked)
        self.refresh_all()
        if checked:
            self._maybe_celebrate_day(date_str)

    def _on_day_cell_context_menu(self, habit_id, day, cell, pos):
        """Quick status menu for a habit day. Right-click lets the user
        explicitly mark a task as not done (✕), including for today,
        without pretending it was completed.
        """
        date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
        target_date = date(self.current_year, self.current_month, day)
        if target_date > date.today():
            return

        menu = QMenu(self)
        done_action = menu.addAction("✓ Mark as done")
        missed_action = menu.addAction("✕ Mark as not done")
        menu.addSeparator()
        clear_action = menu.addAction("↺ Clear status")
        chosen = menu.exec(cell.mapToGlobal(pos))
        if chosen == done_action:
            self.db.toggle_log(habit_id, date_str, True)
            self.refresh_all()
            self._maybe_celebrate_day(date_str)
        elif chosen == missed_action:
            self.db.toggle_log(habit_id, date_str, False)
            self.db.mark_day_reviewed(date_str)
            self.refresh_all()
        elif chosen == clear_action:
            self.db.toggle_log(habit_id, date_str, False)
            # Removing a review is intentionally not exposed here because
            # review state is shared by the day; clearing the task simply
            # returns it to the normal/pending state on the next refresh.
            self.refresh_all()

    def _on_day_header_clicked(self, col):
        """Clicking a day-number column header marks every check-type
        habit done for that day in one go (or undone, if they're all
        already done) — numeric/negative habits are skipped since they
        need an actual value, not just a checkmark."""
        day = col - self.DAY_COL_OFFSET + 1
        days_in_month = calendar.monthrange(self.current_year, self.current_month)[1]
        if not (1 <= day <= days_in_month):
            return
        habits = self.db.get_habits()
        check_habits = [h for h in habits if h.get("habit_type") != "numeric"]
        if not check_habits:
            return
        logs = self.db.get_month_logs(self.current_year, self.current_month)
        all_done = all(logs.get((h["id"], day)) for h in check_habits)
        new_state = not all_done
        date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
        for h in check_habits:
            self.db.toggle_log(h["id"], date_str, new_state)
        self.refresh_all()
        if new_state:
            self._maybe_celebrate_day(date_str)

    def on_value_cell_clicked(self, habit_id, day, *_args):
        """Numeric/negative habit day cell was clicked — ask for the day's
        number instead of just toggling a checkmark."""
        habits = {h["id"]: h for h in self.db.get_habits()}
        habit = habits[habit_id]
        date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
        current = self.db.get_month_values(self.current_year, self.current_month).get((habit_id, day))
        unit = f" ({habit['unit']})" if habit["unit"] else ""
        goal_hint = ""
        if habit["daily_goal"] is not None:
            arrow = "at most" if habit["direction"] == "max" else "at least"
            goal_hint = f" — goal: {arrow} {habit['daily_goal']:g}"
        value, ok = QInputDialog.getDouble(
            self, habit["name"], f"Value for {date(self.current_year, self.current_month, day):%d %b}{unit}{goal_hint}:",
            current if current is not None else (habit["daily_goal"] or 0), 0, 1000000, 1
        )
        if not ok:
            return
        completed = numeric_meets_goal(value, habit["daily_goal"], habit["direction"])
        self.db.set_numeric_value(habit_id, date_str, value, completed)
        self.refresh_all()
        if completed:
            self._maybe_celebrate_day(date_str)

    def on_target_toggled(self, habit_id, enabled):
        self.db.set_target_enabled(habit_id, enabled)
        self.refresh_all()

    def on_target_value_clicked(self, habit_id):
        habits = {h["id"]: h for h in self.db.get_habits()}
        habit = habits[habit_id]
        dlg = HabitEditDialog(existing=habit, parent=self, categories=self.db.get_all_categories())
        if dlg.exec():
            v = dlg.get_values()
            self.db.update_habit_config(
                habit_id, name=v["name"], icon=v["icon"],
                target_enabled=v["target_enabled"], target_value=v["target_value"],
                habit_type=v["habit_type"], direction=v["direction"],
                period=v["period"], unit=v["unit"], daily_goal=v["daily_goal"],
                color=v["color"], category=v["category"],
            )
            self.refresh_all()

    def on_delete_habit_requested(self, habit_id, habit_name):
        resp = QMessageBox.question(
            self, self.tr_("delete_habit_title"),
            self.tr_("delete_habit_body", name=habit_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self.db.delete_habit(habit_id)
            self.refresh_all()

    def on_rows_reordered(self, from_row, to_row):
        """Handles a habit row being dragged to a new position in the
        table. We deliberately ignore Qt's own row-move handling (cell
        widgets don't follow it reliably) and instead recompute the full
        order ourselves, persist it, then rebuild the table from scratch."""
        habits = getattr(self, "_last_rendered_habits", None) or self.db.get_habits()
        if not (0 <= from_row < len(habits)) or not (0 <= to_row < len(habits)):
            return
        if from_row == to_row:
            return
        ordered_ids = [h["id"] for h in habits]
        moved = ordered_ids.pop(from_row)
        ordered_ids.insert(to_row, moved)
        # Any habit NOT in the currently-filtered view (hidden by the
        # category filter) keeps its relative position by being appended
        # after — display_order among them doesn't matter for those.
        all_ids = [h["id"] for h in self.db.get_habits()]
        hidden_ids = [hid for hid in all_ids if hid not in ordered_ids]
        self.db.reorder_habits(ordered_ids + hidden_ids)
        self.refresh_all()

    def on_mood_changed(self, day, index):
        date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
        if index <= 0:
            self.db.set_mood(date_str, None)
        else:
            mood_name = MOODS[index - 1][1]
            self.db.set_mood(date_str, mood_name)
        self.refresh_all()

    def on_note_cell_clicked(self, day):
        date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
        current = self.db.get_note(date_str)
        pretty_date = f"{date(self.current_year, self.current_month, day):%d %b %Y}"
        text, ok = QInputDialog.getMultiLineText(
            self, self.tr_("note_dialog_title", date=pretty_date),
            self.tr_("note_dialog_label"), current
        )
        if ok:
            self.db.set_note(date_str, text)
            self.refresh_all()

    # -----------------------------------------------------------------
    # CELEBRATION (all habits done for a day)
    # -----------------------------------------------------------------
    def _maybe_celebrate_day(self, date_str):
        habits = self.db.get_habits()
        if not habits or date_str in self._celebrated_dates:
            return
        done_ids = self.db.get_day_logs(date_str)
        if all(h["id"] in done_ids for h in habits):
            self._celebrated_dates.add(date_str)
            self._show_celebration_toast(date_str)

    def _show_celebration_toast(self, date_str):
        QApplication.beep()
        pretty_date = date.fromisoformat(date_str).strftime("%d %b")
        self._show_toast(self.tr_("celebrate_toast", date=pretty_date), self.theme()["accent_green"])

    def _show_toast(self, text, bg_color):
        toast = QLabel(text, self)
        toast.setStyleSheet(
            f"background:{bg_color}; color:white; padding:10px 20px; "
            "border-radius:12px; font-weight:800; font-size:13px;"
        )
        toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toast.adjustSize()
        x = (self.width() - toast.width()) // 2
        toast.move(max(0, x), 78)
        toast.show()
        toast.raise_()
        effect = QGraphicsOpacityEffect(toast)
        toast.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", toast)
        anim.setDuration(2600)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(toast.deleteLater)
        toast._fade_anim = anim  # keep a reference alive until it finishes
        QTimer.singleShot(1200, anim.start)

    def _on_cell_clicked(self, row, column):
        if row == getattr(self, "add_row_index", -1) and column in (0, 1, 2):
            self.add_new_habit()

    def _on_table_context_menu(self, pos):
        row = self.table.indexAt(pos).row()
        habits = getattr(self, "_last_rendered_habits", None) or self.db.get_habits()
        if not (0 <= row < len(habits)):
            return
        habit = habits[row]
        menu = QMenu(self)
        edit_action = menu.addAction(f"✏️  {self.tr_('Edit')} \"{habit['icon']} {habit['name']}\"")
        delete_action = menu.addAction(f"🗑️  {self.tr_('Delete')} \"{habit['icon']} {habit['name']}\"")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == edit_action:
            self.on_target_value_clicked(habit["id"])
        elif chosen == delete_action:
            self.on_delete_habit_requested(habit["id"], f"{habit['icon']} {habit['name']}")

    def _on_item_changed(self, item):
        if item.column() == 1 and item.row() != getattr(self, "add_row_index", -1) \
                and item.row() != getattr(self, "mood_row_index", -1):
            habit_id = item.data(Qt.ItemDataRole.UserRole)
            if habit_id is not None:
                new_text = item.text().strip()
                habit = next((h for h in (self._last_rendered_habits or []) if h["id"] == habit_id), None)
                icon = (habit or {}).get("icon", "⭐")
                # The table displays "emoji + two spaces + name". Strip only
                # the known emoji prefix; never discard the first word of a
                # real task/habit name.
                prefix = f"{icon}  "
                new_name = new_text[len(prefix):].strip() if new_text.startswith(prefix) else new_text
                if new_name and new_name != "Unnamed habit":
                    self.db.rename_habit(habit_id, new_name)
                self.refresh_all()

    def add_new_habit(self):
        dlg = HabitEditDialog(parent=self, categories=self.db.get_all_categories())
        if dlg.exec():
            v = dlg.get_values()
            self.db.add_habit(
                v["name"], icon=v["icon"], target_enabled=v["target_enabled"],
                target_value=v["target_value"], habit_type=v["habit_type"],
                direction=v["direction"], period=v["period"], unit=v["unit"],
                daily_goal=v["daily_goal"], color=v["color"], category=v["category"],
            )
            self.refresh_all()


# =====================================================================
# ENTRY POINT
# =====================================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Habit Tracker")
    window = HabitTrackerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
