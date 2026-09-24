# NOTE: 'dict[str, Any] | None' below is PEP 604 syntax (Python 3.10+).
# Without this __future__ import, importing this module on Python 3.9
# raises TypeError at class-creation time, every plugin's declaration()
# fails, and Eva silently ends up with zero usable tools.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _lowercase_schema_types(node: Any) -> Any:
    """Recursively lowercase JSON-Schema "type" values.

    Plugin declarations were originally written for the Gemini SDK, which
    uses uppercase type names ("OBJECT", "STRING", ...). Ollama/Gemma expect
    standard JSON Schema, which is lowercase ("object", "string", ...). Left
    uppercase, the schema is invalid JSON Schema and the model can't reliably
    parse tool parameters, which is why tool calls were failing to execute.
    """
    if isinstance(node, dict):
        fixed = {}
        for key, value in node.items():
            if key == "type" and isinstance(value, str):
                fixed[key] = value.lower()
            else:
                fixed[key] = _lowercase_schema_types(value)
        return fixed
    if isinstance(node, list):
        return [_lowercase_schema_types(v) for v in node]
    return node


@dataclass
class FunctionDeclaration:
    name: str
    description: str
    parameters: dict[str, Any] | None = None
    required: list[str] | None = None

    def to_ollama(self) -> dict:
        schema = _lowercase_schema_types(dict(self.parameters or {}))
        if self.required:
            schema["required"] = list(self.required)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema or {"type": "object", "properties": {}},
            },
        }

class types:
    FunctionDeclaration = FunctionDeclaration
