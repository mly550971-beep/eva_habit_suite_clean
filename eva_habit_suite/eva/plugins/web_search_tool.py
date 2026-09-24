"""
plugins/web_search_tool.py
---------------------------
Three related tools:
  - search_information: returns real text results (title + snippet) for a
    query, so Eva can answer directly instead of opening a browser.
  - search_video: returns real video titles + links for a query (search
    only - never uploads/posts anything).
  - open_browser_search: the old behaviour - actually opens the browser,
    kept for when the user explicitly asks to "open" a search.
Uses DuckDuckGo's HTML endpoint (no API key needed) for text results, and
YouTube's search page (no API key needed) for video results.
"""

import re
import webbrowser
import requests
from urllib.parse import quote as url_quote
from plugins.base import BasePlugin


class SearchInformationPlugin(BasePlugin):
    name = "search_information"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "web_search", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Searches the web and returns real text results (titles and short "
                "summaries) about a topic, so you can read/speak the answer directly. "
                "Use this for any factual or 'search for information about X' request "
                "instead of opening a browser."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {"query": {"type": "STRING", "description": "What to search for"}},
                "required": ["query"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The web search permission is disabled. Enable it via permissions.web_search.enabled in config.yaml."
        query = (args.get("query") or "").strip()
        if not query:
            return "No search text was provided."
        try:
            resp = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=8,
            )
            resp.raise_for_status()
            html = resp.text

            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)

            def clean(s):
                return re.sub(r"<.*?>", "", s).replace("&#x27;", "'").strip()

            results = []
            for i in range(min(3, len(titles))):
                title = clean(titles[i])
                snippet = clean(snippets[i]) if i < len(snippets) else ""
                results.append(f"{title}: {snippet}" if snippet else title)

            if not results:
                # Distinguish "DuckDuckGo genuinely has nothing" from "their
                # HTML markup changed and our regex no longer matches it" -
                # the latter is a silent-failure trap otherwise, since both
                # cases used to return the exact same message.
                if "result__a" not in html and "result__snippet" not in html:
                    return (
                        f"Could not parse search results for '{query}' - DuckDuckGo's page "
                        f"layout may have changed. Try open_browser_search instead."
                    )
                return f"No text results were found for '{query}'."
            return "Search results for '" + query + "':\n" + "\n".join(f"- {r}" for r in results)
        except Exception as exc:
            return f"The search failed due to a network or parsing error: {exc}"


class SearchVideoPlugin(BasePlugin):
    name = "search_video"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "web_search", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Searches YouTube and returns real video titles with their links for a "
                "topic. This only searches/returns results - it never uploads, posts, or "
                "publishes any video."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {"query": {"type": "STRING", "description": "What video to search for"}},
                "required": ["query"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The web search permission is disabled. Enable it via permissions.web_search.enabled in config.yaml."
        query = (args.get("query") or "").strip()
        if not query:
            return "No search text was provided."
        try:
            resp = requests.get(
                f"https://www.youtube.com/results?search_query={url_quote(query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=8,
            )
            resp.raise_for_status()
            html = resp.text

            video_ids = re.findall(r'"videoId":"(.*?)"', html)
            titles = re.findall(r'"title":\{"runs":\[\{"text":"(.*?)"\}\]', html)

            seen = set()
            results = []
            for i, vid in enumerate(video_ids):
                if vid in seen:
                    continue
                seen.add(vid)
                title = titles[i] if i < len(titles) else "(untitled)"
                results.append(f"{title} - https://www.youtube.com/watch?v={vid}")
                if len(results) >= 3:
                    break

            if not results:
                return f"No videos were found for '{query}'."
            return "Video results for '" + query + "':\n" + "\n".join(f"- {r}" for r in results)
        except Exception as exc:
            return f"The video search failed due to a network or parsing error: {exc}"


class OpenBrowserSearchPlugin(BasePlugin):
    name = "open_browser_search"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "web_search", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Actually opens the default web browser to a Google search for the given "
                "query. Only use this when the user explicitly asks to 'open' the browser "
                "or 'open a search', not for general information questions."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {"query": {"type": "STRING", "description": "Search text"}},
                "required": ["query"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The web search permission is disabled. Enable it via permissions.web_search.enabled in config.yaml."
        query = (args.get("query") or "").strip()
        if not query:
            return "No search text was provided."
        webbrowser.open(f"https://www.google.com/search?q={url_quote(query)}")
        return f"Opened the browser to search for: {query}"


PLUGINS = [SearchInformationPlugin(), SearchVideoPlugin(), OpenBrowserSearchPlugin()]
