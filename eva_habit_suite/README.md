# Eva + Habit Tracker — merged project

This folder contains both apps side by side, wired so Eva can read/write
your habits directly, plus one launcher to start both together.

```
eva_habit_suite/
├── eva/                  # Eva assistant (unchanged, except config.yaml below)
│   └── config.yaml       # integrations.habit_tracker now enabled + pointed
│                         # at ../habit_tracker/habit_tracker.db
├── habit_tracker/        # Habit Tracker app (unchanged)
├── requirements.txt      # union of both apps' requirements
├── run_both.py           # starts both apps together, stop both with Ctrl+C
└── start_both.bat        # double-click launcher for Windows
```

## Why two folders instead of one merged codebase

Eva's window is built with Tkinter/customtkinter; Habit Tracker's window
is built with PyQt6. Two GUI toolkits can't share one process's event
loop, so they have to stay two separate running programs — that part
can't be merged. What *is* merged:

- **One project folder**, one `requirements.txt`, one command to start both.
- **One shared database.** Eva's `habit_tracker` tool (see
  `eva/plugins/habit_tracker_tool.py`) talks straight to
  `habit_tracker/habit_tracker.db` — the exact file the Habit Tracker
  window reads and writes. Anything Eva does (mark a habit done, add a
  new one, list today's status) shows up in the Habit Tracker window's
  own auto-refresh within a couple of seconds, and there's nothing kept
  separately "inside" Eva.

## One-time setup

```bash
python -m venv venv
# Windows: venv\Scripts\activate    |   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt --break-system-packages

cd eva
cp .env.example .env      # put your real key(s) inside .env if needed
cd ..
```

If you're using the local Ollama model (see `eva/LOCAL_SETUP.md`), also
run `eva/install_local_model.bat` once, or `ollama pull gemma4:e2b` and
`ollama pull embeddinggemma` manually.

## Running both together

```bash
python run_both.py
```

or on Windows, just double-click `start_both.bat`.

This starts Habit Tracker first (so `habit_tracker.db` exists), waits a
moment, then starts Eva. Two normal windows open, exactly as if you'd run
each app on its own. Press **Ctrl+C** in the terminal to close both, or
just close each window as usual.

Running each one manually still works too, if you ever want just one of
them:

```bash
cd habit_tracker && python main.py
cd eva && python main.py
```

## Talking to your habits through Eva

Once both have been run at least once (so the database and its tables
exist), ask Eva things like:

- "Open Habit Tracker" → launches the window directly (a plain subprocess
  of `habit_tracker/main.py`, nothing routed through Eva's generic
  open-any-app permission/allow-list, so no extra prompt).
- "What habits do I have left today?"
- "Mark reading as done"
- "I drank 3 glasses of water" (numeric habits)
- "Add a new habit called Stretching"
- "Open Habit Tracker and mark reading as done" → opens the window, then
  checks the habit off in the same reply; the window ticks it on its own
  within ~2 seconds (its built-in auto-refresh), so you watch it happen
  live instead of having to switch windows and refresh yourself.

One limitation worth knowing: Eva only knows it already opened Habit
Tracker if it was Eva that launched it (tracked in memory for that
session). If you opened Habit Tracker yourself, or via `run_both.py`,
and then ask Eva to open it too, she can't see that it's already running
and will start a second window - harmless (both talk to the same
database safely) but you'll get two windows instead of one.

This is already turned on in `eva/config.yaml`:

```yaml
integrations:
  habit_tracker:
    enabled: true
    db_path: "../habit_tracker/habit_tracker.db"
```

That relative path only resolves correctly when Eva is launched with the
`eva/` folder as its working directory — both `run_both.py` and running
`python main.py` from inside `eva/` do this correctly. If you ever move
either folder so they're no longer siblings, update `db_path` to the new
location (an absolute path always works too).

## Self-improving code (already built into this project)

Eva already ships with a `self_improve` tool (`eva/plugins/self_improve_tool.py`,
enabled by default via `permissions.self_improve.enabled`). It:

- Reads Eva's own `.py`/`.yaml`/`.yml` files, asks the model for one
  focused unified diff for a stated goal (a bug, a security gap, a
  reliability issue).
- Rejects anything outside `.py`/`.yaml`/`.yml`/`.md`, any file deletion,
  and anything touching credentials, logs, `data/memory.json`, or
  sessions.
- Backs up every touched file before applying, runs the test suite, and
  automatically rolls back if tests fail.

Two things were added on top of the existing tool so you don't have to
re-explain this capability every conversation, and so it actually
improves rather than repeating itself:

1. **Standing awareness.** `eva/config.yaml`'s `system_instruction` now
   tells Eva plainly, every single turn, that reviewing/fixing her own
   code is a normal ability she has - so if she notices a real bug or
   security weakness while working on something, she should say so and
   call `self_improve` herself, instead of waiting for you to remind her
   she's allowed to.
2. **A running memory of past fixes.** Every successful patch now appends
   one line to `eva/data/self_improvement_log.md` (goal, files changed,
   backup location). The tool feeds the recent tail of that log back into
   its own prompt on every future call, so it builds on what it already
   fixed instead of re-discovering (and re-announcing) the same issue.
   That log lives under `data/`, which the patch-safety check already
   blocks patches from touching - so self_improve can't edit its own
   history.

Worth knowing: this doesn't retrain the underlying model or change how it
reasons - it's the *codebase* that improves over successive calls, not
the model's judgment itself. Nothing here is fully unsupervised either:
every change still needs the test suite to pass, keeps a backup, and
never touches credentials/logs/memory. Since this tool can modify Eva's
own permission and security-gating code, it's worth glancing over
`data/self_improvement_log.md` and the diffs under `data/improvements/`
occasionally rather than assuming every change was harmless.

## Background self-review (propose-only, off by default)

On top of the manual `self_improve` tool above, there's now a background
scanner (`eva/self_improve_scanner.py`) that can periodically look over
Eva's own code on its own - without you asking - but it only ever
**proposes**, never applies:

- Turned off by default. Turn it on in `eva/config.yaml`:
  ```yaml
  permissions:
    self_improve_scan:
      enabled: true
      interval_hours: 6   # how often it scans while Eva is running
  ```
- Each scan writes any real findings to
  `eva/data/self_improvement_proposals.md` and shows a desktop
  notification - nothing is changed yet.
- Ask Eva "what did you find?" (or similar) and she'll list pending
  proposals (`list_improvement_proposals`).
- Only once you say yes to a specific one does she apply it
  (`apply_improvement_proposal`), through the exact same backup + test +
  auto-rollback path as a manual request - never automatically, and
  never more than the one proposal you approved.

Why split it this way rather than have it fix things on its own: this
tool can modify Eva's own permission and security-gating code, so the
unattended part (finding things) is low-risk, but the part that actually
changes code stays behind your explicit approval every time.

## One-click launch (no VS Code needed)

Run `create_desktop_shortcut.ps1` once (double-click it, or if Windows
blocks it: right-click -> Run with PowerShell, or run
`powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1`
from inside this folder). It adds an **"Eva + Habit Tracker"** icon to
your Desktop - using the custom `icon.ico` in this folder instead of a
plain Python file icon - that runs `start_both.bat` when you double-click
it. After that, starting everything is just that one icon; you don't
need to open the project in VS Code and hit Run.

## Adhan, prayer times, Quran, and extra reminders

Two more feature packages are merged in on top of everything above:
adhan/prayer-times/scheduler, and extras (water/eye-rest/habit/weather
reminders, Downloads organizer, Do-Not-Disturb, Pomodoro). Both are fully
wired in - `apply_ui_patch.py` has already been run against `ui.py`
(starts/stops the scheduler with Eva, and the emergency-stop hotkey also
stops the adhan), and `offline_commands.py` now calls `media_router.py`
on every request so these are handled instantly, without asking the
model to pick a tool.

**Voice/text commands:**
```
مواعيد الصلاة النهاردة | امتي اذان العصر | الصلاة الجايه امتي
شغل الاذان | وقف الاذان                      (only while it's playing)
شغل سورة الكهف بصوت السديس | اقرا يس | شغل آية الكرسي
متزعجنيش | متزعجنيش 3 ساعات | زعجني تاني
ابدأ بومودورو | ابدأ بومودورو 6 | وقف بومودورو | فاضل قد ايه
رتب التنزيلات
```

**Config** (all in `eva/config.yaml`, already filled in with sensible
defaults - see the comments next to each block): `prayer_times` (defaults
to Asyut, Egypt - change `city`/`country`), `adhan`, `scheduler.friday_reminder`,
`water_reminder`, `eye_rest_reminder`, `habit_reminder` (uses the same
`integrations.habit_tracker.db_path` the habit tools use - already set),
`weather_alert`, `downloads_organizer` (off by default), `do_not_disturb`,
`pomodoro`.

For a fully offline adhan (no internet/YouTube needed), drop an mp3 at
`eva/data/adhan/adhan.mp3` (used for every prayer) and optionally
`eva/data/adhan/adhan_fajr.mp3` (Fajr only). Without internet, prayer
times still work from a built-in astronomical calculation, so the adhan
and reminders never silently stop working.

Do-Not-Disturb and a Pomodoro focus phase silence the extra reminders,
but **never** the adhan - prayer time isn't something a "leave me alone"
mode should suppress.

**Two files had to be reconstructed.** `media_router.py` imports
`web_helpers.py` and calls `plugins/quran_tool.py`, and neither file was
included in either uploaded package - their own text even says the
`media_router.py` they shipped "already includes everything from the two
previous packages," implying an earlier "media/Quran fix" package (not
uploaded this time) originally supplied them. Rather than ship a broken
import, both were rebuilt from scratch to match exactly how `media_router.py`
calls them:
- `eva/web_helpers.py` - Arabic text normalization, search-URL builders
  for Google/YouTube/a dozen common sites, and a best-effort "open the
  first real YouTube result directly" lookup (pure stdlib, no API key;
  falls back to opening the search page on any failure, never raises).
- `eva/plugins/quran_tool.py` - all 114 surah names, a handful of
  well-known reciters, and play/read handling. To avoid guessing at a
  specific Quran-audio CDN's reciter/server IDs (wrong ones would
  silently play the wrong thing with no error), "play" reuses the exact
  same YouTube-search mechanism as every other "play X" command, and
  "read" opens the matching chapter on quran.com - a plain, stable URL,
  no audio CDN involved.

If you have the original package these came from, it's worth sending it
over so your exact versions can be used instead of these rebuilt ones.

A real, pre-existing bug turned up while testing the merge: the shipped
`tests/test_scheduler.py` hardcoded a fixed date (`2026-09-20`) as "a
recent day" for the prayer-times cache test, but `_save_cache()`'s 3-day
retention window is relative to the real *today* - so the test was
already silently failing by the time this was merged. Fixed by computing
that date relative to `date.today()` instead; all 49 tests across the
whole project (`python -m unittest discover -s tests`) pass now.
