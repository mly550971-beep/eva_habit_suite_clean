# EVA — Desktop AI System (Professional Edition v3)

A personal assistant with a two-window graphical interface: it sees through
the camera, listens and speaks, reacts when you raise your hand or smile,
recognizes your face and voice, remembers durable facts about you, and
executes a wide range of real, permission-gated actions on your computer.

## Two windows

1. **Agent View** (main window) — live camera feed, full activity log, and
   diagnostic controls ("Enroll My Face", "Enroll My Voice").
2. **Eva** (small window) — clean daily-use interface: an animated
   equalizer instead of a static dot while Eva speaks, a text box, a "Talk"
   button, and "New Conversation". No transcript shown here on purpose.

Additionally: a **system tray icon** (to show/hide either window or quit)
and a **global hotkey** (default `Ctrl+Space`, works even when no Eva
window is focused) to start a voice command from anywhere.

## Project structure

```
jarvis_pro/
├── main.py              # entry point: launches both windows, tray, hotkey, crash-restart
├── config.yaml           # all settings
├── config.py              # settings loader
├── logger_setup.py         # normal application log
├── audit_log.py             # separate log of every action actually executed
├── brain.py                  # local-model calls, retry, multi-step tool calling, streaming
├── memory.py                  # rolling conversation memory + semantic retrieval
├── profile.py                  # durable facts about the user (separate from memory.py)
├── tools.py                     # auto-discovers tool plugins from plugins/
├── plugins/                      # one file per tool - drop in a new file to add a tool
├── voice.py                       # TTS (+ markdown-to-speech cleanup) + STT
├── wake_word.py                    # wake word ("Eva")
├── gesture.py                       # local hand-raise detection (mediapipe)
├── face.py                           # local face recognition (opencv-contrib)
├── voice_lock.py                      # best-effort voice similarity gate
├── notifier.py                         # desktop notifications wrapper
├── tray.py                              # system tray icon
├── hotkey.py                             # global keyboard shortcut
├── ui.py                                  # AgentWindow + UserWindow
├── requirements.txt
├── .env.example
└── tests/
```

## Running

```bash
pip install -r requirements.txt --break-system-packages
cp .env.example .env      # then put your real key inside .env
python main.py
```

**Important:** `opencv-contrib-python` replaces `opencv-python`. If you
previously had `opencv-python` installed, uninstall it first:
```bash
pip uninstall opencv-python -y
pip install -r requirements.txt --break-system-packages
```

## Everything new in this edition

### Voice quality
- **Markdown-to-speech cleanup**: Eva no longer says "asterisk asterisk" —
  formatting symbols (`**bold**`, `# headers`, `` `code` ``, bullet lists)
  are stripped before text-to-speech, while numbers and normal punctuation
  are spoken naturally.

### Reach and automation (all permission-gated, each with its own on/off switch)
- Open **any** installed application or **any** URL by name (not just a
  fixed list)
- Browser tab control (new tab / close tab) via hotkey to the focused window
- Search directly on a named site (YouTube, Amazon, Wikipedia, etc.)
- Pre-filled WhatsApp messages to saved contacts — **Eva never clicks Send**
- **Media/volume control**: volume up/down, mute, play/pause, next/previous track
- **Screen reading**: takes a screenshot and describes it or answers a
  question about what's currently on screen
- **Reminders**: "remind me in 20 minutes to..." → a real desktop notification
- **Multi-step requests**: a single sentence can now chain several tool
  calls in sequence (e.g. "open YouTube, search for X, then message mom
  about it")

### Awareness
- **Hand-raise detection** (mediapipe, fully local/offline) — Eva checks in
  automatically, no button or wake word needed
- **Face recognition** (opencv-contrib, fully local) — enroll via "Enroll My
  Face" in the Agent View; Eva greets you by name when recognized
- **Optional smile hint** (off by default) — a lightweight, low-confidence
  cue used only to nudge Eva's tone warmer, never a claim about your
  emotional state
- **Long-term facts**: durable preferences ("my home address is...") are
  remembered forever via the `remember_fact` tool, separate from the
  rolling conversation history, and used in every future request

### Safety and reliability
- **Voice lock** (best-effort, NOT secure biometrics): gates a small set of
  sensitive tools (opening arbitrary apps/URLs, tab control, messaging,
  media control) behind a rough voice-similarity check. Enroll via "Enroll
  My Voice" first. Typed text always bypasses this (typing already needs
  physical keyboard access).
- **Separate audit log** (`logs/audit.log`) recording every action Eva
  actually executed, distinct from the normal debug log
