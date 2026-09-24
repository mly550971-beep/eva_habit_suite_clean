"""
secure_storage.py
------------------
At-rest encryption for the JSON files that hold personal data
(data/memory.json, data/profile.json) so they aren't sitting on disk as
plain, readable text. Uses a local symmetric key (data/secret.key,
generated on first run).

Honest scope: this protects the files if they're copied off the machine
(a stolen laptop, a careless cloud backup, an accidental git commit of the
data/ folder) - it does NOT protect against someone with full access to
this same machine, since the key sits right next to the files it decrypts.
Real key-management (OS keychain, a passphrase) is a bigger change; this
is the "easy and safe" first step.

Backward compatible: a file already on disk as plain JSON (from before
this was added) is read as-is, then transparently re-saved encrypted the
next time save_json() runs - no manual migration step needed.

If the `cryptography` package isn't installed, both functions fall back
to plain JSON automatically (with a one-time log warning) instead of
crashing the app.
"""

from __future__ import annotations

import os
import json


def _get_key(logger=None) -> bytes:
    from cryptography.fernet import Fernet

    key_dir = "data"
    key_path = os.path.join(key_dir, "secret.key")
    os.makedirs(key_dir, exist_ok=True)

    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()

    key = Fernet.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    try:
        os.chmod(key_path, 0o600)  # best-effort; no-op on Windows
    except Exception:
        pass
    if logger:
        logger.info("[SecureStorage] Generated a new local encryption key at data/secret.key")
    return key


def load_json(file_path: str, logger=None, default=None):
    """Reads and decrypts file_path. Transparently handles an existing
    plain-JSON file (pre-encryption) or a missing `cryptography` package
    by falling back to reading it as plain JSON."""
    if not os.path.exists(file_path):
        return default

    with open(file_path, "rb") as f:
        raw = f.read()
    if not raw:
        return default

    try:
        from cryptography.fernet import Fernet

        fernet = Fernet(_get_key(logger))
        decrypted = fernet.decrypt(raw)
        return json.loads(decrypted.decode("utf-8"))
    except ImportError:
        if logger:
            logger.warning(
                "[SecureStorage] 'cryptography' not installed - reading "
                f"{file_path} as plain JSON. Run: pip install cryptography"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return default
    except Exception:
        # Most likely an old plaintext file from before encryption existed,
        # not corruption - try plain JSON before giving up. It will be
        # re-saved encrypted the next time save_json() is called.
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            if logger:
                logger.warning(f"[SecureStorage] Could not read {file_path}: {e}")
            return default


def save_json(file_path: str, data, logger=None) -> None:
    """Encrypts and atomically writes data to file_path (temp file +
    os.replace, so a crash mid-write can't leave a half-written file)."""
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        from cryptography.fernet import Fernet

        fernet = Fernet(_get_key(logger))
        payload = fernet.encrypt(payload)
    except ImportError:
        if logger:
            logger.warning(
                "[SecureStorage] 'cryptography' not installed - saving "
                f"{file_path} unencrypted. Run: pip install cryptography"
            )

    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "wb") as f:
        f.write(payload)
    os.replace(tmp_path, file_path)
