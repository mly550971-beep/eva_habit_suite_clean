"""
plugins/base.py
---------------
The interface every tool plugin implements. Dropping a new file in this
folder that defines a module-level `PLUGIN` instance of a BasePlugin
subclass is enough for it to be auto-discovered - no changes needed
anywhere else in the codebase.
"""


class BasePlugin:
    name = "override_me"

    def is_enabled(self, config) -> bool:
        """Return True if this tool's permission is enabled in config.yaml"""
        raise NotImplementedError

    def declaration(self, config):
        """Return a local_types.FunctionDeclaration describing this tool"""
        raise NotImplementedError

    def execute(self, args: dict, config, context: dict) -> str:
        """
        Execute the tool and return a text result to send back to the model.
        `context` carries shared resources: client, model_name, profile,
        notifier, logger, audit_logger.
        """
        raise NotImplementedError
