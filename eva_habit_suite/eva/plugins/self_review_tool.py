"""
plugins/self_review_tool.py
----------------------------
Conversational front-end for the background scanner in
self_improve_scanner.py. That scanner only ever WRITES proposals to
data/self_improvement_proposals.md and shows a desktop notification -
it never changes any code itself. These two tools are how a proposal
actually gets reviewed and (if approved) applied:

- list_improvement_proposals: show what's pending, so the user can ask
  "what did you find?" and get real answers instead of Eva having no
  memory of what the background scan turned up.
- apply_improvement_proposal: apply exactly ONE proposal, by id, through
  the same backup + pytest + auto-rollback path plugins/self_improve_tool.py
  already uses for a manual request. Never call this speculatively - only
  once the user has clearly agreed to a specific numbered proposal.
"""

import re
from pathlib import Path

from plugins.base import BasePlugin
from plugins.self_improve_tool import SelfImprovePlugin

_ROW_RE = re.compile(
    r"id:\s*(?P<id>\d+)\s*\|\s*status:\s*(?P<status>\w+)\s*\|\s*title:\s*(?P<title>.*?)\s*"
    r"\|\s*description:\s*(?P<description>.*?)\s*\|\s*goal:\s*(?P<goal>.*)$"
)


def _proposals_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "self_improvement_proposals.md"


def _read_rows():
    path = _proposals_path()
    if not path.exists():
        return [], path
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.search(line)
        if m:
            rows.append(m.groupdict())
    return rows, path


def _rewrite_status(path: Path, target_id: str, new_status: str):
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        m = _ROW_RE.search(line)
        if m and m.group("id") == target_id:
            line = re.sub(r"status:\s*\w+", f"status: {new_status}", line, count=1)
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


class ListImprovementProposalsPlugin(BasePlugin):
    name = "list_improvement_proposals"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "self_improve_scan", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Lists pending self-improvement proposals the background scanner has found in "
                "Eva's own code (real bugs or security issues) - waiting for the user's "
                "approval before anything is changed. Use when the user asks what you found, "
                "what needs fixing, or for a list of proposals."
            ),
            parameters={"type": "OBJECT", "properties": {}},
        )

    def execute(self, args: dict, config, context: dict) -> str:
        rows, _ = _read_rows()
        pending = [r for r in rows if r["status"] == "pending"]
        if not pending:
            return "No pending self-improvement proposals right now."
        lines = [f"#{r['id']}: {r['title']} - {r['description']}" for r in pending]
        return "Pending proposals:\n" + "\n".join(lines)


class ApplyImprovementProposalPlugin(BasePlugin):
    name = "apply_improvement_proposal"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "self_improve_scan", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Applies ONE previously-listed self-improvement proposal, by its id, after the "
                "user has explicitly approved it in this conversation. Goes through the same "
                "backup + test + auto-rollback path as a manual self_improve request. Never "
                "call this speculatively or on a proposal the user hasn't just agreed to."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING", "description": "The proposal's id number, e.g. '3'"},
                },
                "required": ["id"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        target_id = str(args.get("id") or "").strip()
        if not target_id:
            return "Missing proposal id."
        rows, path = _read_rows()
        row = next((r for r in rows if r["id"] == target_id), None)
        if row is None:
            return f"No proposal with id {target_id}."
        if row["status"] != "pending":
            return f"Proposal #{target_id} is already '{row['status']}'."

        result = SelfImprovePlugin().execute({"goal": row["goal"]}, config, context)
        new_status = "applied" if "applied successfully" in result.lower() else "failed"
        _rewrite_status(path, target_id, new_status)
        return f"Proposal #{target_id} ({row['title']}): {result}"


PLUGINS = [ListImprovementProposalsPlugin(), ApplyImprovementProposalPlugin()]
