"""Web-Oberfläche + JSON-API + abonnierbarer iCal-Feed – Gäste nur lesend, mehr mit Login (siehe security.py)."""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..agent import Agent
from ..auth import new_token
from ..follows import follow_key, matching
from ..kinds import event_kind
from ..prices import format_price
from ..userbot import clean_prefs
from .security import AuthMiddleware, login_routes

STATIC = Path(__file__).parent / "static"
TICKET_TEXT = {"none": "Ticket: noch nicht", "own": "Ticket: selbst gekauft", "other": "Ticket: hat jemand anderes"}


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def create_app(agent: Agent):
    cfg = agent.config
    venue_meta = {v.id: {"id": v.id, "name": v.name, "city": v.city, "type": v.type, "url": v.url}
                  for v in cfg.venues if v.enabled}

    def query_events(req: Request) -> list[dict]:
        p = req.query_params
        past = p.get("past") == "1"                   # Archiv: alles vor heute, neueste zuerst
        start = None if past else date.fromisoformat(p["from"]) if p.get("from") else date.today()
        end = date.today() - timedelta(days=1) if past else date.fromisoformat(p["to"]) if p.get("to") else None
        venues = [v for v in p.get("venues", "").split(",") if v] or None
        if p.get("city"):
            city_ids = [v for v, m in venue_meta.items() if m["city"].lower() == p["city"].lower()]
            venues = [v for v in (venues or city_ids) if v in city_ids]
        evs = agent.store.events(start=start, end=end, venues=venues, q=p.get("q") or None,
                                 new_days=int(p["new"]) if p.get("new") else None)
        if p.get("raw") != "1":
            evs = agent.filtered_events(evs)
        # mehrfach erlaubt: ?genre=Metal&genre=Rock (Genre-Namen enthalten Kommas, z.B. «Soul, R&B & Funk»)
        for e in evs:
            e["kind"] = event_kind(e["title"], e["tags"])
        genres, pops, kinds = set(p.getlist("genre")), set(p.getlist("pop")), set(p.getlist("kind"))
        if kinds:
            evs = [e for e in evs if e["kind"] in kinds]
        if genres:
            evs = [e for e in evs if genres & set(e["extra"].get("genres") or [])]
        if pops:
            evs = [e for e in evs if e["extra"].get("popularity_label") in pops]
        evs = [e for e in evs if e["venue_id"] in venue_meta]
        if past:                                      # mehrtägige, die noch laufen, gehören nicht ins Archiv
            evs = [e for e in evs if (e["end_date"] or e["date"]) < date.today().isoformat()][::-1]
        return evs

    async def index(req):
        return FileResponse(STATIC / "index.html")

    def decorate(evs: list[dict]) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=cfg.settings.new_badge_days)).isoformat()
        for e in evs:
            m = venue_meta.get(e["venue_id"], {})
            e["is_new"] = e["first_seen"] >= cutoff
            e["venue"] = m.get("name", e["venue_id"])        # Location inzwischen abgeschaltet -> ID
            e["city"] = m.get("city", "")
            e.setdefault("kind", event_kind(e["title"], e["tags"]))
            e["price"] = format_price(e["extra"].get("price"))
        return evs

    async def api_events(req):
        return JSONResponse(decorate(query_events(req)))

    async def api_my_events(req):
        """Dashboard «Meine»: alle markierten Events inkl. vergangener, unabhängig von Filtern."""
        u = req.state.user
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        return JSONResponse(decorate(agent.store.marked_events(u["id"])))

    async def api_venues(req):
        runs, counts = agent.store.runs(), agent.store.counts()
        out = []
        for vid, m in venue_meta.items():
            out.append({**m, "upcoming": counts.get(vid, 0), "run": runs.get(vid)})
        return JSONResponse({"venues": out, "interval_hours": cfg.settings.interval_hours,
                             "new_badge_days": cfg.settings.new_badge_days, "version": __version__,
                             "copyright": cfg.settings.copyright})

    async def api_run(req):
        if cfg.auth.enabled and req.state.user is None:     # Middleware lässt Gäste nicht durch – doppelt hält besser
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        threading.Thread(target=agent.run, daemon=True).start()
        return JSONResponse({"started": True})

    async def api_me(req):
        u = req.state.user
        if u is None:                                   # Gast oder Login abgeschaltet
            return JSONResponse({"user": None, "auth": cfg.auth.enabled})
        return JSONResponse({"auth": True, "user": {"username": u["username"], "ical_token": u["ical_token"],
                                                    "share_marks": bool(u["share_marks"])}})

    async def api_marks(req):
        """Eigene Markierungen + (wenn man selbst teilt) die der anderen, die auch teilen."""
        u = req.state.user
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        others = agent.store.shared_marks(u["id"]) if u["share_marks"] else {}
        return JSONResponse({"mine": agent.store.marks(u["id"]), "others": others, "share": bool(u["share_marks"])})

    async def api_mark(req):
        u = req.state.user
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        uid = req.path_params["uid"]
        if req.method == "DELETE":
            agent.store.set_mark(u["id"], uid, None)
            return JSONResponse({"ok": True})
        try:
            body = await req.json()
            status, ticket = body.get("status"), body.get("ticket")
        except (ValueError, AttributeError):
            return JSONResponse({"error": "Ungültige Anfrage"}, 400)
        if status not in agent.store.MARK_STATUS or (ticket is not None and ticket not in agent.store.TICKETS):
            return JSONResponse({"error": "Ungültiger Status"}, 400)
        if not agent.store.event_exists(uid):
            return JSONResponse({"error": "Unbekanntes Event"}, 404)
        agent.store.set_mark(u["id"], uid, status, ticket)
        return JSONResponse({"ok": True, "mark": agent.store.marks(u["id"]).get(uid)})

    async def api_settings(req):
        u = req.state.user
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        try:
            body = await req.json()
        except ValueError:
            return JSONResponse({"error": "Ungültige Anfrage"}, 400)
        if isinstance(body, dict) and isinstance(body.get("share_marks"), bool):
            agent.store.update_user(u["id"], share_marks=int(body["share_marks"]))
        return JSONResponse({"ok": True})

    async def api_new_ical(req):
        """Neuer persönlicher Kalender-Link – der alte funktioniert sofort nicht mehr."""
        u = req.state.user
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        token = new_token()
        agent.store.update_user(u["id"], ical_token=token)
        return JSONResponse({"ical_token": token})

    async def api_telegram(req):
        """Telegram pro Benutzer: Status (GET), Einstellungen (PUT), trennen (DELETE)."""
        u, bot = req.state.user, agent.user_bot
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        if bot is None:
            return JSONResponse({"available": False})
        if req.method == "DELETE":
            chat = agent.store.tg_chat(u["id"])
            agent.store.tg_unlink(u["id"])
            if chat:
                await run_in_threadpool(bot.send, chat["chat_id"], "Getrennt – du bekommst keine Meldungen mehr.")
            return JSONResponse({"ok": True})
        if req.method == "PUT":
            try:
                prefs = clean_prefs(await req.json())
            except ValueError:
                prefs = None
            if prefs is None:
                return JSONResponse({"error": "Ungültige Einstellungen"}, 400)
            if not agent.store.tg_chat(u["id"]):
                return JSONResponse({"error": "Telegram ist nicht verbunden"}, 409)
            agent.store.tg_set_prefs(u["id"], prefs)
        chat = agent.store.tg_chat(u["id"])
        return JSONResponse({"available": True, "linked": bool(chat), "link_minutes": bot.link_minutes,
                             **({"chat": chat["chat_name"], "since": chat["linked"], "prefs": chat["prefs"]} if chat else {})})

    async def api_telegram_link(req):
        """Einmal-Link t.me/<bot>?start=<code> – in Telegram «Start» drücken verbindet den Chat."""
        u, bot = req.state.user, agent.user_bot
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        if bot is None:
            return JSONResponse({"error": "Telegram ist nicht eingerichtet"}, 404)
        try:
            url = await run_in_threadpool(bot.new_link, u["id"])
        except Exception as e:  # noqa: BLE001 – z.B. falscher Token, Telegram nicht erreichbar
            return JSONResponse({"error": f"Telegram nicht erreichbar: {type(e).__name__}"}, 502)
        return JSONResponse({"url": url, "minutes": bot.link_minutes})

    async def api_telegram_test(req):
        u, bot = req.state.user, agent.user_bot
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        chat = agent.store.tg_chat(u["id"]) if bot else None
        if not chat:
            return JSONResponse({"error": "Telegram ist nicht verbunden"}, 409)
        try:
            ok = await run_in_threadpool(bot.send, chat["chat_id"], "🎸 Test: Meldungen vom Konzertkalender kommen an.")
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": f"Senden fehlgeschlagen: {type(e).__name__}"}, 502)
        return JSONResponse({"ok": ok} if ok else {"error": "Chat nicht erreichbar (Bot blockiert?) – Verbindung gelöst"})

    def follows_state(user_id: int) -> dict:
        """Gefolgte Bands + ihre kommenden Shows (für Dashboard und ★ in der Liste)."""
        follows = agent.store.follows(user_id)
        evs = []
        if follows:
            for e in agent.filtered_events(agent.store.events(start=date.today())):
                if e["venue_id"] in venue_meta and (bands := matching(e["title"], e["extra"], follows)):
                    e["follows"] = bands
                    evs.append(e)
        return {"follows": [{"key": k, "name": n} for k, n in follows.items()], "events": decorate(evs)}

    async def api_follows(req):
        """GET: gefolgte Bands + kommende Shows. POST {name}: folgen. DELETE /api/follows/<key>: entfolgen."""
        u = req.state.user
        if u is None:
            return JSONResponse({"error": "Nicht angemeldet"}, 401)
        if req.method == "POST":
            try:
                name = (await req.json()).get("name")
            except (ValueError, AttributeError):
                name = None
            name = " ".join(name.split()) if isinstance(name, str) else ""
            key = follow_key(name)
            if len(key) < 2 or len(name) > 100:
                return JSONResponse({"error": "Ungültiger Bandname"}, 400)
            if len(agent.store.follows(u["id"])) >= 500:
                return JSONResponse({"error": "Zu viele Bands"}, 400)
            agent.store.follow(u["id"], key, name)
        elif req.method == "DELETE":
            agent.store.unfollow(u["id"], req.path_params.get("key", ""))
        return JSONResponse(follows_state(u["id"]))

    async def personal_ics(req):
        """Kalender-Abo mit geheimem Token – Kalender-Apps können sich nicht anmelden.
        Standard: die eigenen markierten Konzerte (?status=going nur «Gehe hin»); ?all=1 = alle Events wie
        calendar.ics (mit denselben Filtern)."""
        u = agent.store.user_by_ical_token(req.path_params["token"])
        if not u:
            return Response("Unbekannter Kalender-Link", status_code=404)
        if req.query_params.get("all") == "1":
            return ics_response(query_events(req), "Konzerte")
        evs = agent.store.marked_events(u["id"])
        if req.query_params.get("status") in agent.store.MARK_STATUS:
            evs = [e for e in evs if e["mark"]["status"] == req.query_params["status"]]
        others = agent.store.shared_marks(u["id"]) if u["share_marks"] else {}

        def describe(e):
            m = e["mark"]
            if m["status"] == "interested":
                lines = ["☆ Interessiert"]
            else:
                lines = [f"✓ Gehe hin · {TICKET_TEXT[m['ticket']]}"]
            going = [o["user"] for o in others.get(e["uid"], []) if o["status"] == "going"]
            if going:
                lines.append("Gehen auch hin: " + ", ".join(going))
            return lines

        def title(e):
            m = e["mark"]
            if m["status"] == "interested":
                return "☆ " + e["title"]
            return "✓ " + e["title"] + (" (ohne Ticket)" if m["ticket"] == "none" else "")

        return ics_response(evs, f"Meine Konzerte ({u['username']})", describe, title,
                            lambda e: "TENTATIVE" if e["mark"]["status"] == "interested" else "CONFIRMED")

    async def ics(req):
        return ics_response(query_events(req), "Konzerte")

    def ics_response(evs, name, describe=lambda e: [], title=lambda e: e["title"], status=lambda e: None):
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//KonzertAgent//DE",
                 f"X-WR-CALNAME:{_ics_escape(name)}", "X-WR-TIMEZONE:Europe/Zurich", "CALSCALE:GREGORIAN"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for e in evs:
            d = date.fromisoformat(e["date"])
            lines += ["BEGIN:VEVENT", f"UID:{e['uid']}@konzert-agent", f"DTSTAMP:{stamp}"]
            if e["time"] and not e["end_date"]:
                hh, mm = e["time"].split(":")
                start = datetime(d.year, d.month, d.day, int(hh), int(mm))
                lines += [f"DTSTART;TZID=Europe/Zurich:{start:%Y%m%dT%H%M%S}",
                          f"DTEND;TZID=Europe/Zurich:{start + timedelta(hours=3):%Y%m%dT%H%M%S}"]
            else:
                end = date.fromisoformat(e["end_date"]) if e["end_date"] else d
                lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{end + timedelta(days=1):%Y%m%d}"]
            summary = title(e) + (" (ABGESAGT)" if e["cancelled"] else " (VERSCHOBEN)" if e.get("moved") else "")
            venue = venue_meta.get(e["venue_id"], {"name": e["venue_id"], "city": ""})
            # verschoben: nicht CANCELLED (findet ja statt, nur anders) – aber auch nicht mehr sicher
            st = "CANCELLED" if e["cancelled"] else "TENTATIVE" if e.get("moved") else status(e)
            moved = [f"Verschoben: {e.get('moved_note') or 'neues Datum/Ort noch offen'}"] if e.get("moved") else []
            price = [f"Preis: {p}"] if (p := format_price(e["extra"].get("price"))) else []
            lines += [f"SUMMARY:{_ics_escape(summary)}",
                      f"LOCATION:{_ics_escape(venue['name'] + (', ' + venue['city'] if venue['city'] else ''))}",
                      f"URL:{e['url']}", f"DESCRIPTION:{_ics_escape(chr(10).join([*moved, *describe(e), *price, e['url']]))}"]
            lines += [f"STATUS:{st}"] if st else []
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        # Zeilen > 75 Oktette falten
        folded = []
        for line in lines:
            while len(line.encode()) > 74:
                cut = 74
                while len(line[:cut].encode()) > 74:
                    cut -= 1
                folded.append(line[:cut]); line = " " + line[cut:]
            folded.append(line)
        return Response("\r\n".join(folded) + "\r\n", media_type="text/calendar; charset=utf-8",
                        headers={"cache-control": "no-store"})

    async def health(req):
        return JSONResponse({"ok": True, "version": __version__})

    login_page, logout = login_routes(agent.store, cfg.auth)

    async def login_or_home(req):
        if not cfg.auth.enabled:
            return RedirectResponse("/", 303)
        return await login_page(req)

    app = Starlette(routes=[
        Route("/", index),
        Route("/login", login_or_home, methods=["GET", "POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/api/me", api_me),
        Route("/api/events", api_events),
        Route("/api/venues", api_venues),
        Route("/api/run", api_run, methods=["POST"]),
        Route("/api/marks", api_marks),
        Route("/api/my-events", api_my_events),
        Route("/api/marks/{uid:path}", api_mark, methods=["PUT", "DELETE"]),
        Route("/api/settings", api_settings, methods=["PUT"]),
        Route("/api/ical-token", api_new_ical, methods=["POST"]),
        Route("/api/follows", api_follows, methods=["GET", "POST"]),
        Route("/api/follows/{key}", api_follows, methods=["DELETE"]),
        Route("/api/telegram", api_telegram, methods=["GET", "PUT", "DELETE"]),
        Route("/api/telegram/link", api_telegram_link, methods=["POST"]),
        Route("/api/telegram/test", api_telegram_test, methods=["POST"]),
        Route("/calendar.ics", ics),
        Route("/ical/{token}.ics", personal_ics),
        Route("/health", health),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])
    return AuthMiddleware(app, agent.store, cfg.auth, cfg.settings.base_url)
