import asyncio
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
from urllib.parse import urlencode

from konzert_agent.__main__ import main
from konzert_agent.agent import Agent
from konzert_agent.auth import LoginLimiter, hash_password, new_token, verify_password
from konzert_agent.config import ArtistSettings, AuthSettings, Config, Settings
from konzert_agent.web.app import create_app


def call(app, method, path, headers=None, body=b""):
    """Minimaler ASGI-Client (httpx ist im Image nicht installiert)."""
    path, _, qs = path.partition("?")
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": method, "path": path, "query_string": qs.encode(), "headers": hdrs,
             "scheme": "http", "server": ("test", 80), "client": ("10.0.0.1", 1234), "root_path": "",
             "http_version": "1.1"}
    out = {"status": None, "headers": [], "body": b""}
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
            out["headers"] = [(k.decode().lower(), v.decode()) for k, v in msg["headers"]]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    asyncio.run(app(scope, receive, send))
    out["h"] = dict(out["headers"])
    out["text"] = out["body"].decode("utf-8", "replace")
    return out


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self):
        h = hash_password("richtig-lang-genug")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertTrue(verify_password("richtig-lang-genug", h))
        self.assertFalse(verify_password("falsch", h))
        self.assertFalse(verify_password("x", "kaputt"))
        self.assertNotEqual(h, hash_password("richtig-lang-genug"))          # Salt

    def test_limiter(self):
        lim = LoginLimiter(max_failures=3, lockout_minutes=15)
        for _ in range(3):
            self.assertEqual(lim.locked_for("u:a"), 0)
            lim.failure("u:a", "ip:1")
        self.assertGreater(lim.locked_for("u:a"), 0)
        self.assertGreater(lim.locked_for("u:other", "ip:1"), 0)              # IP ebenfalls gesperrt
        lim.success("u:a")
        self.assertEqual(lim.locked_for("u:a"), 0)


class WebAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = Config(settings=Settings(database=f"{self.tmp.name}/t.db", base_url="https://konzerte.example.ch"),
                     venues=[], notifiers=[], artists=ArtistSettings(enabled=False),
                     auth=AuthSettings(max_failures=3))
        self.agent = Agent(cfg)
        self.store = self.agent.store
        self.ical = new_token()
        self.uid = self.store.create_user("Anna", hash_password("geheimes-passwort"), self.ical)
        self.app = create_app(self.agent)

    def login(self, user="anna", pw="geheimes-passwort", nxt="/", headers=None):
        body = urlencode({"username": user, "password": pw, "next": nxt}).encode()
        return call(self.app, "POST", "/login", {"content-type": "application/x-www-form-urlencoded",
                                                  "origin": "http://test", "host": "test", **(headers or {})}, body)

    def cookie(self, resp):
        return resp["h"]["set-cookie"].split(";")[0]

    def logged_in(self, cookie):
        return '"username":"Anna"' in call(self.app, "GET", "/api/me", {"cookie": cookie})["text"]

    def test_guest_can_only_read(self):
        self.assertEqual(call(self.app, "GET", "/")["status"], 200)
        self.assertEqual(call(self.app, "GET", "/api/events")["status"], 200)
        self.assertEqual(call(self.app, "GET", "/api/venues")["status"], 200)
        self.assertEqual(call(self.app, "GET", "/calendar.ics")["status"], 200)
        self.assertEqual(call(self.app, "GET", "/static/index.html")["status"], 200)
        me = call(self.app, "GET", "/api/me")
        self.assertIn('"user":null', me["text"])
        self.assertIn('"auth":true', me["text"])
        with mock.patch.object(self.agent, "run") as run:                      # «Jetzt prüfen» nur mit Login
            r = call(self.app, "POST", "/api/run", {"origin": "http://test", "host": "test"})
            self.assertEqual(r["status"], 401)
            run.assert_not_called()
        self.assertEqual(call(self.app, "GET", "/api/unbekannt")["status"], 401)   # Positivliste
        self.assertIn("ohne Anmeldung", call(self.app, "GET", "/login")["text"])

    def test_member_can_run(self):
        c = self.cookie(self.login())
        with mock.patch.object(self.agent, "run"):
            r = call(self.app, "POST", "/api/run", {"cookie": c, "origin": "http://test", "host": "test"})
        self.assertEqual(r["status"], 200)

    def test_everything_behind_login_without_guests(self):
        self.agent.config.auth.guests = False
        app = create_app(self.agent)
        r = call(app, "GET", "/?x=1")
        self.assertEqual((r["status"], r["h"]["location"]), (303, "/login?next=/%3Fx%3D1"))
        self.assertEqual(call(app, "GET", "/api/events")["status"], 401)
        self.assertEqual(call(app, "GET", "/calendar.ics")["status"], 303)
        self.assertEqual(call(app, "GET", "/static/index.html")["status"], 303)
        self.assertEqual(call(app, "GET", "/health")["status"], 200)
        login = call(app, "GET", "/login")["text"]
        self.assertIn("Benutzername", login)
        self.assertNotIn("ohne Anmeldung", login)

    def test_login_flow_and_cookie_flags(self):
        r = self.login(nxt="/?view=month")
        self.assertEqual((r["status"], r["h"]["location"]), (303, "/?view=month"))
        sc = r["h"]["set-cookie"].lower()
        self.assertIn("httponly", sc)
        self.assertIn("samesite=lax", sc)
        self.assertNotIn("secure", sc)                                         # http -> ohne Secure
        me = call(self.app, "GET", "/api/me", {"cookie": self.cookie(r)})
        self.assertEqual(me["status"], 200)
        self.assertIn('"username":"Anna"', me["text"])
        self.assertEqual(call(self.app, "GET", "/api/events", {"cookie": self.cookie(r)})["status"], 200)

    def test_secure_cookie_behind_https_proxy(self):
        r = self.login(headers={"x-forwarded-proto": "https"})
        self.assertIn("secure", r["h"]["set-cookie"].lower())

    def test_wrong_password_and_lockout(self):
        for _ in range(3):
            r = self.login(pw="falsch")
            self.assertEqual(r["status"], 401)
            self.assertIn("Benutzername oder Passwort falsch", r["text"])
            self.assertNotIn("set-cookie", r["h"])
        r = self.login()                                                       # richtig, aber gesperrt
        self.assertEqual(r["status"], 429)
        self.assertIn("Zu viele Fehlversuche", r["text"])

    def test_unknown_user_same_message(self):
        r = self.login(user="niemand", pw="egal")
        self.assertEqual(r["status"], 401)
        self.assertIn("Benutzername oder Passwort falsch", r["text"])

    def test_no_open_redirect(self):
        for evil in ("//evil.example", "https://evil.example", "/\\evil.example"):
            self.assertEqual(self.login(nxt=evil)["h"]["location"], "/")

    def test_csrf_origin_check(self):
        c = self.cookie(self.login())
        r = call(self.app, "POST", "/logout", {"cookie": c, "origin": "https://evil.example", "host": "test"})
        self.assertEqual(r["status"], 403)
        self.assertTrue(self.logged_in(c))
        # öffentliche Adresse aus base_url gilt auch, wenn nginx die interne Adresse als Host schickt
        r = call(self.app, "POST", "/logout", {"cookie": c, "origin": "https://konzerte.example.ch",
                                               "host": "192.168.1.5:9099"})
        self.assertEqual((r["status"], r["h"]["location"]), (303, "/"))
        self.assertFalse(self.logged_in(c))                                               # Sitzung weg

    def test_disabled_user_loses_session(self):
        c = self.cookie(self.login())
        self.assertTrue(self.logged_in(c))
        self.store.update_user(self.uid, disabled=1)
        self.assertFalse(self.logged_in(c))

    def test_personal_ical(self):
        self.assertEqual(call(self.app, "GET", f"/ical/{self.ical}.ics")["status"], 200)
        self.assertIn("BEGIN:VCALENDAR", call(self.app, "GET", f"/ical/{self.ical}.ics?genre=Metal")["text"])
        self.assertEqual(call(self.app, "GET", "/ical/falsch.ics")["status"], 404)
        self.store.update_user(self.uid, disabled=1)
        self.assertEqual(call(self.app, "GET", f"/ical/{self.ical}.ics")["status"], 404)

    def test_security_headers(self):
        h = call(self.app, "GET", "/health")["h"]
        self.assertEqual((h["x-frame-options"], h["x-content-type-options"]), ("DENY", "nosniff"))

    def test_no_users_hint(self):
        self.store.delete_user(self.uid)
        self.assertIn("user add", call(self.app, "GET", "/login")["text"])


class UserCliTests(unittest.TestCase):
    def test_add_list_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = f"{tmp}/c.yaml"
            with open(cfg_path, "w") as f:
                f.write(f"settings: {{database: {tmp}/t.db}}\nvenues: []\n")
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("sys.stdin", io.StringIO("ein-langes-passwort\n")):
                main(["-c", cfg_path, "user", "add", "ben", "--password-stdin"])
            with redirect_stdout(out):
                main(["-c", cfg_path, "user", "disable", "ben"])
                main(["-c", cfg_path, "user", "list"])
            self.assertIn("angelegt", out.getvalue())
            self.assertIn("gesperrt", out.getvalue())
            with mock.patch("sys.stdin", io.StringIO("kurz\n")), self.assertRaises(SystemExit):
                main(["-c", cfg_path, "user", "add", "cara", "--password-stdin"])


if __name__ == "__main__":
    unittest.main()
