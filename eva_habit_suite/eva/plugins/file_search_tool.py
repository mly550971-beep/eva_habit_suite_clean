"""
plugins/file_search_tool.py
----------------------------
Searches for files on disk by (partial) name, so the user can ask "where's
that PDF about the invoice" without opening a file manager. Deliberately
narrow and safe:

  - READ-ONLY: only lists matching paths - never opens, moves, deletes,
    or reads the contents of anything.
  - Search is confined to a configured list of root folders
    (permissions.file_search.roots), never the whole filesystem - so it
    can't be used to go looking through arbitrary system directories.
  - Results are capped (max_results) and each search has a wall-clock
    timeout, so an enormous folder or a network drive can't hang the
    assistant.
  - OFF by default (permissions.file_search.enabled).
"""

import os
import time
import fnmatch

from plugins.base import BasePlugin

DEFAULT_ROOTS = ["~/Desktop", "~/Documents", "~/Downloads"]


class FileSearchPlugin(BasePlugin):
    name = "search_files"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "file_search", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Searches for files by name (partial match, case-insensitive) inside a "
                "fixed set of allowed folders (Desktop/Documents/Downloads by default). "
                "Returns matching file paths only - does not open or read file contents."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "Name or partial name to search for, e.g. 'invoice' or 'report.docx'",
                    },
                },
                "required": ["query"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "File search is disabled. Enable it via permissions.file_search.enabled in config.yaml."

        query = (args.get("query") or "").strip()
        if not query:
            return "search_files requires a non-empty query."

        roots = config.get("permissions", "file_search", "roots", default=DEFAULT_ROOTS) or DEFAULT_ROOTS
        max_results = config.get("permissions", "file_search", "max_results", default=20)
        timeout_seconds = config.get("permissions", "file_search", "timeout_seconds", default=5)

        pattern = f"*{query.lower()}*"
        matches = []
        start = time.time()

        for root in roots:
            root_path = os.path.expanduser(root)
            if not os.path.isdir(root_path):
                continue
            for dirpath, _dirnames, filenames in os.walk(root_path):
                if time.time() - start > timeout_seconds:
                    break
                for filename in filenames:
                    if fnmatch.fnmatch(filename.lower(), pattern):
                        matches.append(os.path.join(dirpath, filename))
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        if not matches:
            return f"No files matching '{query}' were found in the allowed folders ({', '.join(roots)})."

        listing = "\n".join(matches)
        suffix = f" (showing first {max_results})" if len(matches) >= max_results else ""
        return f"Found {len(matches)} file(s){suffix}:\n{listing}"


PLUGIN = FileSearchPlugin()
