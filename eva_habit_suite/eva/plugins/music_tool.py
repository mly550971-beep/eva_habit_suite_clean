"""
plugins/music_tool.py
----------------------
play_music: finds a song/artist on YouTube (same free, keyless search
already used by search_video) and opens the top result directly in the
default browser. YouTube auto-plays a video the moment its watch page is
opened, so this behaves like "play <song>" without needing any YouTube
account, API key, or paid Data API quota.
"""

import re
import webbrowser
import requests
from urllib.parse import quote as url_quote
from plugins.base import BasePlugin


class PlayMusicPlugin(BasePlugin):
    name = "play_music"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "play_music", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Plays a song, artist, or piece of music by finding it on YouTube and "
                "opening it in the browser (YouTube starts playback automatically once "
                "opened). Use this whenever the user asks to play, put on, or listen to "
                "a specific song or artist."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING", "description": "Song name and/or artist to play"}
                },
                "required": ["query"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The play_music permission is disabled. Enable it via permissions.play_music.enabled in config.yaml."
        query = (args.get("query") or "").strip()
        if not query:
            return "No song was specified."
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

            if not video_ids:
                return f"Could not find '{query}' on YouTube."

            top_id = video_ids[0]
            top_title = titles[0] if titles else query
            url = f"https://www.youtube.com/watch?v={top_id}"
            webbrowser.open(url)

            now_playing_cb = (context.get("ui_callbacks") or {}).get("now_playing")
            if now_playing_cb:
                try:
                    now_playing_cb(top_title)
                except Exception:
                    pass  # cosmetic UI feedback only - never let this fail the tool call

            return f"Now playing '{top_title}' on YouTube."
        except Exception as exc:
            return f"Could not play the song due to a network error: {exc}"


PLUGIN = PlayMusicPlugin()
