"""Benutzer, Passwörter, Sitzungen und Sperre nach Fehlversuchen.

* Passwörter: scrypt (Python-Standardbibliothek) mit zufälligem Salt.
* Sitzungen: zufälliges Token im Cookie; in der Datenbank steht nur dessen SHA-256 – ein Datenbank-Leck
  verrät also keine gültigen Cookies. Logout und «alle Sitzungen beenden» wirken sofort.
* Sperre: nach `max_failures` Fehlversuchen in `lockout_minutes` wird der Benutzername UND die
  Client-IP gesperrt. Die Sperre pro Benutzername greift auch dann, wenn jemand die IP fälscht.
* Kalender-Token: pro Benutzer ein geheimes Token für iCal-Abos (Kalender-Apps können sich nicht anmelden).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(h)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


# Gegen Timing-Angriffe: auch bei unbekanntem Benutzer gleich lange rechnen
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_login(user: dict | None, password: str) -> bool:
    if user is None or user.get("disabled"):
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, user["pw_hash"])


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LoginLimiter:
    """Merkt sich Fehlversuche im Speicher (ein Prozess). Ein Neustart hebt Sperren auf – vertretbar,
    die Wartezeit ist ohnehin kurz und das Raten bleibt durch scrypt teuer."""

    def __init__(self, max_failures: int = 5, lockout_minutes: int = 15):
        self.max_failures = max_failures
        self.window = lockout_minutes * 60
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque:
        q = self._fails.get(key)
        if q is None:
            return deque()
        while q and q[0] < now - self.window:
            q.popleft()
        if not q:                            # abgelaufene Schlüssel löschen, sonst wächst der Speicher endlos
            del self._fails[key]
        return q

    def locked_for(self, *keys: str) -> int:
        """Sekunden bis zur Freigabe (0 = nicht gesperrt)."""
        now = time.time()
        with self._lock:
            waits = [int(q[0] + self.window - now) + 1 for k in keys
                     if len(q := self._recent(k, now)) >= self.max_failures]
        return max(waits, default=0)

    def failure(self, *keys: str):
        now = time.time()
        with self._lock:
            for k in keys:
                self._recent(k, now)
                self._fails[k].append(now)

    def success(self, *keys: str):
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)
