from __future__ import annotations
import os, re, subprocess, sys, textwrap, time
from pathlib import Path
from plugins.base import BasePlugin
from local_types import types

class SelfImprovePlugin(BasePlugin):
    name = "self_improve"
    def is_enabled(self, config):
        return config.get("permissions", "self_improve", "enabled", default=True)
    def declaration(self, config):
        return types.FunctionDeclaration(
            name=self.name,
            description="Audit EVA's own Python code, propose a focused improvement, run tests, and apply only a validated low-risk patch with a backup.",
            parameters={
                "type":"object",
                "properties":{"goal":{"type":"string","description":"Specific improvement goal, bug, or capability to work on."}},
                "required":["goal"],
            },
        )
    def execute(self, args, config, context):
        if not self.is_enabled(config): return "Self-improvement is disabled."
        brain=context.get("brain")
        logger=context.get("logger")
        root=Path(__file__).resolve().parent.parent
        goal=(args.get("goal") or "Improve reliability and maintainability").strip()
        allowed_ext={".py",".yaml",".yml",".md"}
        files=[]
        for p in root.rglob("*.py"):
            if any(part in {".venv","venv","__pycache__","logs"} for part in p.parts): continue
            files.append(p)
        files=files[:120]
        manifest=[]
        for p in files:
            try:
                text=p.read_text(encoding="utf-8")
                manifest.append(f"FILE: {p.relative_to(root)}\n{text[:12000]}")
            except Exception: pass
        # Recent history of what self_improve already changed, so a new
        # call builds on past fixes instead of re-discovering (and
        # re-presenting as new) the same one. Best-effort - a missing or
        # unreadable log just means no history, not a failure.
        log_file = root / "data" / "self_improvement_log.md"
        history = ""
        try:
            if log_file.exists():
                lines = log_file.read_text(encoding="utf-8").splitlines()
                history = "\n".join(lines[-40:])
        except Exception:
            history = ""
        history_block = (
            f"Recent self-improvement history (most recent last - do not repeat these):\n{history}\n"
            if history else "No self-improvement history yet.\n"
        )
        prompt=textwrap.dedent(f"""
        You are EVA's software engineer. Goal: {goal}
        Project root: {root}
        {history_block}
        Produce exactly one unified diff patch inside a ```diff code fence.
        Rules: only modify existing .py/.yaml/.yml files; no shell commands; no deletion of files; preserve existing behavior; keep changes focused; do not edit credentials, logs, data/memory.json, or sessions.
        The patch must be syntactically valid and suitable for pytest.
        Project snapshot:\n{chr(10).join(manifest)}
        """)
        if brain is None: return "Self-improvement subsystem is unavailable."
        patch_text=brain.generate_developer_text(prompt, temperature=0.0)
        m=re.search(r"```diff\s*(.*?)\s*```", patch_text, re.S|re.I)
        if not m: return "I generated a proposal, but it was not a valid unified diff, so nothing was changed."
        diff=m.group(1).strip()
        patch_file=root/"data"/"improvements"
        patch_file.mkdir(parents=True, exist_ok=True)
        stamp=time.strftime("%Y%m%d_%H%M%S")
        candidate=patch_file/f"candidate_{stamp}.diff"
        candidate.write_text(diff,encoding="utf-8")
        # Validate patch target paths before applying.
        targets = re.findall(r'^\+\+\+ b/(.+)$', diff, re.M)
        for target in targets:
            path=(root/target).resolve()
            if path.parent != root and root not in path.parents: return f"Rejected unsafe patch path: {target}"
            if path.suffix not in allowed_ext: return f"Rejected unsupported file type: {target}"
            if any(x in path.parts for x in ("data","logs")) and path.name not in {"config.yaml","config.yml"}: return f"Rejected protected path: {target}"

        # Back up the current content of every file the patch will touch,
        # BEFORE applying anything, so a failing test suite can actually be
        # rolled back below - without this, "changes were not kept" was a
        # lie: there was nothing to restore from.
        backup_dir = patch_file / f"backup_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for rel in targets:
            src = root / rel
            if src.exists():
                dst = backup_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(src.read_bytes())

        def parse_and_apply(diff_text, root_path):
            lines = diff_text.splitlines(True)
            i = 0
            changed = []
            while i < len(lines):
                if not lines[i].startswith('--- '):
                    i += 1; continue
                old_line = lines[i].rstrip('\n'); i += 1
                if i >= len(lines) or not lines[i].startswith('+++ '):
                    raise ValueError('Malformed unified diff header')
                new_line = lines[i].rstrip('\n'); i += 1
                target = new_line[4:].strip()
                if target.startswith('b/'):
                    target = target[2:]
                if target.startswith('/dev/null'):
                    raise ValueError('File creation/deletion is not allowed')
                out_path = (root_path / target).resolve()
                if out_path.suffix not in allowed_ext:
                    raise ValueError(f'Unsupported file type: {target}')
                if any(part in {'data','logs'} for part in out_path.relative_to(root_path).parts[:-1]):
                    raise ValueError(f'Protected path: {target}')
                original = out_path.read_text(encoding='utf-8').splitlines(True)
                result = []
                pos = 0
                while i < len(lines) and lines[i].startswith('@@ '):
                    header = lines[i].strip(); i += 1
                    import re as _re
                    hm = _re.match(r'^@@ -(?P<old>\d+)(?:,(?P<oldn>\d+))? \+(?P<new>\d+)(?:,(?P<newn>\d+))? @@', header)
                    if not hm:
                        raise ValueError(f'Bad hunk header: {header}')
                    old_start = int(hm.group('old')) - 1
                    result.extend(original[pos:old_start]); pos = old_start
                    while i < len(lines) and not lines[i].startswith('@@ ') and not lines[i].startswith('--- '):
                        line = lines[i]; i += 1
                        if not line: continue
                        marker=line[0]; body=line[1:]
                        if marker == ' ':
                            if pos >= len(original) or original[pos] != body:
                                raise ValueError(f'Context mismatch while patching {target}')
                            result.append(original[pos]); pos += 1
                        elif marker == '-':
                            if pos >= len(original) or original[pos] != body:
                                raise ValueError(f'Deletion mismatch while patching {target}')
                            pos += 1
                        elif marker == '+':
                            result.append(body)
                        elif marker == '\\':
                            continue
                        else:
                            raise ValueError(f'Unknown diff line: {line!r}')
                result.extend(original[pos:])
                out_path.write_text(''.join(result), encoding='utf-8')
                changed.append(str(out_path))
            return changed

        try:
            changed = parse_and_apply(diff, root)
        except Exception as exc:
            # A partial write may have already landed on disk before the
            # error - restore every target from the backup taken above so a
            # rejected patch never leaves the codebase half-modified.
            for rel in targets:
                src = root / rel
                backup = backup_dir / rel
                if backup.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    src.write_bytes(backup.read_bytes())
            return f"Candidate patch was rejected before application: {exc}"

        # sys.executable, not "python": on Windows the bare name resolves via PATH
        # (often to the Store stub or another interpreter entirely), so the
        # safety tests could run against a Python that has none of Eva's deps -
        # and a patch would then be rolled back (or kept) for the wrong reason.
        tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root,
                               capture_output=True, text=True, timeout=180)
        if tests.returncode!=0:
            for rel in targets:
                src=root/rel
                backup=backup_dir/rel
                if backup.exists():
                    src.parent.mkdir(parents=True,exist_ok=True)
                    src.write_bytes(backup.read_bytes())
            return "I rolled back the patch because the test suite failed. Changes were not kept."

        # Record what changed and why, so future self_improve calls (and
        # the model itself, per the system prompt) can see this happened
        # instead of re-proposing the same fix as if it were new.
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as f:
                f.write(
                    f"- {time.strftime('%Y-%m-%d %H:%M:%S')} | goal: {goal} | "
                    f"files: {', '.join(targets)} | backup: {backup_dir.relative_to(root)}\n"
                )
        except Exception:
            pass

        return f"Self-improvement applied successfully. Tests passed. Backup: {backup_dir.relative_to(root)}"

PLUGIN=SelfImprovePlugin()