- **Toast notification on tool failure**
- **Auto-restart on crash**: if the app crashes unexpectedly it relaunches
  itself automatically (up to 3 times, to avoid an infinite loop if
  something is fundamentally broken)

## Keyboard/mouse control, forget_fact, and the music bar (latest edition)

- **`control_computer`** (permission: `computer_control`, **off by default**) —
  real simulated mouse/keyboard input: move, click, double/right-click, drag,
  scroll, type text, press a single key, or a hotkey combo. This is the
  broadest-reach tool in the app since it affects whatever window currently
  has focus, not just Eva's own windows. It is always gated by voice lock
  when voice lock is enabled, still subject to the hard `blocked_patterns`
  safety net, and `type_text` has a configurable max length
  (`permissions.computer_control.max_type_length`). It still never runs
  shell commands and never deletes/moves files — only simulates input a
  physical keyboard/mouse could also send. Combine it with `read_screen`
  (below) so Eva knows what it's clicking before it clicks.
- **`read_screen`** now folds the recent conversation and known long-term
  facts into its vision prompt, so a follow-up like "what about the button
  next to it?" is answered in context instead of as a cold, disconnected
  screenshot description.
- **`forget_fact`** — removes one previously remembered long-term fact by
  key (say "forget my home address" or edit `data/profile.json` directly).
- **"Now playing" bar**: when `play_music` starts a song, the Eva window
  shows a bottom bar with the song title that slides up automatically and
  slides back down on its own after a few seconds (or dismiss it with ✕).
- **Greeting light-pulse**: the Eva window's border does a brief, soft
  glow pulse timed with the startup greeting.

## Screen-click accuracy fix + locate_on_screen (this edition)

- **The bug**: `read_screen` sends the model a screenshot resized to fit
  its vision input limits, and returns a plain-language description only -
  never coordinates. `control_computer` takes whatever (x, y) it's given
  and sends it straight to pyautogui in real screen-pixel space. Nothing
  converted between "pixel in the resized image" and "pixel on the real
  screen", so any click based on what the model "saw" landed in the wrong
  place - worse on any display using Windows scaling above 100%, since
  screenshots and pyautogui's mouse coordinates can disagree about the
  screen size for an entirely separate, second reason on top of the resize.
- **`locate_on_screen`** (new tool, same `screen_reading` permission as
  `read_screen`) fixes this: it takes its own screenshot, asks the model for
  a pixel position *within that exact image*, then rescales it by
  `real_screen_size / shown_image_size` before returning it. That single
  ratio cancels out both the resize and any DPI mismatch, since both are
  just the same rectangle measured two ways. The model calls this first,
  then passes the returned (x, y) into `control_computer` unchanged - it
  never has to reason about resizing or DPI itself. The system prompt now
  tells it to always do this instead of guessing coordinates from
  `read_screen`'s description.
- Also added `SetProcessDpiAwareness` at startup on Windows
  (`main.py`, best-effort, silently skipped if unavailable) so screenshots
  and mouse coordinates agree on the screen size in the first place - a
  second, independent layer on top of the rescaling above.
- **Sending messages through an already-open app/website (e.g. WhatsApp
  Web in a browser tab)**: the system prompt allows Eva to use
  `locate_on_screen` + `control_computer` to open the right conversation and
  type a message into it, but explicitly tells it to never press Enter or
  click Send there - only the human sends, exactly like
  `send_whatsapp_message`'s own rule. This is enforced by instruction only
  (same as the `remember_fact` safeguard below), not by a hard code gate,
  because `control_computer` is a general-purpose tool that legitimately
  needs to press Enter elsewhere (submitting a search box, for example).
  Treat it as a strong default, not a guarantee - check the chat before
  assuming a message wasn't sent.

## Newest additions

- **`copy_text_from_screen`** (permission: `clipboard_access`, off by
  default) — finds one specific piece of visible text (an email, a code,
  a highlighted line) and copies exactly that to the clipboard.
- **`read_text_aloud`** (permission: `read_aloud`, on by default) — reads
  a piece of text out loud directly, either text already in hand or
  transcribed fresh from the screen (needs `screen_reading` too for that
  case). Capped at `max_chars` per call.
- **`repeat_last_response`** — repeats Eva's last spoken answer, slower
  and a bit louder, for "say that again" moments. Always available.
- **`summarize_conversations`** (permission: `conversation_summary`, on
  by default) — a few bullet points summarizing archived conversations
  from today or the past week.
- **`get_tool_usage_stats`** (permission: `usage_stats`, on by default) —
  reports which tools have actually been used and how often, from real
  counters kept in `data/tool_stats.json`.
