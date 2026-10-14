"""Web-Oberfläche + JSON-API + abonnierbarer iCal-Feed – Gäste nur lesend, mehr mit Login (siehe security.py)."""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..agent import Agent
from .security import AuthMiddleware, login_routes

STATIC = Path(__file__).parent / "static"


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def create_app(agent: Agent):
    cfg = agent.config
    venue_meta = {v.id: {"id": v.id, "name": v.name, "city": v.city, "type": v.type, "url": v.url}
                  for v in cfg.venues if v.enabled}

    def query_events(req: Request) -> list[dict]:
        p = req.query_params
        start = date.fromisoformat(p["from"]) if p.get("from") else date.today()
        end = date.fromisoformat(p["to"]) if p.get("to") else None
        venues = [v for v in p.get("venues", "").split(",") if v] or None
        if p.get("city"):
            city_ids = [v for v, m in venue_meta.items() if m["city"].lower() == p["city"].lower()]
            venues = [v for v in (venues or city_ids) if v in city_ids]
        evs = agent.store.events(start=start, end=end, venues=venues, q=p.get("q") or None,
                                 new_days=int(p["new"]) if p.get("new") else None)
        if p.get("raw") != "1":
            evs = agent.filtered_events(evs)
        # mehrfach erlaubt: ?genre=Metal&genre=Rock (Genre-Namen enthalten Kommas, z.B. «Soul, R&B & Funk»)
        genres, pops = set(p.getlist("genre")), set(p.getlist("pop"))
        if genres:
            evs = [e for e in evs if genres & set(e["extra"].get("genres") or [])]
        if pops:
            evs = [e for e in evs if e["extra"].get("popularity_label") in pops]
        return [e for e in evs if e["venue_id"] in venue_meta]

    async def index(req):
        return FileResponse(STATIC / "index.html")

    def decorate(evs: list[dict]) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=cfg.settings.new_badge_days)).isoformat()
        for e in evs:
            m = venue_meta.get(e["venue_id"], {})
            e["is_new"] = e["first_seen"] >= cutoff
            e["venue"] = m.get("name", e["venue_id"])        # Location inzwischen abgeschaltet -> ID
            e["city"] = m.get("city", "")
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
                             "new_badge_days": cfg.settings.new_badge_days, "version": __version__})

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

    async def personal_ics(req):
        """Kalender-Abo mit geheimem Token – Kalender-Apps können sich nicht anmelden."""
        if not agent.store.user_by_ical_token(req.path_params["token"]):
            return Response("Unbekannter Kalender-Link", status_code=404)
        return await ics(req)

    async def ics(req):
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//KonzertAgent//DE",
                 "X-WR-CALNAME:Konzerte", "X-WR-TIMEZONE:Europe/Zurich", "CALSCALE:GREGORIAN"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for e in query_events(req):
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
            summary = e["title"] + (" (ABGESAGT)" if e["cancelled"] else "")
            venue = venue_meta[e["venue_id"]]
            lines += [f"SUMMARY:{_ics_escape(summary)}",
                      f"LOCATION:{_ics_escape(venue['name'] + (', ' + venue['city'] if venue['city'] else ''))}",
                      f"URL:{e['url']}", f"DESCRIPTION:{_ics_escape(e['url'])}", "END:VEVENT"]
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
        return Response("\r\n".join(folded) + "\r\n", media_type="text/calendar; charset=utf-8")

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
        Route("/calendar.ics", ics),
        Route("/ical/{token}.ics", personal_ics),
        Route("/health", health),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])
    return AuthMiddleware(app, agent.store, cfg.auth, cfg.settings.base_url)
