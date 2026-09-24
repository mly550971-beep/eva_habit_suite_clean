"""
notifier.py
-----------
A thin, safe wrapper around desktop notifications (via plyer). If plyer or
the platform's notification backend isn't available, calls are silently
ignored instead of crashing the app - notifications are a nice-to-have,
never a requirement.
"""


def notify(title: str, message: str, logger=None):
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=6)
    except Exception as e:
        if logger:
            logger.debug(f"[Notifier] Could not show a system notification: {e}")
