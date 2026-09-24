import webbrowser
from urllib.parse import quote as url_quote
from plugins.base import BasePlugin


class SendWhatsAppMessagePlugin(BasePlugin):
    """Opens a pre-filled WhatsApp chat. Eva NEVER clicks Send - only the
    human can send the message. This is a deliberate safety choice."""
    name = "send_whatsapp_message"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "messaging", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description="Opens a pre-filled WhatsApp chat with a known contact. The user must click Send themselves.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "contact_name": {"type": "STRING", "description": "Contact name as spoken by the user"},
                    "message": {"type": "STRING", "description": "The message text to pre-fill"},
                },
                "required": ["contact_name", "message"],
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The messaging permission is disabled. Enable it via permissions.messaging.enabled in config.yaml."
        contact_name = (args.get("contact_name") or "").strip()
        message = (args.get("message") or "").strip()
        contacts: dict = config.get("permissions", "messaging", "contacts", default={}) or {}
        match_key = next((k for k in contacts if k.strip().lower() == contact_name.lower()), None)
        if not match_key:
            return (
                f"Contact '{contact_name}' is not in the known contacts list. "
                f"You can add it manually under permissions.messaging.contacts in config.yaml."
            )
        phone = contacts[match_key]
        url = f"https://wa.me/{phone}?text={url_quote(message)}"
        webbrowser.open(url)
        return f"Opened a pre-filled WhatsApp chat with {match_key}. The user must click Send themselves."


PLUGIN = SendWhatsAppMessagePlugin()