- **Periodic internet health-check** (`health_check.interval_minutes`,
  default 30) — runs for the whole session, not just at startup, and only
  notifies when connectivity actually changes state.
- **One-time API-key-problem notification** — if a request fails with
  what looks like an invalid/expired key, a single desktop notification
  fires (not one per failed request) so it's noticed immediately.

## The real scope of `computer_control` (read this before enabling it)

A full security pass over the project turned up something worth stating
plainly rather than leaving implicit: **enabling `computer_control` means
Eva can ultimately do anything a person sitting at the keyboard could do -
including things no other tool in this app is allowed to do.**

- **It can reach a shell.** `hotkey(["win","r"])` opens the Run dialog,
  `type_text("cmd")` + `press_key("enter")` opens a command prompt, and any
  further `type_text(...)` + `press_key("enter")` runs whatever was typed.
  `permission_matrix.blocked_patterns` will catch a call that literally
  contains one of its listed strings (it checks every tool's arguments,
  including `control_computer`'s), but it is a small denylist of specific
  strings, not a sandbox - it cannot enumerate every harmful command, so
  this is a real gap, not a false alarm. This is a direct consequence of
  giving something general keyboard input, not a bug introduced by this
  tool's own code - there is no way to offer real keyboard/mouse control
  and simultaneously guarantee "can never reach a shell", because opening a
  shell is itself just... using the keyboard. If that risk isn't
  acceptable, keep `computer_control` off; voice lock (when enabled) at
  least requires a verified voice before any of this can run.
- **It can also work around `send_whatsapp_message`'s "only the human
  clicks Send" rule** the same way - by opening the chat and pressing Enter
  or clicking Send itself. The system prompt now explicitly forbids this
  (see below), which meaningfully lowers the odds of it happening, but it
  is a prompt-level instruction the model is expected to follow, not a
  technical restriction `control_computer` enforces - the tool has no way
  to know it's "inside a chat app" versus any other window.

Nothing above is fixed in this edition because neither is fixable by
patching this codebase - they're the inherent price of the feature. What IS
new: the system prompt instructs Eva to never press Enter or click Send
after typing into a messaging app on someone's behalf (see
`locate_on_screen` section above), the audit log no longer stores the raw
text of anything typed/sent/remembered (see below), and the emergency-stop
hotkey now tells you if it failed to register instead of only logging it.
None of that closes the gap above - it narrows it. Enable `computer_control`
only if you're comfortable with what's described here.

## Honest limitations (please read before relying on these)

- **Arbitrary shell command execution and file deletion are still NOT
  implemented**, even with `computer_control` enabled — that tool only
  simulates mouse/keyboard *input*, the same things a person sitting at the
  keyboard could do; it does not run commands or touch the filesystem.
  Enabling it is still a real increase in what a misheard voice command
  could click or type into, so it defaults to off and is voice-lock-gated.
- Long-term facts (`remember_fact`) are only ever stored on the model's own
  judgment call — the system prompt tells it to only store what the user
  directly said, not text encountered inside search/screen results, but
  this is a prompt-level safeguard, not a hard technical guarantee. Check
  `data/profile.json` occasionally, and use `forget_fact` (or edit the file)
  to remove anything that looks wrong. It's also capped
  (`long_term_facts.max_facts`, default 300) so it can't grow unbounded.
- **`browser_tab_control` / `control_media`** only send a keyboard shortcut
  to whichever window currently has focus. They cannot target a specific
  app and do nothing useful if the wrong window is focused — a real
  limitation of hotkey automation, not a bug.
- **Voice lock is NOT secure biometrics.** It's a rough MFCC-similarity
  check that can be fooled by a recording and can reject the real user in
  noisy conditions. Treat it as a basic deterrent, not a security guarantee.
- **Face recognition** uses OpenCV's classic LBPH algorithm (fast, fully
  local, no downloads) rather than a deep-learning model — good enough for
  "who's in front of the camera" in consistent lighting, not
  forensic-grade.
- **The smile/mood hint** is a simple Haar-cascade heuristic, easily wrong,
  and only ever nudges tone — it is never used to make claims about how you
  feel.
- **Reminders only fire while the app is running** (no OS-level background
  service).
- **The global hotkey** may require running the terminal/VS Code as
  Administrator on Windows for the `keyboard` library's global hook to work.
- **The "never press Enter/Send in WhatsApp Web" rule is a system-prompt
  instruction, not a hard code restriction** - see above. `computer_control`
  being enabled at all means a misclick or a misunderstood instruction could
  still send something unintended; this rule lowers that risk, it doesn't
  remove it.
