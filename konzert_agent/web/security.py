"""Login-Schutz für die Web-Oberfläche.

AuthMiddleware: Gäste (nicht angemeldet) dürfen den Kalender nur ansehen – erlaubt sind die Pfade in
GUEST (nur GET). Alles andere, z.B. «Jetzt prüfen» (/api/run) und alles Neue, braucht ein Login.
Mit `auth.guests: false` sind für Gäste nur /login, /health und Kalender-Abos mit Token offen. Ausserdem:

* POST/PUT/DELETE nur von derselben Herkunft (Origin-Prüfung) – zusätzlich zu SameSite=Lax gegen CSRF.
* Sicherheits-Header auf allen Antworten (kein Einbetten in fremde Seiten, kein MIME-Raten).
* Hinter einem Reverse Proxy: HTTPS-Erkennung über X-Forwarded-Proto, Client-IP über den in
  `auth.client_ip_header` konfigurierten Header (nur setzen, wenn der Proxy ihn auch setzt).
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..auth import LoginLimiter, check_login, new_token, token_hash
from ..config import AuthSettings
from ..store import Store

COOKIE = "ka_session"
PUBLIC = re.compile(r"^/(?:login|logout|health|ical/[^/]+\.ics)$")
# Nur-Lesen für Gäste (bewusst eine Positivliste: neue Routen sind automatisch nur für Angemeldete)
GUEST = re.compile(r"^/(?:|calendar\.ics|api/(?:me|events|venues)|static/.+)$")
SECURITY_HEADERS = [
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
]
LOGIN_HTML = (Path(__file__).parent / "static" / "login.html").read_text(encoding="utf-8")


def is_https(req: Request) -> bool:
    proto = req.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (proto or req.url.scheme) == "https"


def client_ip(req: Request, header: str) -> str:
    if header and req.headers.get(header):
        return req.headers[header].split(",")[0].strip()
    return req.client.host if req.client else "?"


def same_origin(req: Request, extra_hosts: set[str] = frozenset()) -> bool:
    """Origin muss zum Host passen – oder zur öffentlichen Adresse aus settings.base_url (hinter nginx
    kommt sonst evtl. die interne Adresse als Host an)."""
    origin = req.headers.get("origin")
    if not origin or origin == "null":
        return origin is None                       # «null» (z.B. aus Sandbox-Frames) ablehnen
    host = (req.headers.get("x-forwarded-host") or req.headers.get("host", "")).split(",")[0].strip()
    return urlsplit(origin).netloc in {host, *extra_hosts}


def safe_next(target: str | None) -> str:
    """Nur relative Pfade auf derselben Seite – kein Weiterleiten auf fremde Domains (//evil.com)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


class AuthMiddleware:
    def __init__(self, app, store: Store, settings: AuthSettings, base_url: str = ""):
        self.app, self.store, self.settings = app, store, settings
        self.extra_hosts = {urlsplit(base_url).netloc} - {""}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + SECURITY_HEADERS
            await send(message)

        req = Request(scope)
        if scope["method"] not in ("GET", "HEAD", "OPTIONS") and not same_origin(req, self.extra_hosts):
            return await JSONResponse({"error": "Anfrage von fremder Seite abgelehnt"}, 403)(
                scope, receive, send_with_headers)

        user = None
        token = req.cookies.get(COOKIE)
        if token:
            user = self.store.session_user(token_hash(token), self.settings.session_days)
        scope.setdefault("state", {})["user"] = user

        path = scope["path"]
        guest_ok = (self.settings.guests and scope["method"] in ("GET", "HEAD") and GUEST.match(path))
        if user or not self.settings.enabled or PUBLIC.match(path) or guest_ok:
            return await self.app(scope, receive, send_with_headers)
        if path.startswith("/api/"):
            resp = JSONResponse({"error": "Nicht angemeldet"}, 401)
        else:
            target = path + (f"?{scope['query_string'].decode()}" if scope.get("query_string") else "")
            resp = RedirectResponse(f"/login?next={quote(target)}", 303)
        await resp(scope, receive, send_with_headers)


def render_login(error: str = "", next_url: str = "/", hint: str = "", status: int = 200,
                 guests: bool = True) -> HTMLResponse:
    back = "<a class='back' href='/'>← ohne Anmeldung ansehen</a>" if guests else ""
    page = (LOGIN_HTML.replace("{{error}}", html.escape(error)).replace("{{next}}", html.escape(next_url))
            .replace("{{hint}}", hint).replace("{{back}}", back))
    return HTMLResponse(page, status_code=status, headers={"cache-control": "no-store"})


def login_routes(store: Store, settings: AuthSettings, limiter: LoginLimiter | None = None):
    limiter = limiter or LoginLimiter(settings.max_failures, settings.lockout_minutes)

    def render(*a, **kw):
        return render_login(*a, guests=settings.guests, **kw)

    def no_users_hint() -> str:
        if store.count_users():
            return ""
        return ("<p class='hint'>Noch keine Benutzer angelegt. Im Docker-Host ausführen:<br>"
                "<code>docker compose exec konzert-agent python -m konzert_agent user add &lt;name&gt;</code></p>")

    async def login_page(req: Request) -> Response:
        if req.method == "GET":
            if req.state.user:
                return RedirectResponse(safe_next(req.query_params.get("next")), 303)
            return render(next_url=safe_next(req.query_params.get("next")), hint=no_users_hint())

        form = {k: v[0] for k, v in parse_qs((await req.body()).decode("utf-8", "replace")).items()}
        username, password = form.get("username", "").strip(), form.get("password", "")
        next_url = safe_next(form.get("next"))
        keys = (f"u:{username.lower()}", f"ip:{client_ip(req, settings.client_ip_header)}")
        wait = limiter.locked_for(*keys)
        if wait:
            return render(f"Zu viele Fehlversuche – bitte in {wait // 60 + 1} Minuten nochmals versuchen.",
                                next_url, status=429)
        user = store.user_by_name(username) if username else None
        if not check_login(user, password):
            limiter.failure(*keys)
            return render("Benutzername oder Passwort falsch.", next_url, no_users_hint(), status=401)

        limiter.success(*keys)
        token = new_token()
        store.create_session(token_hash(token), user["id"], settings.session_days)
        resp = RedirectResponse(next_url, 303)
        secure = settings.secure_cookies == "true" or (settings.secure_cookies == "auto" and is_https(req))
        resp.set_cookie(COOKIE, token, max_age=settings.session_days * 86400, httponly=True,
                        samesite="lax", secure=secure, path="/")
        return resp

    async def logout(req: Request) -> Response:
        token = req.cookies.get(COOKIE)
        if token:
            store.delete_session(token_hash(token))
        resp = RedirectResponse("/" if settings.guests else "/login", 303)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    return login_page, logout
