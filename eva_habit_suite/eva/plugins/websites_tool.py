import webbrowser
from urllib.parse import quote as url_quote
from plugins.base import BasePlugin


class OpenWebsitePlugin(BasePlugin):
    name = "open_website"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "open_websites", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Opens a specific website by name from the allowed websites list.",
            parameters={
                "type": "OBJECT",
                "properties": {"site_name": {"type": "STRING", "description": "Website name as spoken by the user"}},
                "required": ["site_name"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The open-websites permission is disabled. Enable it via permissions.open_websites.enabled in config.yaml."
        site_name = (args.get("site_name") or "").strip()
        allowed: dict = config.get("permissions", "open_websites", "allowed", default={}) or {}
        match_key = next((k for k in allowed if k.strip().lower() == site_name.lower()), None)
        if not match_key:
            return (
                f"Website '{site_name}' is not in the allowed list. "
                f"You can add it manually under permissions.open_websites.allowed in config.yaml."
            )
        webbrowser.open(allowed[match_key])
        return f"Opened {match_key}."


class OpenAnyUrlPlugin(BasePlugin):
    name = "open_any_url"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "open_any_url", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Opens any website URL the user names, without restriction to a whitelist.",
            parameters={
                "type": "OBJECT",
                "properties": {"url": {"type": "STRING", "description": "Full or partial URL, e.g. 'github.com'"}},
                "required": ["url"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The open-any-url permission is disabled. Enable it via permissions.open_any_url.enabled in config.yaml."
        url = (args.get("url") or "").strip()
        if not url:
            return "No URL was provided."
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened {url}."


class SiteSearchPlugin(BasePlugin):
    name = "search_on_site"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "site_search", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Searches directly on a specific known site (e.g. YouTube, Amazon) for a query.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "site_name": {"type": "STRING", "description": "Site name, e.g. 'youtube', 'amazon'"},
                    "query": {"type": "STRING", "description": "What to search for"},
                },
                "required": ["site_name", "query"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The site-search permission is disabled. Enable it via permissions.site_search.enabled in config.yaml."
        site_name = (args.get("site_name") or "").strip().lower()
        query = (args.get("query") or "").strip()
        if not query:
            return "No search text was provided."
        sites: dict = config.get("permissions", "site_search", "sites", default={}) or {}
        match_key = next((k for k in sites if k.strip().lower() == site_name), None)
        if not match_key:
            return (
                f"Site '{site_name}' is not in the known sites list. "
                f"You can add it manually under permissions.site_search.sites in config.yaml."
            )
        url = sites[match_key].format(query=url_quote(query))
        webbrowser.open(url)
        return f"Searched for '{query}' on {match_key}."


PLUGINS = [OpenWebsitePlugin(), OpenAnyUrlPlugin(), SiteSearchPlugin()]
