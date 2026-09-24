"""
plugins/stats_tool.py
-----------------------
get_tool_usage_stats: reports which tools have actually been invoked and
how often, from the counters ToolExecutor keeps in tools.py (persisted to
data/tool_stats.json). Purely introspective/read-only - no permission
gate needed beyond the usual enable switch.
"""

from plugins.base import BasePlugin


class ToolUsageStatsPlugin(BasePlugin):
    name = "get_tool_usage_stats"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "usage_stats", "enabled", default=True)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Reports which tools/capabilities have actually been used and how often "
                "(e.g. 'what do I use you for most'), based on real usage counts."
            ),
            parameters={"type": "OBJECT", "properties": {}},
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "Usage stats are disabled. Enable via permissions.usage_stats.enabled in config.yaml."

        executor = context.get("tool_executor")
        if executor is None:
            return "Usage stats are unavailable right now."

        top = executor.get_usage_summary(top_n=10)
        if not top:
            return "No tools have been used yet in this installation."

        lines = [f"{name}: {count} time(s)" for name, count in top]
        return "Most-used tools:\n" + "\n".join(f"- {line}" for line in lines)


PLUGIN = ToolUsageStatsPlugin()
