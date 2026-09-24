"""
self_improve_scanner.py
------------------------
Background, PROPOSE-ONLY self-review. On a timer (while Eva is running),
asks the local model to look over Eva's own code for concrete bugs or
security weaknesses, and - if it finds any - writes them to
data/self_improvement_proposals.md and shows a desktop notification.

It NEVER applies anything itself. Applying a proposal still goes through
the exact same backup + pytest + auto-rollback path as the manual
self_improve tool, and only after you explicitly approve one (see
plugins/self_review_tool.py: list_improvement_proposals /
apply_improvement_proposal). This split exists on purpose: self_improve
can touch Eva's own permission and security-gating code, so an
unattended background job should be able to notice and describe a
problem, but never be the thing that decides on its own to change that
code while nobody's watching.

Turned off by default - see permissions.self_improve_scan in
config.yaml.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from notifier import notify

_SCAN_PROMPT = """You are reviewing EVA's own source code for concrete, real problems only:
bugs, security weaknesses (missing input validation, unsafe paths, a
permission gated more loosely than it should be, etc.), or clear
reliability issues. Do NOT propose style preferences, refactors, or
anything speculative - only things you can point at as actually wrong.
Do NOT repeat anything in the "already known" list below; if everything
you'd otherwise flag is already there, that's fine, propose nothing new.

Already known (do not repeat these):
{known}

Project snapshot:
{manifest}

Respond with ONLY a JSON array (no prose, no markdown fence). Each item:
{{"title": "short title", "description": "1-3 sentences: what's wrong and why it matters", "goal": "a specific, actionable goal for a coding agent to fix ONLY this"}}
If you find nothing concrete and new, respond with exactly: []
"""


class SelfImproveScanner:
    def __init__(self, config, logger, brain):
        self.config = config
        self.logger = logger
        self.brain = brain
        self.root = Path(__file__).resolve().parent
        self.proposals_file = self.root / "data" / "self_improvement_proposals.md"
        self.log_file = self.root / "data" / "self_improvement_log.md"
        self._timer = None
        self._stopped = False
        self._interval_seconds = 6 * 3600

    def start(self):
        if not self.config.get("permissions", "self_improve_scan", "enabled", default=False):
            return
        interval_hours = float(self.config.get("permissions", "self_improve_scan", "interval_hours", default=6))
        self._interval_seconds = max(interval_hours, 0.25) * 3600
        # First scan happens a couple of minutes after startup, not
        # instantly - so it never competes with the model for GPU/CPU
        # during the boot sequence or an already-in-progress conversation.
        self._schedule_next(delay=120)
        self.logger.info(
            f"[SelfImproveScanner] Background self-review scan enabled, every {interval_hours}h."
        )

    def stop(self):
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()

    def _schedule_next(self, delay=None):
        if self._stopped:
            return
        self._timer = threading.Timer(
            delay if delay is not None else self._interval_seconds, self._run_scan
        )
        self._timer.daemon = True
        self._timer.start()

    def _run_scan(self):
        try:
            self._scan_once()
        except Exception as e:
            self.logger.warning(f"[SelfImproveScanner] scan failed: {e}")
        finally:
            self._schedule_next()

    def _scan_once(self):
        files = []
        for p in self.root.rglob("*.py"):
            if any(part in {".venv", "venv", "__pycache__", "logs"} for part in p.parts):
                continue
            files.append(p)
        files = files[:120]
        manifest = []
        for p in files:
            try:
                text = p.read_text(encoding="utf-8")
                # Smaller per-file cap than the manual self_improve tool -
                # this runs unattended and periodically, so keep each scan
                # cheap rather than feeding the full codebase every time.
                manifest.append(f"FILE: {p.relative_to(self.root)}\n{text[:6000]}")
            except Exception:
                pass

        known_titles = self._known_titles()
        prompt = _SCAN_PROMPT.format(
            known="\n".join(f"- {t}" for t in sorted(known_titles)) or "(none)",
            manifest="\n".join(manifest),
        )
        raw = self.brain.generate_developer_text(prompt, temperature=0.0)
        items = self._parse_items(raw)
        new_items = [
            it for it in items
            if (it.get("title") or "").strip().lower() not in known_titles
        ]
        if not new_items:
            return

        self._append_proposals(new_items)
        notify(
            "Eva - possible improvements found",
            f"Found {len(new_items)} potential fix(es) in Eva's own code, waiting for your "
            f"review. Ask Eva what she found, or check data/self_improvement_proposals.md.",
            self.logger,
        )

    def _known_titles(self) -> set:
        titles = set()
        for f in (self.proposals_file, self.log_file):
            if not f.exists():
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                m = re.search(r"title:\s*(.+?)\s*(\||$)", line, re.I)
                if m:
                    titles.add(m.group(1).strip().lower())
        return titles

    def _parse_items(self, raw: str):
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
        return [d for d in data if isinstance(d, dict) and (d.get("goal") or "").strip()]

    def _append_proposals(self, items):
        self.proposals_file.parent.mkdir(parents=True, exist_ok=True)
        next_id = self._next_id()
        with self.proposals_file.open("a", encoding="utf-8") as f:
            for it in items:
                title = (it.get("title") or "").strip().replace("|", "/")
                description = (it.get("description") or "").strip().replace("|", "/")
                goal = (it.get("goal") or "").strip().replace("|", "/")
                f.write(
                    f"- id: {next_id} | status: pending | title: {title} | "
                    f"description: {description} | goal: {goal}\n"
                )
                next_id += 1

    def _next_id(self) -> int:
        if not self.proposals_file.exists():
            return 1
        max_id = 0
        for line in self.proposals_file.read_text(encoding="utf-8").splitlines():
            m = re.search(r"id:\s*(\d+)", line)
            if m:
                max_id = max(max_id, int(m.group(1)))
        return max_id + 1
