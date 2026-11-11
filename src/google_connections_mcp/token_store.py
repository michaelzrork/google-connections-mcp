"""
Persistent storage for the MCP sign-in and the Google token.

One small JSON file in DATA_DIR. On Railway, mount a volume there (Railway:
the service → Settings → Volumes → mount path /data) so a redeploy keeps it.
Without a volume the file lives on the container's disk and is lost on every
deploy: Claude then has to reconnect, and the Google token falls back to the
GOOGLE_TOKEN_JSON variable if one is set.

What it holds:
  clients      OAuth clients that registered themselves (Claude, ChatGPT, ...)
  codes        one-time sign-in codes (minutes)
  access       access tokens, by SHA-256 of the token (never the token itself)
  refresh      refresh tokens, same
  pending      sign-ins waiting on Google
  google_token the Google credentials (refresh token included)
  connected_at when an AI app first connected through the new sign-in; the
               old open /sse endpoint switches itself off from then on
"""

import hashlib
import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional


def _default_dir() -> str:
    env = os.environ.get('DATA_DIR')
    if env:
        return env
    # Railway volumes are commonly mounted at /data; use it when it's there.
    if os.path.isdir('/data') and os.access('/data', os.W_OK):
        return '/data'
    return os.path.join(os.getcwd(), 'data')


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


class TokenStore:
    SECTIONS = ('clients', 'codes', 'access', 'refresh', 'pending')

    def __init__(self, data_dir: Optional[str] = None):
        self.dir = data_dir or _default_dir()
        self.path = os.path.join(self.dir, 'mcp_store.json')
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {s: {} for s in self.SECTIONS}
        self._data.update({'google_token': None, 'connected_at': None})
        self._load()

    # -- file ----------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for s in self.SECTIONS:
                self._data[s] = data.get(s) or {}
            self._data['google_token'] = data.get('google_token')
            self._data['connected_at'] = data.get('connected_at')
        except FileNotFoundError:
            pass
        except Exception as e:  # a corrupt file must not take the server down
            print(f"[token_store] could not read {self.path}: {e}")

    def _save(self) -> None:
        os.makedirs(self.dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix='.mcp_store.', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self._data, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)  # atomic: never a half-written file
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def persistent(self) -> bool:
        """True when the file sits on what looks like a mounted volume."""
        return os.path.ismount(self.dir) or bool(os.environ.get('DATA_DIR'))

    # -- generic sections ----------------------------------------------------
    def get(self, section: str, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            v = self._data[section].get(key)
            return dict(v) if isinstance(v, dict) else v

    def put(self, section: str, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._data[section][key] = value
            self._save()

    def pop(self, section: str, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            v = self._data[section].pop(key, None)
            if v is not None:
                self._save()
            return v

    def delete_where(self, section: str, **match: Any) -> int:
        with self._lock:
            keys = [k for k, v in self._data[section].items()
                    if all(v.get(f) == want for f, want in match.items())]
            for k in keys:
                del self._data[section][k]
            if keys:
                self._save()
            return len(keys)

    def prune(self) -> None:
        """Drop expired codes, tokens and pending sign-ins."""
        now = time.time()
        with self._lock:
            changed = False
            for section in ('codes', 'access', 'refresh', 'pending'):
                dead = [k for k, v in self._data[section].items()
                        if v.get('expires_at') and v['expires_at'] < now]
                for k in dead:
                    del self._data[section][k]
                    changed = True
            if changed:
                self._save()

    # -- Google token ----------------------------------------------------------
    def google_token(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get('google_token')

    def set_google_token(self, token_info: Dict[str, Any]) -> None:
        with self._lock:
            self._data['google_token'] = token_info
            self._save()

    # -- the legacy switch -----------------------------------------------------
    def connected_at(self) -> Optional[float]:
        with self._lock:
            return self._data.get('connected_at')

    def mark_connected(self) -> None:
        with self._lock:
            if not self._data.get('connected_at'):
                self._data['connected_at'] = time.time()
                self._save()


_store: Optional[TokenStore] = None


def get_store() -> TokenStore:
    global _store
    if _store is None:
        _store = TokenStore()
    return _store