- **`permissions.messaging.contacts` ships with placeholder numbers** -
  `send_whatsapp_message` will not work (and the `wa.me` link will be
  invalid) until you replace them with real numbers in config.yaml.
- **The emergency-stop hotkey (default Ctrl+Alt+K) now notifies you if it
  fails to register** (missing `keyboard` library, no admin rights on
  Windows, etc.) instead of only writing a warning to `logs/eva.log`.
  Previously this failed silently from the user's point of view.
- **The audit log (`logs/audit.log`) no longer stores raw free-text
  content** - `text`/`message`/`value`/`note` arguments (typed text,
  message bodies, remembered facts) are replaced with a
  `<redacted, N chars>` placeholder, and `remember_fact`'s result line is
  redacted too, since it used to echo the stored value back. This matters
  more now that `control_computer` can type anything into any field,
  including a password someone dictates into a login form - previously
  that would have landed in plain text in a log file that outlives log
  rotation. Tool names, actions, coordinates, and contact names are still
  logged in full - only free-text content is redacted.
- **`set_reminder` is now capped**: `permissions.reminders.max_minutes`
  (default 43200, i.e. 30 days) and `permissions.reminders.max_active`
  (default 20 pending at once) - previously neither had a limit.
- **`log_mood`'s storage path is now routed through `config.yaml`
  (`mood.file`)** like every other data file, instead of being a hardcoded
  `"data/mood_log.json"` relative to whatever the current working directory
  happened to be - the old version could silently write its data somewhere
  unexpected if launched from a different directory (e.g. after packaging
  into an .exe with PyInstaller).
- **`get_weather`'s in-memory cache is now lock-protected** - a harmless
  but real race existed where two near-simultaneous weather requests could
  both miss the cache and both hit the network, or one could read a value
  mid-write. Low impact (an extra request, not corruption), same class of
  issue as the `memory.py` fix from the previous edition.

## Permission reference (config.yaml → permissions)

| Permission | What it does | Real-world reach |
|---|---|---|
| `datetime` | tells the time/date | none |
| `web_search` | opens a Google search | opens browser only |
| `open_apps` | opens a whitelisted app | fixed list you define |
| `open_websites` | opens a whitelisted site | fixed list you define |
| `open_any_app` | opens **any** named app | broad — opens only |
| `open_any_url` | opens **any** URL | broad — opens only |
| `browser_tab_control` | Ctrl+T / Ctrl+W hotkey | only the focused window |
| `site_search` | searches directly on a named site | opens browser only |
| `messaging` | pre-fills a WhatsApp message | **never sends automatically** |
| `media_control` | volume/play/pause/track hotkeys | only the focused window |
| `screen_reading` | screenshots + describes/discusses the screen | read-only |
| `computer_control` | real mouse/keyboard input (click, type, scroll, hotkeys) | **broadest** — affects whatever window has focus, off by default |
| `clipboard_access` | copies found text to the clipboard | overwrites current clipboard contents, off by default |
| `read_aloud` | speaks arbitrary text (on-screen or supplied) out loud | sound only, on by default |
| `conversation_summary` | summarizes archived conversations | read-only, on by default |
| `usage_stats` | reports tool usage counts | read-only, on by default |
| `reminders` | schedules a desktop notification | in-process only |

## Setting up the "aware" features

- **Face recognition**: set `face_recognition.enabled: true`, launch the
  app, click **Enroll My Face** in the Agent View, look at the camera for a
  few seconds. Rename yourself by editing `data/face_labels.json` (the
  default enrolled name is `"user"`).
- **Voice lock**: click **Enroll My Voice** and say a phrase, *then* set
  `voice_lock.enabled: true`. If you enable it before enrolling, every
  sensitive command will be refused.
- **Hand-raise sensitivity**: `gesture.raise_hand_zone_ratio` (smaller =
  must raise your hand higher) and `gesture.cooldown_seconds`.

## Turning the project into an executable (optional)

```bash
pip install pyinstaller --break-system-packages
pyinstaller --noconfirm --onefile --windowed --add-data "config.yaml:." main.py
```
Copy `.env`, `config.yaml`, `models/`, and `data/` next to the executable.

## Other notes

- `PyAudio` sometimes needs `portaudio` installed at the OS level first.
- `mediapipe`, `librosa`, and `opencv-contrib-python` can each take a
  minute to install the first time; if any are missing, the corresponding
  feature is simply disabled instead of crashing the app.
- Requires **Python 3.9 or newer** (`from __future__ import annotations` is
  used so modern type hints work even on 3.9).
