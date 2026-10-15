import tempfile
import unittest
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from konzert_agent.agent import Agent
from konzert_agent.auth import hash_password, new_token
from konzert_agent.config import ArtistSettings, AuthSettings, Config, Settings, UserTelegramSettings
from konzert_agent.models import Event
from konzert_agent.userbot import BotBlocked, clean_prefs
from konzert_agent.web.app import create_app

from tests.test_auth import MemberBase, call


class FakeTelegram:
    """Ersetzt UserBot.api – merkt sich gesendete Nachrichten, ohne Netz."""

    def __init__(self):
        self.sent, self.blocked = [], set()

    def __call__(self, method, http_timeout=20, **params):
        if method == "getMe":
            return {"username": "KonzertTestBot"}
        if method == "sendMessage":
            if params["chat_id"] in self.blocked:
                raise BotBlocked("Forbidden: bot was blocked by the user")
            self.sent.append((params["chat_id"], params["text"]))
            return {}
        raise AssertionError(method)


def start(chat_id, text, chat_type="private"):
    return {"update_id": 1, "message": {"chat": {"id": int(chat_id), "type": chat_type},
                                        "from": {"first_name": "Anna", "username": "anna_m"}, "text": text}}


class UserBotTests(MemberBase):
    def setUp(self):
        super().setUp()
        self.agent.config.user_telegram = UserTelegramSettings(token="123:abc")
        self.agent = Agent(self.agent.config, store=self.store)
        self.bot = self.agent.user_bot
        self.tg = self.bot.api = FakeTelegram()
        self.app = create_app(self.agent)

    def link(self, cookie, chat_id="111"):
        r = self.req("POST", "/api/telegram/link", cookie)
        self.assertEqual(r["status"], 200, r["text"])
        url = urlparse(r["json"]["url"])
        self.assertEqual((url.netloc, url.path), ("t.me", "/KonzertTestBot"))
        code = parse_qs(url.query)["start"][0]
        self.bot.handle(start(chat_id, f"/start {code}"))
        return code

    def test_link_with_one_time_code(self):
        self.assertEqual(self.req("GET", "/api/telegram", self.c_anna)["json"], {"available": True, "linked": False,
                                                                                   "link_minutes": 15})
        code = self.link(self.c_anna)
        self.assertIn("Verbunden", self.tg.sent[-1][1])
        st = self.req("GET", "/api/telegram", self.c_anna)["json"]
        self.assertTrue(st["linked"])
        self.assertEqual(st["chat"], "Anna (@anna_m)")
        self.assertEqual(st["prefs"], {"new": "all", "filter": {}, "cancelled": True, "follows": True})
        # Code nur einmal gültig – ein anderer Chat kann ihn nicht nochmals verwenden
        self.bot.handle(start("999", f"/start {code}"))
        self.assertIn("abgelaufen", self.tg.sent[-1][1])
        self.assertEqual([r["chat_id"] for r in self.store.tg_recipients()], ["111"])

    def test_expired_code_and_strangers(self):
        self.store.tg_new_code(self.anna, "altercode", 15)
        self.store.db.execute("UPDATE tg_codes SET expires=?", ((datetime.now() - timedelta(minutes=1)).isoformat(),))
        self.bot.handle(start("111", "/start altercode"))
        self.assertIn("abgelaufen", self.tg.sent[-1][1])
        self.bot.handle(start("222", "hallo"))                  # Fremde: keine Antwort auf beliebigen Text
        self.bot.handle(start("222", "/start erraten", chat_type="group"))   # Gruppen: ignoriert
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(self.store.tg_recipients(), [])

    def test_guests_and_csrf(self):
        self.assertEqual(self.req("GET", "/api/telegram")["status"], 401)
        self.assertEqual(self.req("POST", "/api/telegram/link")["status"], 401)
        r = self.req("POST", "/api/telegram/link", self.c_anna)
        bad = call(self.app, "POST", "/api/telegram/link", {"cookie": self.c_anna, "origin": "http://evil", "host": "test"})
        self.assertEqual((r["status"], bad["status"]), (200, 403))

    def test_prefs_and_unlink(self):
        self.assertEqual(self.req("PUT", "/api/telegram", self.c_anna,
                                  {"new": "off", "cancelled": True})["status"], 409)      # noch nicht verbunden
        self.link(self.c_anna)
        bad = self.req("PUT", "/api/telegram", self.c_anna, {"new": "alles", "cancelled": True})
        self.assertEqual(bad["status"], 400)
        r = self.req("PUT", "/api/telegram", self.c_anna,
                     {"new": "filter", "cancelled": False, "filter": {"venues": ["kiff"], "genres": [], "x": 1}})
        self.assertEqual(r["json"]["prefs"], {"new": "filter", "filter": {"venues": ["kiff"]}, "cancelled": False,
                                              "follows": True})
        self.req("DELETE", "/api/telegram", self.c_anna)
        self.assertIn("Getrennt", self.tg.sent[-1][1])
        self.assertFalse(self.req("GET", "/api/telegram", self.c_anna)["json"]["linked"])

    def test_stop_and_blocked(self):
        self.link(self.c_anna, "111")
        self.bot.handle(start("111", "/status"))
        self.assertIn("Anna", self.tg.sent[-1][1])
        self.bot.handle(start("111", "/stop"))
        self.assertEqual(self.store.tg_recipients(), [])
        self.link(self.c_anna, "111")
        self.bot.handle({"update_id": 5, "my_chat_member": {"chat": {"id": 111}, "new_chat_member": {"status": "kicked"}}})
        self.assertEqual(self.store.tg_recipients(), [])

    def test_notify_per_user(self):
        self.link(self.c_anna, "111")
        self.link(self.c_ben, "222")
        self.req("PUT", "/api/telegram", self.c_ben, {"new": "filter", "cancelled": True,
                                                       "filter": {"venues": ["kiff"], "kinds": ["Party"]}})
        today = date.today()
        concert = Event("kiff", "9", "Neue Band", today + timedelta(days=9))
        party = Event("kiff", "10", "Ü30 Party", today + timedelta(days=9))
        other = Event("schuur", "11", "Andere Band", today + timedelta(days=9))
        cancelled_b = Event("kiff", "2", "Band B", today + timedelta(days=5), cancelled=True)
        self.req("PUT", "/api/marks/kiff%3A2", self.c_ben, {"status": "going"})
        self.tg.sent.clear()
        self.bot.notify([concert, party, other], [cancelled_b])
        anna = "".join(t for c, t in self.tg.sent if c == "111")
        ben = "".join(t for c, t in self.tg.sent if c == "222")
        self.assertIn("Neue Band", anna)
        self.assertIn("Andere Band", anna)
        self.assertIn("Band B", anna)                            # «Alle»: auch alle Absagen
        self.assertIn("Ü30 Party", ben)                          # Filter: nur Partys im Kiff
        self.assertNotIn("Neue Band", ben)
        self.assertNotIn("Andere Band", ben)
        self.assertIn("Band B", ben)                             # markiert -> Absage kommt
        # Aus + keine Absagen -> nichts; blockierter Chat wird getrennt
        self.req("PUT", "/api/telegram", self.c_ben, {"new": "off", "cancelled": False})
        self.tg.blocked.add("111")
        self.tg.sent.clear()
        self.bot.notify([concert], [cancelled_b])
        self.assertEqual(self.tg.sent, [])
        self.assertEqual([r["username"] for r in self.store.tg_recipients()], ["Ben"])

    def test_disabled_and_deleted_users(self):
        self.link(self.c_anna, "111")
        self.store.update_user(self.anna, disabled=1)
        self.assertEqual(self.store.tg_recipients(), [])
        self.store.delete_user(self.anna)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tg_chats").fetchone()[0], 0)

    def test_not_configured(self):
        cfg = Config(settings=Settings(database=f"{self.tmp.name}/o.db"), venues=[], notifiers=[],
                     artists=ArtistSettings(enabled=False), auth=AuthSettings())
        agent = Agent(cfg)
        self.assertIsNone(agent.user_bot)
        agent.store.create_user("Cleo", hash_password("passwort-cleo"), new_token())
        self.app = create_app(agent)
        c = self.login("cleo", "passwort-cleo")
        self.assertEqual(self.req("GET", "/api/telegram", c)["json"], {"available": False})
        self.assertEqual(self.req("POST", "/api/telegram/link", c)["status"], 404)

    def test_clean_prefs(self):
        self.assertIsNone(clean_prefs({"new": "all"}))
        self.assertIsNone(clean_prefs({"new": "all", "cancelled": True, "filter": {"venues": "kiff"}}))
        self.assertEqual(clean_prefs({"new": "all", "cancelled": True}),
                         {"new": "all", "filter": {}, "cancelled": True, "follows": True})
        self.assertIsNone(clean_prefs({"new": "all", "cancelled": True, "follows": "ja"}))

    def test_followed_bands_always_reported(self):
        self.link(self.c_anna, "111")
        self.req("PUT", "/api/telegram", self.c_anna, {"new": "off", "cancelled": True})
        self.req("POST", "/api/follows", self.c_anna, {"name": "Slope"})
        today = date.today()
        hit = Event("kiff", "20", "Headliner + Slope", today + timedelta(days=20))
        miss = Event("kiff", "21", "Andere Band", today + timedelta(days=21))
        self.tg.sent.clear()
        self.bot.notify([hit, miss], [])
        self.assertEqual(len(self.tg.sent), 1)                  # «Aus»: nur die gefolgte Band
        self.assertIn("⭐", self.tg.sent[0][1])
        self.assertIn("<b>Slope</b>", self.tg.sent[0][1])
        self.assertNotIn("Andere Band", self.tg.sent[0][1])
        # «Alle»: gefolgte Band nicht doppelt in der allgemeinen Liste
        self.req("PUT", "/api/telegram", self.c_anna, {"new": "all", "cancelled": True})
        self.tg.sent.clear()
        self.bot.notify([hit, miss], [])
        self.assertEqual([t.count("Headliner + Slope") for _, t in self.tg.sent], [1, 0])
        # abgeschaltet -> nur noch die allgemeine Liste
        self.req("PUT", "/api/telegram", self.c_anna, {"new": "off", "cancelled": True, "follows": False})
        self.tg.sent.clear()
        self.bot.notify([hit], [])
        self.assertEqual(self.tg.sent, [])
